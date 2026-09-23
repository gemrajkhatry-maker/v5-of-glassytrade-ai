# tests/quant/execution/test_terminal_tp_regime.py
"""Wave 4 — regime-aware terminals, BAR path: check_take_profit_tiers must
collapse the Rule-4 ladder to a terminal full close (reason="TP") for
VA_FADE (mean-reversion) signals, while every other/legacy type keeps the
tiered ladder. Derived from position.order.signal — no signature changes."""

import pytest

from quant.decision.signal_builder import Signal
from quant.execution.exit_checks import check_take_profit_tiers, tp2_level
from quant.execution.order import Order, Position


def _signal(model_label):
    return Signal(
        type="LONG", reason="test", entry=100.0, sl=90.0, tp=120.0,
        rr=2.0, model_label=model_label, symbol="TEST", timestamp="t",
    )


def _pos(model_label):
    return Position(order=Order(_signal(model_label), 4.0),
                    open_price=100.0, open_time="t0", size=4.0)


def test_bar_path_fade_tp_touch_is_terminal_full_close():
    dec, tier = check_take_profit_tiers(_pos("VA_Fade"), high=120.0, low=100.5,
                                        tp_tier=0, entry=100.0)
    assert dec is not None and dec.should_exit
    assert dec.reason == "TP"                     # terminal, not TP1 partial
    assert not getattr(dec, "partial_fraction", None)


def test_bar_path_fade_no_touch_stays_open():
    dec, tier = check_take_profit_tiers(_pos("VA_Fade"), high=110.0, low=100.5,
                                        tp_tier=0, entry=100.0)
    assert dec is None and tier == 0              # untouched -> no exit


def test_bar_path_legacy_signal_still_ladders():
    """Regression pin: absent/legacy labels keep the exact Rule-4 ladder."""
    pos = _pos("Triple-A")
    dec, tier = check_take_profit_tiers(pos, high=120.0, low=100.5,
                                        tp_tier=0, entry=100.0)
    assert dec.reason == "TP1" and dec.partial_fraction == 0.5 and tier == 1

    dec, tier = check_take_profit_tiers(pos, high=140.0, low=100.5,
                                        tp_tier=1, entry=100.0)
    assert dec.reason == "TP2" and tier == 2
    assert dec.close_price == pytest.approx(tp2_level(100.0, 120.0))
