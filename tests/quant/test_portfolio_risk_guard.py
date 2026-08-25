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
    assert eng._position is None, "entry proceeded despite register_open rejection"
