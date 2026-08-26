import pytest

from quant.decision.signal_builder import Signal
from quant.execution.order import Order, Position
from quant.execution.exits import ExitEngine


def _position(size=10, sl=99.0, tp=102.0, entry=100.0):
    sig = Signal(type="LONG", reason="r", entry=entry, sl=sl, tp=tp, rr=2.0,
                 model_label="Triple-A", symbol="SYM", timestamp="t0")
    return Position(order=Order(sig, abs(size)), open_price=entry, open_time="t0", size=size)


def _short_position(size=-10, sl=101.0, tp=98.0, entry=100.0):
    sig = Signal(type="SHORT", reason="r", entry=entry, sl=sl, tp=tp, rr=2.0,
                 model_label="Triple-A", symbol="SYM", timestamp="t0")
    return Position(order=Order(sig, abs(size)), open_price=entry, open_time="t0", size=size)


def _dto(cvd_slope=0.0):
    return {"cvdSlope": cvd_slope}

def test_sl_hit():
    d = ExitEngine().evaluate(_position(), bar_close=99.0, bar_index=5)
    assert d.should_exit and d.reason == "SL" and d.close_price == 99.0


def test_tp_hit():
    """First TP touch is TP1 — a 50% partial per spec §13.3, not a full close."""
    d = ExitEngine().evaluate(_position(), bar_close=102.0, bar_index=5)
    assert d.should_exit and d.reason == "TP1" and d.partial_fraction == 0.5


def test_tp2_hit_after_tp1_on_same_position_id():
    engine = ExitEngine()
    pos = _position()
    d1 = engine.evaluate(pos, bar_close=102.0, bar_index=5)
    assert d1.reason == "TP1"
    # Same position._id (as close_partial preserves it) reaching 2x the R distance -> TP2.
    d2 = engine.evaluate(pos, bar_close=104.5, bar_index=6, bar_high=105.0)
    assert d2.should_exit and d2.reason == "TP2" and d2.partial_fraction == 0.5


def test_runner_survives_between_tp1_and_tp2():
    engine = ExitEngine()
    pos = _position()
    engine.evaluate(pos, bar_close=102.0, bar_index=5)  # TP1 fires, tier=1
    d = engine.evaluate(pos, bar_close=102.5, bar_index=6)  # short of TP2 (104.0)
    assert not d.should_exit


def test_time_stop():
    d = ExitEngine(time_stop_bars=10).evaluate(_position(), bar_close=100.5, bar_index=12)
    assert d.should_exit and d.reason == "TIME"


def test_cvd_kill_long():
    d = ExitEngine(cvd_kill_threshold=0.0).evaluate(_position(), bar_close=100.5, amt_dto=_dto(cvd_slope=-8.0), bar_index=5)
    assert d.should_exit and d.reason == "CVD_KILL"


def test_no_exit_in_range():
    d = ExitEngine(time_stop_bars=30).evaluate(_position(), bar_close=100.5, bar_index=5)
    assert not d.should_exit


def test_cvd_kill_requires_adverse_threshold():
    long_pos = _position(size=10)
    short_pos = _short_position()
    engine = ExitEngine(cvd_kill_threshold=1.0)
    d = engine.evaluate(long_pos, bar_close=100.5, amt_dto=_dto(cvd_slope=-0.001), bar_index=5)
    assert not d.should_exit
    d = engine.evaluate(long_pos, bar_close=100.5, amt_dto=_dto(cvd_slope=-2.0), bar_index=5)
    assert d.should_exit and d.reason == "CVD_KILL"
    d = engine.evaluate(long_pos, bar_close=100.5, amt_dto=_dto(cvd_slope=+2.0), bar_index=5)
    assert not d.should_exit
    d = engine.evaluate(short_pos, bar_close=100.5, amt_dto=_dto(cvd_slope=+0.001), bar_index=5)
    assert not d.should_exit
    d = engine.evaluate(short_pos, bar_close=100.5, amt_dto=_dto(cvd_slope=+2.0), bar_index=5)
    assert d.should_exit and d.reason == "CVD_KILL"
    d = engine.evaluate(short_pos, bar_close=100.5, amt_dto=_dto(cvd_slope=-2.0), bar_index=5)
    assert not d.should_exit


