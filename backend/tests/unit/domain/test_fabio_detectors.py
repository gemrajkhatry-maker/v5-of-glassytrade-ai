"""Tests for Fabio detectors."""

from __future__ import annotations

from dataclasses import dataclass

import pytest

from app.domain.fabio_ai.strategy.fabio_detectors import compute_tick_size, compute_volume_above_vah


@dataclass
class ProfileLevel:
    price: float
    volume: float


@dataclass  
class TickData:
    high: float
    low: float
    close: float


def test_compute_tick_size_from_data():
    """compute_tick_size derives tick size from OHLC data."""
    data = [TickData(high=100.05, low=100.0, close=100.0), TickData(high=100.1, low=100.05, close=100.05)]
    result = compute_tick_size(data, default=0.05)
    assert abs(result - 0.05) < 0.01  # 0.049999...


def test_compute_tick_size_default():
    """compute_tick_size returns default when no data."""
    result = compute_tick_size([], default=0.05)
    assert result == 0.05


def test_compute_volume_above_vah():
    """compute_volume_above_vah calculates volume above VAH."""
    profile = [
        ProfileLevel(price=105.0, volume=100),  # At VAH
        ProfileLevel(price=105.5, volume=200),  # Above VAH
        ProfileLevel(price=106.0, volume=150),  # Above VAH
        ProfileLevel(price=104.0, volume=300),  # Below VAH
    ]
    result = compute_volume_above_vah(profile, 105.0)
    # (200 + 150) / (100 + 200 + 150 + 300) * 100 = 46.67%
    assert abs(result - 46.67) < 0.1


def test_compute_volume_above_vah_empty():
    """compute_volume_above_vah returns 0 for empty profile."""
    result = compute_volume_above_vah([], 105.0)
    assert result == 0.0