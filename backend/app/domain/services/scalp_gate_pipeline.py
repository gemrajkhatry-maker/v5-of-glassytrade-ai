"""Scalping Gate Pipeline — 6 lightweight gates for scalp entry.

Optimised for speed (< 1ms total). Unlike structural gates which check
probability/ML, scalping gates check only timing, alignment, proximity,
and portfolio headroom.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from enum import Enum

logger = logging.getLogger(__name__)


class ScalpGate(str, Enum):
    G1_SESSION_TIMING = "G1_SESSION_TIMING"
    G2_MTF_ALIGNMENT = "G2_MTF_ALIGNMENT"
    G3_LEVEL_PROXIMITY = "G3_LEVEL_PROXIMITY"
    G4_RISK_TIER = "G4_RISK_TIER"
    G5_PORTFOLIO_HEADROOM = "G5_PORTFOLIO_HEADROOM"
    G6_NO_DOUBLE_EXPOSURE = "G6_NO_DOUBLE_EXPOSURE"


@dataclass(frozen=True)
class ScalpGateResult:
    gate: ScalpGate
    passed: bool
    reason: str


# NSE prime windows (minutes since 09:15)
NSE_PRIME_WINDOWS = [
    (30, 75),  # 09:45 - 10:30
    (75, 135),  # 10:30 - 11:30
    (255, 345),  # 13:30 - 15:00
]

# MCX prime windows (minutes since 09:00)
MCX_PRIME_WINDOWS = [
    (120, 240),  # 11:00 - 13:00
    (480, 600),  # 17:00 - 19:00
    (720, 840),  # 21:00 - 23:00
]


def check_g1_session_timing(
    exchange: str,
    minutes_since_open: int,
) -> ScalpGateResult:
    """GATE 1: Session timing — only during prime windows."""
    if exchange == "NSE":
        # Never first 30 min or last 15 min
        if minutes_since_open < 30:
            return ScalpGateResult(
                gate=ScalpGate.G1_SESSION_TIMING,
                passed=False,
                reason="First 30 min of NSE session — too choppy",
            )
        if minutes_since_open > 345:  # 15:00+
            return ScalpGateResult(
                gate=ScalpGate.G1_SESSION_TIMING,
                passed=False,
                reason="Last 15 min of NSE session — too choppy",
            )
        for start, end in NSE_PRIME_WINDOWS:
            if start <= minutes_since_open <= end:
                return ScalpGateResult(
                    gate=ScalpGate.G1_SESSION_TIMING,
                    passed=True,
                    reason="",
                )
        return ScalpGateResult(
            gate=ScalpGate.G1_SESSION_TIMING,
            passed=False,
            reason="Outside NSE prime windows (09:45-11:30, 13:30-15:00)",
        )
    else:  # MCX
        if minutes_since_open < 30:
            return ScalpGateResult(
                gate=ScalpGate.G1_SESSION_TIMING,
                passed=False,
                reason="First 30 min of MCX session",
            )
        for start, end in MCX_PRIME_WINDOWS:
            if start <= minutes_since_open <= end:
                return ScalpGateResult(
                    gate=ScalpGate.G1_SESSION_TIMING,
                    passed=True,
                    reason="",
                )
        return ScalpGateResult(
            gate=ScalpGate.G1_SESSION_TIMING,
            passed=False,
            reason="Outside MCX prime windows (11:00-13:00, 17:00-19:00, 21:00-23:00)",
        )


def check_g2_mtf_alignment(
    tf5_bias: str,  # "LONG", "SHORT", "NEUTRAL"
    tf1_aggression: float,  # 1-min aggression score
    tf1_cvd_slope: float,  # 1-min CVD slope
    tf15_trigger: bool,  # 15-sec trigger fired
    direction: str,  # "LONG" or "SHORT"
) -> ScalpGateResult:
    """GATE 2: MTF alignment — all 3 timeframes must align."""
    if direction == "LONG":
        if tf5_bias not in ("LONG", "NEUTRAL"):
            return ScalpGateResult(
                gate=ScalpGate.G2_MTF_ALIGNMENT,
                passed=False,
                reason=f"5-min bias {tf5_bias} conflicts with LONG scalp",
            )
        if tf1_aggression < 2.0 or tf1_cvd_slope <= 15:
            return ScalpGateResult(
                gate=ScalpGate.G2_MTF_ALIGNMENT,
                passed=False,
                reason=f"1-min aggression={tf1_aggression:.1f} < 2.0 or cvd_slope={tf1_cvd_slope:.1f} <= 15",
            )
    else:  # SHORT
        if tf5_bias not in ("SHORT", "NEUTRAL"):
            return ScalpGateResult(
                gate=ScalpGate.G2_MTF_ALIGNMENT,
                passed=False,
                reason=f"5-min bias {tf5_bias} conflicts with SHORT scalp",
            )
        if tf1_aggression < 2.0 or tf1_cvd_slope >= -15:
            return ScalpGateResult(
                gate=ScalpGate.G2_MTF_ALIGNMENT,
                passed=False,
                reason=f"1-min aggression={tf1_aggression:.1f} < 2.0 or cvd_slope={tf1_cvd_slope:.1f} >= -15",
            )

    if not tf15_trigger:
        return ScalpGateResult(
            gate=ScalpGate.G2_MTF_ALIGNMENT,
            passed=False,
            reason="15-sec trigger not fired",
        )

    return ScalpGateResult(gate=ScalpGate.G2_MTF_ALIGNMENT, passed=True, reason="")


def check_g3_level_proximity(
    price: float,
    structural_levels: list[float],
    tick_size: float,
    max_ticks: int = 5,
) -> ScalpGateResult:
    """GATE 3: Entry must be within 5 ticks of a structural level."""
    for level in structural_levels:
        if abs(price - level) <= tick_size * max_ticks:
            return ScalpGateResult(
                gate=ScalpGate.G3_LEVEL_PROXIMITY,
                passed=True,
                reason="",
            )
    return ScalpGateResult(
        gate=ScalpGate.G3_LEVEL_PROXIMITY,
        passed=False,
        reason=f"Price {price} not within {max_ticks} ticks of any structural level",
    )


def check_g4_risk_tier(tier: str) -> ScalpGateResult:
    """GATE 4: Risk tier active check."""
    if tier == "HALT":
        return ScalpGateResult(
            gate=ScalpGate.G4_RISK_TIER,
            passed=False,
            reason="Risk tier HALT",
        )
    return ScalpGateResult(gate=ScalpGate.G4_RISK_TIER, passed=True, reason="")


def check_g5_portfolio_headroom(
    open_positions: int,
    max_positions: int = 5,
) -> ScalpGateResult:
    """GATE 5: Portfolio headroom check."""
    if open_positions >= max_positions:
        return ScalpGateResult(
            gate=ScalpGate.G5_PORTFOLIO_HEADROOM,
            passed=False,
            reason=f"open_positions={open_positions} >= {max_positions}",
        )
    return ScalpGateResult(gate=ScalpGate.G5_PORTFOLIO_HEADROOM, passed=True, reason="")


def check_g6_no_double_exposure(
    scalp_underlying: str,
    open_position_underlyings: list[str],
    exchange: str,
) -> ScalpGateResult:
    """GATE 6: No scalp on symbol with existing structural position."""
    if exchange == "MCX":
        # MCX: different commodities are allowed
        return ScalpGateResult(
            gate=ScalpGate.G6_NO_DOUBLE_EXPOSURE, passed=True, reason=""
        )

    if scalp_underlying in open_position_underlyings:
        return ScalpGateResult(
            gate=ScalpGate.G6_NO_DOUBLE_EXPOSURE,
            passed=False,
            reason=f"Structural position already open on {scalp_underlying}",
        )
    return ScalpGateResult(gate=ScalpGate.G6_NO_DOUBLE_EXPOSURE, passed=True, reason="")


def evaluate_scalp_gates(
    exchange: str,
    minutes_since_open: int,
    tf5_bias: str,
    tf1_aggression: float,
    tf1_cvd_slope: float,
    tf15_trigger: bool,
    direction: str,
    price: float,
    structural_levels: list[float],
    tick_size: float,
    tier: str,
    open_positions: int,
    scalp_underlying: str,
    open_position_underlyings: list[str],
) -> tuple[bool, list[ScalpGateResult]]:
    """Evaluate all 6 scalp gates. First failure stops evaluation."""
    results = []

    r = check_g1_session_timing(exchange, minutes_since_open)
    results.append(r)
    if not r.passed:
        return False, results

    r = check_g2_mtf_alignment(
        tf5_bias, tf1_aggression, tf1_cvd_slope, tf15_trigger, direction
    )
    results.append(r)
    if not r.passed:
        return False, results

    r = check_g3_level_proximity(price, structural_levels, tick_size)
    results.append(r)
    if not r.passed:
        return False, results

    r = check_g4_risk_tier(tier)
    results.append(r)
    if not r.passed:
        return False, results

    r = check_g5_portfolio_headroom(open_positions)
    results.append(r)
    if not r.passed:
        return False, results

    r = check_g6_no_double_exposure(
        scalp_underlying, open_position_underlyings, exchange
    )
    results.append(r)
    if not r.passed:
        return False, results

    return True, results
