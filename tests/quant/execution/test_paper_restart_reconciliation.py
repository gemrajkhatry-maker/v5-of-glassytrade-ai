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


def test_engine_restores_unresolved_paper_fill_into_exposure_state_after_restart():
    from quant.runtime import QuantEngine
    from tests.helpers.synthetic import SyntheticGateway

    original = PaperExecutionSimulator(fill_ratio=0.4)
    original.submit(order_id="entry-1", contract=contract(), side="BUY", quantity=100, reference_price=100)
    restored = PaperExecutionSimulator.from_records(original.export_records())
    engine = QuantEngine(SyntheticGateway([]), "NIFTY", interval_seconds=60)

    engine.reconcile_paper_fills(restored)

    assert engine.exposure_state == ExposureState(
        status=ExposureStatus.RECONCILIATION_REQUIRED,
        symbol="NIFTY",
        order_id="entry-1",
        requested_qty=100,
        filled_qty=40,
        fill_price=100,
    )


def test_engine_paper_reconciliation_is_noop_without_unresolved_fills():
    from quant.runtime import QuantEngine
    from tests.helpers.synthetic import SyntheticGateway

    engine = QuantEngine(SyntheticGateway([]), "NIFTY", interval_seconds=60)
    engine.reconcile_paper_fills(PaperExecutionSimulator())

    assert engine.exposure_state == ExposureState.none()
