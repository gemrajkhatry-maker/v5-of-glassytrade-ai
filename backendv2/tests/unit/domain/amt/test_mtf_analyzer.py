"""Tests for MTF Analyzer."""

import pytest

from app.domain.amt.service.mtf_analyzer import (
    MultiTimeframeAMTAnalyzer,
    MTFState,
    MTFAlignment,
)


class TestMTFAnalyzer:
    """Tests for multi-timeframe analysis."""

    def test_aligned_bullish(self):
        """Daily bullish + hourly bullish -> ALIGNED_BULLISH."""
        analyzer = MultiTimeframeAMTAnalyzer()
        
        # POC > mid means bullish
        daily = {"poc": 103, "vah": 105, "val": 100}  # mid=102.5, POC=103 > mid (bullish)
        hourly = {"poc": 102, "vah": 103, "val": 99}  # mid=101, POC=102 > mid (bullish)
        
        result = analyzer.analyze(daily, hourly)
        
        assert result.alignment == MTFAlignment.ALIGNED_BULLISH

    def test_aligned_bearish(self):
        """Daily bearish + hourly bearish -> ALIGNED_BEARISH."""
        analyzer = MultiTimeframeAMTAnalyzer()
        
        # POC < mid means bearish
        daily = {"poc": 96, "vah": 100, "val": 95}   # mid=97.5, POC=96 < mid (bearish)
        hourly = {"poc": 95, "vah": 99, "val": 94}   # mid=96.5, POC=95 < mid (bearish)
        
        result = analyzer.analyze(daily, hourly)
        
        assert result.alignment == MTFAlignment.ALIGNED_BEARISH

    def test_divergent_signals(self):
        """Daily bullish + hourly bearish -> DIVERGENT."""
        analyzer = MultiTimeframeAMTAnalyzer()
        
        daily = {"poc": 102, "vah": 105, "val": 100}
        hourly = {"poc": 97, "vah": 99, "val": 94}
        
        result = analyzer.analyze(daily, hourly)
        
        assert result.alignment == MTFAlignment.DIVERGENT

    def test_no_higher_tf_data(self):
        """Missing daily data -> NONE alignment."""
        analyzer = MultiTimeframeAMTAnalyzer()
        
        daily = {}
        hourly = {"poc": 101, "vah": 103, "val": 99}
        
        result = analyzer.analyze(daily, hourly)
        
        assert result.alignment == MTFAlignment.NONE

    def test_mtf_constants(self):
        """Daily/hourly VAH/VAL/POC tracked."""
        analyzer = MultiTimeframeAMTAnalyzer()
        
        daily = {"poc": 102, "vah": 105, "val": 100}
        hourly = {"poc": 101, "vah": 103, "val": 99}
        
        result = analyzer.analyze(daily, hourly)
        
        assert result.daily_poc == 102
        assert result.daily_vah == 105
        assert result.daily_val == 100
        assert result.hourly_poc == 101
        assert result.hourly_vah == 103
        assert result.hourly_val == 99

    def test_mtf_state_frozen(self):
        """MTFState is frozen dataclass."""
        state = MTFState(
            daily_poc=100, daily_vah=105, daily_val=95,
            hourly_poc=100, hourly_vah=103, hourly_val=97,
            alignment=MTFAlignment.ALIGNED_BULLISH
        )
        
        with pytest.raises(Exception):
            state.daily_poc = 110

    def test_both_zero_pocs(self):
        """Both POC at 0 -> NONE alignment."""
        analyzer = MultiTimeframeAMTAnalyzer()
        
        daily = {"poc": 0, "vah": 105, "val": 100}
        hourly = {"poc": 0, "vah": 103, "val": 99}
        
        result = analyzer.analyze(daily, hourly)
        
        assert result.alignment == MTFAlignment.NONE