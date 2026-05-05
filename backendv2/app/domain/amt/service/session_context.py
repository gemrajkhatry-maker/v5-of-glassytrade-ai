"""session context — AMT analysis service.

Based on amt_docs §2.1 (Session Context).
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import Enum


class GapSize(str, Enum):
    SMALL = "SMALL"
    MEDIUM = "MEDIUM"
    LARGE = "LARGE"


class OpeningBias(str, Enum):
    LONG_BIAS = "LONG_BIAS"
    SHORT_BIAS = "SHORT_BIAS"
    NEUTRAL = "NEUTRAL"


class SessionPhase(str, Enum):
    MORNING = "MORNING"
    AFTERNOON = "AFTERNOON"


@dataclass(frozen=True)
class SessionContext:
    """Session context information."""
    gap_size: GapSize
    opening_bias: OpeningBias
    session_phase: SessionPhase
    day_type: str
    gap_pct: float
    open_price: float
    prior_close: float


class SessionContextEngine:
    """Analyze session context."""

    def __init__(self, gap_medium_pct: float = 0.5, gap_large_pct: float = 1.0):
        self.gap_medium_pct = gap_medium_pct
        self.gap_large_pct = gap_large_pct
        self._prior_close = 0.0
        self._open_price = 0.0

    def analyze(
        self,
        open_price: float,
        prior_close: float,
        prior_poc: float,
        timestamp: datetime | None = None,
    ) -> SessionContext:
        """
        Analyze session context.
        
        Args:
            open_price: Current session open
            prior_close: Previous session close
            prior_poc: Prior session POC
            timestamp: Current timestamp
        
        Returns:
            SessionContext with analysis
        """
        self._open_price = open_price
        self._prior_close = prior_close

        # Calculate gap
        if prior_close > 0:
            gap_pct = abs(open_price - prior_close) / prior_close * 100
        else:
            gap_pct = 0.0

        # Classify gap size
        if gap_pct > self.gap_large_pct:
            gap_size = GapSize.LARGE
        elif gap_pct > self.gap_medium_pct:
            gap_size = GapSize.MEDIUM
        else:
            gap_size = GapSize.SMALL

        # Determine opening bias
        if prior_poc > 0:
            if open_price > prior_poc * 1.01:
                opening_bias = OpeningBias.LONG_BIAS
            elif open_price < prior_poc * 0.99:
                opening_bias = OpeningBias.SHORT_BIAS
            else:
                opening_bias = OpeningBias.NEUTRAL
        else:
            opening_bias = OpeningBias.NEUTRAL

        # Determine session phase
        if timestamp:
            session_phase = (
                SessionPhase.MORNING if timestamp.hour < 12
                else SessionPhase.AFTERNOON
            )
        else:
            session_phase = SessionPhase.MORNING

        # Simple day type classification
        day_type = "NORMAL"

        return SessionContext(
            gap_size=gap_size,
            opening_bias=opening_bias,
            session_phase=session_phase,
            day_type=day_type,
            gap_pct=gap_pct,
            open_price=open_price,
            prior_close=prior_close,
        )

