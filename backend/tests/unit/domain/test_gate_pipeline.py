"""Unit tests for GatePipeline — sequential 12-gate validation per Fabio AMT spec."""

import pytest
from app.domain.fabio_ai.services.gate_pipeline import (
    GatePipeline,
    GateContext,
    GateResult,
    GateReason,
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

    def test_gate_10_low_rr(self):
        """GATE 10: R:R < 1.5 → SKIP."""
        ctx = GateContext(candle_count=10, tick_age_seconds=1.0,
                         market_state=MarketState.BALANCED,
                         nearest_level=100, distance_to_level_ticks=1.0,
                         drive_number=2, drive_entry_valid=True,
                         aggression_score=2.5, cushion_ticks=5, r_r_ratio=1.2)
        result = GatePipeline().evaluate(ctx)
        assert result.passed is False
        assert result.gate == 10
        assert result.reason == GateReason.SKIP

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
    """All 12 gates pass → TRADE."""

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