# tests/quant/runtime/test_signal_approval_truthful.py
"""SignalApproved means "routed through the OMS" (contract in
quant/execution/ports.py). Observer engines and pre-submit vetoes must not
emit it. Exactly one emission per real submission, before PositionOpened."""

from dataclasses import dataclass, field
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
    metadata: dict = field(default_factory=dict)


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
    eng._oms.is_live = False
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
    from quant.execution.risk import RiskState
    eng._risk.state.return_value = RiskState(
        daily_pnl=0.0, consecutive_losses=0, halted=False, halt_reason="",
        risk_per_trade_pct=0.005, trades_today=0, equity=1_000_000,
    )
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
    sig = _signal()
    eng._strategy.should_enter.return_value = _ApprovedDecision(sig)
    eng._bar_index = 10
    eng._decide({}, _bar(0))
    eng._oms.submit.assert_called_once()
    assert [type(e).__name__ for e in captured] == ["SignalApproved", "PositionOpened"]
    assert captured[0].signal is sig


def test_event_store_failure_does_not_orphan_entry():
    # An EventStore append failure (I/O, corrupt payload) must not skip the
    # post-submit entry bookkeeping — a live order with a flat book would
    # invite a duplicate entry on the next evaluation.
    eng, captured = _engine()
    eng.event_store.append = MagicMock(side_effect=RuntimeError("disk full"))
    eng._bar_index = 10
    eng._decide({}, _bar(0))  # must not raise
    eng._oms.submit.assert_called_once()
    # SignalApproved is a non-lifecycle event and reaches the bus subscriber;
    # PositionOpened is lifecycle and is not published on append failure.
    assert "SignalApproved" in [type(e).__name__ for e in captured]
    assert eng._entry_bar_index == 10
    assert eng._get_position_manager().current_position is not None
