"""Unit tests for LossTracker."""

import json
import time
from datetime import datetime

import pytest

from app.domain.exit.service.loss_tracker import LossTracker


class InMemoryStorage:
    """Simple in-memory key-value storage for testing persistence."""

    def __init__(self):
        self._store = {}

    def persist(self, key, value):
        self._store[key] = value

    def load(self, key):
        return self._store.get(key)


class TestLossRecording:
    """Tests for loss recording functionality."""

    def test_single_loss_recorded(self):
        """A single loss is recorded and reflected in the state."""
        tracker = LossTracker()
        tracker.record_loss("RELIANCE", stop_price=2450.0)

        state = tracker.get_state()
        assert state["global_daily_losses"] == 1
        assert state["symbol_daily_losses"]["RELIANCE"] == 1
        assert state["symbol_consecutive_losses"]["RELIANCE"] == 1

    def test_multiple_symbols_tracked_independently(self):
        """Losses for different symbols are tracked independently."""
        tracker = LossTracker()
        tracker.record_loss("RELIANCE", stop_price=2450.0)
        tracker.record_loss("TCS", stop_price=3500.0)
        tracker.record_loss("RELIANCE", stop_price=2440.0)

        state = tracker.get_state()
        assert state["global_daily_losses"] == 3
        assert state["symbol_daily_losses"]["RELIANCE"] == 2
        assert state["symbol_daily_losses"]["TCS"] == 1
        assert state["symbol_consecutive_losses"]["RELIANCE"] == 2
        assert state["symbol_consecutive_losses"]["TCS"] == 1

    def test_stop_price_recorded(self):
        """The last stop price for a symbol is stored."""
        tracker = LossTracker()
        tracker.record_loss("RELIANCE", stop_price=2450.0)

        assert tracker._symbol_last_stop_price["RELIANCE"] == 2450.0

        tracker.record_loss("RELIANCE", stop_price=2440.0)
        assert tracker._symbol_last_stop_price["RELIANCE"] == 2440.0


class TestWinRecording:
    """Tests for win recording and consecutive loss reset."""

    def test_win_resets_consecutive_losses(self):
        """Recording a win resets the consecutive loss counter for that symbol."""
        tracker = LossTracker()
        tracker.record_loss("RELIANCE", stop_price=2450.0)
        tracker.record_loss("RELIANCE", stop_price=2440.0)

        state = tracker.get_state()
        assert state["symbol_consecutive_losses"]["RELIANCE"] == 2

        tracker.record_win("RELIANCE")

        state = tracker.get_state()
        assert state["symbol_consecutive_losses"]["RELIANCE"] == 0

    def test_win_preserves_daily_count(self):
        """A win does not reduce the daily loss count."""
        tracker = LossTracker()
        tracker.record_loss("RELIANCE", stop_price=2450.0)
        tracker.record_loss("RELIANCE", stop_price=2440.0)

        tracker.record_win("RELIANCE")

        state = tracker.get_state()
        assert state["symbol_daily_losses"]["RELIANCE"] == 2
        assert state["global_daily_losses"] == 2


class TestDailyLimits:
    """Tests for daily loss limit enforcement."""

    def test_symbol_specific_limit_reached(self):
        """Symbol-specific limit (3 losses) blocks further entries."""
        tracker = LossTracker(max_daily_losses=3)
        tracker.record_loss("RELIANCE", stop_price=2450.0)
        tracker.record_loss("RELIANCE", stop_price=2440.0)
        tracker.record_loss("RELIANCE", stop_price=2430.0)

        assert tracker.is_daily_limit_reached("RELIANCE") is True

    def test_global_limit_reached(self):
        """Global limit (3x max_daily_losses) blocks all symbols."""
        tracker = LossTracker(max_daily_losses=3)
        # 9 global losses across different symbols
        for i in range(9):
            tracker.record_loss(f"SYM{i}", stop_price=100.0)

        assert tracker.is_daily_limit_reached("NEW_SYM") is True

    def test_override_bypasses_limit(self):
        """Override with a higher limit allows entries beyond the default."""
        tracker = LossTracker(max_daily_losses=3)
        tracker.record_loss("RELIANCE", stop_price=2450.0)
        tracker.record_loss("RELIANCE", stop_price=2440.0)
        tracker.record_loss("RELIANCE", stop_price=2430.0)

        # Default limit reached
        assert tracker.is_daily_limit_reached("RELIANCE") is True

        # Override allows more
        assert tracker.is_daily_limit_reached_with_override("RELIANCE", max_daily_losses=5) is False


