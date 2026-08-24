"""Tests for detect_high_delta_zones — independent, isolated tests."""

from quant.amt.profile.delta_profile import detect_high_delta_zones


def test_empty_buckets():
    assert detect_high_delta_zones({}, "LONG") == []
    assert detect_high_delta_zones({}, "SHORT") == []


def test_no_qualified_buckets():
    buckets = {
        100.0: [0, 0, 5, 0],  # values[3] == 0 -> excluded from mean
        100.1: [0, 0, -5, 0],
    }
    assert detect_high_delta_zones(buckets, "LONG") == []
    assert detect_high_delta_zones(buckets, "SHORT") == []


def test_long_high_sell_delta_zone():
    buckets = {
        100.0: [10, 100, -90, 1],   # strong sell pressure -> LONG zone
        100.1: [10, 15, -5, 1],     # mild
        100.2: [10, 20, -10, 1],
    }
    zones = detect_high_delta_zones(buckets, "LONG", sigma_mult=2.0)
    assert 100.0 in zones
    assert 100.1 not in zones


def test_short_high_buy_delta_zone():
    buckets = {
        100.0: [100, 10, 90, 1],    # strong buy pressure -> SHORT zone
        100.1: [15, 10, 5, 1],
        100.2: [20, 10, 10, 1],
    }
    zones = detect_high_delta_zones(buckets, "SHORT", sigma_mult=2.0)
    assert 100.0 in zones
    assert 100.1 not in zones


def test_sorted_output():
    buckets = {
        100.2: [10, 100, -90, 1],
        100.0: [10, 100, -90, 1],
        100.1: [10, 20, -10, 1],
    }
    zones = detect_high_delta_zones(buckets, "LONG", sigma_mult=1.0)
    assert zones == sorted(zones)
