from quant.execution.exposure import ExposureState, ExposureStatus


def test_restart_restores_unresolved_exposure_before_entry_decisions():
    state = ExposureState.none().unknown_entry(
        symbol="MCX", order_id="o1", requested_qty=10
    )

    assert state.status is ExposureStatus.RECONCILIATION_REQUIRED
    assert state.can_open_new_position is False


def test_broker_query_failure_does_not_clear_unresolved_exposure():
    state = ExposureState.none().unknown_entry(
        symbol="MCX", order_id="o1", requested_qty=10
    )

    assert state.reconcile(None).status is ExposureStatus.RECONCILIATION_REQUIRED


def test_reconciliation_can_restore_open_or_flat_outcome():
    state = ExposureState.none().unknown_entry(
        symbol="MCX", order_id="o1", requested_qty=10, filled_qty=4, fill_price=100
    )

    opened = state.reconcile({"status": "OPEN", "filled_qty": 4, "fill_price": 101})
    assert opened.status is ExposureStatus.OPEN
    assert opened.filled_qty == 4
    assert opened.fill_price == 101
    assert state.reconcile({"status": "FLAT"}) == ExposureState.none()
