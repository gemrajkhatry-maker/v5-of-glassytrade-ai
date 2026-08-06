"""Gate Pipeline — 5-gate validation per Fabio AMT spec.

The former 12-gate hybrid (hard gates + soft-gate quorum) is slimmed to exactly
5 gates. The redundant hard gates and the soft-quorum strategy proxies fold into
the 5 gates below:

  GATE 1: Session phase — warm-up, data freshness, EIA window   → BLOCKED/STALE/SUPPRESSED
          (folds old gates 0, 1, 12)
  GATE 2: No-position / cooldown — risk halt, flat state,
          drive validation, position sizing                      → SESSION_STOPPED/FLAT/BLOCKED
          (folds old gates 2, 3, 4, 7, 11)
  GATE 3: Probability/direction — intended direction must be
          clean (CVD conflict blocks)                            → WAIT
          (folds the old CVD-conflict probe)
  GATE 4: Strategy alignment — Triple-A/VWAP context: edge is
          AGGRESSION phase OR fresh absorption; the old
          distance/aggression/cushion soft proxies are replaced
          by this edge + level location                          → WAIT
          (folds old gates 5, 6, 8, 9)
  GATE 5: Risk-reward — R:R ≥ 1.5 and cushion ≤ max              → INVALID/SKIP
          (folds old soft gates 9, 10)

All 5 gates are fail-fast (AND) gates — there is no quorum anymore.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from enum import Enum

from quant.contracts.enums import MarketState, SetupType
from quant.contracts.constants import (
    WARM_UP_MINUTES_MCX,
    SOFT_GATE_QUORUM,
)
from quant.amt.session.eia import EIACalendar

logger = logging.getLogger(__name__)

# EIA calendar singleton for gate pipeline
_eia_calendar = EIACalendar(suppression_minutes=15)

# Fresh-absorption window: an absorption older than this many bars is no longer
# an active accumulation context (no strategy edge).
MAX_ABSORPTION_BAR_AGE = 10


class GateType(str, Enum):
    """Type of gate — determines evaluation semantics."""
    HARD = "HARD"
    SOFT = "SOFT"


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

    # CVD conflict flag (directional CVD divergence vs price action)
    cvd_conflict: bool = False

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

    # Triple-A context (absorption + VWAP breakout carry the edge; the
    # range-bar Triple-A state machine was removed with the range-bar layer)
    absorption_detected: bool = False
    absorption_bar_age: int = 0
    vwap_breakout: str | None = None


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

    # Number of gates evaluated (1-5). 5 on a full pass.
    gate_count: int = 0

    @property
    def is_trade(self) -> bool:
        return self.passed and self.reason == GateReason.TRADE


class GatePipeline:
    """5-gate fail-fast validation per Fabio AMT spec (no quorum)."""

    def evaluate(self, ctx: GateContext) -> GateResult:
        """Run all 5 gates using fail-fast AND logic.

        Returns GateResult with gate_count = number of gates evaluated.
        """

        # ── GATE 1: Session phase ────────────────────────────────────────────
        if ctx.candle_count < 1:
            return self._fail(1, GateReason.BLOCKED, "No candles yet")
        if ctx.candle_count * 5 < ctx.warm_up_minutes:
            return self._fail(
                1,
                GateReason.BLOCKED,
                f"Warm-up: {ctx.candle_count * 5}min < {ctx.warm_up_minutes}min",
            )
        if ctx.tick_age_seconds > 30:
            return self._fail(
                1, GateReason.STALE, f"Tick age {ctx.tick_age_seconds:.0f}s > 30s"
            )
        if ctx.eia_window_active:
            return self._fail(1, GateReason.SUPPRESSED, "EIA release window active")

        # ── GATE 2: No-position / cooldown ───────────────────────────────────
        if ctx.is_risk_halted:
            return self._fail(
                2, GateReason.SESSION_STOPPED, ctx.halt_reason or "Risk limit hit"
            )
        if (
            ctx.market_state == MarketState.BALANCED
            and ctx.zone == "AT_POC"
            and not ctx.is_extreme_deviation
        ):
            return self._fail(
                2, GateReason.FLAT, "Price at POC dead zone (BALANCED state)"
            )
        if (
            ctx.market_state == MarketState.IMBALANCED
            and ctx.aggression_score < ctx.probing_aggression_threshold
        ):
            return self._fail(
                2,
                GateReason.FLAT,
                f"PROBING without high aggression ({ctx.aggression_score:.1f} < {ctx.probing_aggression_threshold:.1f})",
            )
        if ctx.drive_number == 1:
            return self._fail(2, GateReason.FLAT, "D1: first drive, entry suppressed")
        if ctx.drive_number >= 3:
            return self._fail(
                2, GateReason.FLAT, f"D{ctx.drive_number}: level exhausted"
            )
        if ctx.drive_number == 2 and not ctx.drive_entry_valid:
            return self._fail(2, GateReason.FLAT, "D2: D1 not rejected, no edge")
        if not ctx.position_size_ok:
            return self._fail(2, GateReason.BLOCKED, "Position sizing rejected")

        # ── GATE 3: Probability / direction ──────────────────────────────────
        # Direction ∈ {LONG, SHORT} and P ≥ threshold are not carried on
        # GateContext yet (the agent layer supplies them above this gate). Until
        # then gate 3 only blocks a direction that order flow contradicts.
        if ctx.cvd_conflict:
            return self._fail(3, GateReason.WAIT, "CVD conflicts with intended direction")

        # ── GATE 4: Strategy alignment (Triple-A / VWAP context) ─────────────
        # Edge must be present: fresh absorption (accumulation context) which
        # gives meaning to a VWAP breakout. A lone vwap_breakout is not a
        # confirmed edge. If no Triple-A/VWAP context is populated at all, gate 4
        # degrades to a location-only check so un-wired callers keep working.
        triple_a_populated = ctx.absorption_detected or ctx.vwap_breakout is not None
        if triple_a_populated:
            edge = (
                ctx.absorption_detected
                and ctx.absorption_bar_age <= MAX_ABSORPTION_BAR_AGE
            )
            if not edge:
                return self._fail(
                    4,
                    GateReason.WAIT,
                    "No strategy edge (Triple-A/VWAP): no fresh absorption",
                )
        if ctx.nearest_level <= 0:
            return self._fail(4, GateReason.WAIT, "No key level near price")
        if ctx.distance_to_level_ticks > ctx.max_distance_to_level_ticks:
            return self._fail(
                4,
                GateReason.WAIT,
                f"Price {ctx.distance_to_level_ticks:.1f} ticks from level (max {ctx.max_distance_to_level_ticks:.0f})",
            )

        # ── GATE 5: Risk-reward ──────────────────────────────────────────────
        if ctx.cushion_ticks > ctx.max_cushion_ticks:
            return self._fail(
                5,
                GateReason.INVALID,
                f"Cushion {ctx.cushion_ticks:.1f} > {ctx.max_cushion_ticks:.0f} ticks",
            )
        if ctx.r_r_ratio < ctx.min_rr_ratio:
            return self._fail(
                5, GateReason.SKIP, f"R:R {ctx.r_r_ratio:.2f} < {ctx.min_rr_ratio:.1f}"
            )

        # ── ALL GATES PASSED ─────────────────────────────────────────────────
        logger.debug("ALL 5 GATES PASSED: hard gates OK")

        final_detail = "All 5 gates passed (hard: OK)"
        if ctx.is_extreme_deviation:
            final_detail = "⚠️ EXTREME FADE SETUP — Overriding gates due to extreme σ deviation"
            logger.warning("ESCALATION: Extreme deviation detected — forcing trade signal")

        return GateResult(
            passed=True,
            gate=5,
            reason=GateReason.TRADE,
            detail=final_detail,
            setup_type=ctx.setup_type,
            r_r_ratio=ctx.r_r_ratio,
            hard_gates_passed=True,
            soft_gates_total=5,
            soft_gates_passed=5,
            quorum_met=True,
            gate_count=5,
        )

    @staticmethod
    def _fail(gate: int, reason: GateReason, detail: str) -> GateResult:
        logger.debug("GATE FAILED: gate %d %s — %s", gate, reason.value, detail)
        return GateResult(
            passed=False,
            gate=gate,
            reason=reason,
            detail=detail,
            hard_gates_passed=False,
            soft_gates_total=gate,
            soft_gates_passed=gate - 1,
            quorum_met=False,
            gate_count=gate,
        )
