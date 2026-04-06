"""Scalp Gate Pipeline — Stub.

Planned feature: 6-gate sequential validation for scalp entries including
session timing, MTF alignment, level proximity, risk tier, portfolio
headroom, and double exposure prevention.

Status: Stub — types and functions defined but not fully implemented.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Optional, Any


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


def check_g1_session_timing(context: ScalpContext) -> ScalpGateResult:
    """Gate 1: Session timing — only scalp during active sessions."""
    return ScalpGateResult(ScalpGate.SESSION_TIMING, passed=True, detail="stub: always passes")


def check_g2_mtf_alignment(context: ScalpContext) -> ScalpGateResult:
    """Gate 2: Multi-timeframe alignment."""
    return ScalpGateResult(ScalpGate.MTF_ALIGNMENT, passed=True, detail="stub: always passes")


def check_g3_level_proximity(context: ScalpContext) -> ScalpGateResult:
    """Gate 3: Price proximity to key level."""
    return ScalpGateResult(ScalpGate.LEVEL_PROXIMITY, passed=True, detail="stub: always passes")


def check_g4_risk_tier(context: ScalpContext) -> ScalpGateResult:
    """Gate 4: Risk tier check."""
    return ScalpGateResult(ScalpGate.RISK_TIER, passed=True, detail="stub: always passes")


def check_g5_portfolio_headroom(context: ScalpContext) -> ScalpGateResult:
    """Gate 5: Portfolio has sufficient headroom."""
    return ScalpGateResult(ScalpGate.PORTFOLIO_HEADROOM, passed=True, detail="stub: always passes")


def check_g6_no_double_exposure(context: ScalpContext) -> ScalpGateResult:
    """Gate 6: No concurrent position in the same direction."""
    return ScalpGateResult(ScalpGate.NO_DOUBLE_EXPOSURE, passed=True, detail="stub: always passes")


def evaluate_scalp_gates(context: ScalpContext) -> list[ScalpGateResult]:
    """Evaluate all 6 scalp gates sequentially."""
    return [
        check_g1_session_timing(context),
        check_g2_mtf_alignment(context),
        check_g3_level_proximity(context),
        check_g4_risk_tier(context),
        check_g5_portfolio_headroom(context),
        check_g6_no_double_exposure(context),
    ]
