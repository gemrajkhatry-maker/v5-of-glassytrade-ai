"""Unit tests for the four live-path critical wiring bugs (Task 6).

Covers:
  1. allow_short pinned False — composition_root imported a nonexistent
     ``app.config.features``; must resolve from ``app.shared.config_features``.
  2. /api/ai/analyze crash — init_singletons received the raw ILLMInference
     adapter (no ``analyze_market``) instead of a GenerativeAIService.
  3. pre-candle advisor inert — the callback was never set, so advisories
     never reached ``session.last_ai_analysis``.
  4. llm_overseer flag ignored — the YAML feature flag was never read, so
     LLMOverseerHandler ran unconditionally.
"""

from __future__ import annotations

import threading
from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest

from app.application.handlers.llm_overseer_handler import LLMOverseerHandler


# =====================================================================
# Fix 1 — allow_short resolution
# =====================================================================

class TestAllowShort:
    def test_resolve_allow_short_reads_flag(self):
        """allow_short must come from the flag system, not be pinned False."""
        from app.application.di.composition_root import _resolve_allow_short
        from app.config import settings as _settings

        resolved = _resolve_allow_short()
        assert isinstance(resolved, bool)
        # strategies/*.yaml set allow_short: true — the broken import defaulted
        # to False; the fixed path must surface the configured flag value.
        assert resolved is bool(_settings.ALLOW_SHORT)
        assert resolved is True

    def test_composed_trading_session_respects_allow_short(self):
        """The allow_short resolved in the composition root reaches the session."""
        from config.consolidated import ConsolidatedConfig as Configuration
        from app.application.di.composition_root import compose_container
        from app.application.services.trading_session import TradingSessionService

        config = Configuration.from_unified()
        container = compose_container(config)
        session = container.resolve(TradingSessionService)
        assert session._allow_short is True


# =====================================================================
# Fix 2 — gen_ai_service passed to init_singletons has analyze_market
# =====================================================================

class TestGenAiServiceWiring:
    def test_init_singletons_receives_generative_ai_service(self):
        """The gen_ai_service wired by main.py must expose analyze_market()."""
        import app.main  # noqa: F401 — module-level bootstrap calls init_singletons
        import app.api.dependencies as deps

        service = deps._gen_ai_service
        assert service is not None
        assert hasattr(service, "analyze_market")
        assert callable(service.analyze_market)


# =====================================================================
# Fix 3 — pre-candle advisor callback
# =====================================================================

@pytest.fixture
def mock_deps():
    """Minimal mocked dependencies for TradingSessionService."""
    broker = MagicMock()
    gen_ai = MagicMock()
    gen_ai.is_ready.return_value = False
    storage = MagicMock()
    storage.get_recent_trades.return_value = []
    storage.get_previous_session_profile.return_value = None
    storage.load_open_positions.return_value = []
    storage.kv_get.return_value = None
    probability_engine = MagicMock()
    probability_engine.is_ready.return_value = False

    return {
        "broker": broker,
        "gen_ai": gen_ai,
        "storage": storage,
        "probability_engine": probability_engine,
    }


def _make_service(mock_deps):
    with patch("app.application.services.forward_test_logger.ForwardTestLogger") as mock_fwd:
        mock_fwd.side_effect = Exception("no-op")
        from app.application.services.trading_session import TradingSessionService
        return TradingSessionService(
            broker=mock_deps["broker"],
            gen_ai_service=mock_deps["gen_ai"],
            storage=mock_deps["storage"],
            probability_engine=mock_deps["probability_engine"],
        )


@pytest.fixture
def cleanup_service_handlers():
    services = []
    yield services
    for svc in services:
        if hasattr(svc, "_llm_handler"):
            svc._llm_handler.cleanup()
        if hasattr(svc, "_overseer_handler"):
            svc._overseer_handler.cleanup()


