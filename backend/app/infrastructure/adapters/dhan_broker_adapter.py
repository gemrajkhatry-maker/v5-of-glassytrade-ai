"""Live Dhan broker adapter for order execution and reconciliation."""

from __future__ import annotations

import logging
import os
import pathlib
import sys
import threading
import time
from datetime import datetime
from decimal import Decimal
from typing import Any

# Ensure the brokers package at repository root is importable from backend modules.
_this_file = pathlib.Path(__file__).resolve()
for _ancestor in _this_file.parents:
    if (_ancestor / "brokers").is_dir():
        root = str(_ancestor)
        if root not in sys.path:
            sys.path.insert(0, root)
        break

from app.config import Configuration
from app.domain.ports.broker import IBroker
from app.domain.trading.models.aggregates import (
    RISK_BY_CONFIDENCE,
    RISK_PER_TRADE,
    Portfolio,
)
from app.domain.trading.models.entities import Position, Signal
from app.domain.trading.models.enums import Side, Source
from brokers.broker import Exchange
from brokers.broker import Instrument, Order
from brokers.broker.types import OrderStatus, OrderType
from brokers.broker.dhan.application.broker import DhanBroker
from brokers.broker.dhan.domain.errors import DhanError

logger = logging.getLogger(__name__)


def _exchange_enum(exchange_str: str | None) -> Exchange:
    mapping = {
        "NSE": Exchange.NSE,
        "NFO": Exchange.NFO,
        "MCX": Exchange.MCX,
        "BSE": Exchange.NSE,
        "INDEX": Exchange.NSE,
    }
    result = mapping.get((exchange_str or "NSE").upper())
    if result is None:
        logger.warning("Unknown exchange '%s', defaulting to NSE", exchange_str)
        result = Exchange.NSE
    return result


def _to_decimal(value: Any, default: str = "0") -> Decimal:
    if isinstance(value, Decimal):
        return value
    if value is None:
        return Decimal(default)
    try:
        return Decimal(str(value))
    except Exception:
        return Decimal(default)


def _to_float(value: Any, default: float = 0.0) -> float:
    try:
        if value is None:
            return default
        return float(value)
    except (TypeError, ValueError):
        return default


class DhanBrokerAdapter(IBroker):
    """Dhan order execution adapter wired to `brokers` library.

    It implements the synchronous ``IBroker`` contract while performing all network
    calls via ``DhanBroker``'s internal sync wrappers, which already bridge async
    internally.
    """

    _MCX_UNDERLYINGS = frozenset(
        {
            "CRUDEOIL",
            "GOLD",
            "SILVER",
            "NATURALGAS",
            "GOLDM",
            "SILVERM",
            "CRUDEOILM",
            "COPPER",
            "ZINC",
            "ALUMINIUM",
            "LEAD",
            "NICKEL",
            "COTTONCANDY",
        }
    )

    def __init__(self, config: Configuration):
        self._config = config
        self._broker: DhanBroker | None = None
        self._broker_lock = threading.Lock()
        self._order_poll_interval = float(
            os.environ.get("DHAN_ORDER_POLL_INTERVAL_SEC", "0.5")
        )
        self._order_poll_timeout = float(
            os.environ.get("DHAN_ORDER_POLL_TIMEOUT_SEC", "30")
        )

        client_id = str(
            getattr(self._config, "dhan_client_id", None) or os.getenv("DHAN_CLIENT_ID", "")
        ).strip()
        access_token = str(
            getattr(self._config, "dhan_access_token", None)
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

        try:
            instrument = self._make_instrument(signal, symbol)
            order = Order(
                instrument=instrument,
                side="BUY" if signal.is_buy else "SELL",
                quantity=qty,
                order_type=self._map_order_type(signal),
                price=float(entry_price),
                trigger_price=_to_float(signal.stop_loss),
                product_type=self._resolve_product_type(signal.metadata or {}),
            )
            # Preserve source trace in in-memory object; Dhan converter sends
            # payload from known fields and ignores extra attrs.
            setattr(order, "user_order_id", str(signal.signal_id))

            placed_order = broker.place_order(order)
            placed_order_id = str(getattr(placed_order, "order_id", ""))
            if not placed_order_id:
                logger.error("Dhan place_order did not return order_id for %s", signal.signal_id)
                return None

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
                return None

            if not self._is_filled(final_order):
                logger.warning(
                    "Order %s terminal status=%s, filled=%s/%s",
                    placed_order_id,
                    getattr(final_order.status, "value", final_order.status),
                    _to_float(final_order.filled_quantity),
                    _to_float(final_order.quantity),
                )
                return None

            fill_price = (
                _to_float(getattr(final_order, "average_fill_price", None))
                or _to_float(getattr(final_order, "price", None), _to_float(signal.price))
                or 0.0
            )
            filled_quantity = _to_float(final_order.filled_quantity)
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

            return Position(
                symbol=str(getattr(final_order.instrument, "symbol", symbol)),
                side=Side.LONG if signal.is_buy else Side.SHORT,
                source=signal.source,
                entry_price=_to_decimal(fill_price),
                size=_to_decimal(filled_quantity),
                stop_loss=_to_decimal(signal.stop_loss),
                take_profit=_to_decimal(signal.take_profit),
                entry_time=entry_time,
                metadata=metadata,
            )
        except DhanError as exc:
            logger.error("Dhan API error executing signal %s: %s", signal.signal_id, exc)
            return None
        except Exception as exc:
            logger.exception("Unexpected error executing signal %s: %s", signal.signal_id, exc)
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

        sym_upper = clean_symbol.upper()
        is_option = (
            ("CALL" in sym_upper)
            or ("PUT" in sym_upper)
            or sym_upper.endswith("CE")
            or sym_upper.endswith("PE")
        )
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
            is_mcx = any(sym_upper.startswith(u) for u in self._MCX_UNDERLYINGS)
            exchange = _exchange_enum("MCX" if is_mcx else "NFO")
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
        explicit_qty = _to_float(
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
        return qty_int

    def _poll_for_terminal_status(
        self,
        order_id: str,
        timeout: float | None = None,
    ):
        broker = self._broker
        if broker is None:
            return None

        timeout = float(timeout or self._order_poll_timeout)
        started_at = time.monotonic()
        last_error = None
        while (time.monotonic() - started_at) < timeout:
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

        quantity = _to_float(order.quantity)
        filled_quantity = _to_float(order.filled_quantity)
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
