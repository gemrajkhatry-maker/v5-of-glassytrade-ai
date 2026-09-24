from datetime import datetime, timezone

from glassytrade.adapters.brokers.dhan_order_events import BrokerEventIngestor, DhanReceipt


class RecordingJournal:
    def __init__(self):
        self.events = []

    def append(self, event):
        self.events.append(event)


def test_receipt_is_committed_before_normalized_event_projection():
    journal = RecordingJournal()
    ingestor = BrokerEventIngestor(journal=journal)
    normalized = ingestor.ingest(receipt("broker-event-1", 1))
    assert len(journal.events) == 1
    assert journal.events[0].event_type == "BrokerFillReceipt"
    assert normalized[0].cumulative_filled_quantity == 1


def receipt(
    event_id: str,
    cumulative: int,
    *,
    quantity: int = 1,
) -> DhanReceipt:
    timestamp = datetime(2026, 9, 24, 10, 0, tzinfo=timezone.utc)
    return DhanReceipt(
        event_id=event_id,
        kind="fill",
        broker_order_id="dhan-1",
        intent_id="intent-1",
        quantity=quantity,
        price="100.05",
        cumulative_filled_quantity=cumulative,
        occurred_at=timestamp,
        payload={"account": "paper"},
    )


def test_duplicate_broker_receipts_are_idempotent():
    ingestor = BrokerEventIngestor()
    first = ingestor.ingest(receipt("broker-event-1", 1))
    duplicate = ingestor.ingest(receipt("broker-event-1", 1))
    assert len(first) == 1
    assert duplicate == ()


def test_semantically_duplicate_receipt_with_new_event_id_is_idempotent():
    ingestor = BrokerEventIngestor()
    first = ingestor.ingest(receipt("broker-event-1", 1))
    duplicate = ingestor.ingest(receipt("broker-event-duplicate", 1))
    assert len(first) == 1
    assert duplicate == ()


def test_out_of_order_cumulative_fill_cannot_regress_projection():
    ingestor = BrokerEventIngestor()
    ingestor.ingest(receipt("broker-event-1", 2, quantity=2))
    ingestor.ingest(receipt("broker-event-2", 1, quantity=1))
    assert ingestor.cumulative_quantity("dhan-1") == 2
    assert ingestor.fills_for_order("dhan-1")[0].quantity == 2