class TestEntryBlocking:
    """Tests for entry blocking logic."""

    def test_consecutive_loss_blocks_entry_within_atr_proximity(self):
        """Two+ consecutive losses block entry within 1.5x ATR of last stop."""
        tracker = LossTracker()
        tracker.record_loss("RELIANCE", stop_price=2450.0)
        tracker.record_loss("RELIANCE", stop_price=2445.0)

        # Price within 1.5x ATR of last stop (|2448 - 2445| = 3 < 15)
        blocked = tracker.should_block_entry("RELIANCE", current_price=2448.0, current_atr=10.0)
        assert blocked is True

        # Price outside 1.5x ATR of last stop (|2470 - 2445| = 25 > 15)
        blocked = tracker.should_block_entry("RELIANCE", current_price=2470.0, current_atr=10.0)
        assert blocked is False

    def test_daily_limit_blocks_entry(self):
        """Daily loss limit blocks all entries for that symbol."""
        tracker = LossTracker(max_daily_losses=3)
        tracker.record_loss("RELIANCE", stop_price=2450.0)
        tracker.record_loss("RELIANCE", stop_price=2440.0)
        tracker.record_loss("RELIANCE", stop_price=2430.0)

        blocked = tracker.should_block_entry("RELIANCE", current_price=2500.0, current_atr=10.0)
        assert blocked is True

    def test_cooldown_period_blocks_entry(self):
        """Recent exit within cooldown window blocks entry."""
        tracker = LossTracker()
        now = time.time()
        tracker.record_exit_time("RELIANCE", current_time=now)

        assert tracker.in_cooldown("RELIANCE", current_time=now + 10.0, cooldown_seconds=30.0) is True
        assert tracker.in_cooldown("RELIANCE", current_time=now + 60.0, cooldown_seconds=30.0) is False


class TestSessionPNL:
    """Tests for session PNL tracking and circuit/target detection."""

    def test_circuit_hit_detection(self):
        """Session circuit is hit when realized PNL falls below -30000."""
        tracker = LossTracker()
        tracker.add_realized_pnl(-15000.0)
        assert tracker.is_session_circuit_hit() is False

        tracker.add_realized_pnl(-16000.0)
        assert tracker.is_session_circuit_hit() is True
        assert tracker.get_session_status() == "CIRCUIT_HIT"

    def test_target_hit_detection(self):
        """Session target is hit when realized PNL reaches 15000."""
        tracker = LossTracker()
        tracker.add_realized_pnl(10000.0)
        assert tracker.is_session_target_hit() is False

        tracker.add_realized_pnl(5000.0)
        assert tracker.is_session_target_hit() is True
        assert tracker.get_session_status() == "TARGET_HIT"


class TestPersistence:
    """Tests for state persistence and reset."""

    def test_save_load_cycle_with_in_memory_storage(self):
        """LossTracker state persists and restores via storage adapter."""
        storage = InMemoryStorage()
        tracker = LossTracker(storage=storage)
        tracker.record_loss("RELIANCE", stop_price=2450.0)
        tracker.record_loss("RELIANCE", stop_price=2440.0)
        tracker.record_loss("TCS", stop_price=3500.0)

        # Verify storage has data
        raw = storage.load("daily_losses_v2")
        assert raw is not None
        payload = json.loads(raw)
        assert payload["global_count"] == 3
        assert payload["symbol_counts"]["RELIANCE"] == 2
        assert payload["symbol_counts"]["TCS"] == 1

        # Create a new tracker with the same storage
        tracker2 = LossTracker(storage=storage)
        state = tracker2.get_state()
        assert state["global_daily_losses"] == 3
        assert state["symbol_daily_losses"]["RELIANCE"] == 2
        assert state["symbol_daily_losses"]["TCS"] == 1

    def test_midnight_reset(self):
        """Daily losses reset when the clock passes midnight."""
        tracker = LossTracker()
        tracker.record_loss("RELIANCE", stop_price=2450.0)
        tracker.record_loss("RELIANCE", stop_price=2440.0)

        # Set reset time to the past to trigger a reset
        tracker._daily_loss_reset_time = time.time() - 10

        state = tracker.get_state()
        assert state["global_daily_losses"] == 0
        assert state["symbol_daily_losses"] == {}
        assert state["symbol_consecutive_losses"] == {}
