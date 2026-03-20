"""Integration tests for RACI component bindings per responsibility matrix.

Validates that components are properly bound according to the dependency
matrix defined in plan/03_responsibility_matrix.md.
"""

import pytest
from app.domain.fabio_ai.services.market_state_engine import (
    detect_market_state,
    classify_zone,
    log_state_transition,
    MarketStateResult,
)
from app.domain.fabio_ai.services.aggression_scorer import AggressionScorer
from app.domain.fabio_ai.services.gate_pipeline import GatePipeline, GateContext, GateReason
from app.domain.fabio_ai.services.eia_calendar import EIACalendar
from app.domain.fabio_ai.services.rule_based_rationale import RuleBasedRationale, RationaleContext
from app.domain.trading.models.enums import MarketState


class TestProfileToMarketStateBinding:
    """RACI: VolumeProfile → MarketStateEngine (VolumeProfile is R, MarketStateEngine is C)."""

    def test_poc_drives_no_trade(self):
        """POC from VolumeProfile drives NO_TRADE state."""
        result = detect_market_state(
            price=100.05, poc=100.0, vah=105.0, val=95.0,
            tick_size=0.10, has_displacement=False, has_acceptance=False,
        )
        assert result.state == MarketState.NO_TRADE
        assert result.zone == "NEAR_POC"

    def test_vah_val_drives_balanced(self):
        """VAH/VAL from VolumeProfile drives BALANCED state."""
        result = detect_market_state(
            price=100.0, poc=97.0, vah=105.0, val=95.0,
            tick_size=0.10, has_displacement=False, has_acceptance=False,
        )
        assert result.state == MarketState.BALANCED

    def test_outside_va_with_displacement_drives_imbalanced(self):
        """Price outside VA + displacement drives IMBALANCED."""
        result = detect_market_state(
            price=106.0, poc=100.0, vah=105.0, val=95.0,
            tick_size=0.10, has_displacement=True, has_acceptance=True,
        )
        assert result.state == MarketState.IMBALANCED

    def test_zone_subclassification(self):
        """Zone sub-classification works correctly."""
        # NEAR_VAH
        assert classify_zone(price=103.0, poc=100.0, vah=105.0, val=95.0) == "NEAR_VAH"
        # NEAR_VAL
        assert classify_zone(price=97.0, poc=100.0, vah=105.0, val=95.0) == "NEAR_VAL"
        # NEAR_POC
        assert classify_zone(price=100.5, poc=100.0, vah=105.0, val=95.0) == "NEAR_POC"


class TestOrderFlowToAggressionBinding:
    """RACI: OrderFlow modules → AggressionScorer (OrderFlow is R, AggressionScorer is C)."""

    def test_footprint_to_aggression(self):
        """FootprintEngine output feeds into AggressionScorer."""
        result = AggressionScorer.score(footprint_confirmed=True)
        assert result.score == pytest.approx(1.0)
        assert result.breakdown["footprint"] == 1.0

    def test_cvd_to_aggression(self):
        """CVDEngine output feeds into AggressionScorer."""
        result = AggressionScorer.score(cvd_confirmed=True)
        assert result.score == pytest.approx(1.0)
        assert result.breakdown["cvd"] == 1.0

    def test_all_orderflow_to_aggression(self):
        """All order flow signals aggregate correctly."""
        result = AggressionScorer.score(
            footprint_confirmed=True,
            cvd_confirmed=True,
            big_trade_confirmed=True,
            absorption_detected=True,
            ofi_aligned=True,
            confluence_bonus=True,
            volume_bubble_near=True,
        )
        assert result.score == pytest.approx(4.5)
        assert result.confidence == "HIGH"
        assert result.pyramid_eligible is True


