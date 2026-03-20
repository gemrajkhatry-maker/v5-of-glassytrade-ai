"""Gate Pipeline — Sequential 12-gate validation per Fabio AMT spec.

First FAIL returns reason immediately. No computation wasted after first reject.

GATE 0: Session time filter (warm-up, dead zone)  → BLOCKED
GATE 1: Data quality (STALE, gap > 30s)           → STALE
GATE 2: Session risk (daily loss, drawdown)        → SESSION_STOPPED
GATE 3: NO_TRADE state (POC ± 2 ticks)            → FLAT
GATE 4: PROBING state (unconfirmed break)          → FLAT
GATE 5: Profile + key level identified             → WAIT
GATE 6: Price at entry zone (within 3 ticks)       → ALERT
GATE 7: Drive = 2 (first drive rejected)           → FLAT/ALERT
GATE 8: Aggression ≥ 2.0                           → WAIT
GATE 9: Cushion ≤ 10 ticks                         → INVALID
GATE 10: R:R ≥ 1.5                                 → SKIP
GATE 11: Position sizing passes risk manager        → BLOCKED
GATE 12: EIA release window                        → SUPPRESSED
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
)
from app.domain.fabio_ai.services.eia_calendar import EIACalendar

logger = logging.getLogger(__name__)

# EIA calendar singleton for gate pipeline
_eia_calendar = EIACalendar(suppression_minutes=15)


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
    weekly_bias_strength: float = 0.0
    

    # Setup
    setup_type: str = "NONE"
    r_r_ratio: float = 0.0
    cushion_ticks: float = 0.0


@dataclass
class GateResult:
    """Result of gate pipeline evaluation."""

    passed: bool  # True if all 12 gates passed
    gate: int  # Gate number that failed (0-12), 12 if all passed
    reason: GateReason  # Output reason
    detail: str  # Human-readable detail
    setup_type: str = "NONE"  # Setup type if passed
    r_r_ratio: float = 0.0  # R:R if passed

    @property
    def is_trade(self) -> bool:
        return self.passed and self.reason == GateReason.TRADE


class GatePipeline:
    """Sequential 12-gate validation. First fail returns immediately."""

    def evaluate(self, ctx: GateContext) -> GateResult:
        """Run all 12 gates. First FAIL returns result."""

        # GATE 0: Session time filter
        if ctx.candle_count < 1:
            return self._fail(0, GateReason.BLOCKED, "No candles yet")
        if ctx.candle_count * 5 < ctx.warm_up_minutes:
            return self._fail(
                0,
                GateReason.BLOCKED,
                f"Warm-up: {ctx.candle_count * 5}min < {ctx.warm_up_minutes}min",
            )

        # GATE 1: Data quality
        if ctx.tick_age_seconds > 30:
            return self._fail(
                1, GateReason.STALE, f"Tick age {ctx.tick_age_seconds:.0f}s > 30s"
            )

        # GATE 2: Session risk
        if ctx.is_risk_halted:
            return self._fail(
                2, GateReason.SESSION_STOPPED, ctx.halt_reason or "Risk limit hit"
            )

        # GATE 3: NO_TRADE state
        if ctx.market_state == MarketState.NO_TRADE:
            return self._fail(
                3, GateReason.FLAT, f"Price at POC dead zone (state=NO_TRADE)"
            )

        # GATE 4: PROBING state
        if ctx.market_state == MarketState.PROBING:
            return self._fail(4, GateReason.FLAT, f"Unconfirmed break (state=PROBING)")

        # GATE 5: Profile + key level
        if ctx.nearest_level <= 0:
            return self._fail(5, GateReason.WAIT, "No key level near price")

        # GATE 6: Price at entry zone
        if ctx.distance_to_level_ticks > 3:
            return self._fail(
                6,
                GateReason.ALERT,
                f"Price {ctx.distance_to_level_ticks:.1f} ticks from level (max 3)",
            )

        # GATE 7: Drive = 2 (D1 rejected)
        if ctx.drive_number == 1:
            return self._fail(7, GateReason.FLAT, "D1: first drive, entry suppressed")
        if ctx.drive_number >= 3:
            return self._fail(
                7, GateReason.FLAT, f"D{ctx.drive_number}: level exhausted"
            )
        if ctx.drive_number == 2 and not ctx.drive_entry_valid:
            return self._fail(7, GateReason.FLAT, "D2: D1 not rejected, no edge")

        # GATE 8: Aggression ≥ 2.0
        if ctx.aggression_score < MIN_AGGRESSION_SCORE:
            return self._fail(
                8,
                GateReason.WAIT,
                f"Aggression {ctx.aggression_score:.1f} < {MIN_AGGRESSION_SCORE}",
            )

        # GATE 9: Cushion ≤ 10 ticks
        if ctx.cushion_ticks > MAX_CUSHION_TICKS:
            return self._fail(
                9,
                GateReason.INVALID,
                f"Cushion {ctx.cushion_ticks:.1f} > {MAX_CUSHION_TICKS} ticks",
            )

        # GATE 10: R:R ≥ 1.5
        if ctx.r_r_ratio < MIN_RR_RATIO:
            return self._fail(
                10, GateReason.SKIP, f"R:R {ctx.r_r_ratio:.2f} < {MIN_RR_RATIO}"
            )

        # GATE 11: Position sizing
        if not ctx.position_size_ok:
            return self._fail(11, GateReason.BLOCKED, "Position sizing rejected")

        # GATE 12: EIA window
        if ctx.eia_window_active:
            return self._fail(12, GateReason.SUPPRESSED, "EIA release window active")

        # ALL GATES PASSED
        return GateResult(
            passed=True,
            gate=12,
            reason=GateReason.TRADE,
            detail="All 12 gates passed",
            setup_type=ctx.setup_type,
            r_r_ratio=ctx.r_r_ratio,
        )

    @staticmethod
    def _fail(gate: int, reason: GateReason, detail: str) -> GateResult:
        logger.debug("GATE %d FAIL: %s — %s", gate, reason.value, detail)
        return GateResult(
            passed=False,
            gate=gate,
            reason=reason,
            detail=detail,
        )
