"""Portfolio Coordinator — Stub.

Planned feature: Central portfolio coordinator that consumes signals
from the SignalBus and makes portfolio-level decisions (entry, exit, sizing).

Status: Stub — types defined but not fully implemented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Optional, Any


@dataclass
class RejectionResult:
    """Result when a signal is rejected by the portfolio coordinator."""
    rejected: bool = False
    reason: str = ""


class PortfolioCoordinator:
    """Coordinate portfolio-level decisions from incoming signals.

    Stub implementation — accepts all signals (no rejections) until
    fully implemented.
    """

    def __init__(self):
        self._signals_received: int = 0
        self._signals_rejected: int = 0

    def evaluate(self, signal: Any, symbol: str = "") -> Optional[RejectionResult]:
        """Evaluate a signal and return rejection reason if rejected."""
        self._signals_received += 1
        return None

    def get_stats(self) -> dict:
        """Return coordinator statistics."""
        return {
            "signals_received": self._signals_received,
            "signals_rejected": self._signals_rejected,
        }
