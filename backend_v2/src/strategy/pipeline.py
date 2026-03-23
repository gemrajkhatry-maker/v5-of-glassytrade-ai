"""
Gate pipeline — sequential 12-gate validation.

First FAIL = immediate output.
All gates must pass for a trade signal.
"""

from dataclasses import dataclass
from typing import Optional

from src.config.engine_config import CFG
from src.core.session_manager import SessionState


@dataclass
class GateContext:
    """Context for gate evaluation."""

    # Session
    session_state: SessionState
    candle_count: int
    tick_age_seconds: float

    # Risk
    is_risk_halted: bool
    consecutive_losses: int
    daily_pnl_pct: float

    # Market
    market_state: str
    zone: str
    poc: Optional[float]
    vah: Optional[float]
    val: Optional[float]
    price: float
    tick_size: float

    # Drive
    drive_number: int
    drive_entry_valid: bool

    # Aggression
    aggression_score: float

    # Trade
    entry_price: Optional[float]
    stop_loss: Optional[float]
    target: Optional[float]
    risk_reward: float
    cushion_ticks: int

    # Position sizing
    position_size_ok: bool

    # EIA
    eia_suppressed: bool


@dataclass
class GateResult:
    """Gate evaluation result."""

    passed: bool
    gate: int
    reason: str  # BLOCKED, STALE, SESSION_STOPPED, FLAT, ALERT, WAIT, INVALID, SKIP, SUPPRESSED, TRADE


class GatePipeline:
    """
    Sequential 12-gate validation.

    Evaluates gates in order. First fail returns immediately.
    """

    def evaluate(self, context: GateContext) -> GateResult:
        """
        Run all 12 gates in order.

        Args:
            context: Gate evaluation context

        Returns:
            GateResult with pass/fail and reason.
        """
        # GATE 0: Session time filter
        if not self._gate_0_session_time(context):
            return GateResult(passed=False, gate=0, reason="BLOCKED")

        # GATE 1: Data quality
        if not self._gate_1_data_quality(context):
            return GateResult(passed=False, gate=1, reason="STALE")

        # GATE 2: Session risk
        if not self._gate_2_session_risk(context):
            return GateResult(passed=False, gate=2, reason="SESSION_STOPPED")

        # GATE 3: NO_TRADE state
        if context.market_state == "NO_TRADE":
            return GateResult(passed=False, gate=3, reason="FLAT")

        # GATE 4: PROBING state
        if context.market_state == "PROBING":
            return GateResult(passed=False, gate=4, reason="FLAT")

        # GATE 5: Profile + key level
        if not self._gate_5_profile_level(context):
            return GateResult(passed=False, gate=5, reason="WAIT")

        # GATE 6: Price at entry zone
        if not self._gate_6_at_entry_zone(context):
            return GateResult(passed=False, gate=6, reason="ALERT")

        # GATE 7: Drive = 2
        if not self._gate_7_drive_valid(context):
            return GateResult(passed=False, gate=7, reason="FLAT")

        # GATE 8: Aggression ≥ 2.0
        if context.aggression_score < CFG.min_aggression_score:
            return GateResult(passed=False, gate=8, reason="WAIT")

        # GATE 9: Cushion ≤ 10 ticks
        if not self._gate_9_cushion(context):
            return GateResult(passed=False, gate=9, reason="INVALID")

        # GATE 10: R:R ≥ 1.5
        if not self._gate_10_rr(context):
            return GateResult(passed=False, gate=10, reason="SKIP")

        # GATE 11: Position sizing
        if not self._gate_11_position_sizing(context):
            return GateResult(passed=False, gate=11, reason="BLOCKED")

        # GATE 12: EIA window
        if not self._gate_12_eia_window(context):
            return GateResult(passed=False, gate=12, reason="SUPPRESSED")

        # ALL GATES PASSED
        return GateResult(passed=True, gate=12, reason="TRADE")

    def _gate_0_session_time(self, context: GateContext) -> bool:
        """GATE 0: Session time filter."""
        if context.session_state == SessionState.OUTSIDE:
            return False
        if context.session_state == SessionState.WARMUP:
            return False
        return True

    def _gate_1_data_quality(self, context: GateContext) -> bool:
        """GATE 1: Data quality check."""
        return context.tick_age_seconds < CFG.stale_threshold_seconds

    def _gate_2_session_risk(self, context: GateContext) -> bool:
        """GATE 2: Session risk check."""
        if context.is_risk_halted:
            return False
        if context.consecutive_losses >= CFG.max_consecutive_losses:
            return False
        if context.daily_pnl_pct <= -CFG.max_daily_loss_pct:
            return False
        return True

    def _gate_5_profile_level(self, context: GateContext) -> bool:
        """GATE 5: Profile and key level identified."""
        return (
            context.poc is not None
            and context.vah is not None
            and context.val is not None
        )

    def _gate_6_at_entry_zone(self, context: GateContext) -> bool:
        """GATE 6: Price at entry zone (within 3 ticks)."""
        if context.entry_price is None:
            return False

        distance = abs(context.price - context.entry_price)
        max_distance = CFG.drive_proximity_ticks * context.tick_size
        return distance <= max_distance

    def _gate_7_drive_valid(self, context: GateContext) -> bool:
        """GATE 7: Drive number = 2 and entry valid."""
        return context.drive_number == 2 and context.drive_entry_valid

    def _gate_9_cushion(self, context: GateContext) -> bool:
        """GATE 9: Cushion ≤ 10 ticks."""
        return context.cushion_ticks <= CFG.max_cushion_ticks

    def _gate_10_rr(self, context: GateContext) -> bool:
        """GATE 10: R:R ≥ 1.5."""
        return context.risk_reward >= CFG.min_rr_ratio

    def _gate_11_position_sizing(self, context: GateContext) -> bool:
        """GATE 11: Position sizing passes."""
        return context.position_size_ok

    def _gate_12_eia_window(self, context: GateContext) -> bool:
        """GATE 12: EIA window check."""
        return not context.eia_suppressed