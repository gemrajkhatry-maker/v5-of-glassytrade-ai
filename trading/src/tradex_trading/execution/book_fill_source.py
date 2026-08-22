"""BookFillSource — tick-level L2 order-book matching for scalping realism.

The other fill sources resolve one price (LTP / next-open / limit) and fill
immediately. ``BookFillSource`` instead matches a marketable order **against a
live order book**: a BUY sweeps the asks from the touch upward, a SELL sweeps
the bids from the touch downward, consuming quantity level by level. The fill
price is the volume-weighted average of the levels consumed — real market
impact, so thin books cost more and large orders walk the book (P1a: the
spread-crossing *is* the slippage model here; no separate friction is applied
on top).

Working-order lifecycle: a limit order resting outside the book is **kept**,
and every later ``update_depth`` re-checks it — when the book moves to its
price it fills (published as ``OrderFilled`` when a bus is bound, so the
engine's inbound-fill bridge applies it exactly like a live broker fill).
Partial fills rest their remainder: a limit remainder rests at the limit
price; a market remainder stays marketable and sweeps whatever size appears
next. ``BacktestEngine`` binds the bus and feeds every ``Depth`` snapshot, so
the book at any fill is exactly the last snapshot in the tape — deterministic
given the same tape (replay parity).
"""

from __future__ import annotations

from dataclasses import dataclass, field
from decimal import Decimal
from typing import TYPE_CHECKING, Any

from tradex_domain.enums import OrderSide, OrderStatus
from tradex_domain.events import OrderFilled
from tradex_domain.execution import Fill, Order, OrderRequest
from tradex_domain.value_objects import OrderId, Price, Quantity

from tradex_trading.execution.fill_model import FillModel
from tradex_trading.execution.fill_sources import _make_order

if TYPE_CHECKING:
    from tradex_domain.market import Depth


@dataclass
class _RestingOrder:
    """One working (unfilled or partially filled) order waiting on the book."""

    request: OrderRequest
    order: Order
    remaining: Decimal = field(default_factory=lambda: Decimal("0"))
    #: Limit price; ``None`` means marketable at any price (market order).
    limit_price: Decimal | None = None


