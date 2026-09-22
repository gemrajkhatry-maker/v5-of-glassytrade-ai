from quant.decision.signal_builder import Signal
from quant.execution.exits import ExitEngine
from quant.execution.order import Order, Position


def _position(size=10, sl=99.0, tp=102.0, entry=100.0):
    sig = Signal(type="LONG", reason="r", entry=entry, sl=sl, tp=tp, rr=2.0,
                 model_label="Triple-A", symbol="SYM", timestamp="t0")
    return Position(order=Order(sig, abs(size)), open_price=entry, open_time="t0", size=size)


def test_manage_exit_prefers_snapshot_market_state_and_vwap():
    from quant.amt.snapshot import AnalysisSnapshot
    from quant.contracts.value_objects import AMTResult

    pm = _mk_pm()
    pos = _position()
    pm.current_position = pos
    snap = AnalysisSnapshot(
        result=AMTResult(
            market_state="DEAD", poc=100.0, value_area_high=101.0, value_area_low=99.0,
            session_vwap=100.0,
        ),
        asof_time="t",
    )
    bar = type("Bar", (), {"time": "2026-08-24T10:01:00+05:30", "close": 100.0, "high": 100.5, "low": 99.5, "open": 100.0})()
    remaining = pm.manage_exit(
        {"marketState": "BALANCED", "sessionVwap": 0.0},
        bar,
        pos,
        bar_index=2,
        entry_bar_index=1,
        entry_time_epoch=0.0,
        snapshot=snap,
    )
    assert remaining is None
    assert pm._exits.last_exit_source == "DETERMINISTIC:DEAD_MARKET"


def test_exit_source_initially_empty():
    eng = ExitEngine()
    assert eng.last_exit_source == ""


def test_exit_source_labels_deterministic_sl():
    eng = ExitEngine()
    d = eng.evaluate(_position(), bar_close=99.0, bar_index=5)
    assert d.should_exit and d.reason == "SL"
    assert eng.last_exit_source == "DETERMINISTIC:SL"


def _mk_pm(events=None):
    from quant.execution.oms import PaperOMS
    from quant.execution.risk import SessionRisk
    from quant.position_manager import PositionManager

    return PositionManager(
        oms=PaperOMS(lot_size=1.0), exits=ExitEngine(),
        risk=SessionRisk(storage=None, symbol="SYM"),
        emit_fn=(events if events is not None else []).append,
        symbol="SYM", market="NSE", contract_expiry=None, tick_size=0.05,
    )


def test_full_close_stamps_source_when_engine_did_not_evaluate():
    """Thesis flip / EOD closes carry their own ExitDecision; without a stamp
    the close log would report a stale source from an earlier bar."""
    from quant.execution.exits import ExitDecision

    pm = _mk_pm()
    pos = _position()
    pm._exits.last_exit_source = "DETERMINISTIC:SL"  # stale, from a prior bar

    pm._execute_full_close(pos, ExitDecision(True, "OPPOSING_SIGNAL", 100.0), "t1")

    assert pm._exits.last_exit_source == "DETERMINISTIC:OPPOSING_SIGNAL"


def test_full_close_preserves_engine_sourced_label():
    """A genuine ExitEngine-sourced close keeps its TIMESFM_RISK_AUTHORITY label."""
    from quant.execution.exits import ExitDecision

    pm = _mk_pm()
    pos = _position()
    pm._exits.last_exit_source = "TIMESFM_RISK_AUTHORITY:VAR_STOP"

    pm._execute_full_close(pos, ExitDecision(True, "VAR_STOP", 100.0), "t1")

    assert pm._exits.last_exit_source == "TIMESFM_RISK_AUTHORITY:VAR_STOP"


def test_session_budget_multiplier_always_one_without_authority():
    """No TimesFM risk authority seam — multiplier stays at the constant 1.0."""
    eng = ExitEngine()
    assert eng.session_budget_multiplier() == 1.0


def test_displayed_stop_is_the_enforced_stop_after_a_ratchet():
    """D-7(c): the portfolio row must show the stop ExitEngine will enforce,
    not the stop originally submitted. Folding a StopMoved ratchet through
    project_state must move the displayed stopLoss."""
    from quant.events import StopMoved
    from quant.state import project_state
    from quant.state_machine import EngineState, PositionState
    from quant.transitions import apply_event

    # Long entered at 100 with submitted SL 99.0.
    state = EngineState(symbol="SYM").with_position(
        PositionState(id="p1", entry=100.0, size=10.0, sl=99.0, tp=103.0, side="LONG")
    )
    displayed_before = project_state(state).portfolio["positions"][0]["stopLoss"]
    assert displayed_before == 99.0

    # The engine ratchets the enforced stop to breakeven; the row must follow.
    state = apply_event(state, StopMoved(symbol="SYM", time="t1", old_sl=99.0,
                                         new_sl=100.5, reason="TRAIL_RATCHET"))
    displayed_after = project_state(state).portfolio["positions"][0]["stopLoss"]
    assert displayed_after == 100.5
