"""
Tests for analytics options detect_buildups.
"""

import pytest
from datetime import datetime

from brokersv2.analytics.options import detect_buildups
from brokersv2.analytics.options.events import (
    OptionChainEvent,
    OptionContract,
    OptionType,
    StrikeLevel,
)


@pytest.fixture
def sample_chain():
    """Create a sample option chain with buildup patterns."""
    # Call with high volume relative to OI (buildup)
    call_buildup = OptionContract(
        symbol="NIFTY24JAN25000CE",
        underlying="NIFTY",
        strike=25000.0,
        expiry=datetime(2024, 1, 25),
        option_type=OptionType.CALL,
        ltp=150.0,
        bid=149.5,
        ask=150.5,
        volume=50000,  # High volume
        open_interest=10000,  # Lower OI -> buildup
        implied_volatility=0.18,
        delta=0.55,
        gamma=0.002,
        theta=-2.5,
        vega=1.8,
    )
    
    # Call with low volume (no buildup)
    call_no_buildup = OptionContract(
        symbol="NIFTY24JAN25200CE",
        underlying="NIFTY",
        strike=25200.0,
        expiry=datetime(2024, 1, 25),
        option_type=OptionType.CALL,
        ltp=100.0,
        bid=99.5,
        ask=100.5,
        volume=500,  # Low volume
        open_interest=20000,
        implied_volatility=0.16,
        delta=0.45,
        gamma=0.003,
        theta=-2.0,
        vega=1.5,
    )
    
    # Put with high volume (buildup)
    put_buildup = OptionContract(
        symbol="NIFTY24JAN24800PE",
        underlying="NIFTY",
        strike=24800.0,
        expiry=datetime(2024, 1, 25),
        option_type=OptionType.PUT,
        ltp=120.0,
        bid=119.5,
        ask=120.5,
        volume=40000,
        open_interest=8000,
        implied_volatility=0.20,
        delta=-0.45,
        gamma=0.003,
        theta=-2.2,
        vega=1.6,
    )
    
    return OptionChainEvent(
        underlying="NIFTY",
        timestamp=datetime.now(),
        expiry=datetime(2024, 1, 25),
        atm_strike=25000.0,
        underlying_price=25050.0,
        strikes=[
            StrikeLevel(
                strike=24800.0,
                put=put_buildup,
                put_oi=8000,
                put_volume=40000,
            ),
            StrikeLevel(
                strike=25000.0,
                call=call_buildup,
                call_oi=10000,
                call_volume=50000,
            ),
            StrikeLevel(
                strike=25200.0,
                call=call_no_buildup,
                call_oi=20000,
                call_volume=500,
            ),
        ],
    )


class TestDetectBuildups:
    """Test detect_buildups function."""
    
    def test_detects_call_buildup(self, sample_chain):
        """Should detect call buildup at 25000 strike."""
        result = detect_buildups(sample_chain, oi_change_threshold=0.1)
        
        assert len(result["call_buildup"]) >= 1
        strikes = [c["strike"] for c in result["call_buildup"]]
        assert 25000.0 in strikes
    
    def test_detects_put_buildup(self, sample_chain):
        """Should detect put buildup at 24800 strike."""
        result = detect_buildups(sample_chain, oi_change_threshold=0.1)
        
        assert len(result["put_buildup"]) >= 1
        strikes = [c["strike"] for c in result["put_buildup"]]
        assert 24800.0 in strikes
    
    def test_respects_volume_threshold(self, sample_chain):
        """Should filter out low volume contracts."""
        result = detect_buildups(sample_chain, volume_threshold=1000)
        
        # 25200 CE has only 500 volume, should be excluded
        all_strikes = (
            [c["strike"] for c in result["call_buildup"]] +
            [c["strike"] for c in result["call_unwinding"]]
        )
        assert 25200.0 not in all_strikes
    
    def test_respects_oi_threshold(self, sample_chain):
        """Should respect OI change threshold."""
        # High threshold - nothing should qualify
        result = detect_buildups(sample_chain, oi_change_threshold=10.0)
        
        assert len(result["call_buildup"]) == 0
        assert len(result["put_buildup"]) == 0
    
    def test_returns_metadata(self, sample_chain):
        """Should include metadata in result."""
        result = detect_buildups(sample_chain)
        
        assert "metadata" in result
        assert result["metadata"]["underlying"] == "NIFTY"
        assert result["metadata"]["atm_strike"] == 25000.0
    
    def test_sorts_by_oi_change(self, sample_chain):
        """Should sort buildups by OI change ratio."""
        result = detect_buildups(sample_chain, oi_change_threshold=0.1)
        
        if len(result["call_buildup"]) > 1:
            ratios = [c["oi_change_ratio"] for c in result["call_buildup"]]
            assert ratios == sorted(ratios, reverse=True)
    
    def test_empty_chain(self):
        """Should handle empty chain."""
        empty_chain = OptionChainEvent(
            underlying="NIFTY",
            timestamp=datetime.now(),
            expiry=datetime(2024, 1, 25),
            atm_strike=25000.0,
            underlying_price=25050.0,
            strikes=[],
        )
        
        result = detect_buildups(empty_chain)
        
        assert len(result["call_buildup"]) == 0
        assert len(result["put_buildup"]) == 0
        assert len(result["call_unwinding"]) == 0
        assert len(result["put_unwinding"]) == 0
