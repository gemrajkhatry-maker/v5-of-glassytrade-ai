"""Tests for market state engine and initial balance engine."""

import pytest
from datetime import datetime, timedelta
from app.domain.amt.service.market_state_engine import (
    detect_market_state,
    MarketState,
    MarketZone,
    MarketStateResult,
)
from app.domain.amt.service.initial_balance_engine import (
    InitialBalanceEngine,
    calculate_initial_balance,
    IBResult,
)


class TestMarketStateEngine:
    """Tests for market state detection (balanced vs imbalanced)."""

    def test_returns_balanced_when_price_inside_va(self):
        """Should detect BALANCED when price inside value area."""
        result = detect_market_state(
            price=100.5,
            vp_levels={"vah": 101.0, "val": 99.0, "poc": 100.0},
        )
        
        assert result.state == MarketState.BALANCED
        assert result.zone in [MarketZone.NEAR_VAH, MarketZone.NEAR_VAL, MarketZone.NEAR_POC]

    def test_returns_imbalanced_when_price_above_vah(self):
        """Should detect IMBALANCED when price above VAH."""
        result = detect_market_state(
            price=102.0,
            vp_levels={"vah": 101.0, "val": 99.0, "poc": 100.0},
        )
        
        assert result.state == MarketState.IMBALANCED
        assert result.zone == MarketZone.OUTSIDE_VA

    def test_returns_imbalanced_when_price_below_val(self):
        """Should detect IMBALANCED when price below VAL."""
        result = detect_market_state(
            price=98.0,
            vp_levels={"vah": 101.0, "val": 99.0, "poc": 100.0},
        )
        
        assert result.state == MarketState.IMBALANCED
        assert result.zone == MarketZone.OUTSIDE_VA

    def test_detects_near_vah_zone(self):
        """Should detect NEAR_VAH when price in upper half of VA."""
        result = detect_market_state(
            price=100.6,  # Above VA mid (100.0)
            vp_levels={"vah": 101.0, "val": 99.0, "poc": 100.0},
        )
        
        assert result.state == MarketState.BALANCED
        assert result.zone == MarketZone.NEAR_VAH

    def test_detects_near_val_zone(self):
        """Should detect NEAR_VAL when price in lower half of VA."""
        result = detect_market_state(
            price=99.4,  # Below VA mid (100.0)
            vp_levels={"vah": 101.0, "val": 99.0, "poc": 100.0},
        )
        
        assert result.state == MarketState.BALANCED
        assert result.zone == MarketZone.NEAR_VAL

    def test_detects_near_poc_zone(self):
        """Should detect NEAR_POC when price at VA midpoint."""
        result = detect_market_state(
            price=100.0,  # Exactly at VA mid
            vp_levels={"vah": 101.0, "val": 99.0, "poc": 100.0},
        )
        
        assert result.state == MarketState.BALANCED
        assert result.zone == MarketZone.NEAR_POC

    def test_returns_default_when_no_levels(self):
        """Should return balanced with default values when no levels."""
        result = detect_market_state(
            price=100.0,
            vp_levels={},
        )
        
        assert result.state == MarketState.BALANCED
        assert result.zone == MarketZone.NEAR_POC
        assert result.confidence == 0.5
        assert result.va_high == 0.0
        assert result.va_low == 0.0

    def test_uses_leg_profile_when_active(self):
        """Should use leg profile levels when active."""
        result = detect_market_state(
            price=105.0,
            vp_levels={"vah": 101.0, "val": 99.0, "poc": 100.0},
            leg_profile={"active": True, "vah": 104.0, "val": 102.0, "poc": 103.0},
        )
        
        # Price 105 > leg VAH 104, should be imbalanced
        assert result.state == MarketState.IMBALANCED
        assert result.va_high == 104.0
        assert result.va_low == 102.0

    def test_detects_extreme_deviation(self):
        """Should detect extreme when price > 3σ from VWAP."""
        result = detect_market_state(
            price=110.0,
            vp_levels={"vah": 101.0, "val": 99.0, "poc": 100.0},
            vwap=100.0,
            vwap_stddev=3.0,  # Deviation = 10/3 = 3.33 > 3.0
        )
        
        assert result.is_extreme is True

    def test_no_extreme_when_within_deviation(self):
        """Should not flag extreme when within 3σ."""
        result = detect_market_state(
            price=105.0,
            vp_levels={"vah": 101.0, "val": 99.0, "poc": 100.0},
            vwap=100.0,
            vwap_stddev=3.0,  # Deviation = 5/3 = 1.67 < 3.0
        )
        
        assert result.is_extreme is False

    def test_no_extreme_when_no_vwap(self):
        """Should not flag extreme when VWAP not provided."""
        result = detect_market_state(
            price=110.0,
            vp_levels={"vah": 101.0, "val": 99.0, "poc": 100.0},
            vwap=0.0,
            vwap_stddev=0.0,
        )
        
        assert result.is_extreme is False

    def test_higher_confidence_for_imbalanced(self):
        """Should assign higher confidence to imbalanced state."""
        balanced = detect_market_state(
            price=100.0,
            vp_levels={"vah": 101.0, "val": 99.0, "poc": 100.0},
        )
        imbalanced = detect_market_state(
            price=102.0,
            vp_levels={"vah": 101.0, "val": 99.0, "poc": 100.0},
        )
        
        assert imbalanced.confidence > balanced.confidence
        assert imbalanced.confidence == 0.85
        assert balanced.confidence == 0.80

    def test_returns_complete_result_object(self):
        """Should return all fields in result."""
        result = detect_market_state(
            price=100.5,
            vp_levels={"vah": 101.0, "val": 99.0, "poc": 100.0},
        )
        
        assert isinstance(result, MarketStateResult)
        assert result.state is not None
        assert result.zone is not None
        assert 0.0 <= result.confidence <= 1.0
        assert isinstance(result.is_extreme, bool)
        assert result.va_high == 101.0
        assert result.va_low == 99.0
        assert result.poc == 100.0


