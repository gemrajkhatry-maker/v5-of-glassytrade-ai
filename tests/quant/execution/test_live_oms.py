import pytest

from quant.decision.signal_builder import Signal as EngineSignal
from quant.execution.live_oms import LiveOMS


def _engine_signal():
    return EngineSignal(
        type="LONG", reason="r", entry=100.0, sl=99.0, tp=102.0, rr=2.0,
        model_label="Triple-A", symbol="NIFTY AUG FUT", timestamp="t0",
    )


class _FakeBroker:
    def __init__(self):
        self.calls = []

    def execute_order(self, signal, portfolio, symbol):
        self.calls.append((signal, portfolio, symbol))
        return "OPENED_POSITION"

    def cancel_order(self, order_id):
        return True


def test_submit_maps_and_calls_broker():
    broker = _FakeBroker()
    oms = LiveOMS(broker, portfolio="PORTFOLIO")
    result = oms.submit(_engine_signal(), quantity=10)
    assert result == "OPENED_POSITION"
    assert len(broker.calls) == 1
    mapped_signal, portfolio, symbol = broker.calls[0]
    assert mapped_signal.type == "BUY"
    assert portfolio == "PORTFOLIO"
    assert symbol == "NIFTY AUG FUT"


def test_close_fails_loud_not_silent():
    oms = LiveOMS(_FakeBroker(), portfolio="PORTFOLIO")
    with pytest.raises(NotImplementedError):
        oms.close(position=object(), price=100.0, time="t1", reason="TP")
