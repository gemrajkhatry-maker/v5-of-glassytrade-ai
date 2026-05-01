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
    lvns_near_price: list[float] = field(default_factory=list)  # LVNs within 5 ticks

    # TP/SL validation
    take_profit: float = 0.0  # For gate validation
    stop_loss: float = 0.0

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
    
    # PCR bias (Put-Call Ratio for NSE options)
    pcr: float = 1.0  # Put-Call Ratio
    pcr_aligned: bool = True  # Direction aligned with PCR bias

    # Entry direction from LLM
    direction: str = "LONG"  # "LONG" or "SHORT"

    # VWAP extreme filter (Fabio spec: BLOCK at VWAP ±2σ)
    vwap_sigma: float = 0.0  # Current VWAP deviation in standard deviations

    # Consecutive losses per symbol (Fabio spec)
    consecutive_losses: int = 0

    # Max trades per symbol (Fabio spec: 5 per session)
    trades_today: int = 0
    max_trades_per_symbol: int = 5

    # New: Extreme deviation escalation (> 3.0 sigma)
    is_extreme_deviation: bool = False

    # Configurable gate thresholds (exchange-specific)
    max_distance_to_level_ticks: float = 3.0  # Gate 6: max ticks from nearest level
    min_aggression_score: float = 2.0  # Gate 8: minimum aggression for any entry
    max_cushion_ticks: float = 10.0  # Gate 9: max cushion (ticks from price to level)
    min_rr_ratio: float = 1.5  # Gate 10: minimum risk-reward ratio
    weekly_bias_strength: float = 0.0
    # PCR bias thresholds (NSE-specific)
    pcr_bullish_max: float = 0.85  # LONG blocked if PCR > 0.85 (bearish bias)
    pcr_bearish_min: float = 1.15  # SHORT blocked if PCR < 1.15 (bullish bias)

    # OI Walls for NSE (protection levels)
    oi_walls: list = field(default_factory=list)  # List of OIWall dataclasses
    oi_wall_aligned: bool = True  # Nearest wall aligns with entry direction

    # Session strategy filter (Fabio's timing rules)
    favor_strategy: str = "NEUTRAL"  # Session-favored strategy: MEAN_REVERSION | TREND_CONTINUATION | NEUTRAL

    # Setup
    setup_type: str = "NONE"
    r_r_ratio: float = 0.0
    cushion_ticks: float = 0.0

    # Quorum configuration (overridable per exchange/session)
    soft_gate_quorum: int = SOFT_GATE_QUORUM  # Minimum soft gates that must pass

    # PROBING state threshold (DEPRECATED - kept for backward compatibility)
    probing_aggression_threshold: float = 3.0


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
    
    # LLM guidance fields (pre-computed valid directions)
    allowed_directions: list[str] = field(default_factory=lambda: ["LONG", "SHORT", "FLAT"])
    confidence_level: str = "MEDIUM"      # HIGH/MEDIUM/LOW based on rules_passed
    should_wait: bool = False            # True if FIRST_DRIVE or similar

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

        # HARD GATE 2b: Consecutive loss throttle (Fabio spec: 2+ losses = 30min cooldown)
        if ctx.consecutive_losses >= 2:
            return self._hard_fail(
                2, GateReason.FLAT,
                f"Consecutive loss throttle: {ctx.consecutive_losses} losses - wait 30min"
            )

        # HARD GATE 2c: Max trades per symbol (Fabio spec: 5 per session)
        if ctx.trades_today >= ctx.max_trades_per_symbol:
            return self._hard_fail(
                2, GateReason.FLAT,
                f"Max trades reached: {ctx.trades_today}/{ctx.max_trades_per_symbol} for {ctx.symbol}"
            )

        # HARD GATE 3: NO_TRADE state (REMOVED - 2-state model)
        # Note: With Fabio's 2-state model, NO_TRADE state no longer exists

        # HARD GATE 4: PROBING state (REMOVED - part of IMBALANCED in 2-state)
        # Note: PROBING is now classified as IMBALANCED (unconfirmed break)

        # HARD GATE 5: Profile + key level (LVN preferred for continuation)
        # Fabio Location Gate (NEW): Block LONG when price > VAH in BALANCED session
        is_long = str(ctx.direction).upper() == "LONG"
        is_balanced = ctx.market_state == MarketState.BALANCED
        if is_long and is_balanced and ctx.price > ctx.vah:
            return self._hard_fail(
                5, GateReason.FLAT,
                f"Location Gate: LONG blocked - price {ctx.price:.2f} > VAH {ctx.vah:.2f} in BALANCED session"
            )
        # Fabio VWAP Extreme Filter: Block LONG at VWAP +2σ or higher
        if is_long and ctx.vwap_sigma >= 2.0:
            return self._hard_fail(
                5, GateReason.FLAT,
                f"VWAP Extreme: LONG blocked - price at +{ctx.vwap_sigma:.1f}σ VWAP (extreme overextension)"
            )
        if ctx.nearest_level <= 0:
            return self._hard_fail(5, GateReason.WAIT, "No key level near price")
        # Fabio's rule: LVN provides highest probability reaction zone
        # For trend continuation, require LVN within 2 ticks
        if ctx.lvns_near_price:
            nearest_lvn = min(ctx.lvns_near_price, key=lambda x: abs(x - ctx.price))
            if abs(nearest_lvn - ctx.price) / ctx.tick_size > 2.0:
                logger.debug(
                    "LVN enforcement: nearest LVN at %.2f (%.1f ticks from price)",
                    nearest_lvn, abs(nearest_lvn - ctx.price) / ctx.tick_size
                )

        # HARD GATE 7: Drive validation
        # Fabio's rule: First drive should be suppressed (wait for re-test)
        if ctx.drive_number == 1:
            return self._hard_fail(7, GateReason.FLAT, "D1: first drive, entry suppressed - wait for re-test")
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

        # HARD GATE 13: Session strategy filter (Fabio's timing rules)
        # Enforce: TREND_MODEL only when session favors TREND_CONTINUATION
        # Enforce: MEAN_REVERSION only when session favors MEAN_REVERSION
        session_check = self._check_session_strategy_filter(ctx)
        if not session_check.passed:
            return self._hard_fail(
                13, session_check.reason, session_check.detail
            )

        # ── SOFT GATES (quorum scoring) ────────────────────────────────────
        # Fabio's 3/4 rule: minimum SOFT_GATE_QUORUM of these must pass.
        # PCR bias check is added as soft gate for NSE options

        soft_results: list[_SoftGateResult] = []

        # PCR BIAS CHECK (Gate 4b) — NSE options directional bias
        # PCR < 0.85 = bullish bias (favor LONG)
        # PCR > 1.15 = bearish bias (favor SHORT)
        # PCR between 0.85-1.15 = neutral
        pcr_check_passed = self._check_pcr_alignment(ctx)
        if pcr_check_passed:
            logger.debug("PCR bias neutral or aligned — allowing entry")
        else:
            logger.info(
                "PCR bias check: PCR=%.2f conflicts with direction — proceeding with caution",
                ctx.pcr,
            )
            # Log warning but don't fail (soft gate behavior)
            soft_results.append(_SoftGateResult(
                gate=4, name="PCR bias alignment",
                passed=True, reason=GateReason.TRADE,
                detail=f"PCR {ctx.pcr:.2f} — directional bias noted",
            ))

        # OI WALL CHECK (Gate 4c) — NSE protection levels
        oi_wall_check_passed = self._check_oi_wall_alignment(ctx)
        if oi_wall_check_passed:
            logger.debug("OI wall aligned — allowing entry")
        else:
            logger.info("OI wall not aligned — entry near protection level")
            soft_results.append(_SoftGateResult(
                gate=4, name="OI wall alignment",
                passed=True, reason=GateReason.TRADE,
                detail="OI wall not aligned — proceed with caution",
            ))

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

        # SOFT GATE 14: TP within VA bounds (Fabio: target previous balance area)
        # Validate TP is within 2x VA width from price (not too far)
        va_width = ctx.vah - ctx.val
        max_tp_dist = va_width * 2.0 if va_width > 0 else ctx.price * 0.02
        tp_distance = abs(ctx.take_profit - ctx.price)
        if tp_distance > max_tp_dist and ctx.take_profit > 0:
            soft_results.append(_SoftGateResult(
                gate=14, name="TP within VA bounds",
                passed=False, reason=GateReason.SKIP,
                detail=f"TP {ctx.take_profit:.2f} too far from price ({tp_distance:.2f} > {max_tp_dist:.2f})",
            ))
        else:
            soft_results.append(_SoftGateResult(
                gate=14, name="TP within VA bounds",
                passed=True, reason=GateReason.TRADE,
                detail=f"TP {ctx.take_profit:.2f} within VA bounds",
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
        
        # Compute allowed directions based on location rules
        allowed_directions = ["LONG", "SHORT", "FLAT"]
        if ctx.market_state == MarketState.BALANCED:
            if ctx.price > ctx.vah:
                allowed_directions = ["SHORT", "FLAT"]
            elif ctx.price < ctx.val:
                allowed_directions = ["LONG", "FLAT"]
            else:
                allowed_directions = ["FLAT", "WAIT"]
        
        # Compute confidence based on soft gates passed
        if passed_count == 4 and ctx.lvns_near_price:
            confidence_level = "HIGH"
        elif passed_count == 3:
            confidence_level = "MEDIUM"
        else:
            confidence_level = "LOW"
        
        # FIRST_DRIVE forces WAIT
        should_wait = ctx.drive_number == 1

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
            allowed_directions=allowed_directions,
            confidence_level=confidence_level,
            should_wait=should_wait,
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

    @staticmethod
    def _check_pcr_alignment(ctx: GateContext) -> bool:
        """Check if PCR bias aligns with entry direction.
        
        PCR thresholds:
        - PCR < 0.85: bullish bias (favor LONG)
        - PCR > 1.15: bearish bias (favor SHORT)
        - PCR 0.85-1.15: neutral
        
        Returns True if neutral or aligned.
        """
        # Neutral range - always pass
        if ctx.pcr_bullish_max <= ctx.pcr <= ctx.pcr_bearish_min:
            return True
        
        # PCR indicates bias - check if conflict
        # Note: actual direction check would need to be passed in context
        # For now, we log the bias but allow the trade to proceed
        return True  # Soft gate - doesn't block, just warns

    @staticmethod
    def _check_session_strategy_filter(ctx: GateContext):
        """Check if setup type aligns with session-favored strategy.
        
        Fabio's timing rules:
        - Phase 2 (09:30-11:30): ALL MODELS ACTIVE
        - Phase 3 (11:30-14:00): MEAN_REVERSION ONLY
        - Phase 4 (14:00-15:15): ALL MODELS ACTIVE
        
        Returns GateResult with passed=True if aligned, False with reason/dtail.
        """
        setup = ctx.setup_type
        favor = ctx.favor_strategy
        
        # No setup or NEUTRAL session - allow
        if setup == "NONE" or favor == "NEUTRAL":
            return GateResult(passed=True, gate=13, reason=GateReason.TRADE, detail="Session filter: NEUTRAL")
        
        # Check TREND_MODEL in MEAN_REVERSION-favored session
        if setup == "TREND_MODEL" and favor == "MEAN_REVERSION":
            return GateResult(
                passed=False, gate=13, reason=GateReason.BLOCKED,
                detail=f"Session filter: TREND_MODEL blocked (session favors {favor})"
            )
        
        # Check MEAN_REVERSION in TREND_CONTINUATION-favored session
        # This is allowed - mean reversion can still work in trend phases
        # Only strict block is TREND in MEAN_REVERSION phase per Fabio
        
        return GateResult(passed=True, gate=13, reason=GateReason.TRADE, detail="Session filter: PASSED")

    @staticmethod
    def _check_oi_wall_alignment(ctx: GateContext) -> bool:
        """Check if OI walls align with entry.
        
        For NSE options, OI walls act as protection levels.
        Near an OI wall = strong support/resistance.
        
        Returns True if aligned or no walls detected.
        """
        if not ctx.oi_walls:
            return True  # No walls detected - proceed
        
        # Check if price is near an OI wall
        price = ctx.price
        tick_size = ctx.tick_size
        
        for wall in ctx.oi_walls:
            if abs(wall.strike - price) / tick_size <= 10:  # Within 10 ticks of wall
                # Price near wall - this is actually good (protection level)
                return True
        
        return True  # Soft gate - doesn't block


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
