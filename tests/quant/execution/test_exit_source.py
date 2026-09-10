from quant.decision.signal_builder import Signal
from quant.execution.exits import ExitEngine
from quant.execution.order import Order, Position


def _position(size=10, sl=99.0, tp=102.0, entry=100.0):
    sig = Signal(type="LONG", reason="r", entry=entry, sl=sl, tp=tp, rr=2.0,
                 model_label="Triple-A", symbol="SYM", timestamp="t0")
    return Position(order=Order(sig, abs(size)), open_price=entry, open_time="t0", size=size)


def test_exit_source_initially_empty():
    eng = ExitEngine()
    assert eng.last_exit_source == ""


def test_exit_source_labels_deterministic_sl():
    eng = ExitEngine()
    d = eng.evaluate(_position(), bar_close=99.0, bar_index=5)
    assert d.should_exit and d.reason == "SL"
    assert eng.last_exit_source == "DETERMINISTIC:SL"