class TestAggressionToTradeConstructionBinding:
    """RACI: AggressionScorer → TradeConstructor (AggressionScorer is R, TradeConstructor is C)."""

    def test_aggression_score_used_in_gate_pipeline(self):
        """Aggression score feeds into GatePipeline Gate 8."""
        # Low aggression fails Gate 8
        ctx = GateContext(
            candle_count=10, tick_age_seconds=1.0,
            market_state=MarketState.BALANCED,
            nearest_level=100, distance_to_level_ticks=1.0,
            drive_number=2, drive_entry_valid=True,
            aggression_score=1.5,  # Below 2.0
        )
        result = GatePipeline().evaluate(ctx)
        assert result.gate == 8
        assert result.reason == GateReason.WAIT

    def test_aggression_score_passes_gate_8(self):
        """Aggression ≥ 2.0 passes Gate 8."""
        ctx = GateContext(
            candle_count=10, tick_age_seconds=1.0,
            market_state=MarketState.BALANCED,
            nearest_level=100, distance_to_level_ticks=1.0,
            drive_number=2, drive_entry_valid=True,
            aggression_score=2.5, cushion_ticks=5, r_r_ratio=2.0,
        )
        result = GatePipeline().evaluate(ctx)
        assert result.gate > 8  # Passed gate 8


class TestRiskToTradeConstructionBinding:
    """RACI: SessionRiskManager → TradeConstructor (SessionRiskManager is R, TradeConstructor is C)."""

    def test_risk_halt_blocks_gate_2(self):
        """Risk halt from SessionRiskManager blocks Gate 2."""
        ctx = GateContext(
            candle_count=10, tick_age_seconds=1.0,
            is_risk_halted=True, halt_reason="Daily loss limit",
        )
        result = GatePipeline().evaluate(ctx)
        assert result.gate == 2
        assert result.reason == GateReason.SESSION_STOPPED


class TestGatePipelineToTradeConstructorBinding:
    """RACI: GatePipeline → TradeConstructor (GatePipeline is R, TradeConstructor is C)."""

    def test_all_gates_pass_enables_trade(self):
        """All 12 gates pass → TRADE signal enabled."""
        ctx = GateContext(
            candle_count=10, tick_age_seconds=1.0,
            market_state=MarketState.BALANCED,
            nearest_level=100, distance_to_level_ticks=1.0,
            drive_number=2, drive_entry_valid=True,
            aggression_score=2.5, cushion_ticks=5, r_r_ratio=2.0,
            position_size_ok=True, eia_window_active=False,
        )
        result = GatePipeline().evaluate(ctx)
        assert result.passed is True
        assert result.reason == GateReason.TRADE

    def test_gate_pipeline_provides_setup_type(self):
        """GatePipeline result includes setup type for TradeConstructor."""
        ctx = GateContext(
            candle_count=10, tick_age_seconds=1.0,
            market_state=MarketState.BALANCED,
            nearest_level=100, distance_to_level_ticks=1.0,
            drive_number=2, drive_entry_valid=True,
            aggression_score=2.5, cushion_ticks=5, r_r_ratio=2.0,
            position_size_ok=True, setup_type="MEAN_REVERSION",
        )
        result = GatePipeline().evaluate(ctx)
        assert result.setup_type == "MEAN_REVERSION"


class TestEIAToGatePipelineBinding:
    """RACI: EIACalendar → GatePipeline (EIACalendar is R, GatePipeline is C)."""

    def test_eia_suppression_blocks_gate_12(self):
        """EIA suppression blocks Gate 12."""
        ctx = GateContext(
            candle_count=10, tick_age_seconds=1.0,
            market_state=MarketState.BALANCED,
            nearest_level=100, distance_to_level_ticks=1.0,
            drive_number=2, drive_entry_valid=True,
            aggression_score=2.5, cushion_ticks=5, r_r_ratio=2.0,
            position_size_ok=True, eia_window_active=True,
        )
        result = GatePipeline().evaluate(ctx)
        assert result.gate == 12
        assert result.reason == GateReason.SUPPRESSED


class TestMarketStateToRationaleBinding:
    """RACI: MarketStateEngine → RationaleGenerator (MarketStateEngine is R, RationaleGenerator is C)."""

    def test_market_state_in_rationale(self):
        """Market state from MarketStateEngine appears in rationale."""
        gen = RuleBasedRationale()
        ctx = RationaleContext(
            market_state="BALANCED", zone="NEAR_VAL",
            poc=100, vah=105, val=95, price=96,
            aggression_score=3.0, aggression_confidence="HIGH",
            footprint_confirmed=True, cvd_confirmed=True,
            big_trade_confirmed=False, absorption_detected=False,
            ofi_aligned=False, confluence_bonus=False, volume_bubble_near=False,
            cvd_slope=0.5, cvd_divergence="",
            drive_number=2, drive_level=95,
            direction="LONG", setup_type="MEAN_REVERSION",
            entry_price=96, stop_loss=94, take_profit=100,
            r_r_ratio=2.0, gate_number=12, profile_shape="b",
        )
        rationale = gen.generate(ctx)
        assert "BALANCED" in rationale
        assert "NEAR_VAL" in rationale


