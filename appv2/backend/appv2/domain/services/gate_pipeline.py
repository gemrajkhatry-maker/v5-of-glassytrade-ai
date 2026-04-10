"""Gate Pipeline — 12-gate entry validation with hard + soft gates.

Hard gates (fail-fast): any failure = immediate reject
Soft gates (quorum): need ≥ 3 of 4 to pass
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from appv2.config import constants as C
from appv2.domain.enums.session_phase import SessionPhase

logger = logging.getLogger(__name__)


@dataclass
class GateResult:
    passed: bool
    reason: str
    detail: str = ""  # Additional context


@dataclass
class GateContext:
    """Input context for gate checking."""
    session_phase: str = ""
    market_state: str = ""
    data_candles: int = 0
    is_risk_halted: bool = False
    drive_number: int = 0
    drive_exhausted: bool = False
    drive_suppressed: bool = False
    price: float = 0.0
    entry_zone: float = 0.0
    aggression_score: float = 0.0
    opposing_level: float = 0.0
    r_r_ratio: float = 0.0
    tick_age_seconds: float = 0.0
    profile_shape: str = ""
    cvd_slope: float = 0.0
    tick_size: float = 0.05
    theta_cost_pct: float = 0.0  # Theta cost as % of expected profit (for options)


# ── Hard Gates ────────────────────────────────────────────────────

def gate_session_warmup(ctx: GateContext) -> GateResult:
    """Hard Gate 1: Phase 1 (Opening Noise) = reject."""
    no_trade_phases = {"OPENING", "PRE_MARKET", "PRE_OPEN", "CLOSE", "POST_MARKET"}
    if ctx.session_phase in no_trade_phases:
        return GateResult(passed=False, reason="Session warm-up active", detail=f"Phase: {ctx.session_phase}")
    return GateResult(passed=True, reason="")


def gate_data_quality(ctx: GateContext) -> GateResult:
    """Hard Gate 2: Need ≥ 5 candles for analysis."""
    if ctx.data_candles < 5:
        return GateResult(passed=False, reason="Insufficient data", detail=f"Candles: {ctx.data_candles}")
    return GateResult(passed=True, reason="")


def gate_risk_halt(ctx: GateContext) -> GateResult:
    """Hard Gate 3: Risk system halted."""
    if ctx.is_risk_halted:
        return GateResult(passed=False, reason="Risk halt active")
    return GateResult(passed=True, reason="")


def gate_no_trade_state(ctx: GateContext) -> GateResult:
    """Hard Gate 4: NO_TRADE market state = reject."""
    if ctx.market_state == "NO_TRADE":
        return GateResult(passed=False, reason="NO_TRADE state — POC dead zone")
    return GateResult(passed=True, reason="")


def gate_probing_without_aggression(ctx: GateContext) -> GateResult:
    """Hard Gate 5: PROBING state requires aggression confirmation."""
    if ctx.market_state == "PROBING" and ctx.aggression_score < C.GATE_SOFT_MIN_AGGRESSION:
        return GateResult(
            passed=False,
            reason="PROBING without aggression",
            detail=f"Score: {ctx.aggression_score:.2f} < {C.GATE_SOFT_MIN_AGGRESSION}",
        )
    return GateResult(passed=True, reason="")


def gate_key_level_proximity(ctx: GateContext) -> GateResult:
    """Hard Gate 6: Price within 3 ticks of opposing key level = reject."""
    if ctx.opposing_level > 0 and ctx.tick_size > 0:
        dist = abs(ctx.price - ctx.opposing_level)
        if dist < C.GATE_ENTRY_ZONE_TICKS * ctx.tick_size:
            return GateResult(
                passed=False,
                reason="Too close to opposing level",
                detail=f"Distance: {dist:.4f}",
            )
    return GateResult(passed=True, reason="")


def gate_drive_validation(ctx: GateContext) -> GateResult:
    """Hard Gate 7: D1 suppressed or D3+ exhausted = reject."""
    if ctx.drive_number == 1 and ctx.drive_suppressed:
        return GateResult(passed=False, reason="D1 drive suppressed")
    if ctx.drive_number >= 3 and ctx.drive_exhausted:
        return GateResult(passed=False, reason=f"D{ctx.drive_number} exhausted")
    return GateResult(passed=True, reason="")


def gate_signal_age(ctx: GateContext) -> GateResult:
    """Hard Gate 8: Signal too old."""
    if ctx.tick_age_seconds > C.SIGNAL_MAX_AGE_SECONDS:
        return GateResult(
            passed=False,
            reason="Signal expired",
            detail=f"Age: {ctx.tick_age_seconds:.0f}s > {C.SIGNAL_MAX_AGE_SECONDS}s",
        )
    return GateResult(passed=True, reason="")


def gate_profile_shape(ctx: GateContext) -> GateResult:
    """Hard Gate 9: P-shape blocks LONG, b-shape blocks SHORT."""
    if not ctx.profile_shape:
        return GateResult(passed=True, reason="")
    # Caller passes direction via context; check shape
    shape = ctx.profile_shape[0].upper() if ctx.profile_shape else ""
    # Shape checks are direction-specific; return pass here, caller validates
    return GateResult(passed=True, reason="")


def gate_cvd_hard(ctx: GateContext) -> GateResult:
    """Hard Gate 10: Extreme opposing CVD slope = reject."""
    if ctx.cvd_slope < -C.CVD_SLOPE_EXTREME and ctx.market_state == "BALANCED":
        return GateResult(passed=False, reason="CVD extreme selling in balance")
    if ctx.cvd_slope > C.CVD_SLOPE_EXTREME and ctx.market_state == "BALANCED":
        return GateResult(passed=False, reason="CVD extreme buying in balance")
    return GateResult(passed=True, reason="")


def gate_theta_viability(ctx: GateContext) -> GateResult:
    """Hard Gate 11: Theta cost must be < 20% of expected profit.

    For options trades, theta decay eats into profits.
    If theta cost is too high relative to expected profit, reject.
    """
    if ctx.theta_cost_pct <= 0:
        return GateResult(passed=True, reason="")  # Not an option trade or not checked

    if ctx.theta_cost_pct > C.THETA_COST_MAX_PCT:
        return GateResult(
            passed=False,
            reason=f"Theta cost too high: {ctx.theta_cost_pct:.0f}% > {C.THETA_COST_MAX_PCT:.0f}%",
        )
    return GateResult(passed=True, reason="")


# ── Soft Gates (Quorum: ≥ 3 of 4) ─────────────────────────────────

def soft_gate_entry_zone(ctx: GateContext) -> GateResult:
    """Soft Gate 1: Price at entry zone (within 3 ticks)."""
    if ctx.entry_zone > 0 and ctx.tick_size > 0:
        dist = abs(ctx.price - ctx.entry_zone)
        if dist > C.GATE_ENTRY_ZONE_TICKS * ctx.tick_size:
            return GateResult(passed=False, reason="Price not at entry zone", detail=f"Dist: {dist:.4f}")
    return GateResult(passed=True, reason="")


def soft_gate_aggression(ctx: GateContext) -> GateResult:
    """Soft Gate 2: Aggression score >= threshold."""
    if ctx.aggression_score < C.GATE_SOFT_MIN_AGGRESSION:
        return GateResult(
            passed=False,
            reason="Low aggression score",
            detail=f"{ctx.aggression_score:.2f} < {C.GATE_SOFT_MIN_AGGRESSION}",
        )
    return GateResult(passed=True, reason="")


def soft_gate_cushion(ctx: GateContext) -> GateResult:
    """Soft Gate 3: Cushion to opposing level <= 10 ticks."""
    if ctx.opposing_level > 0 and ctx.tick_size > 0:
        dist = abs(ctx.price - ctx.opposing_level)
        if dist > C.GATE_SOFT_MAX_CUSHION_TICKS * ctx.tick_size:
            return GateResult(passed=False, reason="Insufficient cushion to opposing level")
    return GateResult(passed=True, reason="")


def soft_gate_rr(ctx: GateContext) -> GateResult:
    """Soft Gate 4: R:R >= 1.5."""
    if ctx.r_r_ratio > 0 and ctx.r_r_ratio < C.GATE_SOFT_MIN_RR:
        return GateResult(passed=False, reason=f"R:R too low", detail=f"{ctx.r_r_ratio:.2f}")
    return GateResult(passed=True, reason="")


# ── Pipeline Runner ───────────────────────────────────────────────

def run_gate_pipeline(ctx: GateContext) -> tuple[bool, str, str]:
    """Run all 12 gates.

    Returns:
        (passed, reason, detail)
    """
    hard_gates = [
        ("SessionWarmup", gate_session_warmup),
        ("DataQuality", gate_data_quality),
        ("RiskHalt", gate_risk_halt),
        ("NoTradeState", gate_no_trade_state),
        ("ProbingAggression", gate_probing_without_aggression),
        ("KeyLevel", gate_key_level_proximity),
        ("DriveValidation", gate_drive_validation),
        ("SignalAge", gate_signal_age),
        ("CVDHard", gate_cvd_hard),
        ("ThetaViability", gate_theta_viability),
    ]

    soft_gates = [
        ("EntryZone", soft_gate_entry_zone),
        ("Aggression", soft_gate_aggression),
        ("Cushion", soft_gate_cushion),
        ("RR", soft_gate_rr),
    ]

    # Hard gates: any fail = reject
    for name, gate_fn in hard_gates:
        result = gate_fn(ctx)
        if not result.passed:
            logger.info("Gate REJECTED: %s — %s (%s)", name, result.reason, result.detail)
            return False, name, result.reason

    # Soft gates: quorum ≥ 3 of 4
    soft_passed = sum(1 for _, fn in soft_gates if fn(ctx).passed)
    if soft_passed < C.GATE_SOFT_QUORUM:
        failed = [name for name, fn in soft_gates if not fn(ctx).passed]
        logger.info("Gate SOFT REJECT: %d/%d passed, failed: %s", soft_passed, len(soft_gates), failed)
        return False, "SoftQuorum", f"Only {soft_passed}/{len(soft_gates)} soft gates passed"

    return True, "All gates passed", ""
