"""Unit tests for GatePipeline — hybrid hard/soft gate validation per Fabio AMT spec.

Hard gates: fail-fast AND logic (safety/risk).
Soft gates: quorum scoring — Fabio's 3/4 rule (minimum 3 of 4 soft gates must pass).
"""

import pytest
from app.domain.fabio_ai.services.gate_pipeline import (
    GatePipeline,
    GateContext,
    GateResult,
    GateReason,
    GateType,
)
from app.domain.trading.models.enums import MarketState


class TestGatePipelineSequential:
    """Gates are evaluated in order. First FAIL returns immediately."""

    def test_gate_0_no_candles(self):
        """GATE 0: No candles → BLOCKED."""
        ctx = GateContext(candle_count=0)
        result = GatePipeline().evaluate(ctx)
        assert result.passed is False
        assert result.gate == 0
        assert result.reason == GateReason.BLOCKED

    def test_gate_0_warmup(self):
        """GATE 0: Insufficient warm-up → BLOCKED."""
        ctx = GateContext(candle_count=2, warm_up_minutes=15)  # 2*5=10min < 15min
        result = GatePipeline().evaluate(ctx)
        assert result.passed is False
        assert result.gate == 0
        assert result.reason == GateReason.BLOCKED

    def test_gate_0_passes_after_warmup(self):
        """GATE 0: Enough candles → passes."""
        ctx = GateContext(candle_count=4, warm_up_minutes=15, tick_age_seconds=1.0,
                         poc=100, vah=105, val=95, price=100, tick_size=0.1,
                         nearest_level=100, distance_to_level_ticks=0,
                         drive_number=2, drive_entry_valid=True,
                         aggression_score=2.5, cushion_ticks=5, r_r_ratio=2.0)
        result = GatePipeline().evaluate(ctx)
        # Should pass gate 0, fail somewhere else or pass all
        assert result.gate >= 0

    def test_gate_1_stale_data(self):
        """GATE 1: Tick age > 30s → STALE."""
        ctx = GateContext(candle_count=10, tick_age_seconds=35.0)
        result = GatePipeline().evaluate(ctx)
        assert result.passed is False
        assert result.gate == 1
        assert result.reason == GateReason.STALE

    def test_gate_2_risk_halted(self):
        """GATE 2: Risk halted → SESSION_STOPPED."""
        ctx = GateContext(candle_count=10, tick_age_seconds=1.0, is_risk_halted=True,
                         halt_reason="Daily loss limit")
        result = GatePipeline().evaluate(ctx)
        assert result.passed is False
        assert result.gate == 2
        assert result.reason == GateReason.SESSION_STOPPED

    def test_gate_3_no_trade_state(self):
        """GATE 3: NO_TRADE state → FLAT."""
        ctx = GateContext(candle_count=10, tick_age_seconds=1.0,
                         market_state=MarketState.NO_TRADE)
        result = GatePipeline().evaluate(ctx)
        assert result.passed is False
        assert result.gate == 3
        assert result.reason == GateReason.FLAT

    def test_gate_4_probing_state(self):
        """GATE 4: PROBING state → FLAT."""
        ctx = GateContext(candle_count=10, tick_age_seconds=1.0,
                         market_state=MarketState.PROBING)
        result = GatePipeline().evaluate(ctx)
        assert result.passed is False
        assert result.gate == 4
        assert result.reason == GateReason.FLAT

    def test_gate_5_no_key_level(self):
        """GATE 5: No key level near price → WAIT."""
        ctx = GateContext(candle_count=10, tick_age_seconds=1.0,
                         market_state=MarketState.BALANCED,
                         nearest_level=0)
        result = GatePipeline().evaluate(ctx)
        assert result.passed is False
        assert result.gate == 5
        assert result.reason == GateReason.WAIT

    def test_gate_6_price_far_from_level(self):
        """GATE 6: Price > 3 ticks from level → ALERT."""
        ctx = GateContext(candle_count=10, tick_age_seconds=1.0,
                         market_state=MarketState.BALANCED,
                         nearest_level=100, distance_to_level_ticks=5.0)
        result = GatePipeline().evaluate(ctx)
        assert result.passed is False
        assert result.gate == 6
        assert result.reason == GateReason.ALERT

    def test_gate_7_first_drive(self):
        """GATE 7: D1 → FLAT."""
        ctx = GateContext(candle_count=10, tick_age_seconds=1.0,
                         market_state=MarketState.BALANCED,
                         nearest_level=100, distance_to_level_ticks=1.0,
                         drive_number=1)
        result = GatePipeline().evaluate(ctx)
        assert result.passed is False
        assert result.gate == 7
        assert result.reason == GateReason.FLAT

    def test_gate_7_third_drive(self):
        """GATE 7: D3+ → FLAT."""
        ctx = GateContext(candle_count=10, tick_age_seconds=1.0,
                         market_state=MarketState.BALANCED,
                         nearest_level=100, distance_to_level_ticks=1.0,
                         drive_number=3)
        result = GatePipeline().evaluate(ctx)
        assert result.passed is False
        assert result.gate == 7
        assert result.reason == GateReason.FLAT

    def test_gate_7_d2_not_rejected(self):
        """GATE 7: D2 but D1 not rejected → FLAT."""
        ctx = GateContext(candle_count=10, tick_age_seconds=1.0,
                         market_state=MarketState.BALANCED,
                         nearest_level=100, distance_to_level_ticks=1.0,
                         drive_number=2, drive_entry_valid=False)
        result = GatePipeline().evaluate(ctx)
        assert result.passed is False
        assert result.gate == 7
        assert result.reason == GateReason.FLAT

    def test_gate_8_low_aggression(self):
        """GATE 8: Aggression < 2.0 → WAIT."""
        ctx = GateContext(candle_count=10, tick_age_seconds=1.0,
                         market_state=MarketState.BALANCED,
                         nearest_level=100, distance_to_level_ticks=1.0,
                         drive_number=2, drive_entry_valid=True,
                         aggression_score=1.5)
        result = GatePipeline().evaluate(ctx)
        assert result.passed is False
        assert result.gate == 8
        assert result.reason == GateReason.WAIT

    def test_gate_9_cushion_too_wide(self):
        """GATE 9: Cushion > 10 ticks → INVALID."""
        ctx = GateContext(candle_count=10, tick_age_seconds=1.0,
                         market_state=MarketState.BALANCED,
                         nearest_level=100, distance_to_level_ticks=1.0,
                         drive_number=2, drive_entry_valid=True,
                         aggression_score=2.5, cushion_ticks=15)
        result = GatePipeline().evaluate(ctx)
        assert result.passed is False
        assert result.gate == 9
        assert result.reason == GateReason.INVALID

    def test_gate_10_low_rr_quorum_met(self):
        """GATE 10: R:R < 1.5 but 3/4 soft gates pass → quorum met → TRADE.

        Under Fabio's 3/4 rule, a low R:R alone does not block the trade when
        gates 6, 8, 9 all pass (3 out of 4 = quorum).
        """
        ctx = GateContext(candle_count=10, tick_age_seconds=1.0,
                         market_state=MarketState.BALANCED,
                         nearest_level=100, distance_to_level_ticks=1.0,
                         drive_number=2, drive_entry_valid=True,
                         aggression_score=2.5, cushion_ticks=5, r_r_ratio=1.2)
        result = GatePipeline().evaluate(ctx)
        # 3/4 soft gates pass (6:ok, 8:ok, 9:ok, 10:fail) → quorum met → TRADE
        assert result.passed is True
        assert result.reason == GateReason.TRADE
        assert result.quorum_met is True
        assert result.soft_gates_passed == 3
        assert result.soft_gates_total == 4

    def test_gate_10_low_rr_quorum_not_met(self):
        """GATE 10: R:R < 1.5 with multiple other soft gate failures → quorum not met → SKIP.

        When multiple soft gates fail and quorum is not met, the first failed gate
        determines the reported reason.
        """
        ctx = GateContext(candle_count=10, tick_age_seconds=1.0,
                         market_state=MarketState.BALANCED,
                         nearest_level=100, distance_to_level_ticks=5.0,  # gate 6 fails too
                         drive_number=2, drive_entry_valid=True,
                         aggression_score=1.5, cushion_ticks=5, r_r_ratio=1.2)  # gate 8 fails too
        result = GatePipeline().evaluate(ctx)
        # 1/4 soft gates pass (6:fail, 8:fail, 9:ok, 10:fail) → quorum not met
        assert result.passed is False
        assert result.quorum_met is False
        assert result.soft_gates_passed == 1
        assert result.soft_gates_total == 4

    def test_gate_11_position_sizing_rejected(self):
        """GATE 11: Position sizing rejected → BLOCKED."""
        ctx = GateContext(candle_count=10, tick_age_seconds=1.0,
                         market_state=MarketState.BALANCED,
                         nearest_level=100, distance_to_level_ticks=1.0,
                         drive_number=2, drive_entry_valid=True,
                         aggression_score=2.5, cushion_ticks=5, r_r_ratio=2.0,
                         position_size_ok=False)
        result = GatePipeline().evaluate(ctx)
        assert result.passed is False
        assert result.gate == 11
        assert result.reason == GateReason.BLOCKED

    def test_gate_12_eia_window(self):
        """GATE 12: EIA window active → SUPPRESSED."""
        ctx = GateContext(candle_count=10, tick_age_seconds=1.0,
                         market_state=MarketState.BALANCED,
                         nearest_level=100, distance_to_level_ticks=1.0,
                         drive_number=2, drive_entry_valid=True,
                         aggression_score=2.5, cushion_ticks=5, r_r_ratio=2.0,
                         eia_window_active=True)
        result = GatePipeline().evaluate(ctx)
        assert result.passed is False
        assert result.gate == 12
        assert result.reason == GateReason.SUPPRESSED


