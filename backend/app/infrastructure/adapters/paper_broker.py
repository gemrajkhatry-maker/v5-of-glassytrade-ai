"""Paper broker adapter — implements BrokerPort for simulated order execution.

Delegates position sizing to the Portfolio aggregate's open_position() method
so that risk constraints are enforced in the domain layer.
"""

from __future__ import annotations

from app.domain.trading.models.entities import Position, Signal
from app.domain.trading.models.aggregates import Portfolio
from app.domain.ports.broker import BrokerPort


class PaperBrokerAdapter(BrokerPort):
    """Paper trading broker — instant fill, no slippage."""

    def execute_order(
        self, signal: Signal, portfolio: Portfolio, symbol: str
    ) -> Position | None:
        """Execute a paper order.

        Delegates to Portfolio.open_position which enforces invariants.
        """
        return portfolio.open_position(signal, symbol)