def test_cvd_kill_disabled_by_default():
    d = ExitEngine().evaluate(_position(), bar_close=100.5, amt_dto=_dto(cvd_slope=-8.0), bar_index=5)
    assert not d.should_exit


def test_intrabar_sl_hit_wins_over_tp():
    d = ExitEngine().evaluate(_position(), bar_close=101.0, bar_index=5, bar_low=98.0, bar_high=103.0)
    assert d.should_exit and d.reason == "SL" and d.close_price == 99.0


def test_intrabar_tp_when_no_sl_pierce():
    d = ExitEngine().evaluate(_position(), bar_close=101.0, bar_index=5, bar_low=99.5, bar_high=103.0)
    assert d.should_exit and d.reason == "TP1"


def test_dead_market_exits_at_close():
    from quant.contracts.enums import MarketState

    d = ExitEngine().evaluate(
        _position(), market_state=MarketState.DEAD, bar_close=100.5, bar_index=5,
    )
    assert d.should_exit and d.reason == "DEAD_MARKET" and d.close_price == 100.5


# ---------------------------------------------------------------------------
# VWAP-aware exits
# ---------------------------------------------------------------------------

def test_vwap_drift_long_exit():
    """LONG drifting 6%+ below VWAP with <1R profit triggers VWAP_DRIFT."""
    pos = _position(entry=100.0, sl=99.0, tp=102.0)  # risk=1.0
    # close at 97.0 = 3.0 below entry, 3.0 below VWAP=100.0 → 3% drift = 6%×entry
    # profit = 97-100 = -3 → negative, won't trigger (need 0 < profit < risk)
    # Actually we need profit > 0 and < risk: entry=100, close=100.5, VWAP=103
    # drift = |100.5-103|/100 = 2.5%, need >6%
    pos2 = _position(entry=100.0, sl=99.0, tp=102.0)
    # Close at 100.3, VWAP at 107 → drift = |100.3-107|/100 = 6.7% > 6%
    # profit = 0.3, risk = 1.0 → 0 < profit < risk ✓
    d = ExitEngine().evaluate(pos2, bar_close=100.3, session_vwap=107.0, bar_index=5)
    assert d.should_exit and d.reason == "VWAP_DRIFT"


def test_vwap_drift_short_exit():
    """SHORT drifting 6%+ above VWAP with <1R profit triggers VWAP_DRIFT."""
    pos = _short_position(entry=100.0, sl=101.0, tp=98.0)  # risk=1.0
    # close at 99.7, VWAP at 93 → drift = |99.7-93|/100 = 6.7% > 6%
    # profit = 100-99.7 = 0.3, risk = 1.0 → 0 < profit < risk ✓
    d = ExitEngine().evaluate(pos, bar_close=99.7, session_vwap=93.0, bar_index=5)
    assert d.should_exit and d.reason == "VWAP_DRIFT"


def test_vwap_drift_no_exit_when_profit_above_risk():
    """VWAP_DRIFT only fires when profit < 1R — above 1R the trail manages it."""
    pos = _position(entry=100.0, sl=99.0, tp=102.0)  # risk=1.0
    # close at 101.5 = 1.5R profit → trail handles, not VWAP_DRIFT
    d = ExitEngine().evaluate(pos, bar_close=101.5, session_vwap=108.0, bar_index=5)
    assert not d.should_exit or d.reason != "VWAP_DRIFT"


def test_vwap_drift_no_exit_when_favorable_side():
    """LONG above VWAP = favorable, no drift exit."""
    pos = _position(entry=100.0, sl=99.0, tp=102.0)
    d = ExitEngine().evaluate(pos, bar_close=100.3, session_vwap=93.0, bar_index=5)
    assert not d.should_exit