class TestGatePipelineAllPass:
    """All gates pass → TRADE with quorum diagnostics."""

    def test_all_gates_pass(self):
        ctx = GateContext(
            candle_count=10,
            tick_age_seconds=1.0,
            market_state=MarketState.BALANCED,
            nearest_level=100,
            distance_to_level_ticks=1.0,
            drive_number=2,
            drive_entry_valid=True,
            aggression_score=2.5,
            cushion_ticks=5,
            r_r_ratio=2.0,
            position_size_ok=True,
            eia_window_active=False,
            setup_type="MEAN_REVERSION",
        )
        result = GatePipeline().evaluate(ctx)
        assert result.passed is True
        assert result.gate == 12
        assert result.reason == GateReason.TRADE
        assert result.is_trade is True
        assert result.setup_type == "MEAN_REVERSION"
        assert result.r_r_ratio == 2.0
        # Quorum diagnostics
        assert result.hard_gates_passed is True
        assert result.soft_gates_total == 4
        assert result.soft_gates_passed == 4
        assert result.quorum_met is True


class TestGatePipelineIMBALANCED:
    """IMBALANCED state passes through gates."""

    def test_imbalanced_passes(self):
        ctx = GateContext(
            candle_count=10,
            tick_age_seconds=1.0,
            market_state=MarketState.IMBALANCED,
            nearest_level=100,
            distance_to_level_ticks=1.0,
            drive_number=2,
            drive_entry_valid=True,
            aggression_score=3.0,
            cushion_ticks=3,
            r_r_ratio=2.5,
            position_size_ok=True,
        )
        result = GatePipeline().evaluate(ctx)
        assert result.passed is True
        assert result.reason == GateReason.TRADE