class BookFillSource(FillModel):
    """Fill source that matches orders against a live L2 order book.

    Parameters
    ----------
    latency_model:
        Optional latency model; fill timestamps route through it exactly like
        every other ``FillModel`` source (deterministic via the request's
        reference timestamp).
    """

    def __init__(self, latency_model: object | None = None) -> None:
        super().__init__(latency_model=latency_model)
        #: Mutable per-instrument book: {instrument_id: {"bids": [[price, qty], ...],
        #: "asks": [[price, qty], ...]}}. ``Depth`` is frozen, so we keep our own
        #: copy to consume levels across fills.
        self._books: dict[str, dict[str, list[list[Decimal]]]] = {}
        #: Working orders per instrument, in submission order (FIFO matching).
        self._resting: dict[str, list[_RestingOrder]] = {}
        #: Bus for publishing OrderFilled when a resting order fills on a later
        #: Depth update (bind via :meth:`bind_bus`; without one the fills are
        #: simply not emitted — the backtest path always binds).
        self._bus: Any | None = None
        #: Monotonic counter for venue-side fill ids. This source IS the venue,
        #: so every fill it mints carries a distinct ``fill_id`` — the engine's
        #: inbound-fill dedup fingerprints by ``fill_id`` when present, which
        #: keeps two equal-lot, equal-price partial fills of one resting order
        #: from being mistaken for a re-published duplicate.
        self._fill_seq = 0

    def bind_bus(self, bus: Any) -> None:
        """Bind the bus that receives ``OrderFilled`` for resting-order fills."""
        self._bus = bus

    def reset(self) -> None:
        """Drop all book and working-order state (dedicated-run reset).

        ``BacktestEngine.run`` calls this when the source is reused across
        runs — without it, run N+1 would start from run N's consumed book
        and stale resting orders, silently changing fills.
        """
        self._books.clear()
        self._resting.clear()
        self._fill_seq = 0

    def has_book(self, instrument: Any) -> bool:
        """Whether a book snapshot exists for *instrument*."""
        return str(instrument.instrument_id) in self._books

    def update_depth(self, depth: Depth) -> None:
        """Replace the instrument's book with *depth* (snapshot semantics).

        The tape's ``Depth`` events arrive in order, so the book at any fill is
        the last snapshot before it — deterministic for replay. After the
        snapshot lands, resting orders are re-checked: any that become
        marketable sweep the new book and publish ``OrderFilled``.
        """
        key = str(depth.instrument.instrument_id)
        self._books[key] = {
            "bids": [[level[0].value, level[1].value] for level in depth.bids],
            "asks": [[level[0].value, level[1].value] for level in depth.asks],
        }
        self._match_resting(key, depth)

    def submit(self, request: OrderRequest) -> tuple[Order, Fill | None]:
        """Match *request* against the instrument's current book.

        Marketable orders sweep immediately. A non-marketable limit order (or
        a market order with nothing to sweep) is **rested**: it stays in the
        working-order queue and is re-checked on every later ``update_depth``,
        filling when the book moves to its price. Returns ``(order, None)``
        for rested orders — the ACK the engine caches, later filled via the
        bound bus.
        """
        book = self._books.get(str(request.instrument.instrument_id))
        order = _make_order(request, status=OrderStatus.ACK)
        if book is None:
            # No book has ever been seen — nothing to evaluate against; rest
            # the order so it fills when the first snapshot lands.
            self._rest(request, order, request.quantity.value)
            return order, None
        if request.side is OrderSide.BUY:
            levels = book["asks"]
            marketable = not levels or (
                request.price is None or request.price.value >= levels[0][0]
            )
        else:
            levels = book["bids"]
            marketable = not levels or (
                request.price is None or request.price.value <= levels[0][0]
            )
        if not marketable:
            # Limit order resting outside the book — keep it working.
            self._rest(request, order, request.quantity.value)
            return order, None

        consumed, notional = self._sweep(levels, request.quantity.value)
        if consumed <= 0:
            # No size on the relevant side of the book — rest as a marketable
            # remainder so it sweeps whatever size appears next.
            self._rest(request, order, request.quantity.value)
            return order, None

        filled = self._filled_order(request, order, consumed)
        fill = self._make_fill(request, filled, consumed, notional)
        if consumed < request.quantity.value:
            # Partial: the remainder keeps working (limit at its price, market
            # stays marketable).
            self._rest(
                request, order, request.quantity.value - consumed,
                limit_price=request.price.value if request.price is not None else None,
            )
            return filled, fill
        return filled, fill

    def _rest(
        self,
        request: OrderRequest,
        order: Order,
        remaining: Decimal,
        *,
        limit_price: Decimal | None = None,
    ) -> None:
        """Queue a working order (submission order = FIFO matching)."""
        if limit_price is None and request.price is not None:
            limit_price = request.price.value
        key = str(request.instrument.instrument_id)
        self._resting.setdefault(key, []).append(
            _RestingOrder(
                request=request,
                order=order,
                remaining=remaining,
                limit_price=limit_price,
            )
        )

    def _match_resting(self, key: str, depth: Depth) -> None:
        """Re-check working orders for *key* against the fresh book.

        Each resting order that has become marketable sweeps the book in FIFO
        order and publishes an ``OrderFilled`` for the matched quantity;
        unfilled remainders stay working. Fills are stamped with the depth's
        timestamp (the tick that triggered them).
        """
        book = self._books.get(key)
        if book is None:
            return
        resting = self._resting.get(key, [])
        still: list[_RestingOrder] = []
        for entry in resting:
            if entry.remaining <= 0:
                continue
            if entry.request.side is OrderSide.BUY:
                levels = book["asks"]
                marketable = not levels or (
                    entry.limit_price is None or entry.limit_price >= levels[0][0]
                )
            else:
                levels = book["bids"]
                marketable = not levels or (
                    entry.limit_price is None or entry.limit_price <= levels[0][0]
                )
            if not marketable:
                still.append(entry)
                continue
            consumed, notional = self._sweep(levels, entry.remaining)
            if consumed <= 0:
                still.append(entry)
                continue
            entry.remaining -= consumed
            filled = self._filled_order(
                entry.request, entry.order, consumed,
            )
            fill = self._make_fill(
                entry.request, filled, consumed, notional,
                timestamp=depth.timestamp,
            )
            if self._bus is not None:
                self._bus.publish(OrderFilled(fill=fill))
            if entry.remaining > 0:
                still.append(entry)
        self._resting[key] = still

    def _filled_order(
        self, request: OrderRequest, order: Order, consumed: Decimal
    ) -> Order:
        """Order reflecting a *consumed*-qty fill (FILLED or PARTIALLY_FILLED)."""
        return _make_order(
            request,
            status=(
                OrderStatus.PARTIALLY_FILLED
                if consumed < request.quantity.value
                else OrderStatus.FILLED
            ),
            order_id=order.order_id,
        )

    def _make_fill(
        self,
        request: OrderRequest,
        order: Order,
        consumed: Decimal,
        notional: Decimal,
        *,
        timestamp: Any = None,
    ) -> Fill:
        """Fill for a swept quantity at the volume-weighted average price.

        The fill carries the CONSUMED quantity (a partial fill must not report
        the full requested quantity), unlike the single-price sources where
        fill qty == order qty. ``timestamp`` falls back to the deterministic
        request-referenced timestamp (latency model applied).
        """
        self._fill_seq += 1
        return Fill(
            order_id=order.order_id,
            instrument=order.instrument,
            side=order.side,
            quantity=Quantity(value=Decimal(str(consumed))),
            price=Price(value=notional / consumed),
            timestamp=timestamp or self.fill_timestamp(request),
            fill_id=f"book:{order.order_id.value}:{self._fill_seq}",
        )

    def _sweep(
        self, levels: list[list[Decimal]], quantity: Decimal
    ) -> tuple[Decimal, Decimal]:
        """Consume *quantity* from *levels*, returning (filled_qty, notional).

        Walks from the touch (index 0) outward, taking ``min(level_qty,
        remaining)`` at each level and mutating the stored book so a later
        order sees the reduced depth. ``filled_qty`` may be less than
        *quantity* when the book is exhausted (partial fill).
        """
        remaining = quantity
        consumed = Decimal("0")
        notional = Decimal("0")
        for level in levels:
            if remaining <= 0:
                break
            take = min(level[1], remaining)
            consumed += take
            notional += take * level[0]
            level[1] -= take
            remaining -= take
        # Drop exhausted levels so future sweeps never re-fill them.
        levels[:] = [lv for lv in levels if lv[1] > 0]
        return consumed, notional

    def cancel(self, order_id: OrderId) -> None:
        """Remove a working order from the queue (no-op for already-filled)."""
        for key, entries in self._resting.items():
            before = len(entries)
            self._resting[key] = [
                e for e in entries if e.order.order_id != order_id
            ]
            if len(self._resting[key]) != before:
                return