class TestInitialBalanceEngine:
    """Tests for initial balance tracking."""

    def test_tracks_high_and_low(self):
        """Should track IB high and low."""
        engine = InitialBalanceEngine(ib_minutes=60)
        base_time = datetime(2024, 1, 1, 9, 15)
        
        engine.update(base_time, 100.0)
        engine.update(base_time + timedelta(minutes=10), 101.0)
        engine.update(base_time + timedelta(minutes=20), 99.0)
        
        result = engine.update(base_time + timedelta(minutes=30), 100.5)
        
        assert result.high == 101.0
        assert result.low == 99.0

    def test_marks_incomplete_before_ib_period(self):
        """Should mark IB as incomplete before period ends."""
        engine = InitialBalanceEngine(ib_minutes=60)
        base_time = datetime(2024, 1, 1, 9, 15)
        
        # First update initializes
        engine.update(base_time, 100.0)
        # Second update calculates elapsed time
        result = engine.update(base_time + timedelta(minutes=30), 100.5)
        
        assert result.complete is False
        assert result.minutes == 30

    def test_marks_complete_after_ib_period(self):
        """Should mark IB as complete after period ends."""
        engine = InitialBalanceEngine(ib_minutes=60)
        base_time = datetime(2024, 1, 1, 9, 15)
        
        # First update initializes
        engine.update(base_time, 100.0)
        # Second update at 60 minutes
        result = engine.update(base_time + timedelta(minutes=60), 100.5)
        
        assert result.complete is True
        assert result.minutes == 60

    def test_resets_correctly(self):
        """Should reset IB tracking."""
        engine = InitialBalanceEngine(ib_minutes=60)
        base_time = datetime(2024, 1, 1, 9, 15)
        
        engine.update(base_time, 100.0)
        engine.reset()
        
        result = engine.update(base_time + timedelta(minutes=70), 105.0)
        
        # Should start fresh
        assert result.high == 105.0
        assert result.low == 105.0
        assert result.minutes == 0

    def test_stores_prior_levels(self):
        """Should store and return prior day levels."""
        engine = InitialBalanceEngine(ib_minutes=60)
        base_time = datetime(2024, 1, 1, 9, 15)
        
        engine.set_prior_levels(poc=100.0, vah=102.0, val=98.0)
        engine.update(base_time, 100.5)
        
        result = engine.update(base_time + timedelta(minutes=5), 101.0)
        
        assert result.prior_poc == 100.0
        assert result.prior_vah == 102.0
        assert result.prior_val == 98.0

    def test_handles_first_tick(self):
        """Should initialize high/low on first tick."""
        engine = InitialBalanceEngine(ib_minutes=60)
        base_time = datetime(2024, 1, 1, 9, 15)
        
        result = engine.update(base_time, 100.0)
        
        assert result.high == 100.0
        assert result.low == 100.0
        assert result.minutes == 0


