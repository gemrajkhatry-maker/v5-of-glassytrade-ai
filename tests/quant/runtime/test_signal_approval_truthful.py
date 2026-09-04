# tests/quant/runtime/test_signal_approval_truthful.py
"""SignalApproved means "routed through the OMS" (contract in
quant/execution/ports.py). Observer engines and pre-submit vetoes must not
emit it. Exactly one emission per real submission, before PositionOpened."""

from dataclasses import dataclass
from unittest.mock import MagicMock

from quant.bars import Bar
from quant.decision.signal_builder import Signal
from quant.events import PositionOpened, SignalApproved
from quant.execution.order import Order, Position
from quant.runtime import QuantEngine


@dataclass
class _ApprovedDecision:
    signal: Signal
    approved: bool = True
    reason: str = "Triple-A"
    phase: str = ""
    gate_results: tuple = ()
    block_reasons: tuple = ()
    model_label: str = "t"


def _signal():
    return Signal(
        type="LONG", reason="t", entry=14.0, sl=13.0, tp=16.0, rr=2.0,
        model_label="t", symbol="TRUTH-CALL", timestamp="t0",
    )


def _engine(execution_enabled=True, can_accept=(True, "")):
    pra = MagicMock()
    pra.can_accept.return_value = can_accept
    pra.register_open.return_value = True
    eng = QuantEngine(
        gateway=MagicMock(),
        symbol="TRUTH-CALL",
        portfolio_risk=pra,
        execution_enabled=execution_enabled,
    )
    eng._oms = MagicMock()
    eng._oms.lot_size = 1
    # ponytail: EventStore checksum-serializes every event eagerly, so the
    # stubbed position must be a real Position — a MagicMock recurses there.
    eng._oms.submit.return_value = Position(
        order=Order(signal=_signal(), quantity=2.0),
        open_price=14.0,
        open_time="t300",
        size=2.0,
    )
    eng._risk = MagicMock()
    eng._risk.can_trade.return_value = (True, "")
    eng._risk.state.return_value = MagicMock(trades_today=0, equity=1_000_000)
    eng._risk.position_size.return_value = 2
    stub = MagicMock()
    stub.should_enter.return_value = _ApprovedDecision(_signal())
    eng._strategy = stub
    captured = []
    eng._bus.subscribe(SignalApproved, lambda e: captured.append(e))
    eng._bus.subscribe(PositionOpened, lambda e: captured.append(e))
    return eng, captured


def _bar(n):
    return Bar(time=f"t{300 + n}", open=14.0, high=14.2, low=13.9, close=14.0, volume=10.0)


def test_observer_engine_emits_no_approval():
    eng, captured = _engine(execution_enabled=False)
    eng._bar_index = 10
    eng._decide({}, _bar(0))
    assert captured == []
    eng._oms.submit.assert_not_called()


def test_sizing_zero_emits_no_approval():
    eng, captured = _engine()
    eng._risk.position_size.return_value = 0
    eng._bar_index = 10
    eng._decide({}, _bar(0))
    assert captured == []
    eng._oms.submit.assert_not_called()


def test_portfolio_reject_emits_no_approval():
    eng, captured = _engine(can_accept=(False, "concurrent root position: TRUTH-CALL active"))
    eng._bar_index = 10
    eng._decide({}, _bar(0))
    assert captured == []
    eng._oms.submit.assert_not_called()


def test_real_submission_emits_approval_before_position_opened():
    eng, captured = _engine()
    eng._bar_index = 10
    eng._decide({}, _bar(0))
    eng._oms.submit.assert_called_once()
    assert [type(e).__name__ for e in captured] == ["SignalApproved", "PositionOpened"]
