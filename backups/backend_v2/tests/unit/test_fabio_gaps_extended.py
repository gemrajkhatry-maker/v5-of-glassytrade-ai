"""
Extended Fabio Valentini Gap Tests - Part 2
"""

import pytest
from src.strategy.drive_tracker import DriveTracker
from src.strategy.aggression_scorer import AggressionScorer
from src.risk.session_risk_manager import SessionRiskManager
from src.trade_management.partition_exit_manager import PartitionExitManager, ManagedPosition
from src.core.candle_builder import Candle
from datetime import datetime


class TestBreakEvenTiming:
    """Verify BE triggers appropriately."""

    def test_be_trigger_at_35_percent(self):
        """BE should trigger at 35% of R."""
        manager = PartitionExitManager()
        position = ManagedPosition(
            entry_price=100.0,
            initial_stop=99.0,
            target=102.0,
            direction="LONG",
            lots=100,
        )
        # Use 100.36 to avoid floating point precision issues
        signals = manager.check_exits(position, 100.36, cvd_slope=1.0)
        assert any(s.exit_type == "BREAK_EVEN" for s in signals)

    def test_be_only_once(self):
        """BE should only trigger once."""
        manager = PartitionExitManager()
        position = ManagedPosition(
            entry_price=100.0,
            initial_stop=99.0,
            target=102.0,
            direction="LONG",
            lots=100,
            breakeven_set=True,
        )
        signals = manager.check_exits(position, 100.50, cvd_slope=1.0)
        assert not any(s.exit_type == "BREAK_EVEN" for s in signals)


class TestDriveSystem:
    """Verify drive system matches Fabio methodology."""

    def test_d1_suppresses_entry(self):
        """D1 should suppress entry."""
        tracker = DriveTracker()
        candle = Candle(
            open=100.0, high=100.5, low=99.5, close=100.2,
            volume=100, buy_vol=60, sell_vol=40, delta=20,
            timestamp=datetime.now(),
            candle_start=datetime.now(),
            candle_end=datetime.now(),
        )
        result = tracker.classify_drive(100.2, 100.0, candle, "LONG")
        assert result.drive_number == 1
        assert result.entry_valid == False

    def test_d2_with_rejection_validates(self):
        """D2 with rejection should validate entry."""
        tracker = DriveTracker()
        candle1 = Candle(
            open=100.0, high=100.5, low=99.5, close=100.2,
            volume=100, buy_vol=60, sell_vol=40, delta=20,
            timestamp=datetime.now(),
            candle_start=datetime.now(),
            candle_end=datetime.now(),
        )
        tracker.classify_drive(100.2, 100.0, candle1, "LONG")
        
        candle2 = Candle(
            open=100.2, high=100.5, low=99.8, close=100.3,
            volume=80, buy_vol=40, sell_vol=40, delta=0,
            timestamp=datetime.now(),
            candle_start=datetime.now(),
            candle_end=datetime.now(),
        )
        result = tracker.classify_drive(100.3, 100.0, candle2, "LONG")
        assert result.drive_number == 2
        assert result.entry_valid == True

    def test_rejection_detection(self):
        """Rejection = wick through + close opposite."""
        candle = Candle(
            open=100.2, high=100.5, low=99.8, close=100.3,
            volume=80, buy_vol=40, sell_vol=40, delta=0,
            timestamp=datetime.now(),
            candle_start=datetime.now(),
            candle_end=datetime.now(),
        )
        rejected = DriveTracker.detect_rejection(candle, 100.0, "LONG")
        assert rejected == True


class TestAggressionScoring:
    """Verify aggression scoring."""

    def test_max_score_is_5_0(self):
        """Max aggression score should be 5.0."""
        result = AggressionScorer.score(
            footprint_confirmed=True,
            cvd_confirmed=True,
            big_trade_confirmed=True,
            absorption_detected=True,
            ofi_aligned=True,
            confluence_bonus=True,
            volume_bubble_near=True,
        )
        assert result.score == 5.0

    def test_min_trade_score_is_2_0(self):
        """Min trade score should be 2.0."""
        result = AggressionScorer.score(
            footprint_confirmed=True,
            cvd_confirmed=True,
        )
        assert result.score == 2.0
        assert result.confirmed == True

    def test_pyramid_requires_3_0(self):
        """Pyramid should require score >= 3.0."""
        result = AggressionScorer.score(
            footprint_confirmed=True,
            cvd_confirmed=True,
            big_trade_confirmed=True,
        )
        assert result.score == 3.0
        assert result.pyramid_eligible == True


class TestRiskManagement:
    """Verify risk management."""

    def test_daily_loss_limit(self):
        """Daily loss limit should be 2%."""
        rm = SessionRiskManager(session_start_equity=100000)
        rm.register_trade_result(-2000)
        can_trade, reason = rm.can_trade()
        assert can_trade == False
        assert "DAILY_LOSS" in reason

    def test_consecutive_loss_limit(self):
        """Consecutive loss limit should be 3."""
        rm = SessionRiskManager(session_start_equity=100000)
        rm.register_trade_result(-100)
        rm.register_trade_result(-100)
        rm.register_trade_result(-100)
        can_trade, reason = rm.can_trade()
        assert can_trade == False
        assert "CONSECUTIVE" in reason