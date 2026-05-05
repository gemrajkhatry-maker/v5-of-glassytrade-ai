"""Gate pipeline — hybrid hard+soft gate validation."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from app.domain.trading.model.enums import MarketState

# Defaults chosen for backendv2 runtime profile.
MIN_AGGRESSION_SCORE = 2.0
MIN_RR_RATIO = 1.5
MAX_CUSHION_TICKS = 10.0
WARM_UP_MINUTES = 45
SOFT_GATE_QUORUM = 3


class GateType(str, Enum):
    HARD = "HARD"
    SOFT = "SOFT"


class GateReason(str, Enum):
    BLOCKED = "BLOCKED"
    STALE = "STALE"
    SESSION_STOPPED = "SESSION_STOPPED"
    FLAT = "FLAT"
    WAIT = "WAIT"
    ALERT = "ALERT"
    INVALID = "INVALID"
    SKIP = "SKIP"
    SUPPRESSED = "SUPPRESSED"
    TRADE = "TRADE"


@dataclass
class GateContext:
    symbol: str = ""
    tick_age_seconds: float = 0.0
    candle_count: int = 0
    warm_up_minutes: int = WARM_UP_MINUTES
    market_state: MarketState = MarketState.BALANCED
    zone: str = ""
    poc: float = 0.0
    vah: float = 0.0
    val: float = 0.0
    price: float = 0.0
    tick_size: float = 0.1
    key_levels: list[float] = field(default_factory=list)
    nearest_level: float = 0.0
    distance_to_level_ticks: float = 0.0
    drive_number: int = 0
    drive_entry_valid: bool = False
    aggression_score: float = 0.0
    cvd_conflict: bool = False
    is_risk_halted: bool = False
    halt_reason: str = ""
    position_size_ok: bool = True
    eia_window_active: bool = False
    weekly_bias: str = "NEUTRAL"
    weekly_bias_aligned: bool = True
    is_extreme_deviation: bool = False
    max_distance_to_level_ticks: float = 3.0
    probing_aggression_threshold: float = 3.0
    min_aggression_score: float = MIN_AGGRESSION_SCORE
    max_cushion_ticks: float = MAX_CUSHION_TICKS
    min_rr_ratio: float = MIN_RR_RATIO
    setup_type: str = "NONE"
    r_r_ratio: float = 0.0
    cushion_ticks: float = 0.0
    soft_gate_quorum: int = SOFT_GATE_QUORUM


@dataclass
class GateResult:
    passed: bool
    gate: int
    reason: GateReason
    detail: str
    setup_type: str = "NONE"
    r_r_ratio: float = 0.0
    hard_gates_passed: bool = True
    soft_gates_total: int = 0
    soft_gates_passed: int = 0
    quorum_met: bool = False

    @property
    def is_trade(self) -> bool:
        return self.passed and self.reason == GateReason.TRADE


@dataclass(frozen=True)
class _SoftGateResult:
    gate: int
    name: str
    passed: bool
    reason: GateReason
    detail: str


class GatePipeline:
    """Execute 12-gate style validation with soft-gate quorum."""

    def evaluate(self, ctx: GateContext) -> GateResult:
        if ctx.candle_count < 1:
            return self._hard_fail(0, GateReason.BLOCKED, "No candles yet")
        if ctx.candle_count * 1 < ctx.warm_up_minutes:
            return self._hard_fail(
                0,
                GateReason.BLOCKED,
                f"Warm-up not complete: {ctx.candle_count}m < {ctx.warm_up_minutes}m",
            )

        if ctx.tick_age_seconds > 30:
            return self._hard_fail(1, GateReason.STALE, f"Tick age {ctx.tick_age_seconds:.0f}s > 30s")

        if ctx.is_risk_halted:
            return self._hard_fail(2, GateReason.SESSION_STOPPED, ctx.halt_reason or "Risk limit hit")

        if ctx.market_state == MarketState.BALANCED and ctx.zone == "AT_POC" and not ctx.is_extreme_deviation:
            return self._hard_fail(3, GateReason.FLAT, "No-trade zone near POC")

        if ctx.market_state == MarketState.IMBALANCED:
            if ctx.aggression_score < ctx.probing_aggression_threshold:
                return self._hard_fail(4, GateReason.FLAT, "IMBALANCED state without aggression")

        if not ctx.key_levels or ctx.nearest_level <= 0:
            return self._hard_fail(5, GateReason.WAIT, "No qualifying structure level near price")

        if ctx.drive_number == 1:
            return self._hard_fail(7, GateReason.FLAT, "D1 drive suppressed")
        if ctx.drive_number >= 3:
            return self._hard_fail(7, GateReason.FLAT, f"D{ctx.drive_number} drive level exhausted")
        if ctx.drive_number == 2 and not ctx.drive_entry_valid:
            return self._hard_fail(7, GateReason.FLAT, "D2 requires prior D1 rejection")

        if not ctx.position_size_ok:
            return self._hard_fail(11, GateReason.BLOCKED, "Position sizing rejected")

        if ctx.eia_window_active:
            return self._hard_fail(12, GateReason.SUPPRESSED, "EIA event window active")

        soft_results: list[_SoftGateResult] = []

        if ctx.distance_to_level_ticks > ctx.max_distance_to_level_ticks:
            soft_results.append(_SoftGateResult(
                gate=6,
                name="Entry distance",
                passed=False,
                reason=GateReason.ALERT,
                detail=f"{ctx.distance_to_level_ticks:.1f} ticks > {ctx.max_distance_to_level_ticks:.0f}",
            ))
        else:
            soft_results.append(_SoftGateResult(
                gate=6,
                name="Entry distance",
                passed=True,
                reason=GateReason.TRADE,
                detail="Entry is within distance gate",
            ))

        if ctx.aggression_score < ctx.min_aggression_score:
            soft_results.append(_SoftGateResult(
                gate=8,
                name="Aggression",
                passed=False,
                reason=GateReason.WAIT,
                detail=f"{ctx.aggression_score:.1f} < {ctx.min_aggression_score:.1f}",
            ))
        else:
            soft_results.append(_SoftGateResult(
                gate=8,
                name="Aggression",
                passed=True,
                reason=GateReason.TRADE,
                detail=f"{ctx.aggression_score:.1f} >= {ctx.min_aggression_score:.1f}",
            ))

        if ctx.cushion_ticks > ctx.max_cushion_ticks:
            soft_results.append(_SoftGateResult(
                gate=9,
                name="Cushion",
                passed=False,
                reason=GateReason.INVALID,
                detail=f"{ctx.cushion_ticks:.1f} > {ctx.max_cushion_ticks:.1f} ticks",
            ))
        else:
            soft_results.append(_SoftGateResult(
                gate=9,
                name="Cushion",
                passed=True,
                reason=GateReason.TRADE,
                detail=f"{ctx.cushion_ticks:.1f} <= {ctx.max_cushion_ticks:.1f} ticks",
            ))

        if ctx.r_r_ratio < ctx.min_rr_ratio:
            soft_results.append(_SoftGateResult(
                gate=10,
                name="R:R",
                passed=False,
                reason=GateReason.SKIP,
                detail=f"{ctx.r_r_ratio:.2f} < {ctx.min_rr_ratio:.1f}",
            ))
        else:
            soft_results.append(_SoftGateResult(
                gate=10,
                name="R:R",
                passed=True,
                reason=GateReason.TRADE,
                detail=f"{ctx.r_r_ratio:.2f} >= {ctx.min_rr_ratio:.1f}",
            ))

        total = len(soft_results)
        passed_count = sum(1 for item in soft_results if item.passed)
        quorum = ctx.soft_gate_quorum
        if passed_count < quorum:
            failed = next(item for item in soft_results if not item.passed)
            return GateResult(
                passed=False,
                gate=failed.gate,
                reason=failed.reason,
                detail=f"Soft gates failed: {passed_count}/{total} passed (need {quorum})",
                soft_gates_total=total,
                soft_gates_passed=passed_count,
                quorum_met=False,
                hard_gates_passed=True,
            )

        return GateResult(
            passed=True,
            gate=12,
            reason=GateReason.TRADE,
            detail=f"All gates passed ({passed_count}/{total} soft gates)",
            setup_type=ctx.setup_type,
            r_r_ratio=ctx.r_r_ratio,
            hard_gates_passed=True,
            soft_gates_total=total,
            soft_gates_passed=passed_count,
            quorum_met=True,
        )

    @staticmethod
    def _hard_fail(gate: int, reason: GateReason, detail: str) -> GateResult:
        return GateResult(
            passed=False,
            gate=gate,
            reason=reason,
            detail=detail,
            hard_gates_passed=False,
            soft_gates_total=0,
            soft_gates_passed=0,
            quorum_met=False,
        )


def run_gate_pipeline(
    data: list[Any],
    amt_result: Any,
    tick: dict,
    **kwargs,
) -> tuple[bool, str, str, int, int]:
    """Compatibility wrapper used by earlier workflow code.

    Returns:
        (passed, reason, detail, soft_passed, soft_total)
    """
    ctx = GateContext(
        candle_count=len(data),
        tick_age_seconds=kwargs.get("tick_age_seconds", 1.1),
        market_state=MarketState.BALANCED if str(kwargs.get("market_state", "BALANCED")).upper() == "BALANCED" else MarketState.IMBALANCED,
        poc=float(getattr(amt_result, "point_of_control", 0.0)),
        vah=float(getattr(amt_result, "value_area_high", 0.0)),
        val=float(getattr(amt_result, "value_area_low", 0.0)),
        price=float(getattr(tick, "close", tick.get("close", 0.0))) if isinstance(tick, dict) else float(getattr(tick, "close", 0.0)),
        key_levels=[float(v) for v in [getattr(amt_result, "value_area_high", 0.0), getattr(amt_result, "value_area_low", 0.0)] if float(v) > 0],
        nearest_level=float(getattr(amt_result, "value_area_high", 0.0)),
        distance_to_level_ticks=kwargs.get("distance_to_level_ticks", 0.0),
        drive_number=kwargs.get("drive_number", 0),
        drive_entry_valid=kwargs.get("drive_entry_valid", False),
        aggression_score=kwargs.get("aggression_score", 0.0),
        cvd_conflict=kwargs.get("cvd_conflict", False),
        is_risk_halted=kwargs.get("is_risk_halted", False),
        halt_reason=kwargs.get("halt_reason", ""),
        position_size_ok=kwargs.get("position_size_ok", True),
        eia_window_active=kwargs.get("eia_window_active", False),
        weekly_bias=kwargs.get("weekly_bias", "NEUTRAL"),
        setup_type=getattr(amt_result, "setup", "NONE"),
        r_r_ratio=kwargs.get("r_r_ratio", getattr(amt_result, "rr_ratio", 0.0)),
        cushion_ticks=kwargs.get("cushion_ticks", 0.0),
        is_extreme_deviation=kwargs.get("is_extreme_deviation", False),
    )
    if ctx.nearest_level == 0 and ctx.key_levels:
        ctx.nearest_level = ctx.key_levels[0]

    if ctx.key_levels:
        ctx.nearest_level = min(ctx.key_levels, key=lambda x: abs(x - ctx.price))
        ctx.distance_to_level_ticks = abs(ctx.price - ctx.nearest_level) / max(kwargs.get("tick_size", 0.05), 0.001)

    result = GatePipeline().evaluate(ctx)
    return result.passed, result.reason.value, result.detail, result.soft_gates_passed, result.soft_gates_total