def test_vwap_tightens_trail_on_adverse_drift():
    """When price drifts 3%+ below VWAP against LONG, trailing tightens to 50%.

    Verifies the tightened trail fires BEFORE the normal trail would have.
    Normal giveback=0.20 at profit=2.0 → trail=101.6
    Tightened giveback=0.10 at profit=2.0 → trail=101.8
    Bar with low=101.75 → tightened trail fires, normal would not.
    """
    engine = ExitEngine(trail_giveback_pct=0.20)
    pos = _position(entry=100.0, sl=99.0, tp=104.0)  # risk=1.0
    # Bar 1: reach 2R (close=102.0) — trail arms at 101.6 (normal giveback)
    d1 = engine.evaluate(pos, bar_close=102.0, bar_index=10)
    assert not d1.should_exit
    # Bar 2: close=102.0, bar_low=101.75, VWAP=106 → drift = 4% below VWAP
    # Tightened: trail = 102.0 - 0.10*2.0 = 101.8 → low=101.75 < 101.8 → TRAIL fires
    d2 = engine.evaluate(pos, bar_close=102.0, bar_index=11, bar_low=101.75, session_vwap=106.0)
    assert d2.should_exit and d2.reason == "TRAIL"


def test_vwap_drift_requires_positive_vwap():
    """session_vwap=0 disables VWAP drift checks."""
    pos = _position(entry=100.0, sl=99.0, tp=102.0)
    d = ExitEngine().evaluate(pos, bar_close=100.3, session_vwap=0.0, bar_index=5)
    assert not d.should_exit


# ---------------------------------------------------------------------------
# StopMoved audit trail (stop_state accessor + manage_exit emission)
# ---------------------------------------------------------------------------

def test_stop_state_returns_none_before_any_move():
    """A fresh position has no BE floor and no active trail."""
    engine = ExitEngine()
    pos = _position(entry=100.0, sl=98.0, tp=102.0)
    be_floor, trail_stop = engine.stop_state(pos)
    assert be_floor is None
    assert trail_stop is None


def test_breakeven_arm_is_reported_by_stop_state():
    """TP1 arms the BE floor at entry; stop_state reflects it."""
    engine = ExitEngine()
    pos = _position(entry=100.0, sl=98.0, tp=102.0)  # risk = 2.0
    d = engine.evaluate(pos, bar_close=102.0, bar_index=5, bar_high=102.0)
    assert d.should_exit and d.reason == "TP1"
    be_floor, trail_stop = engine.stop_state(pos)
    assert be_floor == 100.0          # BE floor armed at entry price (TP1 path)
    assert trail_stop is None


def test_breakeven_arms_at_08r_profit():
    """BE floor also arms once profit reaches 0.8R via the trailing path —
    this is existing ExitEngine behavior, so stop_state must report it."""
    engine = ExitEngine()
    pos = _position(entry=100.0, sl=98.0, tp=104.0)  # risk = 2.0; 0.8R = 1.6
    d = engine.evaluate(pos, bar_close=101.7, bar_index=5, bar_high=101.7, bar_low=101.5)
    assert not d.should_exit
    be_floor, trail_stop = engine.stop_state(pos)
    assert be_floor == 100.0          # BE floor armed at entry price (0.8R path)
    assert trail_stop is None


def test_trail_ratchet_visible_in_stop_state():
    """Trail arms at 1R then ratchets up; stop_state tracks each level."""
    engine = ExitEngine()
    pos = _position(entry=100.0, sl=99.0, tp=120.0)  # risk = 1.0
    d1 = engine.evaluate(pos, _dto(), bar_index=10,
                         bar_high=102.0, bar_low=101.7, bar_close=102.0)
    assert not d1.should_exit
    be1, tr1 = engine.stop_state(pos)
    assert (be1, tr1) == (100.0, 101.6)   # 102 - 0.20 * 2.0
    d2 = engine.evaluate(pos, _dto(), bar_index=11,
                         bar_high=103.0, bar_low=102.7, bar_close=103.0)
    assert not d2.should_exit
    be2, tr2 = engine.stop_state(pos)
    assert (be2, tr2) == (100.0, 102.4)   # 103 - 0.20 * 3.0 — ratcheted
    assert tr2 > tr1


def test_stop_state_short_direction():
    """Trail stop for SHORT sits above price; BE floor still reported."""
    eng = ExitEngine()
    pos = _short_position(entry=100.0, sl=102.0, tp=96.0)  # risk = 2.0
    d = eng.evaluate(pos, bar_close=98.0, bar_index=5, bar_high=98.3, bar_low=98.0)
    assert not d.should_exit
    be_floor, trail_stop = eng.stop_state(pos)
    # BE arms at 0.8R (profit 2.0 >= 1.6); trail stop is the active trailing level.
    assert be_floor == 100.0
    assert trail_stop == pytest.approx(98.4)  # 98 + 0.20*2


