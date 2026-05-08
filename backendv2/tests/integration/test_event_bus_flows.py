"""Integration tests for EventBus flows — publish, subscribe, idempotency, error isolation, history."""

from __future__ import annotations

import pytest
from app.infrastructure.messaging.event_bus import EventBus
from app.domain.shared.event.domain_events import (
    TickReceived,
    AMTAnalyzed,
    SignalGenerated,
    PositionOpened,
    PositionClosed,
    RiskStateChanged,
)


class TestEventBusPublishSubscribe:
    """Test publish → subscribe → consume flows."""

    def setup_method(self):
        self.bus = EventBus()

    def test_publish_tick_received_to_subscriber(self):
        """TickReceived published → subscriber receives correct payload."""
        received = []

        def handler(event):
            received.append(event)

        self.bus.subscribe(TickReceived, handler)
        event = TickReceived(symbol="NIFTY", price=22500.0, volume=100.0)
        count = self.bus.publish(event)

        assert count == 1
        assert len(received) == 1
        assert received[0].symbol == "NIFTY"
        assert received[0].price == 22500.0

    def test_publish_amt_analyzed_to_subscriber(self):
        """AMTAnalyzed published → subscriber receives market state."""
        received = []

        def handler(event):
            received.append(event)

        self.bus.subscribe(AMTAnalyzed, handler)
        event = AMTAnalyzed(symbol="NIFTY", market_state="BALANCED", setup="RANGE")
        count = self.bus.publish(event)

        assert count == 1
        assert len(received) == 1
        assert received[0].market_state == "BALANCED"

    def test_publish_signal_generated_to_subscriber(self):
        """SignalGenerated published → subscriber receives signal dict."""
        received = []

        def handler(event):
            received.append(event)

        self.bus.subscribe(SignalGenerated, handler)
        event = SignalGenerated(symbol="NIFTY", direction="LONG", entry_price=22500.0)
        count = self.bus.publish(event)

        assert count == 1
        assert len(received) == 1
        assert received[0].direction == "LONG"

    def test_multiple_subscribers_all_receive(self):
        """Multiple subscribers to same event — all receive."""
        received_a = []
        received_b = []

        def handler_a(event):
            received_a.append(event)

        def handler_b(event):
            received_b.append(event)

        self.bus.subscribe(TickReceived, handler_a)
        self.bus.subscribe(TickReceived, handler_b)
        event = TickReceived(symbol="BANKNIFTY", price=48000.0)
        count = self.bus.publish(event)

        assert count == 2
        assert len(received_a) == 1
        assert len(received_b) == 1

    def test_event_ordering_preserved(self):
        """Publish A, B, C → subscribers receive in order."""
        received = []

        def handler(event):
            received.append(event.symbol)

        self.bus.subscribe(TickReceived, handler)
        for sym in ["A", "B", "C"]:
            self.bus.publish(TickReceived(symbol=sym, price=100.0))

        assert received == ["A", "B", "C"]

    def test_no_subscribers_returns_zero(self):
        """Publish to event type with no subscribers → handled_count=0."""
        event = TickReceived(symbol="NIFTY")
        count = self.bus.publish(event)
        assert count == 0
        # Event still recorded in history
        assert len(self.bus.get_history()) == 1

    def test_subscribe_same_handler_twice_ignored(self):
        """Subscribe same handler twice → only called once."""
        call_count = [0]

        def handler(event):
            call_count[0] += 1

        self.bus.subscribe(TickReceived, handler)
        self.bus.subscribe(TickReceived, handler)
        self.bus.publish(TickReceived(symbol="NIFTY"))

        assert call_count[0] == 1


class TestEventBusIdempotency:
    """Test duplicate event rejection."""

    def setup_method(self):
        self.bus = EventBus()

    def test_duplicate_event_id_rejected(self):
        """Same event_id → second publish returns 0 handlers."""
        received = []

        def handler(event):
            received.append(event)

        self.bus.subscribe(TickReceived, handler)
        event = TickReceived(event_id="dup-123", symbol="NIFTY", price=100.0)

        count1 = self.bus.publish(event)
        count2 = self.bus.publish(event)

        assert count1 == 1
        assert count2 == 0
        assert len(received) == 1

    def test_same_type_different_ids_accepted(self):
        """Same event type with different IDs → both accepted."""
        count = [0]

        def handler(event):
            count[0] += 1

        self.bus.subscribe(TickReceived, handler)
        self.bus.publish(TickReceived(symbol="A", price=1.0))
        self.bus.publish(TickReceived(symbol="B", price=2.0))

        assert count[0] == 2

    def test_clear_seen_ids_allows_replay(self):
        """clear_seen_ids() → same event can be republished."""
        received = []

        def handler(event):
            received.append(event)

        self.bus.subscribe(TickReceived, handler)
        event = TickReceived(event_id="replay-1", symbol="NIFTY")

        self.bus.publish(event)
        self.bus.clear_seen_ids()
        self.bus.publish(event)

        assert len(received) == 2


