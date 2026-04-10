"""Session-Specific Strategy Mode Selector.

Fabio's approach differs by session:
- London Session → Mean Reversion model (balanced market)
- New York Session → Trend Following model (imbalanced market)

For Indian markets:
- Opening (09:15-09:30) → NO TRADE
- Primary (09:30-11:30) → TREND FOLLOWING (all models)
- Midday (11:30-14:00) → MEAN REVERSION ONLY
- Power Hour (14:00-15:15) → TREND FOLLOWING (all models)
- Close (15:15-15:30) → EXIT ONLY

MCX:
- Morning (09:15-14:00) → TREND FOLLOWING
- Afternoon (14:00-18:00) → TREND FOLLOWING
- Evening (18:00-23:00) → SELECTIVE (reduced liquidity)
- US Session (19:30-23:30) → TREND FOLLOWING (US influence)
- Close (23:00-23:30) → EXIT ONLY
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import Enum


class StrategyMode(str, Enum):
    TREND_FOLLOWING = "TREND_FOLLOWING"
    MEAN_REVERSION = "MEAN_REVERSION"
    NO_TRADE = "NO_TRADE"
    EXIT_ONLY = "EXIT_ONLY"
    SELECTIVE = "SELECTIVE"


@dataclass(frozen=True)
class SessionStrategyConfig:
    mode: StrategyMode
    allowed_directions: list[str]  # ["LONG", "SHORT"] or ["LONG"] or ["SHORT"]
    min_aggression_score: float
    min_rr_ratio: float
    max_position_size_pct: float
    description: str


# Pre-configured strategy modes per session phase
STRATEGY_MODES = {
    # NSE Phases
    "OPENING": SessionStrategyConfig(
        mode=StrategyMode.NO_TRADE,
        allowed_directions=[],
        min_aggression_score=0.0,
        min_rr_ratio=0.0,
        max_position_size_pct=0.0,
        description="Opening noise — DO NOT TRADE",
    ),
    "PRIMARY": SessionStrategyConfig(
        mode=StrategyMode.TREND_FOLLOWING,
        allowed_directions=["LONG", "SHORT"],
        min_aggression_score=2.0,
        min_rr_ratio=1.5,
        max_position_size_pct=0.5,  # 0.5% of capital
        description="Primary setup window — ALL MODELS ACTIVE",
    ),
    "MIDDAY": SessionStrategyConfig(
        mode=StrategyMode.MEAN_REVERSION,
        allowed_directions=["LONG", "SHORT"],
        min_aggression_score=2.5,  # Higher threshold for mean reversion
        min_rr_ratio=1.5,
        max_position_size_pct=0.25,  # Reduced size for mean reversion
        description="Midday consolidation — REVERSION ONLY",
    ),
    "POWER_HOUR": SessionStrategyConfig(
        mode=StrategyMode.TREND_FOLLOWING,
        allowed_directions=["LONG", "SHORT"],
        min_aggression_score=2.0,
        min_rr_ratio=1.5,
        max_position_size_pct=0.5,
        description="Power hour — ALL MODELS ACTIVE",
    ),
    "CLOSE": SessionStrategyConfig(
        mode=StrategyMode.EXIT_ONLY,
        allowed_directions=[],
        min_aggression_score=0.0,
        min_rr_ratio=0.0,
        max_position_size_pct=0.0,
        description="Close protection — EXIT ONLY, NO NEW ENTRIES",
    ),
    # MCX Phases
    "MORNING": SessionStrategyConfig(
        mode=StrategyMode.TREND_FOLLOWING,
        allowed_directions=["LONG", "SHORT"],
        min_aggression_score=2.0,
        min_rr_ratio=1.5,
        max_position_size_pct=0.5,
        description="MCX Morning — ALL MODELS ACTIVE",
    ),
    "AFTERNOON": SessionStrategyConfig(
        mode=StrategyMode.TREND_FOLLOWING,
        allowed_directions=["LONG", "SHORT"],
        min_aggression_score=2.0,
        min_rr_ratio=1.5,
        max_position_size_pct=0.5,
        description="MCX Afternoon — ALL MODELS ACTIVE",
    ),
    "EVENING": SessionStrategyConfig(
        mode=StrategyMode.SELECTIVE,
        allowed_directions=["LONG", "SHORT"],
        min_aggression_score=3.0,  # Higher threshold for evening
        min_rr_ratio=2.0,
        max_position_size_pct=0.25,
        description="MCX Evening — Reduced liquidity, be selective",
    ),
    "US_SESSION": SessionStrategyConfig(
        mode=StrategyMode.TREND_FOLLOWING,
        allowed_directions=["LONG", "SHORT"],
        min_aggression_score=2.0,
        min_rr_ratio=1.5,
        max_position_size_pct=0.5,
        description="MCX US Session — US influence, trend following",
    ),
}


class SessionStrategySelector:
    """Returns the correct strategy config for the current session phase."""

    @staticmethod
    def get_config(session_phase: str, exchange: str = "NSE") -> SessionStrategyConfig:
        """Get strategy config for current session phase.

        Args:
            session_phase: Session phase name (e.g., "PRIMARY", "MIDDAY")
            exchange: "NSE" or "MCX"

        Returns:
            SessionStrategyConfig with mode and parameters
        """
        key = session_phase.upper()

        # Handle MCX US session special case
        if exchange.upper() == "MCX" and key == "EVENING":
            # Check if we're in the US session window (after 19:30)
            # The caller should pass "US_SESSION" instead of "EVENING" for this
            pass

        config = STRATEGY_MODES.get(key)
        if config is None:
            # Default to no trade for unknown phases
            return SessionStrategyConfig(
                mode=StrategyMode.NO_TRADE,
                allowed_directions=[],
                min_aggression_score=0.0,
                min_rr_ratio=0.0,
                max_position_size_pct=0.0,
                description=f"Unknown phase: {session_phase}",
            )

        return config

    @staticmethod
    def can_enter_trade(
        session_phase: str,
        direction: str,
        aggression_score: float,
        rr_ratio: float,
        exchange: str = "NSE",
    ) -> tuple[bool, str]:
        """Check if a trade is allowed by session strategy rules.

        Returns:
            (allowed, reason)
        """
        config = SessionStrategySelector.get_config(session_phase, exchange)

        if config.mode == StrategyMode.NO_TRADE:
            return False, f"No trade during {session_phase} phase"

        if config.mode == StrategyMode.EXIT_ONLY:
            return False, f"Exit only during {session_phase} phase"

        if direction not in config.allowed_directions:
            return False, f"Direction {direction} not allowed in {config.mode.value} mode"

        if aggression_score < config.min_aggression_score:
            return False, (
                f"Aggression score {aggression_score:.1f} < "
                f"{config.min_aggression_score} minimum for {config.mode.value}"
            )

        if rr_ratio < config.min_rr_ratio:
            return False, (
                f"R:R ratio {rr_ratio:.1f} < {config.min_rr_ratio} "
                f"minimum for {config.mode.value}"
            )

        return True, f"Trade allowed in {config.mode.value} mode"
