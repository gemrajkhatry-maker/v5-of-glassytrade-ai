import pytest

from quant.contracts.contracts import ContractRef
from quant.decision.signal_builder import Signal
from quant.execution.order import Order, Position
from quant.execution.oms import PaperOMS
from quant.execution.paper_simulator import PaperExecutionSimulator


def _position():
    signal = Signal(signal_id="s-timeout", symbol="NIFTY", type="LONG", entry=100, sl=90, tp=120, rr=2, reason="test", model_label="test", timestamp="t")
    return Position(order=Order(signal=signal, quantity=25), open_price=100, open_time="t", size=25)


def _oms(*, timeout_attempts=0, max_close_retries=2):
    contract = ContractRef(symbol="NIFTY", exchange="NSE", expiry="2026-09-25", lot_size=25, tick_size=0.05)
    simulator = PaperExecutionSimulator(timeout_attempts=timeout_attempts)
    return PaperOMS(
        simulator=simulator,
        contract=contract,
        max_close_retries=max_close_retries,
    )


def test_paper_close_retries_timeout_with_one_stable_economic_identity():
    oms = _oms(timeout_attempts=2, max_close_retries=2)
    position = _position()
    first = oms.close(position, 110, "t1", "STOP")
    second = oms.close(position, 110, "t2", "STOP")

    assert first.logical_id == second.logical_id == "close:" + first.position.id + ":STOP"
    assert len(oms._simulator.fills) == 1
    assert oms.close_attempts[first.logical_id] == 3


def test_paper_close_falls_back_after_bounded_timeouts():
    oms = _oms(timeout_attempts=9, max_close_retries=2)

    fill = oms.close(_position(), 110, "t1", "STOP")

    assert fill.close_price == 110
    assert oms.close_attempts[fill.logical_id] == 3
    assert len(oms._simulator.fills) == 1


def test_paper_close_rejects_negative_retry_limit():
    with pytest.raises(ValueError, match="max_close_retries"):
        _oms(max_close_retries=-1)
