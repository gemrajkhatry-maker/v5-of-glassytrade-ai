"""Tests for LVN/HVN detection — Low and High Volume Nodes."""

from __future__ import annotations

import pytest

from app.domain.amt.model.amt_models import VolumeProfileLevel
from app.domain.amt.service.lvn_detector import (
    detect_lvn_hvn,
    detect_lvn_play,
    VolumeNode,
)


def _make_level(price: float, volume: float) -> VolumeProfileLevel:
    return VolumeProfileLevel(price=price, volume=volume)


class TestLVNIdentification:
    """Tests for Low Volume Node identification."""

    def test_lvn_detected_below_threshold(self):
        """Volume < 15% of mean is identified as LVN."""
        levels = (
            _make_level(100.0, 1000.0),
            _make_level(101.0, 1000.0),
            _make_level(102.0, 1000.0),
            _make_level(103.0, 10.0),    # Very low volume => LVN
            _make_level(104.0, 1000.0),
        )
        lvns, hvns = detect_lvn_hvn(levels)
        assert len(lvns) >= 1
        lvn_prices = {lvn.price for lvn in lvns}
        assert 103.0 in lvn_prices

    def test_lvn_strength_clamped(self):
        """LVN strength is between 0 and 1."""
        levels = (
            _make_level(100.0, 1000.0),
            _make_level(101.0, 1.0),     # Extremely low
            _make_level(102.0, 1000.0),
        )
        lvns, _ = detect_lvn_hvn(levels)
        assert len(lvns) >= 1
        for lvn in lvns:
            assert 0.0 <= lvn.strength <= 1.0


class TestHVNIdentification:
    """Tests for High Volume Node identification."""

    def test_hvn_detected_above_threshold(self):
        """Volume > 200% of mean is identified as HVN."""
        levels = (
            _make_level(100.0, 100.0),
            _make_level(101.0, 100.0),
            _make_level(102.0, 2000.0),  # Very high volume => HVN
            _make_level(103.0, 100.0),
            _make_level(104.0, 100.0),
        )
        lvns, hvns = detect_lvn_hvn(levels)
        assert len(hvns) >= 1
        hvn_prices = {hvn.price for hvn in hvns}
        assert 102.0 in hvn_prices


class TestPersistence:
    """Tests for minimum separation between nodes."""

    def test_min_separation_prevents_adjacent_nodes(self):
        """Adjacent low-volume levels don't all become LVNs."""
        levels = (
            _make_level(100.0, 1000.0),
            _make_level(101.0, 5.0),     # Low
            _make_level(102.0, 5.0),     # Low (too close to previous)
            _make_level(103.0, 5.0),     # Low (too close to previous)
            _make_level(104.0, 1000.0),
        )
        lvns, _ = detect_lvn_hvn(levels, min_separation=3)
        # With min_separation=3, only one of the adjacent low levels should be LVN
        assert len(lvns) == 1


class TestSessionReset:
    """Tests for empty/edge case handling."""

    def test_empty_levels_returns_empty(self):
        """Empty levels returns empty LVN and HVN lists."""
        lvns, hvns = detect_lvn_hvn(())
        assert lvns == []
        assert hvns == []

    def test_zero_mean_volume_returns_empty(self):
        """All zero volumes returns empty results."""
        levels = (
            _make_level(100.0, 0.0),
            _make_level(101.0, 0.0),
            _make_level(102.0, 0.0),
        )
        lvns, hvns = detect_lvn_hvn(levels)
        assert lvns == []
        assert hvns == []


class TestLVNPlay:
    """Tests for LVN play pattern detection."""

    def test_lvn_play_with_price_reaction(self):
        """LVN play detected when price tests LVN and reacts."""
        levels = (_make_level(100.0, 5.0),)
        lvn_nodes = (VolumeNode(price=100.0, volume=5.0, node_type="LVN", strength=0.8),)
        # Create bars where price tests the LVN and has a reaction
        bars = [
            {"high": 105.0, "low": 95.0, "close": 98.0, "open": 97.0}
            for _ in range(9)
        ]
        # Bar that tests LVN
        bars.append({"high": 102.0, "low": 99.0, "close": 100.0, "open": 101.0})
        # Reaction bar (strong move up)
        bars.append({"high": 108.0, "low": 100.0, "close": 107.0, "open": 100.0})

        result = detect_lvn_play(levels, bars, lvn_nodes)
        assert result is not None
        assert result["lvn_price"] == 100.0
        assert result["reaction"] in ("BULLISH", "BEARISH")

    def test_lvn_play_insufficient_bars(self):
        """LVN play requires at least 10 bars."""
        lvn_nodes = (VolumeNode(price=100.0, volume=5.0, node_type="LVN", strength=0.8),)
        bars = [{"high": 102.0, "low": 98.0, "close": 100.0, "open": 99.0} for _ in range(5)]
        result = detect_lvn_play((), bars, lvn_nodes)
        assert result is None

    def test_lvn_play_no_nodes(self):
        """LVN play requires LVN nodes."""
        bars = [{"high": 102.0, "low": 98.0, "close": 100.0, "open": 99.0} for _ in range(10)]
        result = detect_lvn_play((), bars, ())
        assert result is None