class TestCalculateInitialBalance:
    """Tests for batch IB calculation from bars."""

    def test_calculates_from_bars(self):
        """Should calculate IB high/low from bars."""
        base_time = datetime(2024, 1, 1, 9, 15)
        bars = [
            {"timestamp": base_time, "high": 100.0, "low": 99.5},
            {"timestamp": base_time + timedelta(minutes=10), "high": 101.0, "low": 99.0},
            {"timestamp": base_time + timedelta(minutes=20), "high": 100.5, "low": 98.5},
        ]
        
        result = calculate_initial_balance(bars, minutes=60)
        
        assert result.high == 101.0
        assert result.low == 98.5

    def test_respects_time_window(self):
        """Should only include bars within IB period."""
        base_time = datetime(2024, 1, 1, 9, 15)
        bars = [
            {"timestamp": base_time, "high": 100.0, "low": 99.5},
            {"timestamp": base_time + timedelta(minutes=30), "high": 101.0, "low": 99.0},
            {"timestamp": base_time + timedelta(minutes=70), "high": 105.0, "low": 104.0},  # Outside IB
        ]
        
        result = calculate_initial_balance(bars, minutes=60)
        
        # Should not include bar at minute 70
        assert result.high == 101.0
        assert result.low == 99.0

    def test_returns_empty_for_no_bars(self):
        """Should return empty result for no bars."""
        result = calculate_initial_balance([])
        
        assert result.high == 0.0
        assert result.low == 0.0

    def test_handles_timestamp_as_float(self):
        """Should handle timestamps as floats."""
        base_ts = 1704067200.0  # 2024-01-01 00:00:00 UTC
        bars = [
            {"timestamp": base_ts, "high": 100.0, "low": 99.5},
            {"timestamp": base_ts + 600, "high": 101.0, "low": 99.0},  # +10 minutes
        ]
        
        result = calculate_initial_balance(bars, minutes=60)
        
        assert result.high == 101.0
        assert result.low == 99.0

    def test_ignores_bars_without_timestamp(self):
        """Should skip bars without timestamp."""
        base_time = datetime(2024, 1, 1, 9, 15)
        bars = [
            {"timestamp": base_time, "high": 100.0, "low": 99.5},
            {"high": 101.0, "low": 99.0},  # No timestamp
        ]
        
        result = calculate_initial_balance(bars, minutes=60)
        
        assert result.high == 100.0
        assert result.low == 99.5

    def test_returns_complete_result_object(self):
        """Should return IBResult with all fields."""
        base_time = datetime(2024, 1, 1, 9, 15)
        bars = [
            {"timestamp": base_time, "high": 100.0, "low": 99.5},
        ]
        
        result = calculate_initial_balance(bars, minutes=60)
        
        assert isinstance(result, IBResult)
        assert result.high >= 0.0
        assert result.low >= 0.0
        assert isinstance(result.complete, bool)
        assert isinstance(result.minutes, int)
