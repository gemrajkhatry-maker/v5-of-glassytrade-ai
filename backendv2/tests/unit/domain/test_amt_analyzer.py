"""Unit tests for AMT analyzer based on amt_docs specifications."""
import pytest
from app.domain.amt.service.volume_profile import build_volume_profile, calculate_vwap
from app.domain.amt.service.amt_analyzer import AMTAnalyzer
from app.domain.amt.service.lvn_detector import detect_lvn_hvn, detect_lvn_play
from app.domain.amt.service.orderflow_detectors import detect_absorptions
from app.domain.amt.service.signal_generator import generate_triple_a_signal


class TestVolumeProfile:
    """Tests based on amt_docs section 2.2."""
    
    def test_builds_profile_with_poc_vah_val(self):
        """Test that volume profile has POC, VAH, VAL."""
        bars = [
            {"high": 102, "low": 100, "close": 101, "volume": 100, "buyVolume": 60, "sellVolume": 40},
            {"high": 103, "low": 101, "close": 102, "volume": 200, "buyVolume": 120, "sellVolume": 80},
            {"high": 104, "low": 102, "close": 103, "volume": 150, "buyVolume": 90, "sellVolume": 60},
            {"high": 105, "low": 103, "close": 104, "volume": 50, "buyVolume": 30, "sellVolume": 20},
        ]
        
        vp = build_volume_profile(bars, bucket_size=1.0)
        
        assert vp.poc > 0
        assert vp.vah >= vp.val
        
    def test_poc_is_highest_volume_level(self):
        """Test that POC corresponds to highest volume."""
        bars = [
            {"high": 103, "low": 101, "close": 102, "volume": 500, "buyVolume": 300, "sellVolume": 200},
            {"high": 102, "low": 100, "close": 101, "volume": 100, "buyVolume": 60, "sellVolume": 40},
        ]
        
        vp = build_volume_profile(bars, bucket_size=1.0)
        
        # POC should be near the bar with 500 volume
        assert vp.poc >= 101
        
    def test_empty_bars_returns_empty_profile(self):
        """Test that empty bars input returns empty profile."""
        vp = build_volume_profile([], bucket_size=1.0)
        
        assert vp.poc == 0.0
        assert vp.vah == 0.0
        assert vp.val == 0.0


class TestVWAP:
    """Tests based on amt_docs section 2.3."""
    
    def test_calculates_vwap_with_bands(self):
        """Test that VWAP and bands are calculated."""
        bars = [
            {"high": 102, "low": 100, "close": 101, "volume": 100},
            {"high": 103, "low": 101, "close": 102, "volume": 200},
            {"high": 104, "low": 102, "close": 103, "volume": 150},
        ]
        
        vwap, upper1, lower1, upper2, lower2 = calculate_vwap(bars)
        
        assert vwap > 0
        assert upper1 > vwap
        assert lower1 < vwap
        assert upper2 > upper1
        assert lower2 < lower1
        
    def test_empty_bars_returns_zeros(self):
        """Test that empty bars return zero values."""
        result = calculate_vwap([])
        
        assert result == (0.0, 0.0, 0.0, 0.0, 0.0)


class TestAbsorption:
    """Tests based on amt_docs section 2.4."""
    
    def test_detects_buy_absorption(self):
        """Test detection of BUY absorption pattern."""
        # Create bars with high volume but low price range
        bars = []
        avg_volume = 100
        
        for i in range(25):
            vol = 200 if i == 20 else avg_volume
            # Make the spike bar have significantly compressed range (< 20% of avg)
            bar_range = 0.05 if i == 20 else 0.3
            bars.append({
                "high": 100.5, "low": 100.5 - bar_range, "close": 100.4,
                "volume": vol, "buyVolume": 150, "sellVolume": 50
            })
        
        absorptions = detect_absorptions(bars, avg_volume_multiplier=1.5, range_threshold=0.5)
        
        assert len(absorptions) > 0
        assert absorptions[-1].side == "BUY"
        
    def test_detects_sell_absorption(self):
        """Test detection of SELL absorption pattern."""
        bars = []
        
        for i in range(25):
            vol = 200 if i == 20 else 100
            # Make the spike bar have significantly compressed range (< 20% of avg)
            bar_range = 0.05 if i == 20 else 0.3
            bars.append({
                "high": 100.5, "low": 100.5 - bar_range, "close": 100.4,
                "volume": vol, "buyVolume": 50, "sellVolume": 150
            })
        
        absorptions = detect_absorptions(bars, avg_volume_multiplier=1.5, range_threshold=0.5)
        
        assert len(absorptions) > 0
        assert absorptions[-1].side == "SELL"
        
    def test_ignores_normal_volume(self):
        """Test that normal volume doesn't trigger absorption."""
        bars = [
            {"high": 102, "low": 100, "close": 101, "volume": 100, "buyVolume": 60, "sellVolume": 40}
            for _ in range(25)
        ]
        
        absorptions = detect_absorptions(bars)
        
        assert len(absorptions) == 0


class TestSignalGeneration:
    """Tests based on amt_docs section 2.6 and 4.1."""
    
    def test_generates_long_signal(self):
        """Test LONG signal generation: BUY absorption + price > VWAP."""
        bars = [
            {"high": 102, "low": 100, "close": 105, "volume": 200, "buyVolume": 150, "sellVolume": 50},
            {"high": 106, "low": 101, "close": 106, "volume": 220, "buyVolume": 140, "sellVolume": 60},
            {"high": 107, "low": 102, "close": 107, "volume": 240, "buyVolume": 150, "sellVolume": 70},
        ]
        
        absorptions = [
            type('Absorption', (), {
                'bar_index': 0, 'side': 'BUY', 'strength': 0.8, 'price': 101
            })()
        ]
        
        from app.domain.amt.model.amt_models import VolumeProfile
        vp = VolumeProfile(levels=(), poc=102, vah=103, val=100, step=1.0)
        
        signal = generate_triple_a_signal(bars, absorptions, vp, vwap=103)
        
        assert signal.type == "LONG"
        assert signal.entry >= 105
        assert signal.rr >= 1.5
        
    def test_generates_short_signal(self):
        """Test SHORT signal generation: SELL absorption + price < VWAP."""
        bars = [
            {"high": 102, "low": 100, "close": 95, "volume": 200, "buyVolume": 50, "sellVolume": 150},
            {"high": 99, "low": 94, "close": 94.5, "volume": 220, "buyVolume": 80, "sellVolume": 160},
            {"high": 98, "low": 93, "close": 94.0, "volume": 240, "buyVolume": 90, "sellVolume": 150},
        ]
        
        absorptions = [
            type('Absorption', (), {
                'bar_index': 0, 'side': 'SELL', 'strength': 0.8, 'price': 101
            })()
        ]
        
        from app.domain.amt.model.amt_models import VolumeProfile
        vp = VolumeProfile(levels=(), poc=102, vah=103, val=100, step=1.0)
        
        signal = generate_triple_a_signal(bars, absorptions, vp, vwap=97)
        
        assert signal.type == "SHORT"
        
    def test_no_signal_without_absorption(self):
        """Test that no signal is generated without absorption."""
        bars = [{"high": 102, "low": 100, "close": 101, "volume": 100, "buyVolume": 60, "sellVolume": 40}]
        
        signal = generate_triple_a_signal(bars, [], None, vwap=100)
        
        assert signal.type == "NO_TRADE"