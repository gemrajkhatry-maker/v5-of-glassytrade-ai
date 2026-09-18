from quant.execution.exposure import ExposureState, ExposureStatus
import pytest


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


def test_startup_storage_failure_is_not_converted_to_empty_recovery():
    from quant.multi_engine import QuantCoordinator

    coordinator = object.__new__(QuantCoordinator)
    coordinator._storage = type(
        "BrokenStorage", (),
        {"load_inflight_orders": lambda self: (_ for _ in ()).throw(OSError("db down"))},
    )()

    with pytest.raises(OSError):
        coordinator._load_inflight_orders_for_startup()
