"""
Integration tests for full pipeline.
"""

import pytest
from datetime import datetime
from src.core.tick_processor import Tick, normalize_tick
from src.core.candle_builder import CandleBuilder
from src.profile.volume_profile import VolumeProfileEngine
from src.orderflow.cvd_engine import CVDEngine
from src.strategy.market_state_engine import MarketStateEngine
from src.strategy.aggression_scorer import AggressionScorer
from src.strategy.pipeline import GatePipeline, GateContext
from src.core.session_manager import SessionState


class TestFullPipeline:
    """Test end-to-end pipeline."""

    def test_tick_to_profile(self):
        """Test tick flows to profile update."""
        profile_engine = VolumeProfileEngine(bucket_size=0.10)
        profile = {}

        tick = Tick(
            symbol="NATURALGAS",
            price=9.35,
            volume=100,
            bid_vol=40,
            ask_vol=60,
            delta=20,
            trade_size=100,
            timestamp=datetime.now(),
            exchange="MCX",
        )

        profile_engine.update_bucket(profile, tick.price, tick.volume)
        assert 9.35 in profile or 9.3 in profile  # Bucket rounded

    def test_cvd_accumulation(self):
        """Test CVD accumulates through pipeline."""
        cvd_engine = CVDEngine()
        cvd_engine.update(100)
        cvd_engine.update(-50)
        cvd_engine.update(25)
        assert cvd_engine.get_current() == 75

    def test_market_state_classification(self):
        """Test market state classification."""
        result = MarketStateEngine.detect(
            price=9.1,
            poc=9.1,
            vah=9.5,
            val=8.7,
            tick_size=0.10,
            has_displacement=False,
            has_acceptance=False,
        )
        assert result.state == "NO_TRADE"  # At POC

    def test_aggression_scoring(self):
        """Test aggression scoring in pipeline."""
        result = AggressionScorer.score(
            footprint_confirmed=True,
            cvd_confirmed=True,
        )
        assert result.score == 2.0
        assert result.confirmed == True

    def test_gate_pipeline_pass(self):
        """Test gate pipeline with passing context."""
        pipeline = GatePipeline()
        context = GateContext(
            session_state=SessionState.ACTIVE,
            candle_count=10,
            tick_age_seconds=1.0,
            is_risk_halted=False,
            consecutive_losses=0,
            daily_pnl_pct=0.0,
            market_state="BALANCED",
            zone="NEAR_VAL",
            poc=9.1,
            vah=9.5,
            val=8.7,
            price=8.75,
            tick_size=0.10,
            drive_number=2,
            drive_entry_valid=True,
            aggression_score=2.5,
            entry_price=8.7,
            stop_loss=8.6,
            target=9.1,
            risk_reward=1.5,
            cushion_ticks=5,
            position_size_ok=True,
            eia_suppressed=False,
        )
        result = pipeline.evaluate(context)
        assert result.passed == True
        assert result.reason == "TRADE"

    def test_gate_pipeline_fail_no_trade(self):
        """Test gate pipeline fails at NO_TRADE."""
        pipeline = GatePipeline()
        context = GateContext(
            session_state=SessionState.ACTIVE,
            candle_count=10,
            tick_age_seconds=1.0,
            is_risk_halted=False,
            consecutive_losses=0,
            daily_pnl_pct=0.0,
            market_state="NO_TRADE",
            zone="NEAR_POC",
            poc=9.1,
            vah=9.5,
            val=8.7,
            price=9.1,
            tick_size=0.10,
            drive_number=2,
            drive_entry_valid=True,
            aggression_score=2.5,
            entry_price=9.1,
            stop_loss=9.0,
            target=9.5,
            risk_reward=1.5,
            cushion_ticks=5,
            position_size_ok=True,
            eia_suppressed=False,
        )
        result = pipeline.evaluate(context)
        assert result.passed == False
        assert result.gate == 3
        assert result.reason == "FLAT"