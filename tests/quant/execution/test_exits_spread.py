from quant.decision.signal_builder import Signal
from quant.execution.order import Order, Position
from quant.execution.exits import ExitEngine
def _dto():
    return {}


def _position(size=10, sl=99.0, tp=102.0, entry=100.0):
    sig = Signal(type="LONG", reason="r", entry=entry, sl=sl, tp=tp, rr=2.0,
                 model_label="Triple-A", symbol="SYM", timestamp="t0")
    return Position(order=Order(sig, abs(size)), open_price=entry, open_time="t0", size=size)


def test_spread_blowout_exits_long():
    d = ExitEngine().evaluate(
        _position(), bar_close=100.5, bar_index=5, best_bid=98.5, best_ask=102.5
    )
    assert d.should_exit and d.reason == "SPREAD_BLOWOUT"
    assert d.close_price == 100.5


def test_no_blowout_without_depth():
    d = ExitEngine().evaluate(
        _position(), bar_close=100.5, bar_index=5, best_bid=None, best_ask=None
    )
    assert not d.should_exit
    d = ExitEngine().evaluate(
        _position(), bar_close=100.5, bar_index=5, best_bid=98.5, best_ask=None
    )
    assert not d.should_exit


def test_no_blowout_below_threshold():
    d = ExitEngine().evaluate(
        _position(), bar_close=100.5, bar_index=5, best_bid=100.0, best_ask=101.0
    )
    assert not d.should_exit
