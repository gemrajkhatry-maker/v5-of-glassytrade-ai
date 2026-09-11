from quant.execution.exposure import ExposureStatus, ExposureState
from quant.execution.paper_simulator import PaperExecutionSimulator
from quant.contracts.contracts import ContractRef


def contract():
    return ContractRef(symbol="NIFTY", exchange="NSE", expiry="2026-09-25", lot_size=25, tick_size=0.05)


def test_partial_fills_survive_restart_as_unresolved_exposure():
    original = PaperExecutionSimulator(fill_ratio=0.4)
    original.submit(order_id="entry-1", contract=contract(), side="BUY", quantity=100, reference_price=100)
    restored = PaperExecutionSimulator.from_records(original.export_records())
    assert [fill.order_id for fill in restored.unresolved_fills] == ["entry-1"]


def test_reconciled_exposure_can_clear_entry_block():
    state = ExposureState.none().partial_entry(
        symbol="NIFTY", order_id="entry-1", requested_qty=100, filled_qty=40, fill_price=100
    )
    assert state.status is ExposureStatus.RECONCILIATION_REQUIRED
    assert state.reconciled() == ExposureState.none()
