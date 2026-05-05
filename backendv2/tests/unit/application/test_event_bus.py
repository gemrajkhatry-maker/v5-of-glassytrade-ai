"""Unit tests for the application event bus."""

import pytest
from app.infrastructure.messaging.event_bus import EventBus
from app.domain.shared.event.market import TickReceived
from app.domain.shared.event.signal import SignalGenerated


class TestEventBusPublishSubscribe:
    """Tests for publish/subscribe pattern."""

    def test_subscribe_and_publish(self):
        bus = EventBus()
        received = []
        bus.subscribe(TickReceived, lambda e: received.append(e))
        event = TickReceived(symbol="BTC", price=50000, volume=1.0)
        bus.publish(event)
        assert len(received) == 1
        assert received[0].symbol == "BTC"

    def test_multiple_subscribers(self):
        bus = EventBus()
        received_a = []
        received_b = []
        bus.subscribe(TickReceived, lambda e: received_a.append(e))
        bus.subscribe(TickReceived, lambda e: received_b.append(e))
        bus.publish(TickReceived(symbol="BTC", price=50000, volume=1.0))
        assert len(received_a) == 1
        assert len(received_b) == 1

    def test_type_filtering(self):
        bus = EventBus()
        ticks = []
        signals = []
        bus.subscribe(TickReceived, lambda e: ticks.append(e))
        bus.subscribe(SignalGenerated, lambda e: signals.append(e))
        bus.publish(TickReceived(symbol="BTC", price=50000, volume=1.0))
        bus.publish(SignalGenerated(symbol="BTC", signal_id="s1", direction="LONG"))
        assert len(ticks) == 1
        assert len(signals) == 1


class TestEventBusIdempotency:
    """Tests for idempotency / duplicate suppression."""

    def test_duplicate_suppressed(self):
        bus = EventBus()
        received = []
        bus.subscribe(TickReceived, lambda e: received.append(e))
        event = TickReceived(symbol="BTC", price=50000, volume=1.0)
        bus.publish(event)
        bus.publish(event)  # duplicate
        assert len(received) == 1

    def test_different_events_both_processed(self):
        bus = EventBus()
        received = []
        bus.subscribe(TickReceived, lambda e: received.append(e))
        bus.publish(TickReceived(symbol="BTC", price=50000, volume=1.0))
        bus.publish(TickReceived(symbol="ETH", price=3000, volume=2.0))
        assert len(received) == 2


class TestEventBusErrorIsolation:
    """Tests for error isolation."""

    def test_handler_failure_doesnt_crash_bus(self):
        bus = EventBus()
        received = []

        def failing_handler(event):
            raise ValueError("Handler error")

        def working_handler(event):
            received.append(event)

        bus.subscribe(TickReceived, failing_handler)
        bus.subscribe(TickReceived, working_handler)

        event = TickReceived(symbol="BTC", price=50000, volume=1.0)
        count = bus.publish(event)
        assert count == 1  # only working_handler succeeded
        assert len(received) == 1

    def test_error_counts_tracked(self):
        bus = EventBus()

        def failing_handler(event):
            raise RuntimeError("fail")

        bus.subscribe(TickReceived, failing_handler)
        bus.publish(TickReceived(symbol="BTC", price=50000, volume=1.0))
        stats = bus.get_stats()
        assert stats["error_counts"]["failing_handler"] == 1


class TestEventBusUnsubscribe:
    """Tests for unsubscribe."""

    def test_unsubscribe(self):
        bus = EventBus()
        received = []
        handler = lambda e: received.append(e)
        bus.subscribe(TickReceived, handler)
        bus.unsubscribe(TickReceived, handler)
        bus.publish(TickReceived(symbol="BTC", price=50000, volume=1.0))
        assert len(received) == 0


class TestEventBusHistory:
    """Tests for event history and audit readout."""

    def test_history_recorded(self):
        bus = EventBus()
        bus.publish(TickReceived(symbol="BTC", price=50000, volume=1.0))
        history = bus.get_history()
        assert len(history) == 1

    def test_history_filtered_by_type(self):
        bus = EventBus()
        bus.publish(TickReceived(symbol="BTC", price=50000, volume=1.0))
        bus.publish(SignalGenerated(symbol="BTC", signal_id="s1", direction="LONG"))
        ticks = bus.get_history(event_type=TickReceived)
        assert len(ticks) == 1
        assert isinstance(ticks[0], TickReceived)

    def test_history_filtered_by_symbol(self):
        bus = EventBus()
        bus.publish(TickReceived(symbol="BTC", price=50000, volume=1.0))
        bus.publish(TickReceived(symbol="ETH", price=3000, volume=2.0))
        btc_history = bus.get_history(symbol="BTC")
        assert len(btc_history) == 1
        assert btc_history[0].symbol == "BTC"

    def test_history_limit(self):
        bus = EventBus(max_history=5)
        for i in range(10):
            bus.publish(TickReceived(symbol="BTC", price=50000 + i, volume=1.0))
        history = bus.get_history()
        # History is trimmed to max_history // 2 when it exceeds max_history
        assert len(history) <= 5

    def test_timeline_read_only(self):
        bus = EventBus()
        bus.publish(TickReceived(symbol="BTC", price=50000, volume=1.0))
        timeline = bus.get_timeline(symbol="BTC", limit=10)
        assert len(timeline) == 1
        assert timeline[0]["symbol"] == "BTC"


class TestEventBusStats:
    """Tests for bus statistics."""

    def test_stats(self):
        bus = EventBus()
        bus.subscribe(TickReceived, lambda e: None)
        bus.subscribe(SignalGenerated, lambda e: None)
        bus.publish(TickReceived(symbol="BTC", price=50000, volume=1.0))
        stats = bus.get_stats()
        assert stats["total_event_types"] == 2
        assert stats["total_handlers"] == 2
        assert stats["seen_events"] == 1
        assert stats["history_size"] == 1


class TestEventBusReset:
    """Tests for bus reset."""

    def test_clear_seen_ids(self):
        bus = EventBus()
        event = TickReceived(symbol="BTC", price=50000, volume=1.0)
        bus.publish(event)
        bus.clear_seen_ids()
        received = []
        bus.subscribe(TickReceived, lambda e: received.append(e))
        bus.publish(event)  # should not be suppressed now
        assert len(received) == 1

    def test_reset(self):
        bus = EventBus()
        bus.subscribe(TickReceived, lambda e: None)
        bus.publish(TickReceived(symbol="BTC", price=50000, volume=1.0))
        bus.reset()
        stats = bus.get_stats()
        assert stats["total_event_types"] == 0
        assert stats["seen_events"] == 0
        assert stats["history_size"] == 0
