"""Tests for Watchdog - session crash detection and auto-recovery."""

import pytest
import asyncio
from datetime import date, datetime
from unittest.mock import MagicMock, patch

from app.domain.services.watchdog import Watchdog, SessionWatchEntry


class TestSessionWatchEntry:
    """Tests for SessionWatchEntry dataclass."""

    def test_create_entry(self):
        """Test creating a SessionWatchEntry."""
        entry = SessionWatchEntry(symbol="NIFTY")
        assert entry.symbol == "NIFTY"
        assert entry.task is None
        assert entry.restart_count == 0
        assert entry.crashed is False
        assert entry.max_restarts_per_day == 3

    def test_entry_defaults(self):
        """Test default values."""
        entry = SessionWatchEntry(symbol="BANKNIFTY")
        assert entry.last_restart_date == ""
        assert entry.last_error == ""


class TestWatchdog:
    """Tests for Watchdog class."""

    def setup_method(self):
        """Set up test watchdog."""
        self.watchdog = Watchdog(check_interval=1.0)

    def test_init(self):
        """Test watchdog initialization."""
        assert self.watchdog._check_interval == 1.0
        assert self.watchdog._sessions == {}
        assert self.watchdog._running is False
        assert self.watchdog._alerts == []

    def test_register_session(self):
        """Test registering a session task."""
        mock_task = MagicMock()
        mock_task.done.return_value = False
        mock_task.cancelled.return_value = False

        self.watchdog.register_session("NIFTY", mock_task)

        assert "NIFTY" in self.watchdog._sessions
        entry = self.watchdog._sessions["NIFTY"]
        assert entry.symbol == "NIFTY"
        assert entry.task == mock_task

    def test_register_multiple_sessions(self):
        """Test registering multiple sessions."""
        task1 = MagicMock()
        task2 = MagicMock()

        self.watchdog.register_session("NIFTY", task1)
        self.watchdog.register_session("BANKNIFTY", task2)

        assert len(self.watchdog._sessions) == 2

    def test_unregister_session(self):
        """Test unregistering a session."""
        mock_task = MagicMock()
        self.watchdog.register_session("NIFTY", mock_task)
        assert "NIFTY" in self.watchdog._sessions

        self.watchdog.unregister_session("NIFTY")
        assert "NIFTY" not in self.watchdog._sessions

    def test_unregister_nonexistent_session(self):
        """Test unregistering a session that doesn't exist."""
        # Should not raise
        self.watchdog.unregister_session("NONEXISTENT")

    @pytest.mark.asyncio
    async def test_check_sessions_no_crash(self):
        """Test _check_sessions when no tasks are crashed."""
        mock_task = MagicMock()
        mock_task.done.return_value = False
        mock_task.cancelled.return_value = False

        self.watchdog.register_session("NIFTY", mock_task)
        await self.watchdog._check_sessions()

        # No alerts should be generated
        assert len(self.watchdog._alerts) == 0
        entry = self.watchdog._sessions["NIFTY"]
        assert entry.crashed is False

    @pytest.mark.asyncio
    async def test_check_sessions_crashed_task(self):
        """Test _check_sessions when a task has crashed."""
        mock_task = MagicMock()
        mock_task.done.return_value = True
        mock_task.cancelled.return_value = False
        mock_task.exception.return_value = Exception("Test crash")

        self.watchdog.register_session("NIFTY", mock_task)
        await self.watchdog._check_sessions()

        # Alert should be generated
        assert len(self.watchdog._alerts) == 1
        alert = self.watchdog._alerts[0]
        assert alert["symbol"] == "NIFTY"
        assert "Test crash" in alert["error"]

        entry = self.watchdog._sessions["NIFTY"]
        assert entry.crashed is True
        assert "Test crash" in entry.last_error

    @pytest.mark.asyncio
    async def test_check_sessions_cancelled_task(self):
        """Test _check_sessions ignores cancelled tasks."""
        mock_task = MagicMock()
        mock_task.done.return_value = True
        mock_task.cancelled.return_value = True

        self.watchdog.register_session("NIFTY", mock_task)
        await self.watchdog._check_sessions()

        # No alerts for cancelled tasks
        assert len(self.watchdog._alerts) == 0

    def test_get_alerts(self):
        """Test getting alerts."""
        self.watchdog._alerts = [
            {"symbol": "NIFTY", "error": "crash1"},
            {"symbol": "BANKNIFTY", "error": "crash2"},
        ]

        alerts = self.watchdog.get_alerts()
        assert len(alerts) == 2

    def test_get_alerts_since(self):
        """Test getting alerts since a timestamp."""
        self.watchdog._alerts = [
            {"symbol": "NIFTY", "error": "crash1", "timestamp": "2026-05-01T10:00:00"},
            {"symbol": "BANKNIFTY", "error": "crash2", "timestamp": "2026-05-01T12:00:00"},
        ]

        alerts = self.watchdog.get_alerts(since="2026-05-01T11:00:00")
        assert len(alerts) == 1
        assert alerts[0]["symbol"] == "BANKNIFTY"

    def test_get_status(self):
        """Test getting watchdog status."""
        mock_task = MagicMock()
        self.watchdog.register_session("NIFTY", mock_task)

        status = self.watchdog.get_status()
        assert "running" in status
        assert "sessions" in status
        assert "total_alerts" in status
        assert "NIFTY" in status["sessions"]

    @pytest.mark.asyncio
    async def test_run_stop(self):
        """Test starting and stopping the watchdog."""
        assert self.watchdog._running is False

        # Start watchdog in background
        async def run_watchdog():
            await self.watchdog.start()

        task = asyncio.create_task(run_watchdog())
        await asyncio.sleep(0.1)  # Let it start
        assert self.watchdog._running is True

        # Stop watchdog
        self.watchdog.stop()
        await asyncio.sleep(0.1)
        task.cancel()
        try:
            await task
        except asyncio.CancelledError:
            pass

    def test_max_restarts_per_day(self):
        """Test max restarts per day logic."""
        entry = SessionWatchEntry(symbol="NIFTY")
        today = date.today().isoformat()

        # Simulate 3 restarts today
        entry.restart_count = 3
        entry.last_restart_date = today

        # Should not allow more restarts today
        assert entry.restart_count >= entry.max_restarts_per_day
        assert entry.last_restart_date == today

    @pytest.mark.asyncio
    async def test_restart_count_resets_on_new_day(self):
        """Test that restart count resets on a new day."""
        mock_task = MagicMock()
        mock_task.done.return_value = True
        mock_task.cancelled.return_value = False
        mock_task.exception.return_value = Exception("crash")

        # Simulate old date - should reset on check
        entry = SessionWatchEntry(
            symbol="NIFTY",
            task=mock_task,
            restart_count=3,
            last_restart_date="2026-04-30",  # Yesterday
        )
        self.watchdog._sessions["NIFTY"] = entry

        # Check sessions - should reset count, then increment (since task crashed)
        await self.watchdog._check_sessions()

        # Reset happened (3 -> 0), then incremented (0 -> 1) because task crashed
        assert entry.restart_count == 1
        assert entry.last_restart_date == date.today().isoformat()
        assert entry.crashed is True
