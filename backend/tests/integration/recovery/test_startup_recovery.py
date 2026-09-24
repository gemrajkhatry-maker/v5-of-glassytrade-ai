from glassytrade.application.oms.recovery_service import RecoveryRequest, RecoveryService


class BrokerWithPosition:
    def list_positions(self):
        return (
            {
                "contract_id": "NIFTY",
                "signed_quantity": 1,
                "side": "BUY",
                "average_entry": "100",
                "state": "OPEN",
            },
        )

    def list_orders(self):
        return ()

    def list_fills(self):
        return ()


def test_broker_only_position_blocks_recovery(tmp_path):
    from glassytrade.adapters.persistence.sqlite.migrations import create_database

    report = RecoveryService(
        create_database(tmp_path / "oms.sqlite3"),
        broker=BrokerWithPosition(),
    ).recover(RecoveryRequest(session_key="NSE:2026-09-24", account_id="paper-main"))
    assert report.runtime_ready is False
    assert report.unresolved_cases
    assert report.broker_snapshot_available is True


def test_recovery_rebuilds_projection_and_risk_from_durable_events(tmp_path):
    from datetime import datetime, timezone
    from decimal import Decimal
    from glassytrade.adapters.persistence.sqlite.migrations import create_database
    from glassytrade.application.oms.command_service import OmsCommandService
    from glassytrade.domain.common.ids import ContractId
    from glassytrade.domain.execution.types import Fill
    from glassytrade.domain.strategy.intent import EntryIntent

    connection = create_database(tmp_path / "oms.sqlite3")
    intent = EntryIntent(
        intent_id="entry-1",
        contract_id=ContractId("NFO", "NIFTY", "2026-09-24", "OPTION", "100", "CE", "sec-1"),
        side="BUY",
        desired_quantity=1,
        entry_price=Decimal("100"),
        stop_price=Decimal("95"),
        target_price=Decimal("110"),
        setup="setup",
    )
    oms = OmsCommandService(connection)
    oms.prepare_entry(intent)
    oms.ingest_receipt(
        Fill(
            fill_id="fill-1",
            intent_id="entry-1",
            contract_id=intent.contract_id,
            quantity=1,
            price=Decimal("100"),
            fees=Decimal("0"),
            filled_at=datetime.now(timezone.utc),
        )
    )
    report = RecoveryService(connection).recover(
        RecoveryRequest(session_key="NSE:2026-09-24", account_id="paper-main")
    )
    assert report.rebuilt_sequence > 0
    assert report.account.positions
    assert report.risk.committed_risk == Decimal("5")


def test_wave_six_recovery_never_sets_runtime_ready(tmp_path):
    from glassytrade.adapters.persistence.sqlite.migrations import create_database

    report = RecoveryService(create_database(tmp_path / "oms.sqlite3")).recover(
        RecoveryRequest(session_key="NSE:2026-09-24", account_id="paper-main")
    )
    assert report.journal_verified is True
    assert report.recovery_complete is False
    assert report.runtime_ready is False
