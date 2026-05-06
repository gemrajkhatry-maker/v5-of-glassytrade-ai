"""Scalp gate pipeline — sequential evaluation of scalp-specific checks."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, time
from enum import Enum
from typing import Any


class ScalpGate(str, Enum):
    SESSION_TIMING = "SESSION_TIMING"
    MTF_ALIGNMENT = "MTF_ALIGNMENT"
    LEVEL_PROXIMITY = "LEVEL_PROXIMITY"
    RISK_TIER = "RISK_TIER"
    PORTFOLIO_HEADROOM = "PORTFOLIO_HEADROOM"
    NO_DOUBLE_EXPOSURE = "NO_DOUBLE_EXPOSURE"


@dataclass
class ScalpGateResult:
    gate: ScalpGate
    passed: bool = False
    detail: str = ""


@dataclass
class ScalpContext:
    symbol: str = ""
    current_time: str = ""
    mtf_bias: str = "NEUTRAL"
    distance_to_level_ticks: float = 0.0
    risk_tier: str = "NORMAL"
    portfolio_utilization: float = 0.0
    open_positions: int = 0
    position_size: float = 0.0


def _parse_time(value: Any) -> time | None:
    if isinstance(value, datetime):
        return value.timetz() if value.tzinfo else value.time()
    if isinstance(value, time):
        return value
    if isinstance(value, str):
        try:
            return datetime.strptime(value, "%H:%M:%S").time()
        except ValueError:
            pass
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
            return parsed.timetz() if parsed.tzinfo else parsed.time()
        except ValueError:
            return None
    return None


def _is_session_time(current_time: str) -> bool:
    open_time = time(9, 15)
    close_time = time(15, 20)
    parsed = _parse_time(current_time)
    if parsed is None:
        return False
    return open_time <= parsed <= close_time


def _normalise_risk_tier(value: Any) -> str:
    if value is None:
        return "NORMAL"
    if hasattr(value, "name"):
        return str(value.name)
    if hasattr(value, "value"):
        return str(value.value)
    return str(value)


def check_g1_session_timing(context: ScalpContext) -> ScalpGateResult:
    if _is_session_time(context.current_time):
        return ScalpGateResult(
            ScalpGate.SESSION_TIMING, True, "Session window open for scalp execution"
        )
    return ScalpGateResult(
        ScalpGate.SESSION_TIMING, False, "Outside scalp window (9:15-15:20)"
    )


def check_g2_mtf_alignment(context: ScalpContext) -> ScalpGateResult:
    bias = str(context.mtf_bias or "").upper()
    has_bias = bias in {"BULLISH", "BEARISH", "ALIGNED_BULLISH", "ALIGNED_BEARISH"}
    return ScalpGateResult(
        ScalpGate.MTF_ALIGNMENT,
        has_bias,
        "MTF alignment has directional bias" if has_bias else f"MTF alignment is not directional ({context.mtf_bias})",
    )


def check_g3_level_proximity(context: ScalpContext) -> ScalpGateResult:
    near_level = float(context.distance_to_level_ticks) <= 5.0
    return ScalpGateResult(
        ScalpGate.LEVEL_PROXIMITY,
        near_level,
        "Level proximity within 5 ticks" if near_level else f"Distance to level too wide: {context.distance_to_level_ticks}",
    )


def check_g4_risk_tier(context: ScalpContext) -> ScalpGateResult:
    tier = _normalise_risk_tier(context.risk_tier).upper()
    allowed = tier not in {"CAUTIOUS", "DEFENSIVE"}
    return ScalpGateResult(
        ScalpGate.RISK_TIER,
        allowed,
        "Risk tier allows scalp execution" if allowed else f"Risk tier blocked scalp: {context.risk_tier}",
    )


def check_g5_portfolio_headroom(context: ScalpContext) -> ScalpGateResult:
    allowed = float(context.portfolio_utilization) < 0.7
    return ScalpGateResult(
        ScalpGate.PORTFOLIO_HEADROOM,
        allowed,
        "Portfolio headroom sufficient for scalp" if allowed else f"Portfolio utilization too high: {context.portfolio_utilization}",
    )


def check_g6_no_double_exposure(context: ScalpContext) -> ScalpGateResult:
    no_double = context.open_positions <= 0
    return ScalpGateResult(
        ScalpGate.NO_DOUBLE_EXPOSURE,
        no_double,
        "No concurrent positions detected" if no_double else f"Open positions present ({context.open_positions})",
    )


def evaluate_scalp_gates(context: ScalpContext) -> list[ScalpGateResult]:
    return [
        check_g1_session_timing(context),
        check_g2_mtf_alignment(context),
        check_g3_level_proximity(context),
        check_g4_risk_tier(context),
        check_g5_portfolio_headroom(context),
        check_g6_no_double_exposure(context),
    ]

