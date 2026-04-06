"""Scalp Exit Rules — Stub.

Planned feature: Fast exit management for scalp trades with
ladder-based take profits and counter-aggression exits.

Status: Stub — types defined but not fully implemented.
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional


class ScalpExitAction(str, Enum):
    """Possible scalp exit actions."""
    NONE = "NONE"
    TRAIL_STOP = "TRAIL_STOP"
    PARTIAL_TAKE_PROFIT = "PARTIAL_TAKE_PROFIT"
    BREAKEVEN = "BREAKEVEN"
    FULL_EXIT = "FULL_EXIT"
    COUNTER_AGGRESSION = "COUNTER_AGGRESSION"


class ScalpExitResult:
    """Result of scalp exit evaluation.

    Stub class — all fields default to no-op.
    """

    def __init__(
        self,
        action: ScalpExitAction = ScalpExitAction.NONE,
        price: float = 0.0,
        partial_pct: float = 0.0,
        reason: str = "",
    ):
        self.action = action
        self.price = price
        self.partial_pct = partial_pct
        self.reason = reason

    @property
    def is_exit(self) -> bool:
        return self.action != ScalpExitAction.NONE


class ScalpExitEngine:
    """Evaluate exit conditions for scalp trades.

    Stub implementation — returns no exit action until fully implemented.
    """

    def check(
        self,
        entry_price: float,
        current_price: float,
        stop_loss: float,
        take_profit: float,
        is_long: bool = True,
        cvd_slope: float = 0.0,
        **kwargs,
    ) -> ScalpExitResult:
        """Check all scalp exit conditions."""
        return ScalpExitResult()
