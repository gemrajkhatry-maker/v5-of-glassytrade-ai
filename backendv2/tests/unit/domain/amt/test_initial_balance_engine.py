"""Tests for Initial Balance Engine."""

import pytest
from datetime import datetime, timedelta

from app.domain.amt.service.initial_balance_engine import (
    InitialBalanceEngine,
    calculate_initial_balance,
    IBResult,
)


class TestInitialBalanceEngine:
    """Tests for initial balance tracking."""

    def test_ib_high_low_tracking(self):
        """IB high = max of first N bars, low = min."""
        engine = InitialBalanceEngine(ib_minutes=60)
        
        ts = datetime(2024, 1, 1, 9, 30)
        engine.update(ts, 100.0)
        engine.update(ts, 103.0)
        engine.update(ts, 98.0)
        
        result = engine.update(ts, 102.0)
        
        assert result.high == 103.0
        assert result.low == 98.0

    def test_ib_complete_after_minutes(self):
        """IB complete after configured minutes."""
        engine = InitialBalanceEngine(ib_minutes=60)
        
        ts = datetime(2024, 1, 1, 9, 30)
        result = engine.update(ts, 100.0)
        assert result.complete == False
        
        # After 60 minutes
        ts_later = ts + timedelta(minutes=65)
        result = engine.update(ts_later, 105.0)
        assert result.complete == True

    def test_prior_day_levels_included(self):
        """Prior POC/VAH/VAL passed through."""
        engine = InitialBalanceEngine()
        engine.set_prior_levels(poc=99.5, vah=102.0, val=97.0)
        
        ts = datetime(2024, 1, 1, 9, 30)
        result = engine.update(ts, 100.0)
        
        assert result.prior_poc == 99.5
        assert result.prior_vah == 102.0
        assert result.prior_val == 97.0

    def test_ib_result_fields(self):
        """All IB result fields populated."""
        engine = InitialBalanceEngine(ib_minutes=60)
        
        ts = datetime(2024, 1, 1, 9, 30)
        result = engine.update(ts, 100.0)
        
        assert hasattr(result, 'high')
        assert hasattr(result, 'low')
        assert hasattr(result, 'complete')
        assert hasattr(result, 'minutes')
        assert hasattr(result, 'prior_poc')
        assert hasattr(result, 'prior_vah')
        assert hasattr(result, 'prior_val')

    def test_calculate_initial_balance(self):
        """Calculate IB from bars list."""
        bars = [
            {
                "timestamp": datetime(2024, 1, 1, 9, 30),
                "high": 100,
                "low": 99,
            },
            {
                "timestamp": datetime(2024, 1, 1, 9, 35),
                "high": 102,
                "low": 100,
            },
            {
                "timestamp": datetime(2024, 1, 1, 9, 45),
                "high": 101,
                "low": 98,
            },
        ]
        
        result = calculate_initial_balance(bars, minutes=60)
        
        assert result.high == 102
        assert result.low == 98

    def test_calculate_ib_empty_bars(self):
        """Empty bars -> empty result."""
        result = calculate_initial_balance([])
        
        assert result.high == 0
        assert result.low == 0

    def test_reset(self):
        """Reset clears state."""
        engine = InitialBalanceEngine()
        
        ts = datetime(2024, 1, 1, 9, 30)
        engine.update(ts, 100.0)
        engine.reset()
        
        # After reset, should start fresh
        result = engine.update(ts, 105.0)
        assert result.high == 105.0

    def test_ib_result_frozen(self):
        """IBResult is frozen dataclass."""
        result = IBResult(high=100.0, low=95.0)
        
        with pytest.raises(Exception):
            result.high = 110.0