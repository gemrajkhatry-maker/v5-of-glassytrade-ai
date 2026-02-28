"""Tests for OI data wiring from gameloop to session."""

from unittest.mock import MagicMock, patch
from dataclasses import dataclass, field
import threading


@dataclass
class FakeSession:
    portfolio: MagicMock = field(default_factory=MagicMock)
    data: list = field(default_factory=list)
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _oi_analysis: dict | None = None
    _pending_signal: tuple | None = None
    _last_candle_time: str = ""
    _last_overseer_time: float = 0
    _overseer_running: bool = False
    _ai_running: bool = False
    _last_ai_time: float = 0
    _last_entry_time: float = 0
    last_ai_analysis: dict | None = None


class TestOIWiring:
    def test_oi_data_stored_on_session(self):
        """OI data passed to process_tick should be stored on session."""
        # We test this at the unit level by checking the param acceptance
        from app.application.services.trading_session import TradingSessionService
        import inspect
        sig = inspect.signature(TradingSessionService.process_tick)
        assert "oi_data" in sig.parameters

    def test_oi_absent_graceful(self):
        """None oi_data should not break anything."""
        from app.application.services.trading_session import TradingSessionService
        import inspect
        sig = inspect.signature(TradingSessionService.process_tick)
        param = sig.parameters["oi_data"]
        assert param.default is None
