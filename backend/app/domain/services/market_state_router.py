"""Market State Router — hard blocks AAA model in BALANCED session.

CHANGE 2: Routes to the correct model based on market state.
HARD BLOCK AAA model when session is BALANCED — do not evaluate it at all.

Route table:
  Session=IMBALANCED AND Leg=IMBALANCED  → AAA Trend Model
  Session=BALANCED   AND Leg=BALANCED    → Mean Reversion Model
  Session=BALANCED   AND Leg=IMBALANCED  → Mean Reversion Model only
  CHOP confidence > 75%                  → SKIP (no model runs)
  Contraction detected                   → SKIP
    (current N-candle range < 30% of last expansion leg range)
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC


class ModelRoute(str, Enum):
    AAA_TREND = "AAA_TREND"
    MEAN_REVERSION = "MEAN_REVERSION"
    SKIP = "SKIP"


@dataclass(frozen=True)
class RoutingResult:
    """Result of model routing decision."""

    route: ModelRoute
    reason: str
    chop_confidence: float
    is_contracted: bool


class MarketStateRouter:
    """Routes to correct model based on market state.

    Implements CHANGE 2: HARD BLOCK AAA model when session is BALANCED.
    """

    def route(
        self,
        session_state: str,  # "IMBALANCED", "BALANCED", "NO_TRADE", "PROBING"
        leg_state: str,  # "IMBALANCED", "BALANCED"
        chop_confidence: float = 0.0,
        is_contracted: bool = False,
    ) -> RoutingResult:
        """Route to model based on session state, leg state, and conditions.

        Returns RoutingResult with the model to run (or SKIP).
        """
        # Skip conditions
        if chop_confidence > 75.0:
            return RoutingResult(
                route=ModelRoute.SKIP,
                reason=f"CHOP confidence {chop_confidence:.0f}% > 75% — no model runs",
                chop_confidence=chop_confidence,
                is_contracted=is_contracted,
            )

        if is_contracted:
            return RoutingResult(
                route=ModelRoute.SKIP,
                reason="Contraction detected — N-candle range < 30% of expansion leg",
                chop_confidence=chop_confidence,
                is_contracted=True,
            )

        if session_state in ("NO_TRADE", "CLOSED"):
            return RoutingResult(
                route=ModelRoute.SKIP,
                reason=f"Session state {session_state} — no model runs",
                chop_confidence=chop_confidence,
                is_contracted=is_contracted,
            )

        # Route table
        if session_state == "IMBALANCED" and leg_state == "IMBALANCED":
            return RoutingResult(
                route=ModelRoute.AAA_TREND,
                reason="IMBALANCED session + IMBALANCED leg → AAA Trend",
                chop_confidence=chop_confidence,
                is_contracted=is_contracted,
            )

        if session_state == "BALANCED":
            # HARD BLOCK AAA — never evaluate AAA in BALANCED session
            return RoutingResult(
                route=ModelRoute.MEAN_REVERSION,
                reason="BALANCED session → Mean Reversion only (AAA blocked)",
                chop_confidence=chop_confidence,
                is_contracted=is_contracted,
            )

        # PROBING state
        if session_state == "PROBING":
            return RoutingResult(
                route=ModelRoute.MEAN_REVERSION,
                reason="PROBING state → Mean Reversion only",
                chop_confidence=chop_confidence,
                is_contracted=is_contracted,
            )

        # Default: skip
        return RoutingResult(
            route=ModelRoute.SKIP,
            reason=f"Unknown state combination: {session_state}/{leg_state}",
            chop_confidence=chop_confidence,
            is_contracted=is_contracted,
        )

    def detect_contraction(
        self,
        data: list[OHLC],
        expansion_range: float,
        lookback: int = 5,
    ) -> bool:
        """Detect contraction: current N-candle range < 30% of last expansion leg range."""
        if len(data) < lookback or expansion_range <= 0:
            return False

        recent = data[-lookback:]
        current_range = max(c.high for c in recent) - min(c.low for c in recent)
        return current_range < 0.30 * expansion_range
