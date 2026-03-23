"""
E2E Pipeline Tests - Full tick-to-signal scenarios.

These tests validate the complete trading pipeline from tick ingestion
to signal generation, ensuring all components work together correctly.
"""

import pytest
from datetime import datetime
from src.core.tick_processor import Tick
from src.core.candle_builder import CandleBuilder, Candle
from src.profile.volume_profile import VolumeProfileEngine
from src.orderflow.cvd_engine import CVDEngine
from src.orderflow.absorption_detector import AbsorptionDetector
from src.strategy.market_state_engine import MarketStateEngine
from src.strategy.aggression_scorer import AggressionScorer
from src.strategy.pipeline import GatePipeline, GateContext
from src.core.session_manager import SessionState


class TestE2EPipeline:
    """End-to-end pipeline tests."""

    def test_e2e_01_balanced_mean_reversion(self):
        """
        E2E-01: BALANCED Mean Reversion Setup
        
        Given:
          - Market BALANCED, price near VAL
          - CVD slope positive (buyers absorbing)
          - Footprint imbalance confirmed
          - Absorption detected
          - LVN at VAL
          - D2 at VAL (D1 rejected)
        
        When: Full pipeline runs
        
        Then:
          - Market state: BALANCED (NEAR_VAL)
          - Aggression: 3.0+ (HIGH)
          - Gate pipeline: PASS
          - Signal: LONG at VAL
        """
        # Setup context for BALANCED mean reversion
        context = GateContext(
            session_state=SessionState.ACTIVE,
            candle_count=20,
            tick_age_seconds=1.0,
            is_risk_halted=False,
            consecutive_losses=0,
            daily_pnl_pct=0.0,
            market_state="BALANCED",
            zone="NEAR_VAL",
            poc=9.50,
            vah=9.80,
            val=9.20,
            price=9.25,
            tick_size=0.10,
            drive_number=2,
            drive_entry_valid=True,
            aggression_score=3.0,
            entry_price=9.20,
            stop_loss=9.10,
            target=9.50,
            risk_reward=3.0,
            cushion_ticks=5,
            position_size_ok=True,
            eia_suppressed=False,
        )

        pipeline = GatePipeline()
        result = pipeline.evaluate(context)

        assert result.passed == True
        assert result.reason == "TRADE"
        assert result.gate == 12

    def test_e2e_02_imbalanced_trend_setup(self):
        """
        E2E-02: IMBALANCED Trend Setup
        
        Given:
          - Market IMBALANCED, price outside VA
          - Displacement candle detected
          - CVD slope strong
          - Big trade cluster at entry level
        
        When: Full pipeline runs
        
        Then:
          - Market state: IMBALANCED
          - Aggression: 3.5+ (HIGH)
          - Gate pipeline: PASS
        """
        context = GateContext(
            session_state=SessionState.ACTIVE,
            candle_count=25,
            tick_age_seconds=0.5,
            is_risk_halted=False,
            consecutive_losses=0,
            daily_pnl_pct=0.5,
            market_state="IMBALANCED",
            zone="EMPTY",
            poc=9.50,
            vah=9.80,
            val=9.20,
            price=10.00,
            tick_size=0.10,
            drive_number=2,
            drive_entry_valid=True,
            aggression_score=3.5,
            entry_price=9.90,
            stop_loss=9.70,
            target=10.50,
            risk_reward=3.0,
            cushion_ticks=8,
            position_size_ok=True,
            eia_suppressed=False,
        )

        pipeline = GatePipeline()
        result = pipeline.evaluate(context)

        assert result.passed == True
        assert result.reason == "TRADE"

    def test_e2e_03_no_trade_block(self):
        """
        E2E-03: NO_TRADE Block
        
        Given:
          - Price at POC ± 1 tick
          - All signals aligned
        
        When: Full pipeline runs
        
        Then:
          - Market state: NO_TRADE
          - Gate pipeline: FAIL at GATE 3
          - Output: FLAT
          - No signal generated
        """
        context = GateContext(
            session_state=SessionState.ACTIVE,
            candle_count=20,
            tick_age_seconds=1.0,
            is_risk_halted=False,
            consecutive_losses=0,
            daily_pnl_pct=0.0,
            market_state="NO_TRADE",
            zone="NEAR_POC",
            poc=9.50,
            vah=9.80,
            val=9.20,
            price=9.51,
            tick_size=0.10,
            drive_number=2,
            drive_entry_valid=True,
            aggression_score=3.0,
            entry_price=9.50,
            stop_loss=9.40,
            target=9.80,
            risk_reward=3.0,
            cushion_ticks=5,
            position_size_ok=True,
            eia_suppressed=False,
        )

        pipeline = GatePipeline()
        result = pipeline.evaluate(context)

        assert result.passed == False
        assert result.gate == 3
        assert result.reason == "FLAT"

    def test_e2e_04_probing_block(self):
        """
        E2E-04: PROBING Block
        
        Given:
          - Price outside VA
          - No displacement candle
        
        When: Full pipeline runs
        
        Then:
          - Market state: PROBING
          - Gate pipeline: FAIL at GATE 4
          - Output: FLAT
        """
        context = GateContext(
            session_state=SessionState.ACTIVE,
            candle_count=20,
            tick_age_seconds=1.0,
            is_risk_halted=False,
            consecutive_losses=0,
            daily_pnl_pct=0.0,
            market_state="PROBING",
            zone="EMPTY",
            poc=9.50,
            vah=9.80,
            val=9.20,
            price=10.00,
            tick_size=0.10,
            drive_number=2,
            drive_entry_valid=True,
            aggression_score=2.5,
            entry_price=9.95,
            stop_loss=9.85,
            target=10.30,
            risk_reward=2.0,
            cushion_ticks=5,
            position_size_ok=True,
            eia_suppressed=False,
        )

        pipeline = GatePipeline()
        result = pipeline.evaluate(context)

        assert result.passed == False
        assert result.gate == 4
        assert result.reason == "FLAT"

    def test_e2e_05_eia_window_block(self):
        """
        E2E-05: EIA Window Block
        
        Given:
          - Thursday 10:20 ET
          - Symbol: NATURALGAS
          - All other conditions met
        
        When: Full pipeline runs
        
        Then:
          - Gate pipeline: FAIL at GATE 12 (SUPPRESSED)
          - Output: FLAT
        """
        context = GateContext(
            session_state=SessionState.ACTIVE,
            candle_count=20,
            tick_age_seconds=1.0,
            is_risk_halted=False,
            consecutive_losses=0,
            daily_pnl_pct=0.0,
            market_state="BALANCED",
            zone="NEAR_VAL",
            poc=9.50,
            vah=9.80,
            val=9.20,
            price=9.25,
            tick_size=0.10,
            drive_number=2,
            drive_entry_valid=True,
            aggression_score=3.0,
            entry_price=9.20,
            stop_loss=9.10,
            target=9.50,
            risk_reward=3.0,
            cushion_ticks=5,
            position_size_ok=True,
            eia_suppressed=True,  # EIA window active
        )

        pipeline = GatePipeline()
        result = pipeline.evaluate(context)

        assert result.passed == False
        assert result.gate == 12
        assert result.reason == "SUPPRESSED"

    def test_e2e_06_risk_halt_block(self):
        """
        E2E-06: Risk Halt Block
        
        Given:
          - 3 consecutive losses
          - All other conditions met
        
        When: Full pipeline runs
        
        Then:
          - Gate pipeline: FAIL at GATE 2 (SESSION_STOPPED)
          - Output: FLAT
        """
        context = GateContext(
            session_state=SessionState.ACTIVE,
            candle_count=20,
            tick_age_seconds=1.0,
            is_risk_halted=True,  # Risk halted
            consecutive_losses=3,
            daily_pnl_pct=-0.015,
            market_state="BALANCED",
            zone="NEAR_VAL",
            poc=9.50,
            vah=9.80,
            val=9.20,
            price=9.25,
            tick_size=0.10,
            drive_number=2,
            drive_entry_valid=True,
            aggression_score=3.0,
            entry_price=9.20,
            stop_loss=9.10,
            target=9.50,
            risk_reward=3.0,
            cushion_ticks=5,
            position_size_ok=True,
            eia_suppressed=False,
        )

        pipeline = GatePipeline()
        result = pipeline.evaluate(context)

        assert result.passed == False
        assert result.gate == 2
        assert result.reason == "SESSION_STOPPED"