class TestAggressionToRationaleBinding:
    """RACI: AggressionScorer → RationaleGenerator (AggressionScorer is R, RationaleGenerator is C)."""

    def test_aggression_breakdown_in_rationale(self):
        """Aggression breakdown from AggressionScorer appears in rationale."""
        gen = RuleBasedRationale()
        ctx = RationaleContext(
            market_state="BALANCED", zone="NEAR_VAL",
            poc=100, vah=105, val=95, price=96,
            aggression_score=3.0, aggression_confidence="HIGH",
            footprint_confirmed=True, cvd_confirmed=True,
            big_trade_confirmed=True, absorption_detected=False,
            ofi_aligned=False, confluence_bonus=False, volume_bubble_near=False,
            cvd_slope=0.5, cvd_divergence="",
            drive_number=2, drive_level=95,
            direction="LONG", setup_type="MEAN_REVERSION",
            entry_price=96, stop_loss=94, take_profit=100,
            r_r_ratio=2.0, gate_number=12, profile_shape="b",
        )
        rationale = gen.generate(ctx)
        assert "3.0/4.5" in rationale
        assert "HIGH" in rationale
        assert "footprint imbalance" in rationale
        assert "CVD aligned" in rationale
        assert "institutional prints" in rationale


class TestFullPipelineBinding:
    """End-to-end binding: Profile → MarketState → Aggression → GatePipeline → Rationale."""

    def test_full_binding_balanced_mean_reversion(self):
        """Full pipeline: BALANCED → Mean Reversion → Rationale."""
        # 1. Profile → MarketState
        state_result = detect_market_state(
            price=96.0, poc=100.0, vah=105.0, val=95.0,
            tick_size=0.10, has_displacement=False, has_acceptance=False,
        )
        assert state_result.state == MarketState.BALANCED
        assert state_result.zone == "NEAR_VAL"

        # 2. OrderFlow → Aggression
        agg_result = AggressionScorer.score(
            footprint_confirmed=True,
            cvd_confirmed=True,
            absorption_detected=True,
        )
        assert agg_result.confirmed is True
        assert agg_result.score == pytest.approx(2.5)

        # 3. Aggression → GatePipeline
        ctx = GateContext(
            candle_count=10, tick_age_seconds=1.0,
            market_state=state_result.state,
            poc=100.0, vah=105.0, val=95.0,
            price=96.0, tick_size=0.10,
            nearest_level=95.0, distance_to_level_ticks=1.0,
            drive_number=2, drive_entry_valid=True,
            aggression_score=agg_result.score,
            cushion_ticks=5, r_r_ratio=2.0,
            position_size_ok=True,
        )
        gate_result = GatePipeline().evaluate(ctx)
        assert gate_result.passed is True
        assert gate_result.reason == GateReason.TRADE

        # 4. GatePipeline → Rationale
        gen = RuleBasedRationale()
        rationale_ctx = RationaleContext(
            market_state=state_result.state.value,
            zone=state_result.zone,
            poc=100.0, vah=105.0, val=95.0, price=96.0,
            aggression_score=agg_result.score,
            aggression_confidence=agg_result.confidence,
            footprint_confirmed=True, cvd_confirmed=True,
            big_trade_confirmed=False, absorption_detected=True,
            ofi_aligned=False, confluence_bonus=False, volume_bubble_near=False,
            cvd_slope=0.5, cvd_divergence="",
            drive_number=2, drive_level=95.0,
            direction="LONG", setup_type="MEAN_REVERSION",
            entry_price=96.0, stop_loss=94.0, take_profit=100.0,
            r_r_ratio=2.0, gate_number=12, profile_shape="b",
        )
        rationale = gen.generate(rationale_ctx)
        assert "BALANCED" in rationale
        assert "Mean Reversion" in rationale
        assert "LONG" in rationale