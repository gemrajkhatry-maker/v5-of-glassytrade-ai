"""Stage 4 contract: one ExitPolicy for tick and bar; is_risk_free requires profit."""

from __future__ import annotations

from quant.decision.signal_builder import Signal
from quant.execution.exits import ExitEngine
from quant.execution.order import Order, Position


def _pos(model_label="Triple-A", entry=100.0, sl=90.0, tp=120.0, size=4.0):
    sig = Signal(
        type="LONG", reason="t", entry=entry, sl=sl, tp=tp,
        rr=2.0, model_label=model_label, symbol="S", timestamp="t0",
    )
    return Position(order=Order(sig, size), open_price=entry, open_time="t0", size=size)


def test_is_risk_free_false_when_losing_with_be_armed():
    """CVD-armed BE floor on a losing mark must not unlock pyramiding."""
    eng = ExitEngine()
    pos = _pos()
    eng._breakeven[pos._id] = 100.0  # BE armed
    assert eng.is_risk_free(pos, mark=99.0) is False
    assert eng.is_risk_free(pos, mark=100.0) is True
    assert eng.is_risk_free(pos, mark=101.0) is True


def test_tick_and_bar_protective_stop_same_reason():
    eng = ExitEngine()
    pos = _pos(sl=95.0, tp=120.0)
    eng.restore_stop_state(pos, trail_stop=98.0)
    # Price breaches trail (98) and is still below TP — both paths book TRAIL.
    bar_dec = eng.evaluate(
        pos, bar_close=97.0, bar_high=99.0, bar_low=97.0, bar_index=1,
    )
    tick_dec = eng.evaluate_price_event(
        pos, last=97.0, high=97.0, low=97.0, source="tick",
    )
    assert bar_dec.should_exit and tick_dec.should_exit
    assert bar_dec.reason == tick_dec.reason == "TRAIL"
