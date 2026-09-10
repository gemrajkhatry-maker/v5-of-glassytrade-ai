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
