"""Broker port — abstract interface for order execution."""

from __future__ import annotations

from abc import ABC, abstractmethod

from app.domain.trading.model.entities import Position, Signal
from app.domain.trading.model.aggregates import Portfolio


class IBroker(ABC):
    """Abstract broker for executing trade orders (paper or live).

    Domain defines this port. Infrastructure provides the adapter.
    """

    @abstractmethod
    def execute_order(
        self, signal: Signal, portfolio: Portfolio, symbol: str
    ) -> Position | None:
        """Execute an order based on *signal*.

        Returns the opened Position, or None if the order was rejected.
        """

    @abstractmethod
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order by its ID."""

    @abstractmethod
    def close_position(self, position_id: str, price: float) -> bool:
        """Close an open position at the given price."""
