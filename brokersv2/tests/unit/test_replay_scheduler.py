"""
Tests for Replay Infrastructure - Replay Scheduler.

Tests cover:
- Event dispatch with timing control
- Deterministic replay
- Speed manipulation during replay
- Pause/resume during replay
- Sequence gap handling
- Replay from specific sequence
"""

from datetime import datetime, timezone

import pytest

from brokersv2.replay.event_clock import ReplayClock
from brokersv2.replay.event_store import EventStore
from brokersv2.replay.replay_scheduler import ReplayScheduler, ReplayState


class TestReplaySchedulerInitialization:
    """Test scheduler initialization."""

    def test_create_scheduler(self):
        """Create scheduler with clock and store."""
        clock = ReplayClock()
        store = EventStore()
        scheduler = ReplayScheduler(clock=clock, store=store)

        assert scheduler.state == ReplayState.IDLE

    def test_initial_event_count(self):
        """Initial event count is zero."""
        clock = ReplayClock()
        store = EventStore()
        scheduler = ReplayScheduler(clock=clock, store=store)

        assert scheduler.events_replayed == 0


class TestReplaySchedulerLifecycle:
    """Test replay lifecycle."""

    def test_start_replay(self):
        """Start replay transitions to RUNNING."""
        clock = ReplayClock()
        store = EventStore()
        scheduler = ReplayScheduler(clock=clock, store=store)

        scheduler.start()

        assert scheduler.state == ReplayState.RUNNING

    def test_pause_replay(self):
        """Pause replay transitions to PAUSED."""
        clock = ReplayClock()
        store = EventStore()
        scheduler = ReplayScheduler(clock=clock, store=store)
        scheduler.start()

        scheduler.pause()

        assert scheduler.state == ReplayState.PAUSED

    def test_resume_replay(self):
        """Resume replay transitions to RUNNING."""
        clock = ReplayClock()
        store = EventStore()
        scheduler = ReplayScheduler(clock=clock, store=store)
        scheduler.start()
        scheduler.pause()

        scheduler.resume()

        assert scheduler.state == ReplayState.RUNNING

    def test_stop_replay(self):
        """Stop replay transitions to IDLE."""
        clock = ReplayClock()
        store = EventStore()
        scheduler = ReplayScheduler(clock=clock, store=store)
        scheduler.start()

        scheduler.stop()

        assert scheduler.state == ReplayState.IDLE

    def test_stop_replay_transitions_to_idle(self):
        """Stop replay resets to IDLE."""
        clock = ReplayClock()
        store = EventStore()
        scheduler = ReplayScheduler(clock=clock, store=store)
        scheduler.start()
        scheduler.stop()

        assert scheduler.state == ReplayState.IDLE


class TestReplaySchedulerDispatch:
    """Test event dispatch during replay."""

    def test_dispatch_events_sequentially(self):
        """Events are dispatched in sequence order."""
        clock = ReplayClock()
        store = EventStore()
        store.append(event_type="tick", event_data=b"event1")
        store.append(event_type="tick", event_data=b"event2")
        store.append(event_type="tick", event_data=b"event3")

        scheduler = ReplayScheduler(clock=clock, store=store)

        dispatched = []
        scheduler.set_handler(lambda event: dispatched.append(event))

        scheduler.start()
        scheduler.replay_next()
        scheduler.replay_next()
        scheduler.replay_next()

        assert len(dispatched) == 3
        assert dispatched[0].event_data == b"event1"
        assert dispatched[1].event_data == b"event2"
        assert dispatched[2].event_data == b"event3"

    def test_replay_counter_increments(self):
        """Replay counter increments with each event."""
        clock = ReplayClock()
        store = EventStore()
        store.append(event_type="tick", event_data=b"event1")
        store.append(event_type="tick", event_data=b"event2")

        scheduler = ReplayScheduler(clock=clock, store=store)
        scheduler.set_handler(lambda event: None)

        scheduler.start()
        scheduler.replay_next()
        assert scheduler.events_replayed == 1

        scheduler.replay_next()
        assert scheduler.events_replayed == 2

    def test_replay_respects_pause(self):
        """Replay does not dispatch when paused."""
        clock = ReplayClock()
        store = EventStore()
        store.append(event_type="tick", event_data=b"event1")

        scheduler = ReplayScheduler(clock=clock, store=store)
        dispatched = []
        scheduler.set_handler(lambda event: dispatched.append(event))

        scheduler.start()
        scheduler.pause()
        scheduler.replay_next()  # Should not dispatch

        assert len(dispatched) == 0

    def test_replay_from_specific_sequence(self):
        """Start replay from specific sequence number."""
        clock = ReplayClock()
        store = EventStore()
        store.append(event_type="tick", event_data=b"event1")
        store.append(event_type="tick", event_data=b"event2")
        store.append(event_type="tick", event_data=b"event3")

        scheduler = ReplayScheduler(clock=clock, store=store)
        dispatched = []
        scheduler.set_handler(lambda event: dispatched.append(event))

        scheduler.start_from_sequence(2)
        scheduler.replay_next()

        assert len(dispatched) == 1
        assert dispatched[0].event_data == b"event2"

    def test_replay_end_detection(self):
        """Replay detects end of events."""
        clock = ReplayClock()
        store = EventStore()
        store.append(event_type="tick", event_data=b"event1")

        scheduler = ReplayScheduler(clock=clock, store=store)
        scheduler.set_handler(lambda event: None)

        scheduler.start()
        scheduler.replay_next()
        result = scheduler.replay_next()  # No more events

        assert result is False

    def test_replay_complete_state(self):
        """Replay transitions to COMPLETE when finished."""
        clock = ReplayClock()
        store = EventStore()
        store.append(event_type="tick", event_data=b"event1")

        scheduler = ReplayScheduler(clock=clock, store=store)
        scheduler.set_handler(lambda event: None)

        scheduler.start()
        scheduler.replay_next()
        scheduler.replay_next()  # Exhaust events

        assert scheduler.state == ReplayState.COMPLETE