def test_pop_trail_clears_stop_state():
    """Closing a position resets stop_state to (None, None)."""
    engine = ExitEngine()
    pos = _position(entry=100.0, sl=98.0, tp=104.0)
    engine.evaluate(pos, bar_close=102.0, bar_index=5, bar_high=102.0, bar_low=101.7)
    assert engine.stop_state(pos)[1] is not None
    engine.pop_trail(pos)
    be_floor, trail_stop = engine.stop_state(pos)
    assert be_floor is None and trail_stop is None


def test_stop_state_survives_tp_tier_transition():
    """stop_state remains valid across the TP1 -> runner -> TP2 sequence on the
    same position._id (tier exits return before the trailing rule, so the
    trail level armed by the survivor bar must persist through TP2)."""
    engine = ExitEngine()
    pos = _position(entry=100.0, sl=98.0, tp=104.0)  # risk = 2.0; TP2 = 108.0
    d1 = engine.evaluate(pos, bar_close=104.0, bar_index=5, bar_high=104.0)
    assert d1.should_exit and d1.reason == "TP1"     # BE armed, trail untouched
    assert engine.stop_state(pos) == (100.0, None)
    # Runner survives; trailing arms at 104.5 - 0.20 * 4.5 = 103.6.
    d2 = engine.evaluate(pos, bar_close=104.5, bar_index=6)
    assert not d2.should_exit
    assert engine.stop_state(pos)[1] == pytest.approx(103.6)
    # TP2 fires (high >= 108) before the trailing rule runs — state preserved.
    d3 = engine.evaluate(pos, bar_close=105.0, bar_index=7, bar_high=108.5)
    assert d3.should_exit and d3.reason == "TP2"
    be_floor, trail_stop = engine.stop_state(pos)
    assert be_floor == 100.0
    assert trail_stop == pytest.approx(103.6)


def _mk_pm(emit):
    from quant.execution.oms import PaperOMS
    from quant.execution.risk import SessionRisk
    from quant.position_manager import PositionManager

    return PositionManager(
        oms=PaperOMS(lot_size=1.0), exits=ExitEngine(),
        risk=SessionRisk(storage=None, symbol="S"),
        emit_fn=emit.append, symbol="S", market="NSE",
        contract_expiry=None, tick_size=0.05,
    )


def _bar(time, open_, high, low, close):
    from quant.bars import Bar

    return Bar(time=time, open=open_, high=high, low=low, close=close, volume=100)


def test_manage_exit_emits_stop_moved_events():
    """BE arm and trail ratchet journal a StopMoved each, at the moment of change."""
    from quant.events import StopMoved

    pos = _position(entry=100.0, sl=99.0, tp=120.0)
    events = []
    pm = _mk_pm(events)

    # 0.9R close arms BE at entry (kept clear of the exact 0.8R float boundary).
    r1 = pm.manage_exit({}, _bar("2026-08-24T10:01:00+05:30", 100, 101.1, 100.5, 100.9),
                        pos, bar_index=3, entry_bar_index=1, entry_time_epoch=0.0)
    assert r1 is pos  # survives — no exit decision, only a stop move
    moved = [e for e in events if isinstance(e, StopMoved)]
    assert len(moved) == 1
    assert moved[0].reason == "BREAKEVEN_ARMED"
    assert moved[0].old_sl == 99.0 and moved[0].new_sl == 100.0
    assert moved[0].symbol == "S"

    r2 = pm.manage_exit({}, _bar("2026-08-24T10:02:00+05:30", 101, 102.2, 101.7, 102.0),
                        pos, bar_index=4, entry_bar_index=1, entry_time_epoch=0.0)
    assert r2 is pos
    moved = [e for e in events if isinstance(e, StopMoved)]
    assert len(moved) == 2
    assert moved[1].reason == "TRAIL_RATCHET"
    assert moved[1].old_sl == 99.0 and moved[1].new_sl == 101.6  # prev None -> sig sl


