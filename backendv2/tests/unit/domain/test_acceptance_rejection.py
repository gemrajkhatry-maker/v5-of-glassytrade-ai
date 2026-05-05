"""Tests for Acceptance/Rejection engine."""
import pytest

from app.domain.amt.model.amt_models import InitialBalanceResult
from app.domain.amt.service.acceptance_rejection import detect_acceptance_rejection


class TestAcceptanceRejection:
    """Tests for acceptance/rejection detection."""
    
    @pytest.fixture
    def ib_complete(self):
        return InitialBalanceResult(
            high=50100,
            low=49900,
            complete=True
        )
    
    @pytest.fixture
    def ib_incomplete(self):
        return InitialBalanceResult(
            high=0,
            low=0,
            complete=False
        )
    
    def test_no_bars_returns_empty(self, ib_complete):
        """Test no bars returns empty result."""
        result = detect_acceptance_rejection([], ib_complete, [])
        
        assert result.accepted_above is False
        assert result.accepted_below is False
    
    def test_accepted_above_ib(self, ib_complete):
        """Test detection of acceptance above IB."""
        bars = [
            {'open': 50050, 'high': 50060, 'low': 50040, 'close': 50110, 'volume': 100},
            {'open': 50110, 'high': 50120, 'low': 50100, 'close': 50130, 'volume': 100},
            {'open': 50130, 'high': 50140, 'low': 50120, 'close': 50120, 'volume': 100},
            {'open': 50120, 'high': 50130, 'low': 50110, 'close': 50125, 'volume': 100},
        ]
        
        result = detect_acceptance_rejection(bars, ib_complete, [])
        
        assert result.accepted_above is True
    
    def test_accepted_below_ib(self, ib_complete):
        """Test detection of acceptance below IB."""
        bars = [
            {'open': 49950, 'high': 49960, 'low': 49940, 'close': 49890, 'volume': 100},
            {'open': 49890, 'high': 49900, 'low': 49880, 'close': 49870, 'volume': 100},
            {'open': 49870, 'high': 49880, 'low': 49860, 'close': 49860, 'volume': 100},
            {'open': 49860, 'high': 49870, 'low': 49850, 'close': 49855, 'volume': 100},
        ]
        
        result = detect_acceptance_rejection(bars, ib_complete, [])
        
        assert result.accepted_below is True
    
    def test_rejected_at_high(self, ib_complete):
        """Test detection of rejection at IB high."""
        bars = [
            {'open': 50090, 'high': 50110, 'low': 50080, 'close': 50105, 'volume': 100},
            {'open': 50105, 'high': 50120, 'low': 50100, 'close': 50110, 'volume': 100},
            {'open': 50110, 'high': 50115, 'low': 50090, 'close': 50095, 'volume': 100},
        ]
        
        result = detect_acceptance_rejection(bars, ib_complete, [])
        
        assert result.rejected_at_high is True
        assert result.liquidity_sweep == "SWEEP_HIGH"
    
    def test_rejected_at_low(self, ib_complete):
        """Test detection of rejection at IB low."""
        # IB low = 49900
        # First bar: below IB low (close 49885)
        # Second bar: testing lower (close 49880)
        # Third bar: rejection - goes below IB low (49865) but closes above (49910)
        bars = [
            {'open': 49895, 'high': 49900, 'low': 49875, 'close': 49885, 'volume': 100},
            {'open': 49885, 'high': 49895, 'low': 49870, 'close': 49880, 'volume': 100},
            {'open': 49880, 'high': 49920, 'low': 49865, 'close': 49910, 'volume': 100},  # Rejection above IB low
        ]
        
        result = detect_acceptance_rejection(bars, ib_complete, [])
        
        assert result.rejected_at_low is True
        assert result.liquidity_sweep == "SWEEP_LOW"
    
    def test_incomplete_ib_returns_empty(self, ib_incomplete):
        """Test incomplete IB returns empty result."""
        bars = [{'open': 50000, 'high': 50010, 'low': 49990, 'close': 50000, 'volume': 100}]
        
        result = detect_acceptance_rejection(bars, ib_incomplete, [])
        
        assert result.accepted_above is False
        assert result.accepted_below is False