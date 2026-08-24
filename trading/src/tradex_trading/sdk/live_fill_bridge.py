"""Live order-stream → OrderFilled bridge (HIGH-4 live half).

Live brokers ACK orders synchronously with no fill; the broker's order
stream later pushes updates carrying a *cumulative* filled quantity. This
bridge watches those updates and publishes an ``OrderFilled`` event for each
newly-filled delta, which the ExecutionEngine's fill subscription
(``_apply_fill``) applies to the OMS idempotently — so live fills reach the
PositionManager just like simulated/paper fills.

Cumulative-update safety: the delta is computed against the engine cache's
own ``filled_quantity`` (accumulated by ``OrderManager.on_order_filled``), so
re-published updates with no new quantity publish nothing, and each partial
fill lands exactly once. Engine orders are matched to broker rows via the
correlation id the broker echoes back (``DhanClientFacade`` submits with the
request's correlation id); unmatched rows are recorded by the engine's
unknown-order path. The check-then-publish delta is not locked: the broker
order stream delivers updates sequentially on a single receive thread, and
the engine's per-occurrence fingerprint dedup rescues an identical duplicate
should one ever interleave — matches simulated/paper behavior.

Timestamps: fills are stamped with the wall clock (``datetime.now(UTC)``) —
a deliberate live-only exception to the deterministic-reference timestamps
used by simulated/paper fills, because live fills are real-time events and
real timestamps are the accurate record. If a future broker row carries a
trade timestamp, prefer it here.
"""

from __future__ import annotations

import logging
import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import UTC, datetime
from decimal import Decimal, InvalidOperation

from tradex_domain.enums import OrderStatus
from tradex_domain.events import OrderFilled
from tradex_domain.execution import Fill, Order
from tradex_domain.value_objects import OrderId, Price, Quantity

log = logging.getLogger(__name__)

_FILL_STATUSES = frozenset({OrderStatus.FILLED, OrderStatus.PARTIALLY_FILLED})


@dataclass(frozen=True, slots=True)
class TradeRef:
    """A broker exchange trade: its trade id and traded price (if reported)."""

    trade_id: str
    price: Decimal | None = None


class TradeBookFillIdResolver:
    """Hand out distinct exchange trade ids per order from a broker's REST
    trade book, so genuine equal-lot partial fills get distinguishable
    ``fill_id`` values (closes the Dhan ``tradeId`` → ``Fill.fill_id`` gap).

    The engine's live-fill dedup fingerprints a fill by ``fill_id`` when one
    is present; without it, two equal-lot, same-price partials of one order
    are indistinguishable from a re-publish and the second is silently
    skipped — under-counting the position. Each new delta's fill is stamped
    with the next unseen trade id for that order from the trade book; a
    re-published delta reuses the same id (so the engine skips it) and a
    network failure yields ``None`` (caller falls back to the composite
    fingerprint — current behavior).
    """

    def __init__(
        self,
        trade_book: Callable[[], list[dict]],
        *,
        order_id_key: str = "orderId",
        trade_id_key: str = "tradeId",
        price_keys: tuple[str, ...] = (
            "tradedPrice", "traded_price", "average_price",
        ),
    ) -> None:
        """
        Parameters
        ----------
        trade_book : Callable[[], list[dict]]
            Zero-arg callable returning the broker's executed-trade rows
            (e.g. ``DhanClientFacade.trade_book`` → ``GET /trades``).
        price_keys : tuple[str, ...]
            Candidate row keys for the traded price (Dhan uses
            ``tradedPrice``, Upstox ``average_price``). The first key present
            with a parseable value wins.
        """
        self._trade_book = trade_book
        self._order_id_key = order_id_key
        self._trade_id_key = trade_id_key
        self._price_keys = price_keys
        self._given: dict[str, set[str]] = {}
        self._lock = threading.Lock()

    def next_trade(self, order_id: str) -> TradeRef | None:
        """Next unseen trade for *order_id*, or ``None`` when the trade book
        is unavailable or has nothing new. Each returned trade id is handed
        out at most once per order; re-published updates reuse their id. The
        ref carries the trade's price when the row reports one.

        Note: called once per live fill delta — one ``GET /trades`` REST
        call each. Acceptable for partial-fill rates; a short TTL cache
        would cut traffic if a broker ever floods per-trade updates.
        """
        with self._lock:
            given = self._given.setdefault(order_id, set())
            try:
                rows = self._trade_book()
            except Exception:  # noqa: BLE001 – network hiccup: degrade to composite fingerprint
                return None
            for row in rows:
                oid = row.get(self._order_id_key)
                tid = row.get(self._trade_id_key)
                # str-normalize the row's order id: a numeric orderId from a
                # broker must still match (and never silently drop the benefit).
                if str(oid) == order_id and tid is not None and str(tid) not in given:
                    given.add(str(tid))
                    return TradeRef(trade_id=str(tid), price=self._price_of(row))
            return None

    def _price_of(self, row: dict) -> Decimal | None:
        """Traded price from a trade-book row, or ``None`` if unreported."""
        for key in self._price_keys:
            value = row.get(key)
            if value not in (None, ""):
                try:
                    return Decimal(str(value))
                except (InvalidOperation, ValueError):
                    continue
        return None