def test_no_stop_moved_when_bar_exits():
    """StopMoved never fires on a FULL-close bar: no position survives, and
    the close is journaled through its own PositionClosed chain instead."""
    from quant.events import PositionClosed, StopMoved

    pos = _position(entry=100.0, sl=99.0, tp=120.0)
    events = []
    pm = _mk_pm(events)

    # Arm BE (0.9R), then arm trail at 101.6.
    pm.manage_exit({}, _bar("2026-08-24T10:01:00+05:30", 100, 101.1, 100.5, 100.9),
                   pos, bar_index=3, entry_bar_index=1, entry_time_epoch=0.0)
    pm.manage_exit({}, _bar("2026-08-24T10:02:00+05:30", 101, 102.2, 101.7, 102.0),
                   pos, bar_index=4, entry_bar_index=1, entry_time_epoch=0.0)
    moved_before = [e for e in events if isinstance(e, StopMoved)]
    assert [m.reason for m in moved_before] == ["BREAKEVEN_ARMED", "TRAIL_RATCHET"]

    # Trail ratchets to 104.0 (105 - 0.20*5) and low pierces it: TRAIL exit.
    result = pm.manage_exit({}, _bar("2026-08-24T10:03:00+05:30", 102, 105.2, 103.9, 105.0),
                            pos, bar_index=5, entry_bar_index=1, entry_time_epoch=0.0)
    assert result is None
    closed = [e for e in events if isinstance(e, PositionClosed)]
    assert closed and closed[-1].fill.reason == "TRAIL"
    # The ratchet that fired WITH this bar's exit is not journaled as StopMoved.
    assert [e for e in events if isinstance(e, StopMoved)] == moved_before


def test_tp1_partial_exit_bar_journals_be_arm():
    """A TP1 bar arms the BE floor inside evaluate() AND reduces the position;
    the arm is still a stop move and must be journaled (controller ruling)."""
    from quant.events import PositionReduced, StopMoved

    pos = _position(entry=100.0, sl=98.0, tp=102.0)  # risk = 2.0
    events = []
    pm = _mk_pm(events)

    result = pm.manage_exit({}, _bar("2026-08-24T10:04:00+05:30", 101, 102, 100.9, 102.0),
                            pos, bar_index=6, entry_bar_index=1, entry_time_epoch=0.0)
    assert result is not None and abs(result.size) == 5  # runner survives
    reduced = [e for e in events if isinstance(e, PositionReduced)]
    assert reduced
    moved = [e for e in events if isinstance(e, StopMoved)]
    assert len(moved) == 1
    assert moved[0].reason == "BREAKEVEN_ARMED"
    assert moved[0].old_sl == 98.0 and moved[0].new_sl == 100.0
    # Journaled on the partial-exit path: after the reduction event chain.
    assert events.index(moved[0]) > events.index(reduced[0])


def test_manage_exit_emits_short_trail_ratchet():
    """SHORT mirror of the long emission test: the trail ratchets DOWNWARD,
    so TRAIL_RATCHET carries new_sl < old_sl."""
    from quant.events import StopMoved

    pos = _short_position(entry=100.0, sl=102.0, tp=80.0)  # risk = 2.0
    events = []
    pm = _mk_pm(events)

    # Bar 1: profit 1.8 >= 0.8R -> BE floor armed at entry.
    r1 = pm.manage_exit({}, _bar("2026-08-24T10:01:00+05:30", 99, 98.5, 98.0, 98.2),
                        pos, bar_index=3, entry_bar_index=1, entry_time_epoch=0.0)
    assert r1 is pos
    moved = [e for e in events if isinstance(e, StopMoved)]
    assert len(moved) == 1
    assert moved[0].reason == "BREAKEVEN_ARMED"
    assert moved[0].old_sl == 102.0 and moved[0].new_sl == 100.0

    # Bar 2: profit 2.5 >= 1R -> trail arms at 97.5 + 0.20*2.5 = 98.0.
    r2 = pm.manage_exit({}, _bar("2026-08-24T10:02:00+05:30", 98, 97.9, 97.0, 97.5),
                        pos, bar_index=4, entry_bar_index=1, entry_time_epoch=0.0)
    assert r2 is pos
    moved = [e for e in events if isinstance(e, StopMoved)]
    assert len(moved) == 2
    assert moved[1].reason == "TRAIL_RATCHET"
    assert moved[1].old_sl == 102.0 and moved[1].new_sl == 98.0  # prev None -> sig sl
    assert moved[1].new_sl < moved[1].old_sl