class TestEventBusErrorIsolation:
    """Test subscriber exceptions don't block other handlers."""

    def setup_method(self):
        self.bus = EventBus()

    def test_one_subscriber_exception_doesnt_block_others(self):
        """Subscriber A raises → subscriber B still called."""
        results = []

        def bad_handler(event):
            results.append("bad")
            raise RuntimeError("handler failed")

        def good_handler(event):
            results.append("good")

        self.bus.subscribe(TickReceived, bad_handler)
        self.bus.subscribe(TickReceived, good_handler)
        count = self.bus.publish(TickReceived(symbol="NIFTY"))

        # Only good_handler succeeded
        assert count == 1
        assert "bad" in results
        assert "good" in results

    def test_bus_continues_after_crash(self):
        """Bus continues operating after handler crash."""
        def bad_handler(event):
            raise ValueError("crash")

        self.bus.subscribe(TickReceived, bad_handler)
        # First publish — handler crashes
        self.bus.publish(TickReceived(symbol="A"))
        # Second publish — bus still works
        count = self.bus.publish(TickReceived(symbol="B"))
        # Event still recorded even though handler failed
        assert len(self.bus.get_history()) == 2

    def test_all_subscribers_complete_even_if_one_crashes(self):
        """Three subscribers, middle one crashes → first and third complete."""
        order = []

        def h1(event):
            order.append(1)

        def h2(event):
            order.append(2)
            raise Exception("boom")

        def h3(event):
            order.append(3)

        self.bus.subscribe(TickReceived, h1)
        self.bus.subscribe(TickReceived, h2)
        self.bus.subscribe(TickReceived, h3)
        self.bus.publish(TickReceived(symbol="X"))

        assert order == [1, 2, 3]


class TestEventBusHistory:
    """Test event history retrieval and filtering."""

    def setup_method(self):
        self.bus = EventBus()

    def test_get_history_returns_events_in_order(self):
        """get_history() returns events in insertion order."""
        for sym in ["A", "B", "C"]:
            self.bus.publish(TickReceived(symbol=sym, price=1.0))

        history = self.bus.get_history()
        assert [e.symbol for e in history] == ["A", "B", "C"]

    def test_filter_by_event_type(self):
        """get_history(event_type=TickReceived) filters correctly."""
        self.bus.publish(TickReceived(symbol="A"))
        self.bus.publish(SignalGenerated(symbol="A", direction="LONG"))
        self.bus.publish(TickReceived(symbol="B"))

        ticks = self.bus.get_history(event_type=TickReceived)
        assert len(ticks) == 2
        assert all(isinstance(e, TickReceived) for e in ticks)

    def test_filter_by_symbol(self):
        """get_history(symbol='NIFTY') returns only matching events."""
        self.bus.publish(TickReceived(symbol="NIFTY", price=1.0))
        self.bus.publish(TickReceived(symbol="BANKNIFTY", price=1.0))
        self.bus.publish(TickReceived(symbol="NIFTY", price=2.0))

        nifty = self.bus.get_history(symbol="NIFTY")
        assert len(nifty) == 2
        assert all(e.symbol == "NIFTY" for e in nifty)

    def test_history_limit(self):
        """get_history(limit=N) returns at most N events."""
        for i in range(50):
            self.bus.publish(TickReceived(symbol=f"S{i}"))

        history = self.bus.get_history(limit=10)
        assert len(history) == 10
        # Returns last 10
        assert history[0].symbol == "S40"

    def test_max_history_enforced(self):
        """History limited to max_history, oldest events dropped."""
        bus = EventBus(max_history=5)
        for i in range(10):
            bus.publish(TickReceived(symbol=f"S{i}"))

        assert bus.get_stats()["history_size"] <= 5

    def test_get_timeline(self):
        """get_timeline() returns audit-ready dicts."""
        self.bus.publish(TickReceived(symbol="NIFTY", price=1.0))
        timeline = self.bus.get_timeline()

        assert len(timeline) == 1
        assert timeline[0]["event_type"] == "TickReceived"
        assert timeline[0]["symbol"] == "NIFTY"
        assert "event_id" in timeline[0]
        assert "timestamp" in timeline[0]


