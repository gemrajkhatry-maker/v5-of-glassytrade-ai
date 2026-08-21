from quant.decision.signal_builder import Signal
from quant.execution.order import Order, Position
from quant.execution.exits import ExitEngine
def _position(size=10, sl=99.0, tp=1000.0, entry=100.0):
    # tp far away so TP never fires in these tests; risk = 1.0 (1R at 101).
    sig = Signal(type="LONG", reason="r", entry=entry, sl=sl, tp=tp, rr=2.0,
                 model_label="Triple-A", symbol="SYM", timestamp="t0")
    return Position(order=Order(sig, abs(size)), open_price=entry, open_time="t0", size=size)


def _short_position(size=-10, sl=101.0, tp=0.0, entry=100.0):
    sig = Signal(type="SHORT", reason="r", entry=entry, sl=sl, tp=tp, rr=2.0,
                 model_label="Triple-A", symbol="SYM", timestamp="t0")
    return Position(order=Order(sig, abs(size)), open_price=entry, open_time="t0", size=size)


def test_trailing_activates_at_1r_long():
    eng = ExitEngine()
    d = eng.evaluate(
        _position(), bar_close=102.0, bar_index=5, bar_high=102.0, bar_low=101.2
    )
    assert d.should_exit and d.reason == "TRAIL"
    assert d.trail_stop == 102.0 - 0.20 * 2.0


def test_trailing_never_widens_long():
    eng = ExitEngine()
    pos = _position()
    d = eng.evaluate(pos, bar_close=102.0, bar_index=5, bar_high=102.0, bar_low=101.7)
    assert not d.should_exit
    assert eng._trail[pos._id].stop == 101.60
    d = eng.evaluate(pos, bar_close=101.8, bar_index=6, bar_high=102.0, bar_low=101.59)
    assert d.should_exit and d.reason == "TRAIL"
    assert d.trail_stop == 101.60


def test_trailing_short():
    eng = ExitEngine()
    pos = _short_position()
    d = eng.evaluate(pos, bar_close=98.0, bar_index=5, bar_high=98.3, bar_low=98.0)
    assert not d.should_exit
    assert eng._trail[pos._id].stop == 98.0 + 0.20 * 2.0
    d = eng.evaluate(pos, bar_close=98.2, bar_index=6, bar_high=98.45, bar_low=98.0)
    assert d.should_exit and d.reason == "TRAIL"
    assert d.trail_stop == 98.40


def test_pop_trail_cleans_up():
    eng = ExitEngine()
    pos = _position()
    eng.evaluate(pos, bar_close=102.0, bar_index=5, bar_high=102.0, bar_low=101.7)
    assert pos._id in eng._trail
    eng.pop_trail(pos)
    assert pos._id not in eng._trail
