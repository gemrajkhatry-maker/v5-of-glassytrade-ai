"""_decide must abort the entry when register_open rejects (race backstop)."""

from unittest.mock import MagicMock

from quant.bars import Bar
from quant.decision.signal_builder import Signal
from quant.runtime import QuantEngine


class _ApprovedDecision:
    def __init__(self, signal):
        self.approved = True
        self.signal = signal
        self.reason = "test"
        self.phase = ""
        self.gate_results = ()
        self.block_reasons = ()
        self.model_label = ""


def test_decide_aborts_when_register_open_rejects():
    pra = MagicMock()
    pra.can_accept.return_value = (True, "")
    pra.register_open.return_value = False  # another engine won the race

    eng = QuantEngine(gateway=MagicMock(), symbol="TEST FUT", portfolio_risk=pra)
    sig = Signal(type="LONG", reason="t", entry=100.0, sl=95.0, tp=110.0, rr=2.0,
                 model_label="t", symbol="TEST FUT", timestamp="t0")
    stub = MagicMock()
    stub.should_enter.return_value = _ApprovedDecision(sig)
    eng._strategy = stub

    bar = Bar(time="t300", open=99.0, high=101.0, low=98.5, close=100.0, volume=10.0)
    eng._decide({}, bar)

    pra.register_open.assert_called_once()
    assert eng.state.position is None, "entry proceeded despite register_open rejection"


def test_manage_exit_partial_releases_proportional_portfolio_risk():
    from quant.execution.exits import ExitDecision

    eng = QuantEngine(gateway=MagicMock(), symbol="TEST FUT")
    pra = MagicMock()
    eng._portfolio_risk = pra

    sig = Signal(type="LONG", reason="t", entry=100.0, sl=99.0, tp=102.0, rr=2.0,
                 model_label="t", symbol="TEST FUT", timestamp="t0")
    position = eng._oms.submit(sig, 100.0)
    from quant.transitions import _position_to_state
    eng.state = eng.state.with_position(_position_to_state(position))
    eng._get_position_manager().current_position = position
    eng._open_trade_risk = 500.0

    exits = MagicMock()
    exits.evaluate.return_value = ExitDecision(True, "TP1", 102.0, partial_fraction=0.5)
    exits.is_risk_free.return_value = False
    exits.stop_state.return_value = (None, None)
    eng._exits = exits

    bar = Bar(time="t300", open=100.0, high=102.5, low=99.5, close=102.0, volume=10.0)
    eng._manage_exit({}, bar)

    pra.record_close.assert_called_once()
    released, pnl = pra.record_close.call_args[0]
    assert abs(released - 250.0) < 1e-6, f"expected half of 500 released, got {released}"
    assert pnl > 0
    assert eng.state.position is not None  # runner remains
    assert abs(eng._open_trade_risk - 250.0) < 1e-6


def test_manage_exit_full_close_books_pyramid_pnl_to_portfolio():
    from quant.execution.exits import ExitDecision

    eng = QuantEngine(gateway=MagicMock(), symbol="TEST FUT")
    pra = MagicMock()
    eng._portfolio_risk = pra

    sig = Signal(type="LONG", reason="t", entry=100.0, sl=99.0, tp=102.0, rr=2.0,
                 model_label="t", symbol="TEST FUT", timestamp="t0")
    position = eng._oms.submit(sig, 100.0)
    from quant.transitions import _position_to_state
    eng.state = eng.state.with_position(_position_to_state(position))
    eng._get_position_manager().current_position = position
    eng._open_trade_risk = 500.0
    pyramid = eng._oms.add_pyramid(base=position, entry_price=101.0,
                                   new_sl=100.0, size=50.0, time="t1", pyramid_level=1)

    exits = MagicMock()
    exits.evaluate.return_value = ExitDecision(True, "TRAIL", 103.0)
    exits.stop_state.return_value = (None, None)
    # Set exits on the PositionManager (not the engine)
    pm = eng._get_position_manager()
    pm._exits = exits
    pm.pyramid_positions = [pyramid]

    bar = Bar(time="t300", open=102.0, high=103.5, low=101.5, close=103.0, volume=10.0)
    eng._manage_exit({}, bar)

    pnls = [c.args[1] for c in pra.record_close.call_args_list]
    assert any(abs(p - (103.0 - 101.0) * 50.0) < 1e-6 for p in pnls), \
        f"pyramid pnl not booked to portfolio authority: {pnls}"
    assert eng.state.position is None
