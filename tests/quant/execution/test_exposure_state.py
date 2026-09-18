from quant.execution.exposure import ExposureStatus, ExposureState


def test_partial_entry_is_reconciliation_required():
    state = ExposureState.none().partial_entry(
        symbol="NIFTY", order_id="o1", requested_qty=100,
        filled_qty=40, fill_price=100.0,
    )
    assert state.status is ExposureStatus.RECONCILIATION_REQUIRED
    assert state.filled_qty == 40
    assert state.requested_qty == 100
    assert state.order_id == "o1"


def test_reconciliation_required_blocks_new_position():
    state = ExposureState.none().partial_entry(
        symbol="NIFTY", order_id="o1", requested_qty=100,
        filled_qty=40, fill_price=100.0,
    )
    assert state.can_open_new_position is False


def test_engine_entry_guards_block_reconciliation_required_exposure():
    from tests.helpers.synthetic import SyntheticGateway
    from quant.runtime import QuantEngine
    engine = QuantEngine(SyntheticGateway([]), "SYM", interval_seconds=60)
    engine.exposure_state = ExposureState.none().partial_entry(
        symbol="SYM", order_id="o1", requested_qty=100,
        filled_qty=40, fill_price=100.0,
    )
    blocked, cooldown = engine._entry_guards(type("Bar", (), {"time": "t"})())
    assert blocked is True
    assert cooldown == 0.0


def test_reconciliation_rejects_snapshot_for_different_order_or_symbol():
    state = ExposureState.none().unknown_entry(
        symbol="MCX", order_id="o1", requested_qty=10, filled_qty=4, fill_price=100
    )

    assert state.reconcile({"status": "OPEN", "symbol": "OTHER", "order_id": "o1"}) == state
    assert state.reconcile({"status": "OPEN", "symbol": "MCX", "order_id": "o2"}) == state


def test_reconciliation_requires_both_snapshot_identities():
    state = ExposureState.none().unknown_entry(
        symbol="MCX", order_id="o1", requested_qty=10
    )

    assert state.reconcile({"status": "OPEN", "symbol": "MCX"}) == state
    assert state.reconcile({"status": "FLAT", "order_id": "o1"}) == state
