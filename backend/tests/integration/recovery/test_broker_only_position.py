class BrokerWithUnknownPosition:
    def list_positions(self):
        return (
            {
                "contract_id": "UNKNOWN",
                "signed_quantity": 2,
                "side": "BUY",
                "average_entry": "100",
                "state": "UNKNOWN",
            },
        )

    def list_orders(self):
        return ()

    def list_fills(self):
        return ()


def test_broker_only_position_is_recorded_as_an_unresolved_case(tmp_path):
    from glassytrade.adapters.persistence.sqlite.migrations import create_database
    from glassytrade.application.oms.recovery_service import RecoveryRequest, RecoveryService

    report = RecoveryService(
        create_database(tmp_path / "oms.sqlite3"),
        broker=BrokerWithUnknownPosition(),
    ).recover(RecoveryRequest(session_key="NSE:2026-09-24", account_id="paper-main"))
    assert report.unresolved_cases
    assert report.unresolved_cases[0].discrepancy == "broker_only_position"
    assert report.runtime_ready is False
