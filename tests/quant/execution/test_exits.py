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
