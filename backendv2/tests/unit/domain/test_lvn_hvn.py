"""Tests for LVN/HVN detection."""

import pytest
from app.domain.amt.model.amt_models import VolumeProfileLevel
from app.domain.amt.service.lvn_detector import detect_lvn_hvn, detect_lvn_play, LVNLevel, HVNLevel


class TestLVNHVNDetection:
    """Tests for LVN/HVN detection."""

    @pytest.fixture
    def sample_levels(self):
        return tuple([
            VolumeProfileLevel(price=49900, volume=1000, buy_volume=500, sell_volume=500),
            VolumeProfileLevel(price=49950, volume=2000, buy_volume=1000, sell_volume=1000),
            VolumeProfileLevel(price=50000, volume=5000, buy_volume=2500, sell_volume=2500),
            VolumeProfileLevel(price=50050, volume=8000, buy_volume=4000, sell_volume=4000),  # HVN
            VolumeProfileLevel(price=50100, volume=100, buy_volume=50, sell_volume=50),      # LVN
            VolumeProfileLevel(price=50150, volume=3000, buy_volume=1500, sell_volume=1500),
            VolumeProfileLevel(price=50200, volume=500, buy_volume=250, sell_volume=250),     # LVN
            VolumeProfileLevel(price=50250, volume=1500, buy_volume=750, sell_volume=750),
        ])

    def test_detects_hvn(self, sample_levels):
        lvns, hvns = detect_lvn_hvn(sample_levels)
        assert len(hvns) >= 1
        assert any(h.price == 50050 for h in hvns)
        assert all(isinstance(h, HVNLevel) for h in hvns)

    def test_detects_lvn(self, sample_levels):
        lvns, hvns = detect_lvn_hvn(sample_levels)
        assert len(lvns) >= 1
        assert any(l.price == 50100 for l in lvns)
        assert all(isinstance(l, LVNLevel) for l in lvns)

    def test_empty_levels_returns_empty(self):
        lvns, hvns = detect_lvn_hvn(())
        assert lvns == []
        assert hvns == []

    def test_no_nodes_below_thresholds(self):
        levels = tuple([
            VolumeProfileLevel(price=50000 + i * 50, volume=1000, buy_volume=500, sell_volume=500)
            for i in range(10)
        ])
        lvns, hvns = detect_lvn_hvn(levels, lvn_threshold=0.1, hvn_threshold=2.0)
        assert len(lvns) == 0
        assert len(hvns) == 0

    def test_lvn_play_detection(self, sample_levels):
        bars = [
            {'open': 50050, 'high': 50060, 'low': 50040, 'close': 50050, 'volume': 100},
            {'open': 50050, 'high': 50055, 'low': 50045, 'close': 50050, 'volume': 100},
            {'open': 50050, 'high': 50070, 'low': 50040, 'close': 50060, 'volume': 100},
            {'open': 50060, 'high': 50075, 'low': 50050, 'close': 50065, 'volume': 100},
            {'open': 50065, 'high': 50080, 'low': 50055, 'close': 50070, 'volume': 100},
            {'open': 50070, 'high': 50085, 'low': 50060, 'close': 50075, 'volume': 100},
            {'open': 50075, 'high': 50090, 'low': 50065, 'close': 50080, 'volume': 100},
            {'open': 50080, 'high': 50100, 'low': 50070, 'close': 50090, 'volume': 100},
            {'open': 50090, 'high': 50110, 'low': 50080, 'close': 50100, 'volume': 100},
            {'open': 50100, 'high': 50105, 'low': 50090, 'close': 50100, 'volume': 100},
            {'open': 50100, 'high': 50120, 'low': 50095, 'close': 50110, 'volume': 150},
        ]
        lvns, hvns = detect_lvn_hvn(sample_levels)
        play = detect_lvn_play(sample_levels, bars, tuple(lvns))
        assert play is None or 'lvn_price' in play

    def test_lvn_strength(self, sample_levels):
        lvns, hvns = detect_lvn_hvn(sample_levels)
        for lvn in lvns:
            assert 0.0 <= lvn.strength <= 1.0

    def test_hvn_has_bucket_index(self, sample_levels):
        lvns, hvns = detect_lvn_hvn(sample_levels)
        for hvn in hvns:
            assert hvn.bucket_index >= 0


class TestLVNPlay:
    """Tests for LVN play pattern detection."""

    def test_no_play_without_lvn(self):
        levels = tuple([
            VolumeProfileLevel(price=50000 + i * 50, volume=2000, buy_volume=1000, sell_volume=1000)
            for i in range(10)
        ])
        play = detect_lvn_play(levels, [], ())
        assert play is None

    def test_no_play_with_insufficient_bars(self):
        from app.domain.amt.service.lvn_detector import LVNLevel
        lvn_nodes = (LVNLevel(price=50100, strength=0.8, bucket_index=4),)
        bars = [{'open': 50000, 'high': 50010, 'low': 49990, 'close': 50000, 'volume': 100}]
        play = detect_lvn_play([], bars, lvn_nodes)
        assert play is None
