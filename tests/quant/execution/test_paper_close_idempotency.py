from quant.contracts.contracts import ContractRef
from quant.decision.signal_builder import Signal
from quant.execution.oms import PaperOMS
from quant.execution.order import Position, Order
from quant.execution.paper_simulator import PaperExecutionSimulator


def test_retried_paper_close_uses_one_economic_identity():
    signal = Signal(signal_id="s1", symbol="NIFTY", type="LONG", entry=100, sl=90, tp=120, rr=2, reason="test", model_label="test", timestamp="t")
    position = Position(order=Order(signal=signal, quantity=25), open_price=100, open_time="t", size=25)
    oms = PaperOMS(
        simulator=PaperExecutionSimulator(),
        contract=ContractRef(symbol="NIFTY", exchange="NSE", expiry="2026-09-25", lot_size=25, tick_size=0.05),
    )
    first = oms.close(position, 110, "t1", "STOP")
    second = oms.close(position, 110, "t2", "STOP")
    assert first.logical_id == second.logical_id == f"close:{position.id}:STOP"
    assert oms._simulator.fills[0].order_id == first.logical_id
