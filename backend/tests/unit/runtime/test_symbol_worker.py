from glassytrade.application.runtime.symbol_worker import SymbolWorker
from glassytrade.domain.common.ids import ContractId
from glassytrade.domain.market_data.events import MarketDataEvent
from glassytrade.domain.common.provenance import EvidenceQuality
from datetime import datetime, timezone
from decimal import Decimal

CONTRACT_A = ContractId("NFO", "NIFTY", "2026-09-24", "OPTION", "100", "CE", "a")
CONTRACT_B = ContractId("NFO", "BANKNIFTY", "2026-09-24", "OPTION", "100", "CE", "b")


def market_event(contract_id: ContractId, sequence: int) -> MarketDataEvent:
    now = datetime.now(timezone.utc)
    return MarketDataEvent(
        event_id=f"evt-{contract_id.root}-{sequence}",
        contract_id=contract_id,
        exchange_timestamp=now,
        received_timestamp=now,
        sequence_number=sequence,
        event_type="LTP",
        price=Decimal("100"),
        size=1,
        side=None,
        provenance=EvidenceQuality.EXACT,
    )


class FakeCoordinator:
    def __init__(self):
        self.mutations = 0
        self.intents = []

    def submit_entry(self, intent):
        self.mutations += 1
        self.intents.append(intent)
        return intent


class FakeAnalyzer:
    def decide(self, contract_id, event):
        from glassytrade.domain.strategy.intent import EntryIntent
        return EntryIntent(
            intent_id=f"{contract_id.root}:{event.sequence_number}",
            contract_id=contract_id,
            side="BUY",
            desired_quantity=1,
            entry_price=event.price,
            stop_price=event.price - Decimal("1"),
            target_price=event.price + Decimal("1"),
            setup="test",
        )


def test_workers_analyze_concurrently_but_only_coordinator_mutates_account():
    coordinator = FakeCoordinator()
    worker_a = SymbolWorker(CONTRACT_A, coordinator, FakeAnalyzer())
    worker_b = SymbolWorker(CONTRACT_B, coordinator, FakeAnalyzer())
    assert worker_a.offer(market_event(CONTRACT_A, 1)) is True
    assert worker_b.offer(market_event(CONTRACT_B, 1)) is True
    worker_a.run()
    worker_b.run()
    assert coordinator.mutations == 2
    assert worker_a.worker_state().contract_id == CONTRACT_A
    assert worker_b.worker_state().contract_id == CONTRACT_B


def test_worker_rejects_other_contract_and_applies_backpressure():
    coordinator = FakeCoordinator()
    worker = SymbolWorker(CONTRACT_A, coordinator, FakeAnalyzer(), mailbox_capacity=1)
    assert worker.offer(market_event(CONTRACT_B, 1)) is False
    assert worker.offer(market_event(CONTRACT_A, 1)) is True
    assert worker.offer(market_event(CONTRACT_A, 2)) is False
    worker.stop()
    assert worker.worker_state().running is False
