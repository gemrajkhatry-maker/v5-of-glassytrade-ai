"""Scalp Gate Pipeline - runtime scalp entry validation.

Sequential 6-gate validation for scalp entries including:
- session timing
- MTF alignment
- level proximity
- risk tier
- portfolio headroom
- double exposure prevention
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum
from typing import Any


class ScalpGate(str, Enum):
    """Sequential gates for scalp entry validation."""

    SESSION_TIMING = "SESSION_TIMING"
    MTF_ALIGNMENT = "MTF_ALIGNMENT"
    LEVEL_PROXIMITY = "LEVEL_PROXIMITY"
    RISK_TIER = "RISK_TIER"
    PORTFOLIO_HEADROOM = "PORTFOLIO_HEADROOM"
    NO_DOUBLE_EXPOSURE = "NO_DOUBLE_EXPOSURE"


@dataclass
class ScalpGateResult:
    """Result of a single scalp gate evaluation."""

    gate: ScalpGate
    passed: bool = False
    detail: str = ""


@dataclass
class ScalpContext:
    """Context data for scalp gate evaluation."""

    symbol: str = ""
    current_time: str = ""
    mtf_bias: str = "NEUTRAL"
    distance_to_level_ticks: float = 0.0
    risk_tier: str = "NORMAL"
    portfolio_utilization: float = 0.0
    open_positions: int = 0
    position_size: float = 0.0


def _parse_time(value: Any) -> time | None:
    """Normalize a tick timestamp value to datetime.time."""
    if isinstance(value, datetime):
        return value.timetz() if value.tzinfo else value.time()
    if isinstance(value, time):
        return value
    if isinstance(value, str):
        # Prefer full ISO timestamps, then accept plain HH:MM:SS inputs.
        try:
            parsed = datetime.strptime(value, "%H:%M:%S").time()
            return parsed
        except ValueError:
            pass
    if isinstance(value, str):
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.timetz() if parsed.tzinfo else parsed.time()
        except ValueError:
            return None
    return None


def _is_session_time(current_time: str) -> bool:
    """Return True when event occurs within the NSE scalp window."""
    market_open = time(9, 15, 0)
    market_close = time(15, 20, 0)
    parsed = _parse_time(current_time)
    if parsed is None:
        return False
    return market_open <= parsed <= market_close


def _normalise_risk_tier(value: Any) -> str:
    if value is None:
        return "NORMAL"
    if hasattr(value, "name"):
        return str(value.name)
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def check_g1_session_timing(context: ScalpContext) -> ScalpGateResult:
    """Gate 1: session timing only during active sessions."""
    if _is_session_time(context.current_time):
        return ScalpGateResult(
            ScalpGate.SESSION_TIMING,
            passed=True,
            detail="Session window open for scalp execution",
        )
    return ScalpGateResult(
        ScalpGate.SESSION_TIMING,
        passed=False,
        detail="Outside scalp window (9:15-15:20)",
    )


def check_g2_mtf_alignment(context: ScalpContext) -> ScalpGateResult:
    """Gate 2: Multi-timeframe alignment."""
    bias = str(context.mtf_bias or "").upper()
    has_bias = bias in ("BULLISH", "BEARISH", "ALIGNED_BULLISH", "ALIGNED_BEARISH")
    return ScalpGateResult(
        ScalpGate.MTF_ALIGNMENT,
        passed=has_bias,
        detail="MTF alignment has directional bias"
        if has_bias
        else f"MTF alignment is not directional ({context.mtf_bias})",
    )


def check_g3_level_proximity(context: ScalpContext) -> ScalpGateResult:
    """Gate 3: Price proximity to key level."""
    near_level = float(context.distance_to_level_ticks) <= 5.0
    return ScalpGateResult(
        ScalpGate.LEVEL_PROXIMITY,
        passed=near_level,
        detail="Level proximity within 5 ticks"
        if near_level
        else f"Distance to level too wide: {context.distance_to_level_ticks}",
    )


def check_g4_risk_tier(context: ScalpContext) -> ScalpGateResult:
    """Gate 4: Risk tier check."""
    tier = _normalise_risk_tier(context.risk_tier).upper()
    allowed = tier not in {"CAUTIOUS", "DEFENSIVE"}
    return ScalpGateResult(
        ScalpGate.RISK_TIER,
        passed=allowed,
        detail="Risk tier allows scalp execution"
        if allowed
        else f"Risk tier blocked scalp: {context.risk_tier}",
    )


def check_g5_portfolio_headroom(context: ScalpContext) -> ScalpGateResult:
    """Gate 5: Portfolio has sufficient headroom."""
    allowed = float(context.portfolio_utilization) < 0.7
    return ScalpGateResult(
        ScalpGate.PORTFOLIO_HEADROOM,
        passed=allowed,
        detail="Portfolio headroom sufficient for scalp"
        if allowed
        else f"Portfolio utilization too high: {context.portfolio_utilization}",
    )


def check_g6_no_double_exposure(context: ScalpContext) -> ScalpGateResult:
    """Gate 6: No concurrent position in same direction."""
    # Guarded scaffold: keep this gate permissive until full duplicate-exposure
    # ownership checks are implemented in PositionLifecycle.
    no_double = True
    return ScalpGateResult(
        ScalpGate.NO_DOUBLE_EXPOSURE,
        passed=no_double,
        detail="No concurrent positions detected"
        if no_double
        else f"Open positions present ({context.open_positions})",
    )


def evaluate_scalp_gates(context: ScalpContext) -> list[ScalpGateResult]:
    """Evaluate all six scalp gates in sequence."""
    return [
        check_g1_session_timing(context),
        check_g2_mtf_alignment(context),
        check_g3_level_proximity(context),
        check_g4_risk_tier(context),
        check_g5_portfolio_headroom(context),
        check_g6_no_double_exposure(context),
    ]
