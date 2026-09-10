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


def test_bar_path_books_trail_not_sl_when_trail_is_tighter():
    """D-13: the bar path checked the raw frozen SL before the merged
    trail/breakeven stop, so the same breach booked SL at the worse price on
    the bar path and TRAIL on the tick path."""
    from quant.decision.signal_builder import Signal
    from quant.execution.exits import ExitEngine, _Trail
    from quant.execution.order import Order, Position

    sig = Signal(type="LONG", reason="r", entry=100.0, sl=95.0, tp=110.0,
                 rr=2.0, model_label="Triple-A", symbol="SYM", timestamp="t0")
    pos = Position(order=Order(sig, 10.0), open_price=100.0, open_time="t0", size=10.0)

    eng = ExitEngine()
    # Arm a trailing stop well above the raw SL.
    eng._trail[pos._id] = _Trail(active=True, stop=99.0)

    # Bar sweeps below BOTH the trail (99.0) and the raw SL (95.0).
    d = eng.evaluate(pos, bar_close=94.0, bar_high=101.0, bar_low=94.0, bar_index=5)

    assert d.should_exit is True
    assert d.reason == "TRAIL", f"expected TRAIL, got {d.reason} at {d.close_price}"
    assert d.close_price == 99.0
    assert eng.last_exit_source == "DETERMINISTIC:TRAIL"


def test_tick_and_bar_paths_agree_on_the_breached_stop():
    """The bar path and the tick path must book the same reason and price."""
    from quant.decision.signal_builder import Signal
    from quant.execution.exits import ExitEngine, _Trail
    from quant.execution.order import Order, Position
    from quant.execution.oms import PaperOMS
    from quant.execution.risk import SessionRisk
    from quant.position_manager import PositionManager

    def _pos(pid):
        sig = Signal(type="LONG", reason="r", entry=100.0, sl=95.0, tp=110.0,
                     rr=2.0, model_label="Triple-A", symbol="SYM", timestamp="t0")
        return Position(order=Order(sig, 10.0), open_price=100.0,
                        open_time="t0", size=10.0, _id=pid)

    eng_bar = ExitEngine()
    pos_bar = _pos("bar")
    eng_bar._trail[pos_bar._id] = _Trail(active=True, stop=99.0)
    d_bar = eng_bar.evaluate(pos_bar, bar_close=94.0, bar_high=101.0,
                             bar_low=94.0, bar_index=5)

    eng_tick = ExitEngine()
    pos_tick = _pos("tick")
    eng_tick._trail[pos_tick._id] = _Trail(active=True, stop=99.0)
    pm = PositionManager(oms=PaperOMS(lot_size=1.0), exits=eng_tick,
                         risk=SessionRisk(storage=None, symbol="SYM"),
                         emit_fn=lambda e: None, symbol="SYM", market="NSE",
                         contract_expiry=None, tick_size=0.05)
    pm.manage_tick_exit(pos_tick, 94.0, "t1")
    tick_reason = pm._exits.last_exit_source

    assert d_bar.reason == "TRAIL"
    assert tick_reason == "DETERMINISTIC:TRAIL"


def test_protective_stop_wins_when_one_bar_satisfies_both():
    """D-13 follow-up: the Rule-2 reorder made the tightest protective stop
    outrank the Rule-4 TP tiers inside a SINGLE bar. Pin that intent (it
    matches the tick path, which checks the merged stop first): a bar that
    satisfies both books the PROTECTIVE reason, at the protective price."""
    from quant.decision.signal_builder import Signal
    from quant.execution.exits import ExitEngine, _Trail
    from quant.execution.order import Order, Position

    sig = Signal(type="LONG", reason="r", entry=100.0, sl=95.0, tp=110.0,
                 rr=2.0, model_label="Triple-A", symbol="SYM", timestamp="t0")
    pos = Position(order=Order(sig, 10.0), open_price=100.0, open_time="t0", size=10.0)
    eng = ExitEngine()
    eng._trail[pos._id] = _Trail(active=True, stop=100.8)

    # One bar: high 111 reaches TP1 (110) AND low 99.9 breaches the trail.
    d = eng.evaluate(pos, bar_close=100.0, bar_high=111.0, bar_low=99.9, bar_index=5)
    assert d.should_exit and d.reason == "TRAIL"
    assert d.close_price == 100.8
    assert d.partial_fraction is None       # full close, not a TP1 partial
    assert d.trail_stop == 100.8

    # Same shape with a pre-armed breakeven floor and no trail.
    pos2 = Position(order=Order(sig, 10.0), open_price=100.0, open_time="t0", size=10.0)
    eng2 = ExitEngine()
    eng2._breakeven[pos2._id] = 100.0
    d2 = eng2.evaluate(pos2, bar_close=100.0, bar_high=121.0, bar_low=99.0, bar_index=5)
    assert d2.should_exit and d2.reason == "BREAKEVEN"
    assert d2.close_price == 100.0
    assert d2.partial_fraction is None
    # A breakeven floor is not a trailing stop: the label stays clean.
    assert d2.trail_stop is None


def test_tp_still_books_when_bar_does_not_breach_the_protective_stop():
    """Regression pin: reaching TP without breaching the protective stop must
    still book the tier (the Rule-2 reorder did not suppress Rule 4)."""
    from quant.decision.signal_builder import Signal
    from quant.execution.exits import ExitEngine
    from quant.execution.order import Order, Position

    sig = Signal(type="LONG", reason="r", entry=100.0, sl=95.0, tp=110.0,
                 rr=2.0, model_label="Triple-A", symbol="SYM", timestamp="t0")
    pos = Position(order=Order(sig, 10.0), open_price=100.0, open_time="t0", size=10.0)
    eng = ExitEngine()
    eng._breakeven[pos._id] = 100.0          # armed floor, low stays above it

    d = eng.evaluate(pos, bar_close=110.0, bar_high=111.0, bar_low=103.0, bar_index=5)
    assert d.should_exit and d.reason == "TP1"
    assert d.close_price == 110.0
    assert d.partial_fraction == 0.5
