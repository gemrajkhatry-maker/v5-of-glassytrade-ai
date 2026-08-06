"""Tests for IBBreakoutScalpEngine — standalone unit + parity.

No dedicated backend test existed for ib_breakout_scalp (grep found zero hits);
unit tests mirror the established port style, parity drives evaluate_setup_a
with fixed inputs via assert_parity.
"""

from __future__ import annotations

from app.domain.services.ib_breakout_scalp import (
    IBBreakoutScalpEngine as LegacyIBBreakoutScalpEngine,
)
from quant.amt.session.ib_scalp import (
    IBBreakoutScalpEngine,
    IBScalpSignal,
    IBScalpType,
)
from quant.amt.session.ib_engine import IBLocation, IBState
from tests.quant.parity import assert_parity


def _ib_state(
    ib_high=105.0,
    ib_low=95.0,
    is_complete=True,
    location=IBLocation.INSIDE,
    ib_position_pct=50.0,
) -> IBState:
    return IBState(
        ib_high=ib_high,
        ib_low=ib_low,
        ib_mid=(ib_high + ib_low) / 2,
        ib_width=ib_high - ib_low,
        is_complete=is_complete,
        location=location,
        ib_position_pct=ib_position_pct,
    )


class TestIBBreakoutScalpEngine:
    def test_ib_not_complete_rejected(self):
        engine = IBBreakoutScalpEngine()
        sig = engine.evaluate_setup_a(
            ib_state=_ib_state(is_complete=False),
            current_price=100.0,
            current_high=106.0,
            current_low=99.0,
            current_volume=5000,
            avg_volume=1000,
            cvd_slope_1m=5.0,
            bar_index=10,
            tick_size=0.05,
        )
        assert sig.setup_valid is False
        assert sig.scalp_type == IBScalpType.NONE
        assert sig.rejection_reason == "IB not complete"

    def test_ib_zero_width_rejected(self):
        engine = IBBreakoutScalpEngine()
        sig = engine.evaluate_setup_a(
            ib_state=_ib_state(ib_high=100.0, ib_low=100.0),
            current_price=100.0,
            current_high=101.0,
            current_low=99.0,
            current_volume=5000,
            avg_volume=1000,
            cvd_slope_1m=5.0,
            bar_index=10,
            tick_size=0.05,
        )
        assert sig.setup_valid is False
        assert sig.rejection_reason == "IB width is zero"

    def test_long_breakout_volume_not_confirmed(self):
        engine = IBBreakoutScalpEngine()
        sig = engine.evaluate_setup_a(
            ib_state=_ib_state(),
            current_price=105.1,
            current_high=106.0,
            current_low=104.0,
            current_volume=1000,
            avg_volume=1000,
            cvd_slope_1m=5.0,
            bar_index=10,
            tick_size=0.05,
        )
        assert sig.setup_valid is False
        assert sig.scalp_type == IBScalpType.BREAKOUT_CONTINUATION
        assert sig.rejection_reason == "Volume not confirmed"

    def test_long_breakout_cvd_not_positive(self):
        engine = IBBreakoutScalpEngine()
        sig = engine.evaluate_setup_a(
            ib_state=_ib_state(),
            current_price=105.1,
            current_high=106.0,
            current_low=104.0,
            current_volume=5000,
            avg_volume=1000,
            cvd_slope_1m=-1.0,
            bar_index=10,
            tick_size=0.05,
        )
        assert sig.setup_valid is False
        assert sig.rejection_reason == "1-min CVD not positive"

    def test_long_breakout_valid_at_retest(self):
        engine = IBBreakoutScalpEngine()
        sig = engine.evaluate_setup_a(
            ib_state=_ib_state(ib_high=105.0, ib_low=95.0),
            current_price=105.1,
            current_high=106.0,
            current_low=104.0,
            current_volume=5000,
            avg_volume=1000,
            cvd_slope_1m=5.0,
            bar_index=10,
            tick_size=0.05,
        )
        assert sig.setup_valid is True
        assert sig.scalp_type == IBScalpType.BREAKOUT_CONTINUATION
        assert sig.direction == "LONG"
        assert sig.entry_price == 105.0
        assert sig.stop_loss == 104.95
        assert sig.take_profit == 115.0  # ib_high + ib_width

    def test_short_breakout_valid_at_retest(self):
        engine = IBBreakoutScalpEngine()
        sig = engine.evaluate_setup_a(
            ib_state=_ib_state(ib_high=105.0, ib_low=95.0),
            current_price=94.9,
            current_high=95.5,
            current_low=94.0,
            current_volume=5000,
            avg_volume=1000,
            cvd_slope_1m=-5.0,
            bar_index=10,
            tick_size=0.05,
        )
        assert sig.setup_valid is True
        assert sig.direction == "SHORT"
        assert sig.entry_price == 95.0
        assert sig.stop_loss == 95.05
        assert sig.take_profit == 85.0

    def test_no_breakout_detected(self):
        engine = IBBreakoutScalpEngine()
        sig = engine.evaluate_setup_a(
            ib_state=_ib_state(),
            current_price=100.0,
            current_high=104.0,
            current_low=96.0,
            current_volume=5000,
            avg_volume=1000,
            cvd_slope_1m=5.0,
            bar_index=10,
            tick_size=0.05,
        )
        assert sig.setup_valid is False
        assert sig.rejection_reason == "No breakout detected"

    def test_reset(self):
        engine = IBBreakoutScalpEngine()
        engine._breakout_detected = True
        engine._breakout_direction = "LONG"
        engine._breakout_bar_index = 5
        engine.reset()
        assert engine._breakout_detected is False
        assert engine._breakout_direction == ""
        assert engine._breakout_bar_index == 0


