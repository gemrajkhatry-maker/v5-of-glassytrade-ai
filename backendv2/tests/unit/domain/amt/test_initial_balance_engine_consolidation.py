"""Tests for InitialBalanceEngine consolidation.

Characterization tests to verify both legacy and AMT IB engines
before and after consolidation.
"""
from __future__ import annotations

from datetime import datetime, timedelta

from app.domain.amt.service.initial_balance_engine import (
    InitialBalanceEngine as AmtInitialBalanceEngine,
    IBResult,
    calculate_initial_balance,
)
from app.domain.services.initial_balance_engine import (
    LegacyInitialBalanceEngine,
    IBState,
    IBLocation,
)
from app.domain.trading.model.value_objects import OHLC


class TestAmtInitialBalanceEngine:
    """Characterization tests for AMT InitialBalanceEngine."""

    def test_initial_state(self):
        engine = AmtInitialBalanceEngine(ib_minutes=60)
        result = engine.update(datetime(2024, 1, 1, 9, 15), 100.0)
        assert result.high == 100.0
        assert result.low == 100.0
        assert result.complete is False
        assert result.minutes == 0

    def test_tracks_high_low(self):
        engine = AmtInitialBalanceEngine(ib_minutes=60)
        base = datetime(2024, 1, 1, 9, 15)
        engine.update(base, 100.0)
        engine.update(base + timedelta(minutes=5), 105.0)
        engine.update(base + timedelta(minutes=10), 98.0)
        result = engine.update(base + timedelta(minutes=15), 102.0)
        assert result.high == 105.0
        assert result.low == 98.0
        assert result.complete is False

    def test_completes_after_ib_minutes(self):
        engine = AmtInitialBalanceEngine(ib_minutes=30)
        base = datetime(2024, 1, 1, 9, 15)
        engine.update(base, 100.0)
        result = engine.update(base + timedelta(minutes=31), 102.0)
        assert result.complete is True
        assert result.minutes == 31

    def test_set_prior_levels(self):
        engine = AmtInitialBalanceEngine(ib_minutes=60)
        engine.set_prior_levels(150.0, 160.0, 140.0)
        result = engine.update(datetime(2024, 1, 1, 9, 15), 100.0)
        assert result.prior_poc == 150.0
        assert result.prior_vah == 160.0
        assert result.prior_val == 140.0

    def test_reset_clears_state(self):
        engine = AmtInitialBalanceEngine(ib_minutes=60)
        base = datetime(2024, 1, 1, 9, 15)
        engine.update(base, 100.0)
        engine.update(base + timedelta(minutes=10), 105.0)
        engine.reset()
        result = engine.update(base + timedelta(minutes=15), 102.0)
        assert result.high == 102.0
        assert result.low == 102.0
        assert result.complete is False


class TestCalculateInitialBalance:
    """Tests for calculate_initial_balance function."""

    def test_empty_bars(self):
        result = calculate_initial_balance([], minutes=60)
        assert result.high == 0.0
        assert result.low == 0.0

    def test_single_bar(self):
        bars = [{"timestamp": datetime(2024, 1, 1, 9, 15), "high": 105.0, "low": 99.0}]
        result = calculate_initial_balance(bars, minutes=60)
        assert result.high == 105.0
        assert result.low == 99.0

    def test_ignores_bars_after_window(self):
        bars = [
            {"timestamp": datetime(2024, 1, 1, 9, 15), "high": 105.0, "low": 99.0},
            {"timestamp": datetime(2024, 1, 1, 9, 45), "high": 110.0, "low": 100.0},
            {"timestamp": datetime(2024, 1, 1, 10, 30), "high": 120.0, "low": 95.0},
        ]
        result = calculate_initial_balance(bars, minutes=30)
        # Second bar at 9:45 is exactly 30 min, so included; third at 10:30 excluded
        assert result.high == 110.0
        assert result.low == 99.0


