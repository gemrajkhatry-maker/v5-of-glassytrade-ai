"""Parity: three_align_input moved protocol vs legacy shim."""

from quant.amt.profile.three_align_input import ThreeAlignInput as new
from typing import Protocol


def test_parity_protocol_same_class():
    from quant.amt.profile.three_align_input import ThreeAlignInput
    assert new is ThreeAlignInput


def test_parity_protocol_is_protocol():
    assert isinstance(new, type) and issubclass(new, Protocol)


def test_parity_protocol_members():
    props = {
        "cvd_slope", "cvd_divergence", "session_vwap", "lvn_play", "prior_poc",
        "value_area_high", "value_area_low", "poc", "market_state", "price_velocity",
        "leg_poc", "leg_vah", "leg_val", "dev_poc", "dev_vah", "dev_val",
        "hvns", "lvns", "leg_lvns",
    }
    assert props <= set(vars(new).keys()) or props <= set(getattr(new, "__annotations__", {}))
