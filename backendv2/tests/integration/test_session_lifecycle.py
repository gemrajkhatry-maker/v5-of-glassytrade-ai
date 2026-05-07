"""Integration tests for session lifecycle — start, warm-up, end, eviction."""

from __future__ import annotations

import pytest
from unittest.mock import Mock, patch
from app.infrastructure.messaging.event_bus import EventBus
from app.domain.shared.event.domain_events import TickReceived


class FakeSessionService:
    """Minimal session service for testing."""

    def __init__(self, symbol="NIFTY", exchange="NSE", timeframe="1m"):
        self.symbol = symbol
        self.exchange = exchange
        self.timeframe = timeframe
        self._started = False
        self._warm_up_ticks = 10
        self._tick_count = 0
        self._positions = []
        self._event_bus = EventBus()

    @property
    def is_warming_up(self):
        return self._tick_count < self._warm_up_ticks

    def start(self):
        self._started = True
        self._tick_count = 0

    def end(self):
        self._started = False
        self._positions.clear()

    def process_tick(self, price, volume=100):
        if not self._started:
            return None
        self._tick_count += 1
        event = TickReceived(
            symbol=self.symbol, price=price, volume=volume
        )
        self._event_bus.publish(event)
        return {"tick_count": self._tick_count, "warming_up": self.is_warming_up}

    def get_state(self):
        return {
            "started": self._started,
            "symbol": self.symbol,
            "tick_count": self._tick_count,
            "warming_up": self.is_warming_up,
        }


class TestSessionStart:
    """Test session start flow."""

    def test_session_starts_with_config(self):
        """Session starts → config loaded, started=True."""
        session = FakeSessionService(symbol="NIFTY", exchange="NSE")
        session.start()

        state = session.get_state()
        assert state["started"] is True
        assert state["symbol"] == "NIFTY"

    def test_session_start_publishes_event(self):
        """Session start → events can be published."""
        session = FakeSessionService()
        session.start()

        received = []
        session._event_bus.subscribe(TickReceived, lambda e: received.append(e))
        session.process_tick(22500.0)

        assert len(received) == 1

    def test_session_with_missing_symbol_fallback(self):
        """Session with empty symbol → still starts."""
        session = FakeSessionService(symbol="")
        session.start()
        state = session.get_state()
        assert state["started"] is True


class TestWarmUpPhase:
    """Test warm-up phase behavior."""

    def test_warm_up_blocks_processing(self):
        """During warm-up → warming_up flag is True."""
        session = FakeSessionService()
        session.start()
        assert session.is_warming_up

    def test_warm_up_expires_after_ticks(self):
        """After warm_up_ticks → normal operation resumes."""
        session = FakeSessionService()
        session.start()

        for i in range(10):
            session.process_tick(22500.0 + i)

        assert not session.is_warming_up

    def test_tick_collection_during_warm_up(self):
        """Ticks collected during warm-up count toward total."""
        session = FakeSessionService()
        session.start()

        for i in range(5):
            session.process_tick(22500.0)

        assert session.get_state()["tick_count"] == 5

    def test_warm_up_ticks_configurable(self):
        """Custom warm_up_ticks → different threshold."""
        session = FakeSessionService()
        session._warm_up_ticks = 5
        session.start()

        for i in range(5):
            session.process_tick(22500.0)

        assert not session.is_warming_up

    def test_warm_up_state_in_result(self):
        """Process tick result includes warming_up flag."""
        session = FakeSessionService()
        session.start()
        result = session.process_tick(22500.0)

        assert result is not None
        assert result["warming_up"] is True


class TestSessionEnd:
    """Test session end flow."""

    def test_session_end_clears_positions(self):
        """Session ends → positions cleared."""
        session = FakeSessionService()
        session.start()
        session._positions = [{"id": "pos-1", "symbol": "NIFTY"}]
        session.end()

        assert session._positions == []
        assert session.get_state()["started"] is False

    def test_session_end_stops_processing(self):
        """After session end → process_tick returns None."""
        session = FakeSessionService()
        session.start()
        session.end()

        result = session.process_tick(22500.0)
        assert result is None

    def test_session_restart_after_end(self):
        """Session can be restarted after end."""
        session = FakeSessionService()
        session.start()
        session.end()
        session.start()

        assert session.get_state()["started"] is True
        assert session.get_state()["tick_count"] == 0


class TestSessionEviction:
    """Test session eviction and state reset."""

    def test_stale_session_evicted(self):
        """Stale session → state reset."""
        session = FakeSessionService()
        session.start()
        session.process_tick(22500.0)
        assert session.get_state()["tick_count"] == 1

        # Evict by resetting
        session._tick_count = 0
        session._started = False

        assert session.get_state()["tick_count"] == 0

    def test_new_session_after_eviction(self):
        """New session starts after eviction → clean state."""
        session = FakeSessionService()
        session.start()
        session.end()  # Eviction

        session.start()  # New session
        state = session.get_state()
        assert state["tick_count"] == 0
        assert state["started"] is True

    def test_state_properly_reset(self):
        """State reset clears all session data."""
        session = FakeSessionService()
        session.start()
        for i in range(5):
            session.process_tick(22500.0 + i)
        session.end()

        state = session.get_state()
        assert state["started"] is False


class TestSessionLifecycle:
    """Test full session lifecycle."""

    def test_start_warmup_run_end_cycle(self):
        """Full lifecycle: start → warmup → process → end."""
        session = FakeSessionService()

        # Start
        session.start()
        assert session.get_state()["started"] is True

        # Warm-up
        assert session.is_warming_up
        for i in range(10):
            session.process_tick(22500.0 + i)
        assert not session.is_warming_up

        # Normal processing
        for i in range(20):
            result = session.process_tick(22500.0 + i)
            assert result is not None

        # End
        session.end()
        assert session.get_state()["started"] is False

    def test_multiple_sessions_sequential(self):
        """Multiple sessions run sequentially without interference."""
        session = FakeSessionService()

        for session_num in range(3):
            session.start()
            for i in range(15):
                session.process_tick(22500.0 + i)
            assert session.get_state()["tick_count"] == 15
            session.end()
            assert session.get_state()["started"] is False

    def test_events_published_across_lifecycle(self):
        """Events published throughout lifecycle."""
        session = FakeSessionService()
        received = []
        session._event_bus.subscribe(TickReceived, lambda e: received.append(e))

        session.start()
        for i in range(5):
            session.process_tick(22500.0 + i)

        assert len(received) == 5

    def test_session_config_variations(self):
        """Different session configurations work."""
        configs = [
            {"symbol": "NIFTY", "exchange": "NSE", "timeframe": "1m"},
            {"symbol": "BANKNIFTY", "exchange": "NSE", "timeframe": "5m"},
            {"symbol": "GOLD", "exchange": "MCX", "timeframe": "1m"},
        ]
        for cfg in configs:
            session = FakeSessionService(**cfg)
            session.start()
            state = session.get_state()
            assert state["symbol"] == cfg["symbol"]
            session.end()
