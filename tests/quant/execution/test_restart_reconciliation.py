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

    opened = state.reconcile({
        "status": "OPEN", "symbol": "MCX", "order_id": "o1",
        "filled_qty": 4, "fill_price": 101,
    })
    assert opened.status is ExposureStatus.OPEN
    assert opened.filled_qty == 4
    assert opened.fill_price == 101
    assert state.reconcile({"status": "FLAT", "symbol": "MCX", "order_id": "o1"}) == ExposureState.none()


def test_startup_storage_failure_is_not_converted_to_empty_recovery():
    from quant.multi_engine import QuantCoordinator

    coordinator = object.__new__(QuantCoordinator)
    coordinator._storage = type(
        "BrokenStorage", (),
        {"load_inflight_orders": lambda self: (_ for _ in ()).throw(OSError("db down"))},
    )()

    with pytest.raises(OSError):
        coordinator._load_inflight_orders_for_startup()


def test_startup_issue_blocks_actual_entry_guard_even_when_exposure_is_open():
    from quant.engine.decision_loop import DecisionLoop

    loop = DecisionLoop(
        config={"symbol": "MCX", "cooldown_bars": 0},
        deps={
            "risk": type("Risk", (), {"can_trade": lambda self: (True, "OK"), "state": lambda self: type("S", (), {"trades_today": 0})()})(),
            "oms": object(), "strategy": object(), "amt_engine": object(),
            "get_position_manager": lambda: None,
        },
        state={
            "get_bar_index": lambda: 10, "get_entry_bar_index": lambda: 0,
            "get_last_close_bar_index": lambda: -1,
            "get_exposure_state": lambda: ExposureState.none(),
            "set_entry_bar_index": lambda value: None,
            "get_latch": lambda: {}, "set_latch": lambda key, value: None,
            "clear_latch": lambda: None, "get_cert_records": lambda: [],
        },
        emit=lambda event: None, forecast_fn=lambda: None,
    )
    loop._get_startup_block = lambda: True

    blocked, _ = loop._entry_guards(type("Bar", (), {"time": "t"})())

    assert blocked is True


def test_risk_reservation_unavailable_blocks_entry_after_broker_open():
    from quant.engine.decision_loop import DecisionLoop

    loop = DecisionLoop(
        config={"symbol": "MCX", "cooldown_bars": 0},
        deps={
            "risk": type("Risk", (), {"can_trade": lambda self: (True, "OK"), "state": lambda self: type("S", (), {"trades_today": 0})()})(),
            "oms": object(), "strategy": object(), "amt_engine": object(),
            "get_position_manager": lambda: None,
        },
        state={
            "get_bar_index": lambda: 10, "get_entry_bar_index": lambda: 0,
            "get_last_close_bar_index": lambda: -1,
            "get_exposure_state": lambda: ExposureState.none(),
            "get_startup_block": lambda: True,
            "set_entry_bar_index": lambda value: None,
            "get_latch": lambda: {}, "set_latch": lambda key, value: None,
            "clear_latch": lambda: None, "get_cert_records": lambda: [],
        },
        emit=lambda event: None, forecast_fn=lambda: None,
    )

    assert loop._entry_guards(type("Bar", (), {"time": "t"})())[0] is True


def test_coordinator_reconciliation_failure_remains_a_decision_block():
    from quant.multi_engine import QuantCoordinator

    coordinator = object.__new__(QuantCoordinator)
    coordinator._unresolved_startup = set()
    coordinator.broker = type(
        "BrokenBroker", (),
        {"reconcile_order": lambda self, order_id: (_ for _ in ()).throw(OSError("broker down"))},
    )()
    engine = type(
        "Engine", (),
        {"symbol": "MCX", "reconcile_unresolved_order": lambda self, snapshot: None},
    )()

    coordinator._reconcile_restored_order(
        engine, {"symbol": "MCX", "order_id": "o1", "risk_reserved": 1}
    )

    assert any(issue.startswith("broker-reconciliation-failed:") for issue in coordinator._unresolved_startup)
