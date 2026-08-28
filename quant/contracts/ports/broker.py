"""Broker port — abstract interface for order execution.

Dual-port note (WS4, 2026-08-25): the canonical broker abstraction for this
repo is ``brokers.broker.ports.IBrokerPort`` (8 ISP protocols + primary ABC).
``IBroker`` here is the legacy quant-side port and remains LIVE: it is
implemented by the backend DI adapters
(``app.infrastructure.adapters.dhan_broker_adapter.DhanBrokerAdapter`` and
``app.infrastructure.adapters.paper_broker.PaperBrokerAdapter``), resolved via
``app.application.di.composition_root``, and consumed by ``backend/app/main.py``
and the FastAPI dependencies. Its only quant-internal caller class is
``quant.execution.live_oms.LiveOMS``, which itself is currently dead code
(see spec open-decision #1). Do not delete either port without migrating the
DI composition root first.
"""

from __future__ import annotations

from abc import ABC, abstractmethod

from quant.contracts.entities import Position, Signal
from quant.contracts.aggregates import Portfolio


class IBroker(ABC):
    """Abstract broker for executing trade orders (paper or live)."""

    @abstractmethod
    def execute_order(
        self, signal: Signal, portfolio: Portfolio, symbol: str
    ) -> Position | None:
        """Execute an order based on *signal*.

        Returns the opened Position, or None if the order was rejected.
        """

    @abstractmethod
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
            reference_price: Optional expected exit price. Live brokers may use it
                to bound slippage (marketable-LIMIT collar); a close must still
                fill, so implementations treat this as advisory, not a hard gate.

        Returns:
            Position with entry_price = actual fill price, or None on failure.
        """
        ...

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order (like a standalone Stop-Loss bracket) by its ID."""
        ...