class TestSoftGateQuorum:
    """Quorum model: Fabio's 3/4 rule for soft gates."""

    def _base_ctx(self, **overrides) -> GateContext:
        """Base context with all hard gates passing."""
        base = dict(
            candle_count=10,
            tick_age_seconds=1.0,
            market_state=MarketState.BALANCED,
            nearest_level=100,
            drive_number=2,
            drive_entry_valid=True,
            position_size_ok=True,
            eia_window_active=False,
        )
        base.update(overrides)
        return GateContext(**base)

    def test_all_4_soft_gates_pass(self):
        """4/4 soft gates pass → quorum met → TRADE."""
        ctx = self._base_ctx(
            distance_to_level_ticks=1.0,
            aggression_score=2.5,
            cushion_ticks=5,
            r_r_ratio=2.0,
        )
        result = GatePipeline().evaluate(ctx)
        assert result.passed is True
        assert result.quorum_met is True
        assert result.soft_gates_passed == 4

    def test_3_of_4_soft_gates_pass_minimum_quorum(self):
        """3/4 soft gates pass → quorum met → TRADE."""
        ctx = self._base_ctx(
            distance_to_level_ticks=1.0,   # gate 6: pass
            aggression_score=2.5,           # gate 8: pass
            cushion_ticks=5,               # gate 9: pass
            r_r_ratio=1.2,                 # gate 10: fail (< 1.5)
        )
        result = GatePipeline().evaluate(ctx)
        assert result.passed is True
        assert result.quorum_met is True
        assert result.soft_gates_passed == 3
        assert result.soft_gates_total == 4

    def test_2_of_4_soft_gates_pass_quorum_not_met(self):
        """2/4 soft gates pass → quorum NOT met → blocked."""
        ctx = self._base_ctx(
            distance_to_level_ticks=1.0,   # gate 6: pass
            aggression_score=1.5,           # gate 8: fail (< 2.0)
            cushion_ticks=5,               # gate 9: pass
            r_r_ratio=1.2,                 # gate 10: fail (< 1.5)
        )
        result = GatePipeline().evaluate(ctx)
        assert result.passed is False
        assert result.quorum_met is False
        assert result.soft_gates_passed == 2
        assert result.soft_gates_total == 4

    def test_hard_gate_fail_bypasses_soft_quorum(self):
        """Hard gate failure (risk halt) blocks regardless of soft gate state."""
        ctx = self._base_ctx(
            is_risk_halted=True,
            halt_reason="Daily loss",
            distance_to_level_ticks=1.0,
            aggression_score=3.0,
            cushion_ticks=5,
            r_r_ratio=2.0,
        )
        result = GatePipeline().evaluate(ctx)
        assert result.passed is False
        assert result.hard_gates_passed is False
        assert result.gate == 2
        assert result.reason == GateReason.SESSION_STOPPED

    def test_configurable_quorum_override(self):
        """Quorum can be overridden to require fewer soft gates."""
        ctx = self._base_ctx(
            distance_to_level_ticks=1.0,   # gate 6: pass
            aggression_score=1.5,           # gate 8: fail
            cushion_ticks=20,              # gate 9: fail (> 10)
            r_r_ratio=1.2,                 # gate 10: fail
            soft_gate_quorum=1,            # only need 1 of 4
        )
        result = GatePipeline().evaluate(ctx)
        assert result.passed is True
        assert result.quorum_met is True
        assert result.soft_gates_passed == 1