class TestPreCandleAdvisorWiring:
    def test_pre_candle_advisor_callback_is_set(self, mock_deps, cleanup_service_handlers):
        """PreCandleAdvisor must have a callback wired so advisories flow."""
        svc = _make_service(mock_deps)
        cleanup_service_handlers.append(svc)

        advisor = svc._pre_candle_advisor
        assert advisor._on_advisory is not None
        assert callable(advisor._on_advisory)

    def test_pre_candle_advisory_persists_to_session(self, mock_deps, cleanup_service_handlers):
        """Advisory results must land in session.last_ai_analysis."""
        svc = _make_service(mock_deps)
        cleanup_service_handlers.append(svc)

        advisory = SimpleNamespace(
            symbol="NIFTY",
            scenario="range build near POC",
            expected_setup="mean reversion long",
            key_levels="99.5 / 100.5",
        )
        svc._on_pre_candle_advisory(advisory)

        session = svc.get_or_create_session("NIFTY")
        stored = session.last_ai_analysis["pre_candle_advisory"]
        assert stored["scenario"] == "range build near POC"
        assert stored["expected_setup"] == "mean reversion long"
        assert stored["key_levels"] == "99.5 / 100.5"


# =====================================================================
# Fix 4 — llm_overseer feature flag
# =====================================================================

_created_handlers = []


@pytest.fixture(autouse=True)
def cleanup_handlers():
    yield
    for handler in _created_handlers:
        handler.cleanup()
    _created_handlers.clear()


def _make_overseer():
    adapter = MagicMock()
    adapter.predict.return_value = '{"action":"HOLD","reason":"test"}'
    gen_ai = MagicMock()
    gen_ai.llm_adapter = adapter
    gen_ai.is_ready.return_value = True

    handler = LLMOverseerHandler(
        gen_ai_service=gen_ai,
        trade_manager=MagicMock(),
        storage=MagicMock(),
    )
    _created_handlers.append(handler)
    return handler


@dataclass
class FakeSession:
    portfolio: MagicMock = field(default_factory=MagicMock)
    data: list = field(default_factory=list)
    last_ai_analysis: dict | None = None
    _lock: threading.Lock = field(default_factory=threading.Lock)
    _last_overseer_time: float = 0
    _overseer_running: bool = False
    _last_ai_time: float = 0
    _ai_running: bool = False


def _flag_overseer(monkeypatch, enabled: bool):
    from app.config import settings

    fake_mode = MagicMock()
    fake_mode.system_config.flags.llm_overseer = enabled
    monkeypatch.setattr(settings, "get_mode_config", lambda: fake_mode)


class TestOverseerFlag:
    def test_overseer_enabled_when_flag_on(self):
        handler = _make_overseer()
        assert handler._overseer_enabled() is True

    def test_overseer_disabled_when_flag_off(self, monkeypatch):
        _flag_overseer(monkeypatch, enabled=False)
        handler = _make_overseer()
        assert handler._overseer_enabled() is False

    def test_run_overseer_skipped_when_flag_off(self, monkeypatch):
        _flag_overseer(monkeypatch, enabled=False)
        handler = _make_overseer()

        mock_pos = MagicMock()
        mock_pos.is_open = True
        mock_pos.symbol = "SYM"
        session = FakeSession()
        session.portfolio.positions = [mock_pos]

        handler.run_overseer(session, "SYM", MagicMock(), MagicMock())

        assert session._overseer_running is False
        assert "SYM" not in handler._llm_queues

    def test_run_overseer_queues_when_flag_on(self, monkeypatch):
        _flag_overseer(monkeypatch, enabled=True)
        handler = _make_overseer()

        mock_pos = MagicMock()
        mock_pos.is_open = True
        mock_pos.symbol = "SYM"
        mock_pos.id = "pos-1"
        mock_pos.side.value = "LONG"
        mock_pos.entry_price = 100.0
        mock_pos.metadata = {}
        mock_pos.partial_taken = False
        session = FakeSession()
        session.portfolio.positions = [mock_pos]

        tick = MagicMock()
        tick.close = 105.0
        tick.delta = 10.0
        tick.vwap = 100.0
        tick.volume = 1000

        amt = MagicMock()
        amt.market_state = "BALANCED"
        amt.poc = 100.0
        amt.value_area_high = 105.0
        amt.value_area_low = 95.0
        amt.cvd_slope = 0.0
        amt.cvd_divergence = None
        amt.aggressive_prints = []
        amt.session_vwap = 100.0
        amt.hvns = []
        amt.lvns = []
        amt.leg_poc = 0
        amt.leg_lvns = []
        amt.profile_shape = "D"
        amt.lvn_play = None

        handler.run_overseer(session, "SYM", tick, amt)
        assert "SYM" in handler._llm_queues
        assert session._overseer_running is True