class LiveFillBridge:
    """Translate broker order-stream updates into bus ``OrderFilled`` events."""

    def __init__(
        self,
        bus,
        engine,
        subscribe_orders,
        trade_id_resolver: TradeBookFillIdResolver | None = None,
        *,
        unsubscribe_orders: Callable[[object], None] | None = None,
    ) -> None:
        """``subscribe_orders`` is the broker stream backend's subscribe method
        (``backend.subscribe_orders(handler)``); the bridge owns the returned
        subscription and tears it down in :meth:`close`. ``unsubscribe_orders``
        is the backend's ``unsubscribe(subscription_id)`` — the real Dhan/
        Upstox backends return a subscription id string and drop it via
        ``unsubscribe``, matching ``MarketFeed``. When it is None, the bridge
        falls back to a duck-typed ``.dispose()`` on the returned object
        (test/double streams). ``trade_id_resolver``, when provided, stamps
        each delta ``Fill.fill_id`` with the broker's exchange trade id so
        equal-lot partials dedup exactly (see :class:`TradeBookFillIdResolver`)."""
        self._bus = bus
        self._engine = engine
        self._resolver = trade_id_resolver
        self._unsubscribe_orders = unsubscribe_orders
        self._subscription = subscribe_orders(self._on_order)

    def _on_order(self, order: Order) -> None:
        """Emit an OrderFilled for the newly-filled delta of *order*."""
        if order.status not in _FILL_STATUSES:
            return
        total = order.filled_quantity.value
        if total <= 0:
            return  # no tradeable fill yet (e.g. a status-only update)

        order_id = self._engine_order_id(order) or order.order_id.value
        delta = total - self._applied(order_id)
        if delta <= 0:
            return  # no new fill — duplicate/older cumulative update

        # Resolve the exchange trade id AND the traded price from the REST
        # trade book. The stream row's price is already the traded price for
        # Dhan/Upstox when present; the trade book is the authoritative
        # fallback when it is missing (e.g. a market order with no limit and
        # no ``tradedPrice``).
        fill_id = None
        fill_price = order.price
        if self._resolver is not None:
            ref = self._resolver.next_trade(order.order_id.value)
            if ref is not None:
                fill_id = ref.trade_id
                if ref.price is not None:
                    fill_price = Price(value=ref.price)

        if fill_price is None or fill_price.value <= 0:
            return  # no tradeable price anywhere — nothing to do

        fill = Fill(
            order_id=OrderId(value=order_id),
            instrument=order.instrument,
            side=order.side,
            quantity=Quantity(value=delta),
            price=fill_price,
            timestamp=datetime.now(UTC),
            fill_id=fill_id,
        )
        self._bus.publish(OrderFilled(fill=fill))
        log.info(
            "Stream fill delta %s @ %s for %s (total %s, fill_id=%s)",
            delta, fill_price.value, order_id, total, fill_id,
        )

    def _engine_order_id(self, order: Order) -> str | None:
        """The engine's own order id for a broker row, matched by correlation
        id (the broker echoes the request's correlation id)."""
        oid = getattr(order, "correlation_id", None)
        if oid is None:
            return None
        for cached in self._engine.cache.all_orders():
            cid = getattr(cached, "correlation_id", None)
            if cid is not None and cid.value == oid.value:
                return cached.order_id.value
        return None

    def _applied(self, order_id: str) -> Decimal:
        """Quantity already applied for this order in the OMS cache."""
        cached = self._engine.cache.get_order(order_id)
        if cached is None:
            return Decimal("0")
        return cached.filled_quantity.value

    def close(self) -> None:
        """Tear down the order-stream subscription.

        Prefers the backend's ``unsubscribe(subscription_id)`` (the real
        Dhan/Upstox contract); falls back to a duck-typed ``.dispose()`` for
        streams that return a disposable object.
        """
        try:
            if self._unsubscribe_orders is not None:
                self._unsubscribe_orders(self._subscription)
            elif hasattr(self._subscription, "dispose"):
                self._subscription.dispose()
        except Exception as exc:  # pragma: no cover
            log.error("error disposing live fill bridge: %s", exc)


__all__ = ["LiveFillBridge", "TradeBookFillIdResolver"]
