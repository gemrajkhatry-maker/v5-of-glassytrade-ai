from glassytrade.application.oms.reconciliation_service import (
    ReconciliationRequest,
    ReconciliationService,
)


def position(contract_id: str, quantity: int, side: str = "BUY", average: str = "100") -> dict:
    return {
        "contract_id": contract_id,
        "signed_quantity": quantity if side == "BUY" else -quantity,
        "side": side,
        "average_entry": average,
        "state": "OPEN",
    }


def test_same_count_quantity_mismatch_blocks_recovery():
    report = ReconciliationService().compare(
        ReconciliationRequest(
            ledger_events=(),
            oms_positions=(position("NIFTY", 10),),
            broker_positions=(position("NIFTY", 5),),
            broker_available=True,
        )
    )
    assert report.accepting_orders is False
    assert report.has_quantity_mismatch is True
    assert report.discrepancies


def test_matching_full_identity_allows_order_acceptance():
    local = position("NIFTY", 10)
    broker = position("NIFTY", 10)
    report = ReconciliationService().compare(
        ReconciliationRequest(
            ledger_events=(),
            oms_positions=(local,),
            broker_positions=(broker,),
            broker_available=True,
        )
    )
    assert report.accepting_orders is True
    assert report.has_quantity_mismatch is False


def test_broker_outage_is_not_empty_truth():
    report = ReconciliationService().compare(
        ReconciliationRequest(
            ledger_events=(),
            oms_positions=(),
            broker_positions=(),
            broker_available=False,
        )
    )
    assert report.accepting_orders is False
    assert "broker_snapshot_unavailable" in report.discrepancies
