"""
Tests for Replay Infrastructure - Event Clock.

Tests cover:
- LiveClock real-time behavior
- ReplayClock simulated time
- Speed control (0.5x, 1x, 2x, 10x)
- Pause/resume/stop/reset
- State transitions
- Edge cases
"""

import time
from datetime import datetime, timedelta, timezone

import pytest

from brokersv2.replay.event_clock import ClockState, EventClock, LiveClock, ReplayClock


class TestLiveClock:
    """Test real-time clock behavior."""

    def test_live_clock_returns_current_time(self):
        """LiveClock returns current UTC time."""
        clock = LiveClock()
        before = datetime.now(timezone.utc)
        result = clock.now()
        after = datetime.now(timezone.utc)

        assert before <= result <= after

    def test_live_clock_state_is_running(self):
        """LiveClock state is always RUNNING."""
        clock = LiveClock()
        assert clock.state() == ClockState.RUNNING

    def test_live_clock_sleep_blocks(self):
        """LiveClock.sleep blocks for real duration."""
        clock = LiveClock()
        start = time.time()
        clock.sleep(0.1)
        elapsed = time.time() - start

        assert elapsed >= 0.1

    def test_live_clock_repr(self):
        """String representation."""
        clock = LiveClock()
        assert repr(clock) == "LiveClock()"


class TestReplayClockInitialization:
    """Test ReplayClock initialization."""

    def test_default_start_time(self):
        """Default start time is now."""
        before = datetime.now(timezone.utc)
        clock = ReplayClock()
        after = datetime.now(timezone.utc)

        assert before <= clock._start_time <= after

    def test_custom_start_time(self):
        """Custom start time is respected."""
        start = datetime(2024, 1, 1, 9, 15, 0, tzinfo=timezone.utc)
        clock = ReplayClock(start_time=start)

        assert clock._start_time == start

    def test_default_speed(self):
        """Default speed is 1.0."""
        clock = ReplayClock()
        assert clock.speed == 1.0

    def test_custom_speed(self):
        """Custom speed is set."""
        clock = ReplayClock(speed=2.0)
        assert clock.speed == 2.0

    def test_initial_state_is_stopped(self):
        """Initial state is STOPPED."""
        clock = ReplayClock()
        assert clock.state() == ClockState.STOPPED


class TestReplayClockSpeedControl:
    """Test speed manipulation."""

    def test_set_speed_valid(self):
        """Set valid speed values."""
        clock = ReplayClock()
        clock.set_speed(0.5)
        assert clock.speed == 0.5

        clock.set_speed(2.0)
        assert clock.speed == 2.0

        clock.set_speed(10.0)
        assert clock.speed == 10.0

    def test_set_speed_invalid(self):
        """Reject invalid speed values."""
        clock = ReplayClock()

        with pytest.raises(ValueError, match="Speed must be > 0"):
            clock.set_speed(0)

        with pytest.raises(ValueError, match="Speed must be > 0"):
            clock.set_speed(-1.0)


class TestReplayClockStateTransitions:
    """Test clock state management."""

    def test_start_clock(self):
        """Start transitions to RUNNING."""
        clock = ReplayClock()
        clock.start()

        assert clock.state() == ClockState.RUNNING

    def test_pause_clock(self):
        """Pause transitions to PAUSED."""
        clock = ReplayClock()
        clock.start()
        clock.pause()

        assert clock.state() == ClockState.PAUSED

    def test_resume_clock(self):
        """Resume transitions to RUNNING."""
        clock = ReplayClock()
        clock.start()
        clock.pause()
        clock.resume()

        assert clock.state() == ClockState.RUNNING

    def test_stop_clock(self):
        """Stop transitions to STOPPED."""
        clock = ReplayClock()
        clock.start()
        clock.stop()

        assert clock.state() == ClockState.STOPPED

    def test_resume_from_stopped_no_effect(self):
        """Resume from stopped has no effect."""
        clock = ReplayClock()
        clock.resume()

        assert clock.state() == ClockState.STOPPED


class TestReplayClockTimeProgression:
    """Test time advancement."""

    def test_now_returns_start_when_stopped(self):
        """Clock returns start time when stopped."""
        start = datetime(2024, 1, 1, 9, 15, 0, tzinfo=timezone.utc)
        clock = ReplayClock(start_time=start)

        assert clock.now() == start

    def test_elapsed_calculation(self):
        """Elapsed time is calculated correctly."""
        start = datetime(2024, 1, 1, 9, 15, 0, tzinfo=timezone.utc)
        clock = ReplayClock(start_time=start)

        # Simulate time advancement
        clock._current_time = start + timedelta(seconds=60)

        assert clock.elapsed() == timedelta(seconds=60)

    def test_sleep_advances_time_when_paused(self):
        """Sleep advances time without real delay when paused."""
        start = datetime(2024, 1, 1, 9, 15, 0, tzinfo=timezone.utc)
        clock = ReplayClock(start_time=start)
        clock.start()
        clock.pause()

        before = clock.now()
        clock.sleep(10.0)  # Should advance by 10 seconds
        after = clock.now()

        assert (after - before) == timedelta(seconds=10.0)

    def test_reset_clock(self):
        """Reset returns to start time."""
        start = datetime(2024, 1, 1, 9, 15, 0, tzinfo=timezone.utc)
        clock = ReplayClock(start_time=start)
        clock.start()
        clock._current_time = start + timedelta(hours=1)

        clock.reset()

        assert clock.now() == start
        assert clock.state() == ClockState.STOPPED

    def test_reset_with_new_time(self):
        """Reset with new start time."""
        start = datetime(2024, 1, 1, 9, 15, 0, tzinfo=timezone.utc)
        new_start = datetime(2024, 2, 1, 10, 0, 0, tzinfo=timezone.utc)
        clock = ReplayClock(start_time=start)

        clock.reset(new_start_time=new_start)

        assert clock.now() == new_start


class TestReplayClockEdgeCases:
    """Test edge cases and error conditions."""

    def test_multiple_pause_calls(self):
        """Multiple pause calls are idempotent."""
        clock = ReplayClock()
        clock.start()
        clock.pause()
        clock.pause()  # Should not error

        assert clock.state() == ClockState.PAUSED

    def test_multiple_start_calls(self):
        """Multiple start calls reset last_real_time."""
        clock = ReplayClock()
        clock.start()
        clock.start()  # Should not error

        assert clock.state() == ClockState.RUNNING

    def test_repr_contains_state_info(self):
        """Repr contains key state information."""
        start = datetime(2024, 1, 1, 9, 15, 0, tzinfo=timezone.utc)
        clock = ReplayClock(start_time=start, speed=2.0)

        repr_str = repr(clock)
        assert "2024" in repr_str
        assert "speed=2.0" in repr_str