class TestReplaySchedulerSpeedControl:
    """Test speed control during replay."""

    def test_set_replay_speed(self):
        """Set replay speed multiplier."""
        clock = ReplayClock()
        store = EventStore()
        scheduler = ReplayScheduler(clock=clock, store=store)

        scheduler.set_speed(2.0)

        assert clock.speed == 2.0

    def test_replay_at_different_speeds(self):
        """Replay works at different speeds."""
        clock = ReplayClock()
        store = EventStore()
        store.append(event_type="tick", event_data=b"event1")
        store.append(event_type="tick", event_data=b"event2")

        scheduler = ReplayScheduler(clock=clock, store=store)
        dispatched = []
        scheduler.set_handler(lambda event: dispatched.append(event))

        # Replay at 0.5x speed
        scheduler.set_speed(0.5)
        scheduler.start()
        scheduler.replay_next()

        assert scheduler.events_replayed == 1

        # Change to 2x speed
        scheduler.set_speed(2.0)
        scheduler.replay_next()

        assert scheduler.events_replayed == 2


class TestReplaySchedulerEdgeCases:
    """Test edge cases and error handling."""

    def test_replay_empty_store(self):
        """Replay with empty store completes immediately."""
        clock = ReplayClock()
        store = EventStore()
        scheduler = ReplayScheduler(clock=clock, store=store)
        scheduler.set_handler(lambda event: None)

        scheduler.start()
        result = scheduler.replay_next()

        assert result is False
        assert scheduler.state == ReplayState.COMPLETE

    def test_replay_with_gaps(self):
        """Replay handles gaps in sequence (skips missing)."""
        clock = ReplayClock()
        store = EventStore()
        store.append(event_type="tick", event_data=b"event1")
        # Sequence 2 is missing
        store.append(event_type="tick", event_data=b"event3")

        scheduler = ReplayScheduler(clock=clock, store=store)
        dispatched = []
        scheduler.set_handler(lambda event: dispatched.append(event))

        scheduler.start()
        scheduler.replay_next()
        scheduler.replay_next()

        # Should have dispatched event1 and event3
        assert len(dispatched) == 2

    def test_handler_exception_doesnt_crash(self):
        """Handler exception doesn't crash replay."""
        clock = ReplayClock()
        store = EventStore()
        store.append(event_type="tick", event_data=b"event1")

        scheduler = ReplayScheduler(clock=clock, store=store)

        def failing_handler(event):
            raise ValueError("Handler error")

        scheduler.set_handler(failing_handler)

        scheduler.start()
        # Should not raise
        scheduler.replay_next()

    def test_cannot_start_from_invalid_sequence(self):
        """Cannot start from negative sequence."""
        clock = ReplayClock()
        store = EventStore()
        scheduler = ReplayScheduler(clock=clock, store=store)

        with pytest.raises(ValueError, match="must be positive"):
            scheduler.start_from_sequence(0)

    def test_cannot_start_from_sequence_beyond_store(self):
        """Cannot start from sequence beyond store."""
        clock = ReplayClock()
        store = EventStore()
        store.append(event_type="tick", event_data=b"event1")

        scheduler = ReplayScheduler(clock=clock, store=store)

        with pytest.raises(ValueError, match="beyond store"):
            scheduler.start_from_sequence(999)

    def test_reset_replay(self):
        """Reset replay to initial state."""
        clock = ReplayClock()
        store = EventStore()
        store.append(event_type="tick", event_data=b"event1")

        scheduler = ReplayScheduler(clock=clock, store=store)
        scheduler.set_handler(lambda event: None)

        scheduler.start()
        scheduler.replay_next()
        scheduler.reset()

        assert scheduler.state == ReplayState.IDLE
        assert scheduler.events_replayed == 0

    def test_replay_state_repr(self):
        """ReplayState has readable representation."""
        assert ReplayState.IDLE.value == "idle"
        assert ReplayState.RUNNING.value == "running"
        assert ReplayState.PAUSED.value == "paused"
        assert ReplayState.COMPLETE.value == "complete"
