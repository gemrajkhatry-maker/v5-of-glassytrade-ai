"""Gate Pipeline — Hybrid 12-gate validation per Fabio AMT spec.

Fabio's spec: 4-rule checklist where 3/4 must pass (scoring/quorum model).
Our implementation reconciles this with a hybrid approach:

HARD GATES (fail-fast AND logic — safety/risk):
  GATE 0: Session time filter (warm-up)             → BLOCKED
  GATE 1: Data quality (STALE, gap > 30s)           → STALE
  GATE 2: Session risk (daily loss, drawdown)        → SESSION_STOPPED
  GATE 3: NO_TRADE state (POC ± 2 ticks)            → FLAT
  GATE 4: PROBING state (unconfirmed break)          → FLAT
  GATE 5: Profile + key level identified             → WAIT
  GATE 7: Drive = 2 (first drive rejected)           → FLAT/ALERT
  GATE 11: Position sizing passes risk manager       → BLOCKED
  GATE 12: EIA release window                        → SUPPRESSED

SOFT GATES (quorum model — Fabio's 3/4 rule):
  GATE 6: Price at entry zone (within 3 ticks)       → ALERT  (strategy quality)
  GATE 8: Aggression ≥ 2.0                           → WAIT   (strategy quality)
  GATE 9: Cushion ≤ 10 ticks                         → INVALID (strategy quality)
  GATE 10: R:R ≥ 1.5                                 → SKIP   (strategy quality)

Soft gate quorum: minimum SOFT_GATE_QUORUM (default=3) of 4 soft gates must pass.
This reconciles Fabio's "3 of 4 rules pass" with our structured pipeline.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

from app.domain.trading.models.enums import MarketState, SetupType
from app.domain.constants import (
    MIN_AGGRESSION_SCORE,
    MIN_RR_RATIO,
    MAX_CUSHION_TICKS,
    WARM_UP_MINUTES_MCX,
    SOFT_GATE_QUORUM,
)
from app.domain.fabio_ai.services.eia_calendar import EIACalendar

logger = logging.getLogger(__name__)

# EIA calendar singleton for gate pipeline
_eia_calendar = EIACalendar(suppression_minutes=15)


class GateType(str, Enum):
    """Type of gate — determines evaluation semantics."""

    HARD = "HARD"  # Must pass unconditionally; fail-fast on first failure
    SOFT = "SOFT"  # Participates in quorum scoring (Fabio's 3/4 rule)


class GateReason(str, Enum):
    """Output reason when a gate fails."""

    BLOCKED = "BLOCKED"
    STALE = "STALE"
    SESSION_STOPPED = "SESSION_STOPPED"
    FLAT = "FLAT"
    WAIT = "WAIT"
    ALERT = "ALERT"
    INVALID = "INVALID"
    SKIP = "SKIP"
    SUPPRESSED = "SUPPRESSED"
    TRADE = "TRADE"  # All gates passed


@dataclass
class GateContext:
    """Context passed through the gate pipeline.

    All data needed for gate decisions, collected once before pipeline runs.
    """

    # Symbol (for EIA window check)
    symbol: str = ""

    # Data quality
    tick_age_seconds: float = 0.0  # Seconds since last tick
    candle_count: int = 0  # Number of candles in session
    warm_up_minutes: int = WARM_UP_MINUTES_MCX

    # Market state (from MarketStateEngine)
    market_state: MarketState = MarketState.BALANCED
    zone: str = ""

    # Volume profile
    poc: float = 0.0
    vah: float = 0.0
    val: float = 0.0
    price: float = 0.0
    tick_size: float = 0.1

    # Key levels
    key_levels: list[float] = field(default_factory=list)
    nearest_level: float = 0.0
    distance_to_level_ticks: float = 0.0

    # Drive state (from DriveTracker)
    drive_number: int = 0
    drive_entry_valid: bool = False

    # Aggression (from AggressionScorer)
    aggression_score: float = 0.0

    # Risk
    is_risk_halted: bool = False
    halt_reason: str = ""

    # Position sizing
    position_size_ok: bool = True

    # EIA window
    eia_window_active: bool = False
    # Weekly bias (Gap #4 — Composite Profile)
    weekly_bias: str = "NEUTRAL"
    weekly_bias_aligned: bool = True
    
    # New: Extreme deviation escalation (> 3.0 sigma)
    is_extreme_deviation: bool = False

    # Configurable gate thresholds (exchange-specific)
    max_distance_to_level_ticks: float = 3.0  # Gate 6: max ticks from nearest level
    probing_aggression_threshold: float = (
        3.0  # Gate 4: min aggression for PROBING state
    )
    min_aggression_score: float = 2.0  # Gate 8: minimum aggression for any entry
    max_cushion_ticks: float = 10.0  # Gate 9: max cushion (ticks from price to level)
    min_rr_ratio: float = 1.5  # Gate 10: minimum risk-reward ratio
    weekly_bias_strength: float = 0.0

    # Setup
    setup_type: str = "NONE"
    r_r_ratio: float = 0.0
    cushion_ticks: float = 0.0

    # Quorum configuration (overridable per exchange/session)
    soft_gate_quorum: int = SOFT_GATE_QUORUM  # Minimum soft gates that must pass


@dataclass
class GateResult:
    """Result of gate pipeline evaluation."""

    passed: bool  # True if all hard gates passed AND soft gate quorum met
    gate: int  # Gate number that failed (0-12), 12 if all passed
    reason: GateReason  # Output reason
    detail: str  # Human-readable detail
    setup_type: str = "NONE"  # Setup type if passed
    r_r_ratio: float = 0.0  # R:R if passed

    # Quorum diagnostics
    hard_gates_passed: bool = True       # False if any hard gate failed
    soft_gates_total: int = 0            # Total soft gates evaluated
    soft_gates_passed: int = 0           # Soft gates that passed
    quorum_met: bool = False             # True if soft_gates_passed >= quorum

    @property
    def is_trade(self) -> bool:
        return self.passed and self.reason == GateReason.TRADE


@dataclass
class _SoftGateResult:
    """Internal: result of a single soft gate evaluation."""

    gate: int
    name: str
    passed: bool
    reason: GateReason
    detail: str


class GatePipeline:
    """Hybrid 12-gate validation.

    Hard gates: fail-fast AND logic (safety/risk gates).
    Soft gates: quorum scoring — minimum SOFT_GATE_QUORUM must pass (Fabio's 3/4).
    """

    def evaluate(self, ctx: GateContext) -> GateResult:
        """Run all 12 gates using hybrid hard/soft logic."""

        # ── HARD GATES (fail-fast) ─────────────────────────────────────────

        # HARD GATE 0: Session time filter
        if ctx.candle_count < 1:
            return self._hard_fail(0, GateReason.BLOCKED, "No candles yet")
        if ctx.candle_count * 5 < ctx.warm_up_minutes:
            return self._hard_fail(
                0,
                GateReason.BLOCKED,
                f"Warm-up: {ctx.candle_count * 5}min < {ctx.warm_up_minutes}min",
            )

        # HARD GATE 1: Data quality
        if ctx.tick_age_seconds > 30:
            return self._hard_fail(
                1, GateReason.STALE, f"Tick age {ctx.tick_age_seconds:.0f}s > 30s"
            )

        # HARD GATE 2: Session risk
        if ctx.is_risk_halted:
            return self._hard_fail(
                2, GateReason.SESSION_STOPPED, ctx.halt_reason or "Risk limit hit"
            )

        # HARD GATE 3: NO_TRADE state
        if ctx.market_state == MarketState.NO_TRADE:
            # EXCEPTION: If it's an extreme deviation, we override NO_TRADE
            # because we want to fade the extreme even if it's near POC of a leg.
            if not ctx.is_extreme_deviation:
                return self._hard_fail(
                    3, GateReason.FLAT, "Price at POC dead zone (state=NO_TRADE)"
                )
            else:
                logger.info("Responsive Fade: Overriding NO_TRADE due to extreme σ deviation")

        # HARD GATE 4: PROBING state — allow with aggression confirmation
        # PROBING can trade when: aggression >= threshold AND at a key level
        # This supports the PROBING + BALANCED playbook (acceptance/rejection)
        if ctx.market_state == MarketState.PROBING:
            if ctx.aggression_score < ctx.probing_aggression_threshold:
                return self._hard_fail(
                    4,
                    GateReason.FLAT,
                    f"PROBING without high aggression ({ctx.aggression_score:.1f} < {ctx.probing_aggression_threshold:.1f})",
                )
            # PROBING + HIGH aggression → allow through (playbook handles direction)

        # HARD GATE 5: Profile + key level
        if ctx.nearest_level <= 0:
            return self._hard_fail(5, GateReason.WAIT, "No key level near price")

        # HARD GATE 7: Drive validation
        if ctx.drive_number == 1:
            return self._hard_fail(7, GateReason.FLAT, "D1: first drive, entry suppressed")
        if ctx.drive_number >= 3:
            return self._hard_fail(
                7, GateReason.FLAT, f"D{ctx.drive_number}: level exhausted"
            )
        if ctx.drive_number == 2 and not ctx.drive_entry_valid:
            return self._hard_fail(7, GateReason.FLAT, "D2: D1 not rejected, no edge")

        # HARD GATE 11: Position sizing
        if not ctx.position_size_ok:
            return self._hard_fail(11, GateReason.BLOCKED, "Position sizing rejected")

        # HARD GATE 12: EIA window
        if ctx.eia_window_active:
            return self._hard_fail(12, GateReason.SUPPRESSED, "EIA release window active")

        # ── SOFT GATES (quorum scoring) ────────────────────────────────────
        # Fabio's 3/4 rule: minimum SOFT_GATE_QUORUM of these must pass.

        soft_results: list[_SoftGateResult] = []

        # SOFT GATE 6: Price at entry zone
        if ctx.distance_to_level_ticks > ctx.max_distance_to_level_ticks:
            soft_results.append(_SoftGateResult(
                gate=6, name="Price at entry zone",
                passed=False, reason=GateReason.ALERT,
                detail=f"Price {ctx.distance_to_level_ticks:.1f} ticks from level (max {ctx.max_distance_to_level_ticks:.0f})",
            ))
        else:
            soft_results.append(_SoftGateResult(
                gate=6, name="Price at entry zone",
                passed=True, reason=GateReason.TRADE,
                detail=f"Price {ctx.distance_to_level_ticks:.1f} ticks from level (within {ctx.max_distance_to_level_ticks:.0f})",
            ))

        # SOFT GATE 8: Aggression ≥ threshold
        if ctx.aggression_score < ctx.min_aggression_score:
            soft_results.append(_SoftGateResult(
                gate=8, name="Aggression minimum",
                passed=False, reason=GateReason.WAIT,
                detail=f"Aggression {ctx.aggression_score:.1f} < {ctx.min_aggression_score:.1f}",
            ))
        else:
            soft_results.append(_SoftGateResult(
                gate=8, name="Aggression minimum",
                passed=True, reason=GateReason.TRADE,
                detail=f"Aggression {ctx.aggression_score:.1f} >= {ctx.min_aggression_score:.1f}",
            ))

        # SOFT GATE 9: Cushion ≤ threshold
        if ctx.cushion_ticks > ctx.max_cushion_ticks:
            soft_results.append(_SoftGateResult(
                gate=9, name="Cushion ticks",
                passed=False, reason=GateReason.INVALID,
                detail=f"Cushion {ctx.cushion_ticks:.1f} > {MAX_CUSHION_TICKS} ticks",
            ))
        else:
            soft_results.append(_SoftGateResult(
                gate=9, name="Cushion ticks",
                passed=True, reason=GateReason.TRADE,
                detail=f"Cushion {ctx.cushion_ticks:.1f} <= {ctx.max_cushion_ticks:.0f} ticks",
            ))

        # SOFT GATE 10: R:R ≥ threshold
        if ctx.r_r_ratio < ctx.min_rr_ratio:
            soft_results.append(_SoftGateResult(
                gate=10, name="R:R ratio",
                passed=False, reason=GateReason.SKIP,
                detail=f"R:R {ctx.r_r_ratio:.2f} < {ctx.min_rr_ratio:.1f}",
            ))
        else:
            soft_results.append(_SoftGateResult(
                gate=10, name="R:R ratio",
                passed=True, reason=GateReason.TRADE,
                detail=f"R:R {ctx.r_r_ratio:.2f} >= {ctx.min_rr_ratio:.1f}",
            ))

        # ── Evaluate quorum ───────────────────────────────────────────────
        total = len(soft_results)
        passed_count = sum(1 for r in soft_results if r.passed)
        quorum = ctx.soft_gate_quorum
        quorum_met = passed_count >= quorum

        # Log soft gate outcomes
        for sg in soft_results:
            if sg.passed:
                logger.debug(
                    "SOFT GATE %d PASS: %s — %s (%d/%d quorum: %s)",
                    sg.gate, sg.name, sg.detail, passed_count, total,
                    "MET" if quorum_met else "NOT MET",
                )
            else:
                # ENHANCED LOGGING: Print exact threshold vs actual for debugging
                actual_value = _extract_actual_value(ctx, sg.gate)
                threshold_value = _extract_threshold(sg.gate, ctx)
                logger.info(
                    "SOFT GATE FAILED: %s (gate %d) — ACTUAL: %.2f, THRESHOLD: %.2f, DETAIL: %s (%d/%d quorum: %s)",
                    sg.name, sg.gate,
                    actual_value, threshold_value,
                    sg.detail, passed_count, total,
                    "MET" if quorum_met else "NOT MET",
                )

        if not quorum_met:
            # Find the first failed soft gate to report as the gating reason
            first_fail = next(r for r in soft_results if not r.passed)
            logger.info(
                "SOFT GATE QUORUM NOT MET: %d/%d passed (need %d) — blocking on gate %d (%s)",
                passed_count, total, quorum, first_fail.gate, first_fail.name,
            )
            return GateResult(
                passed=False,
                gate=first_fail.gate,
                reason=first_fail.reason,
                detail=(
                    f"Soft gate quorum not met: {passed_count}/{total} passed "
                    f"(need {quorum}). First fail: {first_fail.detail}"
                ),
                hard_gates_passed=True,
                soft_gates_total=total,
                soft_gates_passed=passed_count,
                quorum_met=False,
            )

        # ALL GATES PASSED
        logger.debug(
            "ALL GATES PASSED: hard gates OK, soft quorum met (%d/%d)",
            passed_count, total,
        )

        # ── ESCALATION (3 PM Fix) ──────────────────────────────────────────
        # If extreme deviation is present, upgrade the result to TRADE
        # and explicitly mark it as an EXTREME FADE setup.
        final_reason = GateReason.TRADE
        final_detail = f"All gates passed (hard: OK, soft: {passed_count}/{total} >= quorum {quorum})"

        if ctx.is_extreme_deviation:
            final_detail = "⚠️ EXTREME FADE SETUP — Overriding gates due to extreme σ deviation"
            logger.warning("ESCALATION: Extreme deviation detected — forcing trade signal")

        return GateResult(
            passed=True,
            gate=12,
            reason=final_reason,
            detail=final_detail,
            setup_type=ctx.setup_type,
            r_r_ratio=ctx.r_r_ratio,
            hard_gates_passed=True,
            soft_gates_total=total,
            soft_gates_passed=passed_count,
            quorum_met=True,
        )

    @staticmethod
    def _hard_fail(gate: int, reason: GateReason, detail: str) -> GateResult:
        logger.debug("HARD GATE FAILED: gate %d %s — %s", gate, reason.value, detail)
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


def _extract_actual_value(ctx: GateContext, gate: int) -> float:
    """Extract the actual value for a soft gate (for logging)."""
    if gate == 6:
        return ctx.distance_to_level_ticks
    if gate == 8:
        return ctx.aggression_score
    if gate == 9:
        return ctx.cushion_ticks
    if gate == 10:
        return ctx.r_r_ratio
    return 0.0


def _extract_threshold(gate: int, ctx: GateContext) -> float:
    """Extract the threshold value for a soft gate (for logging)."""
    if gate == 6:
        return ctx.max_distance_to_level_ticks
    if gate == 8:
        return ctx.min_aggression_score
    if gate == 9:
        return ctx.max_cushion_ticks
    if gate == 10:
        return ctx.min_rr_ratio
    return 0.0
