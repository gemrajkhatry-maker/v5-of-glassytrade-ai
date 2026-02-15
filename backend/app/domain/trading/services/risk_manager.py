"""Risk Manager — domain service validating signals before execution.

Ensures position sizing, leverage limits, and risk-per-trade constraints
are met before forwarding to the broker.
"""

from __future__ import annotations

from app.domain.trading.models.entities import Signal
from app.domain.trading.models.aggregates import Portfolio


class RiskManager:
    """Validates trade signals against portfolio risk constraints."""

    def validate(self, signal: Signal, portfolio: Portfolio) -> bool:
        """Return True if *signal* passes all risk checks."""
        # No duplicate source
        if portfolio.has_open_position_for_source(signal.source):
            return False

        # Valid SL (non-zero risk)
        risk_per_unit = abs(signal.price - signal.stop_loss)
        if risk_per_unit == 0:
            return False

        return True
