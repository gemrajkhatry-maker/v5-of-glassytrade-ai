"""FillModel — the single fill-resolution path shared by every execution mode.

CROSS-MODE PARITY: backtest (SimulatedFillSource), paper (PaperFillSource),
live (BrokerFillSource) and replay (ReplayFillSource) all build their Fill from
the same price-resolution + slippage + timestamp rules, so the same input
events produce identical fill prices and quantities in every mode (HIGH-6b).
"""

from __future__ import annotations

from datetime import UTC, datetime
from typing import TYPE_CHECKING

from tradex_domain.enums import OrderSide
from tradex_domain.execution import Fill, Order, OrderRequest
from tradex_domain.value_objects import OrderId, Price

if TYPE_CHECKING:
    from tradex_domain.market import Depth


class FillModel:
    """Encapsulates the COMMON fill logic shared by all fill sources.

    Each fill source keeps only its mode-specific concerns — Paper's LTP
    cache lookup, Broker's ACK-only submission, Replay's recorded-fill
    re-stamp — and delegates price resolution, slippage, the
    ValueError-on-zero-price guard, latency, and deterministic Fill
    construction here.
    """

    def __init__(
        self,
        slippage_model: object | None = None,
        latency_model: object | None = None,
    ) -> None:
        self._slippage_model = slippage_model
        self._latency_model = latency_model

    def resolve_fill_price(
        self,
        request: OrderRequest,
        market_price: Price | None = None,
        book: Depth | None = None,
    ) -> Price:
        """Resolve the fill price for *request* and apply slippage.

        Order-book aware: when *book* (a ``Depth`` snapshot) is provided the
        fill crosses the spread at the touch — BUY pays the best ask
        (``asks[0]``), SELL receives the best bid (``bids[0]``) — instead of
        filling at mid/LTP. Otherwise uses *market_price* (an LTP quote / next
        bar's open reference), falling back to the request's limit price, then
        its trigger price.

        Raises ValueError on a non-positive price so a zero-priced fill can
        never silently corrupt P&L (avg_price=0). Slippage (if configured) is
        applied identically for every source, so net P&L agrees across
        backtest/paper/live for the same events.
        """
        price: Price | None = None
        if book is not None and book.bids and book.asks:
            touch = book.asks[0][0] if request.side is OrderSide.BUY else book.bids[0][0]
            price = touch
        if price is None:
            price = market_price
        if price is None:
            price = request.price or request.trigger_price
        if price is None or price.value <= 0:
            raise ValueError(
                f"cannot fill {request.instrument} ({request.side.value}) "
                f"without a positive price"
            )
        if self._slippage_model is not None and hasattr(
            self._slippage_model, "apply"
        ):
            price = self._slippage_model.apply(
                price, request.side, request.quantity
            )
        return price

    def fill_timestamp(self, request: OrderRequest) -> datetime:
        """Deterministic fill timestamp — the request's market-data reference
        timestamp, or ``now(UTC)``, plus the configured latency model (P1a).
        Reproducible event logs across runs."""
        base = request.reference_timestamp or datetime.now(UTC)
        if self._latency_model is not None and hasattr(
            self._latency_model, "apply"
        ):
            base = self._latency_model.apply(base)
        return base

    def make_fill(
        self,
        order: Order,
        price: Price,
        timestamp: datetime,
        order_id_override: OrderId | None = None,
    ) -> Fill:
        """Build a Fill from an order + resolved price.

        ``order_id_override`` lets a source re-stamp the fill with a different
        order id (Replay matches the fill to the replayed order).
        """
        return Fill(
            order_id=order_id_override or order.order_id,
            instrument=order.instrument,
            side=order.side,
            quantity=order.quantity,
            price=price,
            timestamp=timestamp,
        )

    @staticmethod
    def restamp_fill(fill: Fill, order_id: OrderId) -> Fill:
        """Rebuild a fill with a new order id, preserving its recorded identity
        (instrument/side/quantity/price/timestamp). Used by ReplayFillSource to
        match a historical fill to the freshly minted order."""
        return Fill(
            order_id=order_id,
            instrument=fill.instrument,
            side=fill.side,
            quantity=fill.quantity,
            price=fill.price,
            timestamp=fill.timestamp,
        )


__all__ = ["FillModel"]
