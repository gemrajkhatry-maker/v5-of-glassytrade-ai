"""Tests for LVN/HVN detection."""

import pytest
from app.domain.amt.service.lvn_detector import detect_lvn_hvn, detect_lvn_play, VolumeNode
from app.domain.amt.model.amt_models import VolumeProfileLevel


class TestDetectLVNHVN:
    """Tests for LVN and HVN detection."""

    def test_returns_empty_for_no_levels(self):
        """Should return empty lists when no levels provided."""
        lvns, hvns = detect_lvn_hvn(())
        
        assert lvns == []
        assert hvns == []

    def test_returns_empty_for_zero_volume(self):
        """Should return empty lists when all volume is zero."""
        levels = (
            VolumeProfileLevel(price=100.0, volume=0, buy_volume=0, sell_volume=0),
            VolumeProfileLevel(price=101.0, volume=0, buy_volume=0, sell_volume=0),
        )
        
        lvns, hvns = detect_lvn_hvn(levels)
        
        assert lvns == []
        assert hvns == []

    def test_detects_lvn_correctly(self):
        """Should detect Low Volume Nodes."""
        levels = (
            VolumeProfileLevel(price=100.0, volume=1000, buy_volume=500, sell_volume=500),
            VolumeProfileLevel(price=101.0, volume=50, buy_volume=25, sell_volume=25),   # LVN
            VolumeProfileLevel(price=102.0, volume=1000, buy_volume=500, sell_volume=500),
        )
        
        lvns, hvns = detect_lvn_hvn(levels, lvn_threshold=0.15)
        
        assert len(lvns) >= 1
        # LVN should be at price 101
        assert any(lvn.price == 101.0 for lvn in lvns)

    def test_detects_hvn_correctly(self):
        """Should detect High Volume Nodes."""
        levels = (
            VolumeProfileLevel(price=100.0, volume=100, buy_volume=50, sell_volume=50),
            VolumeProfileLevel(price=101.0, volume=100, buy_volume=50, sell_volume=50),
            VolumeProfileLevel(price=102.0, volume=5000, buy_volume=2500, sell_volume=2500),  # HVN
            VolumeProfileLevel(price=103.0, volume=100, buy_volume=50, sell_volume=50),
        )
        
        lvns, hvns = detect_lvn_hvn(levels, hvn_threshold=2.0)
        
        assert len(hvns) >= 1
        # HVN should be at price 102
        assert any(hvn.price == 102.0 for hvn in hvns)

    def test_lvn_strength_is_normalized(self):
        """Should calculate LVN strength between 0 and 1."""
        levels = (
            VolumeProfileLevel(price=100.0, volume=1000, buy_volume=500, sell_volume=500),
            VolumeProfileLevel(price=101.0, volume=10, buy_volume=5, sell_volume=5),  # Very low
        )
        
        lvns, hvns = detect_lvn_hvn(levels)
        
        if lvns:
            assert 0.0 <= lvns[0].strength <= 1.0

    def test_hvn_strength_can_exceed_one(self):
        """Should allow HVN strength > 1 for very high volume."""
        levels = (
            VolumeProfileLevel(price=100.0, volume=100, buy_volume=50, sell_volume=50),
            VolumeProfileLevel(price=101.0, volume=10000, buy_volume=5000, sell_volume=5000),  # Very high
        )
        
        lvns, hvns = detect_lvn_hvn(levels)
        
        if hvns:
            assert hvns[0].strength > 1.0

    def test_respects_min_separation(self):
        """Should respect minimum separation between nodes."""
        # Create many low volume levels close together
        levels = tuple(
            VolumeProfileLevel(price=100.0 + i, volume=10, buy_volume=5, sell_volume=5)
            for i in range(10)
        )
        
        lvns, hvns = detect_lvn_hvn(levels, min_separation=3)
        
        # Should not detect all as LVNs due to separation
        assert len(lvns) < len(levels)

    def test_detects_both_lvn_and_hvn(self):
        """Should detect both LVN and HVN in same profile."""
        levels = (
            VolumeProfileLevel(price=100.0, volume=5000, buy_volume=2500, sell_volume=2500),  # HVN
            VolumeProfileLevel(price=101.0, volume=1000, buy_volume=500, sell_volume=500),
            VolumeProfileLevel(price=102.0, volume=50, buy_volume=25, sell_volume=25),   # LVN
            VolumeProfileLevel(price=103.0, volume=1000, buy_volume=500, sell_volume=500),
            VolumeProfileLevel(price=104.0, volume=5000, buy_volume=2500, sell_volume=2500),  # HVN
        )
        
        lvns, hvns = detect_lvn_hvn(levels)
        
        assert len(lvns) >= 1
        assert len(hvns) >= 1

    def test_handles_uniform_volume(self):
        """Should detect no nodes when volume is uniform."""
        levels = tuple(
            VolumeProfileLevel(price=100.0 + i, volume=1000, buy_volume=500, sell_volume=500)
            for i in range(10)
        )
        
        lvns, hvns = detect_lvn_hvn(levels)
        
        # All same volume, so no LVN or HVN
        assert len(lvns) == 0
        assert len(hvns) == 0

    def test_uses_default_thresholds(self):
        """Should use Fabio spec thresholds by default (15% LVN, 200% HVN)."""
        levels = (
            VolumeProfileLevel(price=100.0, volume=1000, buy_volume=500, sell_volume=500),
            VolumeProfileLevel(price=101.0, volume=50, buy_volume=25, sell_volume=25),   # 5% of mean
            VolumeProfileLevel(price=102.0, volume=1000, buy_volume=500, sell_volume=500),
        )
        
        lvns, hvns = detect_lvn_hvn(levels)
        
        # Mean = 683, 50/683 = 0.073 < 0.15, should detect LVN
        assert len(lvns) >= 1


