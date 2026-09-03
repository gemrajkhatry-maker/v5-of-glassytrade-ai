"""Live Dhan broker adapter for order execution and reconciliation."""

from __future__ import annotations

import logging
import os
import threading
import time
from datetime import datetime
from decimal import Decimal
from types import SimpleNamespace
from typing import Any

from app.config import Configuration, settings
from app.infrastructure.adapters._dhan_common import (  # noqa: F401  (bootstrap + re-export)
    _exchange_enum,
    classify_symbol,
)
from brokers.broker import Exchange, Instrument, Order
from brokers.broker.dhan.application.broker import DhanBroker
from brokers.broker.dhan.domain.errors import DhanError
from brokers.broker.types import OrderStatus, OrderType
from quant.contracts.aggregates import (
    RISK_BY_CONFIDENCE,
    RISK_PER_TRADE,
    Portfolio,
)
from quant.contracts.entities import Position, Signal
from quant.contracts.enums import Side, Source
from quant.contracts.exchange_config import ExchangeConfig
from quant.contracts.numeric import to_float
from quant.contracts.ports.broker import IBroker
from shared.money import to_decimal as _strict_to_decimal

logger = logging.getLogger(__name__)


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    """Lenient adapter-edge converter: unparseable input -> Decimal(default)."""
    if value is None:
        return Decimal(default)
    try:
        return _strict_to_decimal(value)
    except (ValueError, TypeError, ArithmeticError):
        return Decimal(default)


