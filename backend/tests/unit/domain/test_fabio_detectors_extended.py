"""Tests for fabio_detectors.py - increase coverage."""

from __future__ import annotations

import pytest

from app.domain.fabio_ai.strategy.fabio_detectors import (
    detect_vah_probe, check_exhaustion, compute_volume_above_vah,
    track_drives,
)
from app.domain.trading.models.value_objects import OHLC


def test_detect_vah_probe_none_when_below_vah():
    """detect_vah_probe returns None when price below VAH."""
    result = detect_vah_probe(live_price=95.0, vah=100.0, ib_high=101.0, vwap_deviation_sigmas=2.5, delta_score=0.05)
    assert result is None


def test_detect_vah_probe_extreme_at_ib():
    """detect_vah_probe detects extreme at IB."""
    result = detect_vah_probe(live_price=101.0, vah=100.0, ib_high=101.0, vwap_deviation_sigmas=2.5, delta_score=0.0)
    assert result in ("VAH_PROBE_EXHAUSTION", "IB_BREAKOUT", "VAH_PROBE_TESTING")


def test_check_exhaustion_none_normal():
    """check_exhaustion returns None in normal conditions."""
    result = check_exhaustion(delta_score=0.5, vwap_deviation_sigmas=0.5, aggression=2.0, volume_above_vah_pct=20.0)
    assert result is None


def test_check_exhaustion_delta_flat_extreme():
    """check_exhaustion detects delta flat at extreme."""
    result = check_exhaustion(delta_score=0.0, vwap_deviation_sigmas=2.5, aggression=2.0, volume_above_vah_pct=5.0)
    assert result is not None


def test_compute_volume_above_vah_empty_profile():
    """compute_volume_above_vah handles empty profile."""
    result = compute_volume_above_vah([], vah=100.0)
    assert result == 0.0


def test_compute_volume_above_vah_zero_vah():
    """compute_volume_above_vah handles zero VAH."""
    class MockLevel:
        def __init__(self, price, volume):
            self.price = price
            self.volume = volume
    result = compute_volume_above_vah([MockLevel(100, 100)], vah=0.0)
    assert result == 0.0


def test_track_drives_no_levels():
    """track_drives handles no levels."""
    result = track_drives(live_price=100.0, poc=0.0, lvns=[], hvns=[], vah=0.0, val=0.0, tick_size=0.05, current=None, drive_tracker=None)
    assert isinstance(result, tuple)