class TestEventBusUnsubscribe:
    """Test handler unsubscription."""

    def setup_method(self):
        self.bus = EventBus()

    def test_unsubscribed_handler_no_longer_called(self):
        """Handler unsubscribed → not called on publish."""
        count = [0]

        def handler(event):
            count[0] += 1

        self.bus.subscribe(TickReceived, handler)
        self.bus.publish(TickReceived(symbol="A"))
        assert count[0] == 1

        self.bus.unsubscribe(TickReceived, handler)
        self.bus.publish(TickReceived(symbol="B"))
        assert count[0] == 1

    def test_unsubscribe_nonexistent_handler_no_crash(self):
        """Unsubscribe handler that was never subscribed → no crash."""
        def handler(event):
            pass

        self.bus.unsubscribe(TickReceived, handler)  # Should not raise

    def test_unsubscribe_during_dispatch_handled(self):
        """Handler unsubscribes itself during dispatch → no crash."""
        calls = []

        def self_unsub(event):
            calls.append("self_unsub")
            # Unsubscribe itself during dispatch
            self.bus.unsubscribe(TickReceived, self_unsub)

        def other(event):
            calls.append("other")

        self.bus.subscribe(TickReceived, self_unsub)
        self.bus.subscribe(TickReceived, other)
        self.bus.publish(TickReceived(symbol="A"))
        # Second publish — self_unsub should not be called again
        self.bus.publish(TickReceived(symbol="B"))

        assert calls == ["self_unsub", "other", "other"]


class TestEventBusStats:
    """Test diagnostic counters."""

    def setup_method(self):
        self.bus = EventBus()

    def test_get_stats_returns_correct_counts(self):
        """get_stats() returns handler and event counts."""
        def handler(event):
            pass

        self.bus.subscribe(TickReceived, handler)
        self.bus.publish(TickReceived(symbol="A"))

        stats = self.bus.get_stats()
        assert stats["total_event_types"] >= 1
        assert stats["total_handlers"] >= 1
        assert stats["seen_events"] == 1
        assert stats["history_size"] == 1

    def test_get_subscribers(self):
        """get_subscribers() returns handlers for event type."""
        def handler(event):
            pass

        self.bus.subscribe(TickReceived, handler)
        subs = self.bus.get_subscribers(TickReceived)
        assert len(subs) == 1
        assert subs[0] is handler

    def test_get_subscribers_empty(self):
        """get_subscribers() for unregistered type returns empty list."""
        subs = self.bus.get_subscribers(PositionOpened)
        assert subs == []

    def test_reset_clears_everything(self):
        """reset() clears handlers, history, and diagnostics."""
        def handler(event):
            pass

        self.bus.subscribe(TickReceived, handler)
        self.bus.publish(TickReceived(symbol="A"))
        self.bus.reset()

        stats = self.bus.get_stats()
        assert stats["total_handlers"] == 0
        assert stats["history_size"] == 0
        assert stats["seen_events"] == 0

    def test_error_counts_tracked(self):
        """Handler errors tracked in error_counts."""
        def bad_handler(event):
            raise RuntimeError("fail")

        self.bus.subscribe(TickReceived, bad_handler)
        self.bus.publish(TickReceived(symbol="A"))
        self.bus.publish(TickReceived(symbol="B"))

        stats = self.bus.get_stats()
        assert stats["error_counts"].get("bad_handler", 0) == 2

    def test_clear_history(self):
        """clear_history() removes events but keeps handlers."""
        def handler(event):
            pass

        self.bus.subscribe(TickReceived, handler)
        self.bus.publish(TickReceived(symbol="A"))
        self.bus.clear_history()

        assert self.bus.get_stats()["history_size"] == 0
        # Handler still subscribed
        assert len(self.bus.get_subscribers(TickReceived)) == 1