class DhanBrokerAdapter(IBroker):
    """Dhan order execution adapter wired to `brokers` library.

    It implements the synchronous ``IBroker`` contract while performing all network
    calls via ``DhanBroker``'s internal sync wrappers, which already bridge async
    internally.
    """

    _MCX_UNDERLYINGS = ExchangeConfig.for_exchange("MCX").underlyings

    # C7: default worst-case slippage bound for entry orders. A naked MARKET
    # order on a thin option can fill arbitrarily far from the signal price;
    # converting entries to a marketable LIMIT bounded by this tolerance caps
    # the damage (a no-fill simply skips the entry, which is safe).
    _DEFAULT_ENTRY_SLIPPAGE_TOLERANCE_PCT = 0.01

    # C7 (close side): worst-case slippage bound for closing orders. Tightened
    # to 2% now that the WS fill feed detects a missed collar instantly and the
    # C3 retry / EOD watchdog re-queue with a fresh reference price — the cost
    # of a rare re-queue is one tick, not a 30s blind poll. Set to 0 to disable
    # the collar entirely (plain MARKET close).
    _DEFAULT_CLOSE_SLIPPAGE_TOLERANCE_PCT = 0.02

    def __init__(self, config: Configuration, storage=None):
        self._config = config
        # C4: optional durable order storage. When wired, every order state
        # transition is persisted so a crash between place_order and the fill
        # ack cannot silently lose an in-flight order. None in tests/paper.
        self._storage = storage
        self._broker: DhanBroker | None = None
        self._broker_lock = threading.Lock()
        self._order_poll_interval = float(
            os.environ.get("DHAN_ORDER_POLL_INTERVAL_SEC", "0.5")
        )
        self._order_poll_timeout = float(
            os.environ.get("DHAN_ORDER_POLL_TIMEOUT_SEC", "30")
        )
        self._entry_slippage_tol = float(
            os.environ.get(
                "DHAN_ENTRY_SLIPPAGE_TOLERANCE_PCT",
                str(self._DEFAULT_ENTRY_SLIPPAGE_TOLERANCE_PCT),
            )
        )
        # C7 (close side): slippage bound for closing orders. A close MUST
        # fill (stops/EOD), so this stays wider than the entry collar and only
        # caps extreme slippage; set to 0 to disable (plain MARKET).
        self._close_slippage_tol = float(
            os.environ.get(
                "DHAN_CLOSE_SLIPPAGE_TOLERANCE_PCT",
                str(self._DEFAULT_CLOSE_SLIPPAGE_TOLERANCE_PCT),
            )
        )
        # C4: async fill feed — WS order updates with REST-poll fallback. The
        # feed is started lazily on the first order poll; when it is disabled
        # or unhealthy, waiting falls back to the proven REST loop unchanged.
        self._order_feed_enabled = os.environ.get(
            "DHAN_ORDER_WS", "1"
        ).strip().lower() not in ("0", "false", "no")
        self._order_feed = None
        self._order_feed_lock = threading.Lock()
        # Dhan broker order id -> our durable order row id (signal id), used by
        # the WS callback to persist fill state even if the engine thread is
        # blocked or dead.
        self._broker_order_to_signal: dict[str, str] = {}
        # Duplicate-order protection: signal_ids currently being executed (or
        # already executed). A duplicate submission of the same signal (e.g. a
        # replay, a double-click, or a concurrent consumer) must never reach
        # place_order twice — each signal_id maps to exactly one broker order.
        # Broker-side dedup is the backstop (correlationId in the payload);
        # this guard stops the second call before it leaves the process.
        self._executing_signal_ids: set[str] = set()
        self._executing_lock = threading.Lock()

        client_id = str(
            getattr(self._config, "dhan_client_id", None)
            or getattr(settings, "DHAN_CLIENT_ID", None)
            or os.getenv("DHAN_CLIENT_ID", "")
        ).strip()
        access_token = str(
            getattr(self._config, "dhan_access_token", None)
            or getattr(settings, "DHAN_ACCESS_TOKEN", None)
            or os.getenv("DHAN_ACCESS_TOKEN", "")
        ).strip()
        if not client_id:
            raise ValueError(
                "Dhan client id is required for live execution. Set DHAN_CLIENT_ID or "
                "configuration `dhan_client_id`."
            )
        if not access_token:
            logger.warning(
                "DHAN_ACCESS_TOKEN is not set; DhanBroker may auto-refresh if DHAN_TOTP_SECRET "
                "and DHAN_PIN are configured."
            )
        self._client_id = client_id
        self._access_token = access_token
        self._broker = self._create_broker()

    def _create_broker(self) -> DhanBroker:
        with self._broker_lock:
            return DhanBroker.create(
                client_id=self._client_id,
                access_token=self._access_token,
            )

    def execute_order(
        self, signal: Signal, portfolio: Portfolio, symbol: str
    ) -> Position | None:
        broker = self._broker
        if broker is None:
            logger.error("DhanBroker not initialized")
            return None

        entry_price = _to_decimal(signal.price)
        if entry_price <= 0:
            logger.error("Rejecting signal %s: invalid entry price=%s", signal.signal_id, signal.price)
            return None

        qty = self._resolve_quantity(signal, portfolio)
        if qty <= 0:
            logger.error(
                "Rejecting signal %s for %s: invalid order quantity=%s",
                signal.signal_id,
                symbol,
                qty,
            )
            return None

        # Duplicate-order protection: refuse a second execution of a signal
        # that is already placed/in-flight (or was already executed). Each
        # signal_id must map to exactly one broker order — duplicates would
        # double the position.
        signal_id = str(getattr(signal, "signal_id", "") or "").strip()
        if signal_id:
            with self._executing_lock:
                if signal_id in self._executing_signal_ids:
                    logger.warning(
                        "Duplicate order request for signal %s (%s) — skipping",
                        signal_id, symbol,
                    )
                    return None
                self._executing_signal_ids.add(signal_id)

        try:
            instrument = self._make_instrument(signal, symbol)
            meta = signal.metadata or {}
            order_type = self._map_order_type(signal)
            limit_price = float(entry_price)
            trigger_price = to_float(signal.stop_loss)
            tol = getattr(
                self, "_entry_slippage_tol",
                self._DEFAULT_ENTRY_SLIPPAGE_TOLERANCE_PCT,
            )
            # C7: when no explicit order_type was requested, the default MARKET
            # entry becomes a marketable LIMIT bounded by the slippage tolerance
            # so a thin contract cannot fill arbitrarily far from the signal
            # price. An explicitly requested order_type is honored unchanged.
            if "order_type" not in meta and order_type == OrderType.MARKET and tol > 0:
                order_type = OrderType.LIMIT
                limit_price = self._marketable_limit_price(
                    float(entry_price), signal.is_buy, tol
                )
                trigger_price = 0.0
            order = Order(
                instrument=instrument,
                side="BUY" if signal.is_buy else "SELL",
                quantity=qty,
                order_type=order_type,
                price=limit_price,
                trigger_price=trigger_price,
                product_type=self._resolve_product_type(meta),
            )
            # Preserve source trace in in-memory object; Dhan converter sends
            # payload from known fields and ignores extra attrs.
            setattr(order, "user_order_id", str(signal.signal_id))

            # C4: persist SUBMITTED before place_order so a crash mid-submit is
            # recoverable; record the broker order id once we have it.
            self._persist_order_submitted(signal, symbol, qty, order_type, limit_price)
            placed_order = broker.place_order(order)
            placed_order_id = str(getattr(placed_order, "order_id", ""))
            if not placed_order_id:
                logger.error("Dhan place_order did not return order_id for %s", signal.signal_id)
                self._persist_order_terminal(signal, "REJECTED")
                return None
            self._persist_order_terminal(signal, "SUBMITTED", broker_order_id=placed_order_id)

            final_order = self._poll_for_terminal_status(
                placed_order_id, timeout=self._order_poll_timeout
            )
            if final_order is None:
                logger.warning("Order %s did not reach terminal state within timeout", placed_order_id)
                try:
                    broker.cancel_order(placed_order_id)
                    logger.info("Order %s cancelled after timeout", placed_order_id)
                except Exception:
                    logger.debug("Failed to cancel timed-out order %s", placed_order_id, exc_info=True)
                self._persist_order_terminal(signal, "CANCELLED", broker_order_id=placed_order_id)
                return None

            if not self._is_filled(final_order):
                terminal_status = str(
                    getattr(final_order.status, "value", final_order.status)
                ).upper()
                logger.warning(
                    "Order %s terminal status=%s, filled=%s/%s",
                    placed_order_id,
                    terminal_status,
                    to_float(final_order.filled_quantity),
                    to_float(final_order.quantity),
                )
                self._persist_order_terminal(
                    signal,
                    "CANCELLED" if terminal_status in ("CANCELLED", "CLOSED") else terminal_status,
                    broker_order_id=placed_order_id,
                    filled_quantity=to_float(final_order.filled_quantity),
                )
                return None

            fill_price = (
                to_float(getattr(final_order, "average_fill_price", None))
                or to_float(getattr(final_order, "price", None), to_float(signal.price))
                or 0.0
            )
            filled_quantity = to_float(final_order.filled_quantity)
            if filled_quantity <= 0:
                # Defensive fallback from requested quantity if broker omits filled qty.
                filled_quantity = float(placed_order.quantity)

            entry_time = self._format_time(getattr(final_order, "timestamp", None))
            metadata = dict(signal.metadata or {})
            metadata.update(
                {
                    "broker_name": "dhan",
                    "broker_order_id": placed_order_id,
                    "dhan_order_status": str(getattr(final_order.status, "value", final_order.status)),
                    "dhan_filled_quantity": str(filled_quantity),
                    "dhan_avg_fill_price": str(fill_price),
                    "requested_quantity": str(qty),
                }
            )

            # 40/30/30 scale-in plan: the broker only deployed 40% of target.
            # Record the target full size + deployed fraction so
            # Portfolio.add_to_position can size the 30% confirm/breakout adds.
            if (signal.metadata or {}).get("scale_in"):
                deployed_fraction = 0.4
                metadata["full_size"] = str(float(filled_quantity) / deployed_fraction)
                metadata["deployed_fraction"] = str(deployed_fraction)

            self._persist_order_terminal(
                signal,
                "FILLED",
                broker_order_id=placed_order_id,
                filled_quantity=filled_quantity,
                avg_fill_price=fill_price,
            )
            return Position(
                symbol=str(getattr(final_order.instrument, "symbol", symbol)),
                side=Side.LONG if signal.is_buy else Side.SHORT,
                source=signal.source,
                entry_price=_to_decimal(fill_price),
                size=_to_decimal(filled_quantity),
                stop_loss=_to_decimal(signal.stop_loss),
                take_profit=_to_decimal(signal.take_profit),
                entry_time=entry_time,
                # initial_stop is the original stop — required by the exit
                # engine (R-multiple, ATR/VWAP trail, partition exits).  Without
                # it those risk calculations silently no-op on live positions.
                initial_stop=_to_decimal(signal.stop_loss),
                metadata=metadata,
            )
        except DhanError as exc:
            logger.error("Dhan API error executing signal %s: %s", signal.signal_id, exc)
            self._persist_order_terminal(signal, "REJECTED")
            return None
        except Exception as exc:
            logger.exception("Unexpected error executing signal %s: %s", signal.signal_id, exc)
            self._persist_order_terminal(signal, "REJECTED")
            return None

    def close_position(
        self,
        symbol: str,
        side: str,
        quantity: int,
        portfolio: Portfolio,
        reference_price: float | None = None,
    ) -> Position | None:
        """Close (or reduce) an open position by placing an opposing order.

        Args:
            symbol: Trading symbol.
            side: The CLOSING side — "SELL" to close a LONG, "BUY" to close a SHORT.
            quantity: Number of units to close.
            portfolio: Portfolio for cost model / tracking.

        Returns:
            Position with entry_price = actual fill price, or None on failure.
        """
        broker = self._broker
        if broker is None:
            logger.error("DhanBroker not initialized")
            return None
        if quantity <= 0:
            logger.warning("close_position called with quantity=%d for %s", quantity, symbol)
            return None

        try:
            # Build a closing instrument — same symbol, opposite side.
            clean_symbol = str(symbol or "").strip()
            is_option, _is_call, _is_put, dhan_exchange = classify_symbol(clean_symbol)
            if is_option:
                from quant.contracts.instrument_registry import DEFAULT_REGISTRY
                spec = DEFAULT_REGISTRY.try_resolve(clean_symbol)
                exchange = _exchange_enum(spec.dhan_exchange) if spec else dhan_exchange
            else:
                exchange = _exchange_enum(dhan_exchange)

            instrument = Instrument(
                symbol=clean_symbol,
                exchange=exchange,
                security_id="",  # closing order — security_id not required
            )

            # C7: close-side slippage collar. When a reference price is available
            # and the collar is enabled (tol > 0), convert the naked MARKET close
            # into a marketable LIMIT bounded by the close tolerance so a thin
            # contract cannot fill arbitrarily far from the expected exit price.
            # The limit stays marketable (priced to cross the spread) because a
            # close must still fill; tol=0 disables it (plain MARKET).
            tol = getattr(self, "_close_slippage_tol", 0.0)
            order_type = OrderType.MARKET
            limit_price = 0.0
            if reference_price and float(reference_price) > 0 and tol > 0:
                order_type = OrderType.LIMIT
                limit_price = self._marketable_limit_price(
                    float(reference_price), side.upper() == "BUY", tol
                )
            collared = order_type == OrderType.LIMIT
            order = Order(
                instrument=instrument,
                side=side.upper(),  # "SELL" to close LONG, "BUY" to close SHORT
                quantity=quantity,
                order_type=order_type,
                price=limit_price,
                trigger_price=0.0,
                product_type="INTRADAY",
            )
            # Stable logical id lets broker-side correlation deduplicate a
            # repeated close request after a lost response.
            setattr(
                order,
                "user_order_id",
                self._close_order_id(clean_symbol, side, quantity),
            )

            placed_order = broker.place_order(order)
            placed_order_id = str(getattr(placed_order, "order_id", ""))
            if not placed_order_id:
                logger.error("close_position: Dhan place_order did not return order_id for %s", symbol)
                return None

            final_order = self._poll_for_terminal_status(
                placed_order_id, timeout=self._order_poll_timeout
            )
            if final_order is None:
                logger.warning("close_position: order %s did not reach terminal state", placed_order_id)
                try:
                    broker.cancel_order(placed_order_id)
                except Exception:
                    logger.debug("Failed to cancel timed-out close order %s", placed_order_id, exc_info=True)
                # A fill can race the cancel — the post-cancel state decides.
                final_order = self._safe_order_status(placed_order_id)
                if final_order is not None and self._is_filled(final_order):
                    pass  # honored below via the normal filled path
                elif collared and (
                    final_order is None or to_float(final_order.filled_quantity) <= 0
                ):
                    # C7 completion: the collared close missed (stale reference
                    # price — e.g. the EOD backstop using the entry price after
                    # the feed died — or a gap through the collar) and NOTHING
                    # filled. Guarantee the flatten with Dhan's MPP-bounded
                    # MARKET; a zero fill means re-placing full size cannot
                    # over-close.
                    final_order = self._market_fallback_close(
                        symbol, side, quantity, instrument
                    )
                    if final_order is None:
                        return None
                else:
                    return None

            if not self._is_filled(final_order):
                if collared and to_float(final_order.filled_quantity) <= 0:
                    # Same zero-fill guarantee for a terminal non-fill
                    # (CANCELLED/REJECTED collar order with nothing done).
                    final_order = self._market_fallback_close(
                        symbol, side, quantity, instrument
                    )
                    if final_order is None:
                        return None
                else:
                    logger.warning(
                        "close_position: order %s terminal status=%s",
                        placed_order_id, getattr(final_order.status, "value", final_order.status),
                    )
                    return None

            fill_price = (
                to_float(getattr(final_order, "average_fill_price", None))
                or to_float(getattr(final_order, "price", None), 0.0)
                or 0.0
            )
            filled_quantity = to_float(final_order.filled_quantity)
            if filled_quantity <= 0:
                filled_quantity = float(quantity)

            entry_time = self._format_time(getattr(final_order, "timestamp", None))

            return Position(
                symbol=symbol,
                side=Side.LONG if side.upper() == "BUY" else Side.SHORT,
                source=Source.AMT,
                entry_price=_to_decimal(fill_price),  # fill price on close
                size=_to_decimal(filled_quantity),
                stop_loss=_to_decimal(0),
                take_profit=_to_decimal(0),
                entry_time=entry_time,
                metadata={
                    "broker_name": "dhan",
                    "broker_order_id": placed_order_id,
                    "dhan_filled_quantity": str(filled_quantity),
                    "dhan_avg_fill_price": str(fill_price),
                    "close_side": side,
                },
            )
        except DhanError as exc:
            logger.error("Dhan API error closing position for %s: %s", symbol, exc)
            return None
        except Exception as exc:
            logger.exception("Unexpected error closing position for %s: %s", symbol, exc)
            return None

    def cancel_order(self, order_id: str) -> bool:
        broker = self._broker
        if broker is None:
            logger.error("DhanBroker not initialized")
            return False
        if not order_id:
            logger.warning("cancel_order called with empty order_id")
            return False
        try:
            return bool(broker.cancel_order(order_id))
        except DhanError as exc:
            logger.error("Dhan API error canceling order %s: %s", order_id, exc)
            return False
        except Exception as exc:
            logger.exception("Unexpected error canceling order %s: %s", order_id, exc)
            return False

    def get_positions(self) -> list[Position]:
        broker = self._broker
        if broker is None:
            logger.error("DhanBroker not initialized")
            return []

        positions = []
        try:
            raw_positions = broker.get_positions() or []
        except DhanError as exc:
            logger.error("Dhan API error querying open positions: %s", exc)
            return []
        except Exception as exc:
            logger.exception("Unexpected error querying open positions: %s", exc)
            return []

        for raw_pos in raw_positions:
            quantity = _to_decimal(getattr(raw_pos, "quantity", 0))
            if quantity == 0:
                continue
            entry_price = _to_decimal(
                getattr(raw_pos, "avg_price", None),
                default="0",
            )
            symbol_value = str(
                getattr(getattr(raw_pos, "instrument", None), "symbol", "")
            )
            entry_time = self._format_time(getattr(raw_pos, "timestamp", None))
            if not entry_time:
                entry_time = datetime.now().isoformat()

            positions.append(
                Position(
                    symbol=symbol_value,
                    side=Side.LONG if quantity >= 0 else Side.SHORT,
                    source=Source.AMT,
                    entry_price=entry_price,
                    size=abs(quantity),
                    stop_loss=_to_decimal(0),
                    take_profit=_to_decimal(0),
                    entry_time=entry_time,
                    metadata={
                        "broker_name": "dhan",
                        "dhan_symbol": str(symbol_value),
                        "dhan_raw_position": str(type(raw_pos).__name__),
                        "dhan_raw_size": str(quantity),
                    },
                )
            )
        return positions

    def _make_instrument(self, signal: Signal, symbol: str) -> Instrument:
        """Build broker Instrument from symbol and signal metadata."""
        meta = signal.metadata or {}
        clean_symbol = str(symbol or "").strip()
        exchange_hint = meta.get("exchange")
        if ":" in clean_symbol:
            _prefix, _symbol = clean_symbol.split(":", 1)
            if not exchange_hint:
                exchange_hint = _prefix.strip()
            clean_symbol = _symbol.strip()

        is_option, _is_call, _is_put, dhan_exchange = classify_symbol(clean_symbol)
        option_type = meta.get("option_type")
        if option_type is not None and not isinstance(option_type, str):
            option_type = str(option_type)

        option_type_enum = None
        if is_option:
            from brokers.broker.types import OptionType

            option_type_enum = (
                OptionType.PUT if (option_type in {"PUT", "PE", "put", "pe"}) else OptionType.CALL
            )

        if is_option:
            from quant.contracts.instrument_registry import DEFAULT_REGISTRY
            hint = (exchange_hint or "").upper()
            if hint in ("", "NSE", "INDEX"):
                spec = DEFAULT_REGISTRY.try_resolve(clean_symbol)
                exchange = _exchange_enum(spec.dhan_exchange) if spec else dhan_exchange
            else:
                exchange = _exchange_enum(exchange_hint)
            return Instrument(
                symbol=clean_symbol,
                exchange=exchange,
                security_id=str(meta.get("security_id") or meta.get("securityId") or ""),
                option_type=option_type_enum,
            )

        return Instrument(
            symbol=clean_symbol,
            exchange=_exchange_enum(exchange_hint),
            security_id=str(meta.get("security_id") or meta.get("securityId") or ""),
        )

    def _map_order_type(self, signal: Signal) -> OrderType:
        meta = signal.metadata or {}
        raw = str(meta.get("order_type", "MARKET")).strip().upper().replace("-", "_")
        if raw in {"SL", "STOP_LOSS"}:
            return OrderType.SL
        if raw in {"SLM", "STOP_LOSS_MARKET"}:
            return OrderType.SLM
        if raw == "LIMIT":
            return OrderType.LIMIT
        return OrderType.MARKET

    @staticmethod
    def _close_order_id(
        symbol: str, side: str, quantity: int, *, fallback: bool = False
    ) -> str:
        """Build a stable broker correlation id for one logical close."""
        prefix = "close-fallback" if fallback else "close"
        normalized = "".join(
            char if char.isalnum() else "_" for char in str(symbol).upper()
        ).strip("_")
        return f"{prefix}:{normalized}:{side.upper()}:{int(quantity)}"[:36]

    @staticmethod
    def _marketable_limit_price(price: float, is_buy: bool, tolerance_pct: float) -> float:
        """Marketable limit price bounded by ``tolerance_pct`` (C7).

        A BUY is willing to pay up to ``price * (1 + tol)``; a SELL accepts
        down to ``price * (1 - tol)``. The order still crosses the spread and
        fills at market when the market is near ``price``, but it can never
        fill worse than the tolerance — unlike a naked MARKET order.
        """
        if price <= 0 or tolerance_pct <= 0:
            return price
        factor = 1.0 + tolerance_pct if is_buy else 1.0 - tolerance_pct
        return round(price * factor, 2)

    def _safe_order_status(self, order_id: str):
        """Best-effort order-status read (None on any failure)."""
        broker = self._broker
        if broker is None:
            return None
        try:
            return broker.get_order_status(order_id)
        except Exception:
            logger.debug("close_position: status read failed for %s", order_id, exc_info=True)
            return None

    def _market_fallback_close(self, symbol: str, side: str, quantity: int, instrument):
        """C7 completion: guarantee a collared close that missed with ZERO fill.

        A collar can miss when its reference price went stale (the EOD backstop
        uses the entry price once the feed dies) or the market gapped through
        the band — and then the position would never flatten. Since nothing
        filled, re-placing the full size as MARKET cannot over-close, and Dhan
        itself bounds MARKET orders with MPP (market protection %). One attempt
        only: if even this fails, the engine's retry path (C3) and the EOD
        watchdog take over.
        """
        broker = self._broker
        if broker is None:
            return None
        logger.warning(
            "close_position: collared close missed for %s (%s, qty=%d) with zero "
            "fill — re-placing as MPP-bounded MARKET",
            symbol, side.upper(), quantity,
        )
        try:
            fb_order = Order(
                instrument=instrument,
                side=side.upper(),
                quantity=quantity,
                order_type=OrderType.MARKET,
                price=0.0,
                trigger_price=0.0,
                product_type="INTRADAY",
            )
            setattr(
                fb_order,
                "user_order_id",
                self._close_order_id(
                    symbol, side, quantity, fallback=True
                ),
            )
            placed = broker.place_order(fb_order)
            placed_id = str(getattr(placed, "order_id", ""))
            if not placed_id:
                logger.error("close_position: MARKET fallback place_order failed for %s", symbol)
                return None
            final = self._poll_for_terminal_status(placed_id, timeout=self._order_poll_timeout)
            if final is None:
                try:
                    broker.cancel_order(placed_id)
                except Exception:
                    logger.debug("Failed to cancel MARKET fallback %s", placed_id, exc_info=True)
                final = self._safe_order_status(placed_id)
                if final is not None and self._is_filled(final):
                    return final
                return None
            if not self._is_filled(final):
                logger.warning(
                    "close_position: MARKET fallback terminal status=%s for %s",
                    getattr(final.status, "value", final.status), symbol,
                )
                return None
            return final
        except DhanError as exc:
            logger.error("close_position: MARKET fallback Dhan error for %s: %s", symbol, exc)
            return None
        except Exception:
            logger.exception("close_position: MARKET fallback failed for %s", symbol)
            return None

    @staticmethod
    def _resolve_product_type(meta: dict[str, Any]) -> str:
        if "product_type" in meta:
            product_type = str(meta.get("product_type", "")).strip()
            if product_type:
                return product_type
        if "product" in meta:
            product = str(meta.get("product", "")).strip()
            if product:
                return product
        return "INTRADAY"

    def _resolve_quantity(self, signal: Signal, portfolio: Portfolio) -> int:
        meta = signal.metadata or {}
        explicit_qty = to_float(
            meta.get("order_quantity", meta.get("size", 0)),
            default=0.0,
        )
        if explicit_qty > 0:
            return int(explicit_qty)

        if not portfolio:
            logger.error("Cannot auto-size order without Portfolio context for %s", signal.signal_id)
            return 0

        risk_pct = _to_decimal(meta.get("session_risk_pct"), default=str(RISK_PER_TRADE))
        if risk_pct <= 0:
            risk_pct = RISK_BY_CONFIDENCE.get(str(meta.get("confidence", "Medium")), RISK_PER_TRADE)

        # keep Fabio-safe bounds (0.25% - 0.5%)
        risk_pct = max(Decimal("0.0025"), min(Decimal("0.005"), risk_pct))
        risk_amount = portfolio.equity * risk_pct

        risk_per_unit = abs(_to_decimal(signal.price) - _to_decimal(signal.stop_loss))
        if risk_per_unit <= 0:
            return 0

        full_size = risk_amount / risk_per_unit
        max_notional = portfolio.equity * Decimal(str(getattr(portfolio, "leverage", 1)))
        signal_price = _to_decimal(signal.price)
        if full_size * signal_price > max_notional:
            full_size = max_notional / signal_price

        scale_in = bool(meta.get("scale_in", False))
        scale_fraction = Decimal("0.4") if scale_in else Decimal("1")
        quantity = full_size * min(max(scale_fraction, Decimal("0")), Decimal("1"))
        if quantity <= 0:
            return 0

        lot_size = _to_decimal(meta.get("option_lot_size", 0))
        if lot_size > 0:
            # Nearest lot multiple, no truncation.
            num_lots = max(1.0, round(float(quantity) / float(lot_size)))
            quantity = Decimal(int(num_lots)) * lot_size
            if quantity < lot_size * Decimal("0.5"):
                quantity = lot_size

        qty_int = int(quantity)
        if qty_int <= 0:
            return 0

        # Exchange order freeze limit guard (e.g. NIFTY 1800, BANKNIFTY 900)
        sym = str(getattr(signal, "symbol", "") or "")
        is_mcx = ExchangeConfig.for_exchange("MCX").is_underlying(sym)
        ex_cfg = ExchangeConfig.for_exchange("MCX" if is_mcx else "NSE")
        freeze_limit = ex_cfg.get_freeze_limit(sym)
        if freeze_limit > 0 and qty_int > freeze_limit:
            logger.warning(
                "Order quantity %d for %s exceeds exchange freeze limit %d — capping to freeze limit",
                qty_int, getattr(signal, "symbol", ""), freeze_limit
            )
            if lot_size > 0:
                qty_int = max(int(lot_size), int((freeze_limit // int(lot_size)) * int(lot_size)))
            else:
                qty_int = freeze_limit

        return qty_int

    # ------------------------------------------------------------------
    # C4: durable order state persistence (crash recovery)
    # ------------------------------------------------------------------

    def _persist_order_submitted(
        self, signal: Signal, symbol: str, qty: int, order_type, price: float
    ) -> None:
        """Record SUBMITTED before place_order so a crash mid-submit still leaves
        a durable record of the intended order. Best-effort: a persistence
        failure must never block trading."""
        storage = getattr(self, "_storage", None)
        order_id = str(getattr(signal, "signal_id", "") or "").strip()
        if storage is None or not order_id:
            return
        try:
            from quant.contracts.timezones import IST

            now = datetime.now(tz=IST).isoformat()
            storage.save_order(
                {
                    "order_id": order_id,
                    "signal_id": order_id,
                    "symbol": symbol,
                    "side": "BUY" if signal.is_buy else "SELL",
                    "quantity": float(qty),
                    "order_type": str(getattr(order_type, "value", order_type)),
                    "price": float(price),
                    "status": "SUBMITTED",
                    "reason": str(getattr(signal, "reason", "") or ""),
                    "submitted_at": now,
                    "updated_at": now,
                }
            )
        except Exception:
            logger.exception(
                "order persistence (SUBMITTED) failed for %s — trading continues", order_id
            )

    def _persist_order_terminal(
        self,
        signal: Signal,
        status: str,
        *,
        broker_order_id: str | None = None,
        filled_quantity: float | None = None,
        avg_fill_price: float | None = None,
    ) -> None:
        """Transition the durable order row to a new state (best-effort)."""
        storage = getattr(self, "_storage", None)
        order_id = str(getattr(signal, "signal_id", "") or "").strip()
        if storage is None or not order_id:
            return
        if broker_order_id:
            # C4: let the WS feed's callback locate this durable row when the
            # broker pushes updates under its own order id. Lazy mapping so
            # test-built adapters (no __init__) work unchanged.
            mapping = getattr(self, "_broker_order_to_signal", None)
            if mapping is None:
                mapping = {}
                self._broker_order_to_signal = mapping
            mapping[str(broker_order_id)] = order_id
        try:
            storage.update_order_status(
                order_id,
                status,
                broker_order_id=broker_order_id,
                filled_quantity=filled_quantity,
                avg_fill_price=avg_fill_price,
            )
        except Exception:
            logger.exception(
                "order persistence (%s) failed for %s — trading continues", status, order_id
            )

    def _poll_for_terminal_status(
        self,
        order_id: str,
        timeout: float | None = None,
    ):
        """Wait for an order to reach a terminal state.

        Interleaved dual path (C4 async fill feed):

        - **Push**: a WS order update wakes the wait instantly and is honored
          on the next loop pass — no REST call at all when the feed delivers.
        - **Pull**: after every quiet slice (no push within one poll interval)
          exactly one REST status poll fires, preserving the proven legacy
          cadence as the safety net for missed/disconnected feeds.

        When the feed is disabled the behaviour is byte-for-byte the pre-C4
        REST polling loop.
        """
        broker = self._broker
        if broker is None:
            return None

        timeout = float(timeout or self._order_poll_timeout)
        feed = self._ensure_order_feed()
        if feed is None:
            return self._poll_rest_for_terminal_status(order_id, timeout)

        started_at = time.monotonic()
        last_error = None
        while (time.monotonic() - started_at) < timeout:
            if not feed.healthy:
                remaining = timeout - (time.monotonic() - started_at)
                logger.info("Order %s: WS feed down — REST polling takes over", order_id)
                return self._poll_rest_for_terminal_status(order_id, max(remaining, 0.0))

            # Push path: honor any buffered or just-arrived WS update instantly.
            snap = feed.snapshot(order_id)
            if snap is not None:
                ws_order = self._ws_snapshot_to_order(snap)
                if self._is_terminal(ws_order.status):
                    logger.info(
                        "Order %s terminal via WS update: %s",
                        order_id, snap.get("raw_status"),
                    )
                    return ws_order

            remaining = timeout - (time.monotonic() - started_at)
            if remaining <= 0:
                break
            woke = feed.wait_for_update(
                order_id, timeout=min(self._order_poll_interval, remaining)
            )
            if woke:
                continue  # fresh push — re-check snapshot immediately, skip REST
            # Pull path: one REST poll per quiet slice (legacy safety net).
            try:
                order_status = broker.get_order_status(order_id)
                if self._is_terminal(order_status.status):
                    return order_status
            except DhanError as exc:
                last_error = exc
                logger.debug("Dhan get_order_status failed for %s: %s", order_id, exc)
            except Exception as exc:
                last_error = exc
                logger.exception("Unexpected status poll error for %s", order_id)

        logger.warning("Order status poll timed out for %s after %.1fs", order_id, timeout)
        if last_error:
            logger.debug("Last poll error for %s: %s", order_id, last_error)
        return None

    @staticmethod
    def _ws_snapshot_to_order(snap: dict):
        """Adapt a normalized WS snapshot to the shape _is_terminal/_is_filled
        and the execute/close paths already consume (duck-typed order status)."""
        return SimpleNamespace(
            status=snap.get("status"),
            quantity=to_float(snap.get("quantity")),
            filled_quantity=to_float(snap.get("filled_quantity")),
            average_fill_price=to_float(snap.get("average_fill_price")),
            instrument=SimpleNamespace(symbol=str(snap.get("symbol") or "")),
            timestamp=str(snap.get("timestamp") or ""),
        )

    def _ensure_order_feed(self):
        """Return the WS order-update feed (None when disabled).

        Lifecycle policy: the feed object is created once and reused while its
        thread runs — whether connected or still connecting. A dead thread is
        respawned at most once per minute; in between (and whenever the feed is
        unhealthy) the poll loop's REST path covers order status. Test doubles
        without ``is_running`` are treated as running so they are never
        replaced by a real connection.
        """
        if not getattr(self, "_order_feed_enabled", False):
            return None

        def _usable(f) -> bool:
            if f is None:
                return False
            if f.healthy:
                return True
            is_running = getattr(f, "is_running", None)
            return is_running() if callable(is_running) else True

        feed = self._order_feed
        if _usable(feed):
            return feed
        if feed is not None and (time.monotonic() - getattr(self, "_last_feed_start", 0.0)) < 60.0:
            return feed  # recently (re)started and dead — REST covers, no respawn spam

        with self._order_feed_lock:
            feed = self._order_feed
            if _usable(feed):
                return feed
            if feed is not None and (
                time.monotonic() - getattr(self, "_last_feed_start", 0.0)
            ) < 60.0:
                return feed
            try:
                from app.infrastructure.adapters.dhan_order_feed import (
                    DhanOrderUpdateFeed,
                )

                feed = DhanOrderUpdateFeed(
                    client_id=self._client_id,
                    access_token=self._access_token,
                    on_update=self._on_order_feed_update,
                )
                feed.start()
                self._order_feed = feed
                self._last_feed_start = time.monotonic()
                logger.info("Dhan order-update WS feed started")
                return feed
            except Exception:
                logger.exception(
                    "Failed to start order-update WS feed — REST polling remains"
                )
                self._order_feed = None
                return None

    def _on_order_feed_update(self, snap: dict) -> None:
        """WS callback: persist fill state for the durable order row.

        Runs on the feed thread; must never raise into the feed. A crash
        between place_order and the engine's fill handling is exactly the C4
        scenario — persisting here keeps the durable row truthful even when
        the engine thread is blocked or dead.
        """
        try:
            broker_order_id = str(snap.get("order_id") or "")
            if not broker_order_id:
                return
            signal_id = getattr(self, "_broker_order_to_signal", {}).get(broker_order_id)
            storage = getattr(self, "_storage", None)
            if signal_id is None or storage is None:
                return
            durable = {
                OrderStatus.FILLED: "FILLED",
                OrderStatus.COMPLETED: "FILLED",
                OrderStatus.CLOSED: "FILLED",
                OrderStatus.REJECTED: "REJECTED",
                OrderStatus.CANCELLED: "CANCELLED",
            }.get(snap.get("status"))
            if durable is None:
                # Non-terminal transition (PENDING/OPEN): the durable row stays
                # in-flight, which is exactly what restart reconciliation wants.
                return
            filled = to_float(snap.get("filled_quantity"))
            avg = to_float(snap.get("average_fill_price"))
            storage.update_order_status(
                signal_id,
                durable,
                filled_quantity=filled if filled > 0 else None,
                avg_fill_price=avg if avg > 0 else None,
            )
        except Exception:
            logger.exception("order-feed persistence failed — trading continues")

    def _poll_rest_for_terminal_status(
        self,
        order_id: str,
        timeout: float,
    ):
        started_at = time.monotonic()
        last_error = None
        while (time.monotonic() - started_at) < timeout:
            try:
                broker = self._broker
                if broker is None:
                    return None
                order_status = broker.get_order_status(order_id)
                if self._is_terminal(order_status.status):
                    return order_status
            except DhanError as exc:
                last_error = exc
                logger.debug("Dhan get_order_status failed for %s: %s", order_id, exc)
            except Exception as exc:
                last_error = exc
                logger.exception("Unexpected status poll error for %s", order_id)
            time.sleep(self._order_poll_interval)
        logger.warning("Order status poll timed out for %s after %.1fs", order_id, timeout)
        if last_error:
            logger.debug("Last poll error for %s: %s", order_id, last_error)
        return None

    @staticmethod
    def _is_terminal(status: Any) -> bool:
        terminal = {
            OrderStatus.FILLED,
            OrderStatus.COMPLETED,
            OrderStatus.CANCELLED,
            OrderStatus.CLOSED,
            OrderStatus.REJECTED,
        }
        if isinstance(status, OrderStatus):
            return status in terminal
        return str(status).strip().upper() in {s.value for s in terminal}

    @staticmethod
    def _is_filled(order: Any) -> bool:
        status = getattr(order, "status", None)
        if status in {OrderStatus.FILLED, OrderStatus.COMPLETED}:
            return True
        status_value = str(status).strip().upper()
        if status_value in {"FILLED", "COMPLETED"}:
            return True

        quantity = to_float(order.quantity)
        filled_quantity = to_float(order.filled_quantity)
        return quantity > 0 and filled_quantity >= quantity

    @staticmethod
    def _format_time(timestamp: Any) -> str:
        if timestamp is None:
            return ""
        if isinstance(timestamp, str):
            return timestamp
        if isinstance(timestamp, datetime):
            return timestamp.isoformat()
        return ""