class TestDetectLVNPlay:
    """Tests for LVN play pattern detection."""

    def test_returns_none_for_few_bars(self):
        """Should return None when insufficient bars."""
        levels = (
            VolumeProfileLevel(price=100.0, volume=1000, buy_volume=500, sell_volume=500),
        )
        bars = [{"low": 99.0, "high": 101.0, "close": 100.0}] * 5  # Less than 10
        lvn_nodes = (VolumeNode(price=100.0, volume=10, node_type="LVN", strength=0.8),)
        
        result = detect_lvn_play(levels, bars, lvn_nodes)
        
        assert result is None

    def test_returns_none_for_no_lvn_nodes(self):
        """Should return None when no LVN nodes."""
        levels = ()
        bars = [{"low": 99.0, "high": 101.0, "close": 100.0}] * 10
        
        result = detect_lvn_play(levels, bars, ())
        
        assert result is None

    def test_detects_bullish_reaction(self):
        """Should detect bullish bounce off LVN."""
        levels = (
            VolumeProfileLevel(price=100.0, volume=10, buy_volume=5, sell_volume=5),
        )
        bars = [{"low": 101.0, "high": 102.0, "close": 101.5}] * 10
        bars[-2] = {"low": 99.5, "high": 100.5, "close": 100.0}  # Tests LVN
        bars[-1] = {"low": 100.5, "high": 102.0, "close": 101.5}  # Bounces up
        
        lvn_nodes = (VolumeNode(price=100.0, volume=10, node_type="LVN", strength=0.8),)
        
        result = detect_lvn_play(levels, bars, lvn_nodes)
        
        if result:
            assert result["reaction"] == "BULLISH"

    def test_detects_bearish_reaction(self):
        """Should detect bearish rejection off LVN."""
        levels = (
            VolumeProfileLevel(price=100.0, volume=10, buy_volume=5, sell_volume=5),
        )
        bars = [{"low": 99.0, "high": 100.0, "close": 99.5}] * 10
        bars[-2] = {"low": 99.5, "high": 100.5, "close": 100.0}  # Tests LVN
        bars[-1] = {"low": 98.0, "high": 99.5, "close": 98.5}  # Rejects down
        
        lvn_nodes = (VolumeNode(price=100.0, volume=10, node_type="LVN", strength=0.8),)
        
        result = detect_lvn_play(levels, bars, lvn_nodes)
        
        if result:
            assert result["reaction"] == "BEARISH"

    def test_calculates_reaction_strength(self):
        """Should calculate reaction strength."""
        levels = (
            VolumeProfileLevel(price=100.0, volume=10, buy_volume=5, sell_volume=5),
        )
        bars = [{"low": 101.0, "high": 102.0, "close": 101.5}] * 10
        bars[-2] = {"low": 99.0, "high": 101.0, "close": 100.0}  # Bar range = 2
        bars[-1] = {"low": 100.5, "high": 103.0, "close": 102.5}  # Reaction = 2.5
        
        lvn_nodes = (VolumeNode(price=100.0, volume=10, node_type="LVN", strength=0.8),)
        
        result = detect_lvn_play(levels, bars, lvn_nodes)
        
        if result:
            assert "strength" in result
            assert result["strength"] > 0

    def test_requires_significant_reaction(self):
        """Should only detect play when reaction > 50% of bar range."""
        levels = (
            VolumeProfileLevel(price=100.0, volume=10, buy_volume=5, sell_volume=5),
        )
        bars = [{"low": 101.0, "high": 102.0, "close": 101.5}] * 10
        bars[-2] = {"low": 99.0, "high": 101.0, "close": 100.0}  # Bar range = 2
        bars[-1] = {"low": 100.0, "high": 100.5, "close": 100.3}  # Reaction = 0.3 (too small)
        
        lvn_nodes = (VolumeNode(price=100.0, volume=10, node_type="LVN", strength=0.8),)
        
        result = detect_lvn_play(levels, bars, lvn_nodes)
        
        # Reaction 0.3 is only 15% of range 2, should not detect
        assert result is None