# ======================================================================
# Parity: fixed evaluate_setup_a inputs (legacy shim vs quant module)
# ======================================================================

_SETUP_A_CASES = [
    dict(ib_state=_ib_state(is_complete=False), current_price=100.0, current_high=106.0,
         current_low=99.0, current_volume=5000, avg_volume=1000, cvd_slope_1m=5.0,
         bar_index=10, tick_size=0.05),
    dict(ib_state=_ib_state(ib_high=100.0, ib_low=100.0), current_price=100.0, current_high=101.0,
         current_low=99.0, current_volume=5000, avg_volume=1000, cvd_slope_1m=5.0,
         bar_index=10, tick_size=0.05),
    dict(ib_state=_ib_state(), current_price=105.1, current_high=106.0, current_low=104.0,
         current_volume=1000, avg_volume=1000, cvd_slope_1m=5.0, bar_index=10, tick_size=0.05),
    dict(ib_state=_ib_state(), current_price=105.1, current_high=106.0, current_low=104.0,
         current_volume=5000, avg_volume=1000, cvd_slope_1m=-1.0, bar_index=10, tick_size=0.05),
    dict(ib_state=_ib_state(), current_price=105.1, current_high=106.0, current_low=104.0,
         current_volume=5000, avg_volume=1000, cvd_slope_1m=5.0, bar_index=10, tick_size=0.05),
    dict(ib_state=_ib_state(), current_price=94.9, current_high=95.5, current_low=94.0,
         current_volume=5000, avg_volume=1000, cvd_slope_1m=-5.0, bar_index=10, tick_size=0.05),
    dict(ib_state=_ib_state(), current_price=100.0, current_high=104.0, current_low=96.0,
         current_volume=5000, avg_volume=1000, cvd_slope_1m=5.0, bar_index=10, tick_size=0.05),
]


def test_ib_scalp_parity_setup_a():
    legacy = LegacyIBBreakoutScalpEngine()
    new = IBBreakoutScalpEngine()
    for kwargs in _SETUP_A_CASES:
        assert_parity(
            lambda: legacy.evaluate_setup_a(**kwargs),
            lambda: new.evaluate_setup_a(**kwargs),
        )
