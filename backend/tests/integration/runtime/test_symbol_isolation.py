from glassytrade.application.runtime.symbol_worker import SymbolWorker
from glassytrade.domain.common.ids import ContractId
from glassytrade.domain.common.provenance import EvidenceQuality
from glassytrade.domain.market_data.events import MarketDataEvent
from datetime import datetime, timezone
from decimal import Decimal


class Coordinator:
    def __init__(self):
        self.intents = []

    def submit_entry(self, intent):
        self.intents.append(intent)
        return intent


class Analyzer:
    def decide(self, contract_id, event):
        from glassytrade.domain.strategy.intent import EntryIntent
        return EntryIntent(
            intent_id=f"{contract_id.root}-{event.sequence_number}",
            contract_id=contract_id,
            side="BUY",
            desired_quantity=1,
            entry_price=event.price,
            stop_price=event.price - 1,
            target_price=event.price + 1,
            setup="isolation",
        )


def event(contract_id, sequence):
    now = datetime.now(timezone.utc)
    return MarketDataEvent(
        event_id=f"{contract_id.root}-{sequence}",
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


def test_workers_do_not_cross_publish_contract_state():
    coordinator = Coordinator()
    first = SymbolWorker(ContractId("NFO", "NIFTY", "2026-09-24", "OPTION", "100", "CE", "a"), coordinator, Analyzer())
    second = SymbolWorker(ContractId("NFO", "BANKNIFTY", "2026-09-24", "OPTION", "100", "CE", "b"), coordinator, Analyzer())
    first.offer(event(first.contract_id, 1))
    second.offer(event(second.contract_id, 1))
    first.run()
    second.run()
    assert {intent.contract_id.root for intent in coordinator.intents} == {"NIFTY", "BANKNIFTY"}
    assert first.worker_state().last_sequence == 1
    assert second.worker_state().last_sequence == 1
