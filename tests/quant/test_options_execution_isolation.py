"""Tests for options execution isolation and signal debounce."""

from dataclasses import dataclass
from unittest.mock import MagicMock

from quant.bars import Bar
from quant.decision.signal_builder import Signal
from quant.runtime import QuantEngine


@dataclass
class _ApprovedDecision:
    signal: Signal
    approved: bool = True
    reason: str = "test"
    phase: str = ""
    gate_results: tuple = ()
    block_reasons: tuple = ()
    model_label: str = ""
    metadata: dict = None

    def __post_init__(self):
        if self.metadata is None:
            self.metadata = {}


def test_execution_disabled_does_not_submit_orders():
    """An engine marked execution_enabled=False (e.g. underlying feed) must not trade."""
    pra = MagicMock()
    eng = QuantEngine(
        gateway=MagicMock(),
        symbol="NATURALGAS SEP FUT",
        portfolio_risk=pra,
        execution_enabled=False,
    )
    sig = Signal(
        type="LONG", reason="t", entry=100.0, sl=95.0, tp=110.0, rr=2.0,
        model_label="t", symbol="NATURALGAS SEP FUT", timestamp="t0",
    )
    stub = MagicMock()
    stub.should_enter.return_value = _ApprovedDecision(sig)
    eng._strategy = stub

    bar = Bar(time="t300", open=99.0, high=101.0, low=98.5, close=100.0, volume=10.0)
    eng._decide({}, bar)

    # Must NOT call portfolio risk or submit OMS order
    pra.can_accept.assert_not_called()
    pra.register_open.assert_not_called()
    assert eng.state.position is None


def test_rejected_signal_is_debounced():
    """When portfolio risk rejects an entry, the engine must debounce repeated calls."""
    pra = MagicMock()
    pra.can_accept.return_value = (False, "concurrent root position active")

    eng = QuantEngine(
        gateway=MagicMock(),
        symbol="NATURALGAS SEP FUT",
        portfolio_risk=pra,
        execution_enabled=True,
    )
    sig = Signal(
        type="LONG", reason="t", entry=14.0, sl=13.0, tp=16.0, rr=2.0,
        model_label="t", symbol="NATURALGAS SEP FUT", timestamp="t0",
    )
    stub = MagicMock()
    stub.should_enter.return_value = _ApprovedDecision(sig)
    eng._strategy = stub

    bar1 = Bar(time="t60", open=14.0, high=14.2, low=13.9, close=14.0, volume=10.0)
    eng._bar_index = 10
    eng._decide({}, bar1)
    assert pra.can_accept.call_count == 1

    # Next bar (bar_index = 11) should be debounced
    bar2 = Bar(time="t120", open=14.0, high=14.2, low=13.9, close=14.0, volume=10.0)
    eng._bar_index = 11
    eng._decide({}, bar2)
    # Still 1 because it was debounced
    assert pra.can_accept.call_count == 1

    # Later bar (bar_index = 13) can re-evaluate
    bar3 = Bar(time="t180", open=14.0, high=14.2, low=13.9, close=14.0, volume=10.0)
    eng._bar_index = 13
    eng._decide({}, bar3)
    assert pra.can_accept.call_count == 2
