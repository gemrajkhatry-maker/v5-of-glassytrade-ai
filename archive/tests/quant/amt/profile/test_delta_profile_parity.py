"""Parity: delta_profile moved module vs legacy shim."""

from quant.amt.profile.delta_profile import detect_high_delta_zones as new
from tests.quant.parity import assert_parity


# bucket map: price -> [buy, sell, net, active]; active=1 counts toward the mean
CLEAR_LONG = {
    100.0: [10, 100, -90, 1],   # strong sell pressure -> LONG zone
    100.1: [10, 15, -5, 1],
    100.2: [10, 20, -10, 1],
    100.3: [10, 25, -15, 1],
}

CLEAR_SHORT = {
    100.0: [100, 10, 90, 1],    # strong buy pressure -> SHORT zone
    100.1: [15, 10, 5, 1],
    100.2: [20, 10, 10, 1],
    100.3: [25, 10, 15, 1],
}

CASES = [
    (CLEAR_LONG, "LONG", 2.0),
    (CLEAR_LONG, "SHORT", 2.0),
    (CLEAR_SHORT, "SHORT", 2.0),
    (CLEAR_SHORT, "LONG", 2.0),
    ({}, "LONG", 2.5),
    (CLEAR_LONG, "LONG", 2.5),  # default mult from constants
]


def test_parity():
    for buckets, direction, sigma_mult in CASES:
        new(buckets, direction, sigma_mult=sigma_mult)


def test_parity_default_sigma_mult():
    new(CLEAR_LONG, "LONG")


def test_parity_result_long_zone():
    zones = new(CLEAR_LONG, "LONG", sigma_mult=2.0)
    assert 100.0 in zones
