"""Broker port — abstract interface for order execution."""

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
    def cancel_order(self, order_id: str) -> bool:
        """Cancel an open order (like a standalone Stop-Loss bracket) by its ID."""
        ...