class TestLegacyInitialBalanceEngine:
    """Characterization tests for legacy InitialBalanceEngine."""

    def test_initial_state(self):
        engine = LegacyInitialBalanceEngine(ib_minutes=30)
        candle = OHLC(open=100.0, high=101.0, low=99.0, close=100.5, volume=1000, time="2024-01-01T09:15:00")
        state = engine.update(candle)
        assert state.ib_high == 101.0
        assert state.ib_low == 99.0
        assert state.is_complete is False
        assert state.location == IBLocation.BUILDING

    def test_completes_after_ib_minutes(self):
        engine = LegacyInitialBalanceEngine(ib_minutes=30)
        base = datetime(2024, 1, 1, 9, 15)
        
        # First candle at 9:15
        candle1 = OHLC(open=100.0, high=101.0, low=99.0, close=100.5, volume=1000, time=base.isoformat())
        engine.update(candle1)
        
        # Candle at 9:45 (> 30 min)
        candle2 = OHLC(open=100.5, high=102.0, low=100.0, close=101.0, volume=1000, time=(base + timedelta(minutes=31)).isoformat())
        state = engine.update(candle2)
        assert state.is_complete is True
        assert state.ib_high == 102.0

    def test_classify_breakout_long(self):
        engine = LegacyInitialBalanceEngine(ib_minutes=30)
        base = datetime(2024, 1, 1, 9, 15)
        
        # Build IB over 35 minutes so it completes
        for i in range(36):
            high = 101.0 if i < 10 else 105.0
            candle = OHLC(
                open=100.0, high=high, low=99.0, close=100.5,
                volume=1000, time=(base + timedelta(minutes=i)).isoformat()
            )
            engine.update(candle)
        
        assert engine.is_complete is True
        
        # Breakout: high > ib_high (105) AND open <= ib_high
        breakout = OHLC(
            open=104.0, high=106.0, low=103.0, close=105.5,
            volume=1000, time=(base + timedelta(minutes=40)).isoformat()
        )
        assert engine.classify_breakout(breakout) == "LONG_BREAKOUT"

    def test_classify_breakout_short(self):
        engine = LegacyInitialBalanceEngine(ib_minutes=30)
        base = datetime(2024, 1, 1, 9, 15)
        
        # Build IB over 35 minutes so it completes
        for i in range(36):
            low = 99.0 if i < 10 else 95.0
            candle = OHLC(
                open=100.0, high=101.0, low=low, close=100.5,
                volume=1000, time=(base + timedelta(minutes=i)).isoformat()
            )
            engine.update(candle)
        
        assert engine.is_complete is True
        
        # Breakdown: low < ib_low (95) AND open >= ib_low
        breakdown = OHLC(
            open=96.0, high=97.0, low=94.0, close=95.5,
            volume=1000, time=(base + timedelta(minutes=40)).isoformat()
        )
        assert engine.classify_breakout(breakdown) == "SHORT_BREAKOUT"

    def test_location_inside(self):
        engine = LegacyInitialBalanceEngine(ib_minutes=30)
        base = datetime(2024, 1, 1, 9, 15)
        
        # Complete IB: high=105, low=95
        for i in range(35):
            high = 105.0 if i == 10 else 101.0
            low = 95.0 if i == 20 else 99.0
            candle = OHLC(
                open=100.0, high=high, low=low, close=100.0,
                volume=1000, time=(base + timedelta(minutes=i)).isoformat()
            )
            engine.update(candle)
        
        assert engine.is_complete is True
        state = engine.get_state()
        assert state["ib_high"] == 105.0
        assert state["ib_low"] == 95.0

    def test_reset_clears_state(self):
        engine = LegacyInitialBalanceEngine(ib_minutes=30)
        base = datetime(2024, 1, 1, 9, 15)
        candle = OHLC(open=100.0, high=101.0, low=99.0, close=100.5, volume=1000, time=base.isoformat())
        engine.update(candle)
        engine.reset()
        assert engine.ib_high == 0.0
        assert engine.ib_low == 0.0
        assert engine.is_complete is False
