"""Tests for AMT cleanup Task 6 — SL watchdog closes route through the exit lifecycle.

Verifies:
- The SL watchdog force-close persists EXACTLY ONE ``trades`` row and sets the
  ``close_reason`` on the position (was: direct close+persist, skipping the
  dedup / learning / post-trade path).
- The tick path cannot duplicate the watchdog's close (shared ``_recorded_trade_ids``
  dedup guard).
- The overseer gets a non-None broadcast target via the composition root so
  overseer actions push an immediate UI update (was: ``_engine`` never injected).
"""

from __future__ import annotations

from decimal import Decimal
from unittest.mock import MagicMock, patch

import pytest

from app.application.watchdog_manager import WatchdogManager
from app.application.handlers.llm_overseer_handler import LLMOverseerHandler
from app.domain.trading.models.entities import Position
from app.domain.trading.models.enums import PositionStatus, Side, Source
from app.domain.trading.models.value_objects import OHLC


# ---------------------------------------------------------------------------
# TradingSessionService construction (mirrors test_trading_session_unit.py)
# ---------------------------------------------------------------------------


@pytest.fixture
def mock_deps():
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


@pytest.fixture
def services(mock_deps):
    with patch("app.application.services.forward_test_logger.ForwardTestLogger") as mock_fwd:
        mock_fwd.side_effect = Exception("no-op")
        from app.application.services.trading_session import TradingSessionService

        svc = TradingSessionService(
            broker=mock_deps["broker"],
            gen_ai_service=mock_deps["gen_ai"],
            storage=mock_deps["storage"],
            probability_engine=mock_deps["probability_engine"],
        )
    yield svc
    svc._llm_handler.cleanup()
    svc._overseer_handler.cleanup()
    post_trade = getattr(svc, "_post_trade_analyst", None)
    if post_trade is not None and hasattr(post_trade, "shutdown"):
        post_trade.shutdown()


def _make_position(pos_id: str, symbol: str = "NIFTY", sl: float = 95.0) -> Position:
    return Position(
        id=pos_id,
        symbol=symbol,
        side=Side.LONG,
        source=Source.LLM,
        entry_price=Decimal("100"),
        size=Decimal("1"),
        stop_loss=Decimal(str(sl)),
        take_profit=Decimal("110"),
        pnl=Decimal("0"),
        entry_time="2026-01-15T10:30:00Z",
        status=PositionStatus.OPEN,
    )


def _tick(close: float) -> OHLC:
    return OHLC(
        time="2026-01-15T10:35:00Z",
        open=close,
        high=close * 1.01,
        low=close * 0.99,
        close=close,
        volume=100.0,
    )


def _make_watchdog(svc, ltp: float) -> WatchdogManager:
    broadcaster = MagicMock()
    broadcaster.get_latest_state.return_value = {"ltp": ltp}
    wd = WatchdogManager(
        session_service=svc,
        stream_manager=MagicMock(),
        state_broadcaster=broadcaster,
    )
    wd.set_active_symbols(["NIFTY"])
    return wd


# =====================================================================
# SL watchdog → lifecycle routing
# =====================================================================


class TestWatchdogLifecycleRouting:
    def test_watchdog_close_routes_through_lifecycle_single_trade_row(
        self, services, mock_deps
    ):
        svc = services
        storage = mock_deps["storage"]
        session = svc.get_or_create_session("NIFTY")
        pos = _make_position("wd-1")
        session.portfolio.positions.append(pos)

        wd = _make_watchdog(svc, ltp=94.0)  # breaches SL=95
        wd._sl_check_symbol("NIFTY")

        assert pos.status == PositionStatus.CLOSED
        assert pos.id in svc._recorded_trade_ids
        assert pos.id in svc._exit_coordinator._recorded_close_ids
        assert storage.save_trade.call_count == 1
        assert storage.delete_open_position.call_count == 1
        payload = storage.save_trade.call_args.args[0]
        assert payload["position_id"] == "wd-1"
        assert payload["reason"] == "WATCHDOG_Stop Loss"

    def test_watchdog_close_records_close_reason(self, services, mock_deps):
        svc = services
        session = svc.get_or_create_session("NIFTY")
        pos = _make_position("wd-reason")
        session.portfolio.positions.append(pos)

        wd = _make_watchdog(svc, ltp=94.0)
        wd._sl_check_symbol("NIFTY")

        assert pos.close_reason == "WATCHDOG_Stop Loss"

    def test_tick_path_does_not_duplicate_watchdog_close(self, services, mock_deps):
        svc = services
        storage = mock_deps["storage"]
        session = svc.get_or_create_session("NIFTY")
        pos = _make_position("wd-dup")
        session.portfolio.positions.append(pos)

        wd = _make_watchdog(svc, ltp=94.0)
        wd._sl_check_symbol("NIFTY")
        assert storage.save_trade.call_count == 1

        # Tick path: a subsequent tick must NOT add a second trades row
        svc.process_tick("NIFTY", _tick(close=94.0))
        assert storage.save_trade.call_count == 1

        # Direct re-detection of the same close (e.g. stale snapshot) dedups
        svc._record_and_persist_closed_trade("NIFTY", pos, session)
        assert storage.save_trade.call_count == 1

    def test_watchdog_no_close_when_sl_not_breached(self, services, mock_deps):
        svc = services
        storage = mock_deps["storage"]
        session = svc.get_or_create_session("NIFTY")
        pos = _make_position("wd-safe")
        session.portfolio.positions.append(pos)

        wd = _make_watchdog(svc, ltp=96.0)  # above SL=95, below TP=110
        wd._sl_check_symbol("NIFTY")

        assert pos.status == PositionStatus.OPEN
        assert storage.save_trade.call_count == 0


# =====================================================================
# Overseer immediate-broadcast wiring (engine reference is not None)
# =====================================================================


class TestOverseerBroadcastWiring:
    def test_overseer_handler_guards_without_engine(self):
        gen_ai = MagicMock()
        gen_ai.is_ready.return_value = True
        handler = LLMOverseerHandler(gen_ai_service=gen_ai, trade_manager=MagicMock())
        try:
            # No engine → broadcast path is a guarded no-op (no exception)
            if handler._engine:
                handler._engine.trigger_immediate_update("NIFTY")
            assert handler._engine is None
        finally:
            handler.cleanup()

    def test_composition_root_wires_broadcast_bridge_into_overseer(self):
        from app.application.di.composition_root import (
            _OverseerBroadcastBridge,
            _wire_overseer_broadcast,
        )

        gen_ai = MagicMock()
        gen_ai.is_ready.return_value = True
        handler = LLMOverseerHandler(gen_ai_service=gen_ai, trade_manager=MagicMock())
        try:
            svc = MagicMock()
            svc._overseer_handler = handler
            _wire_overseer_broadcast(svc)

            assert handler._engine is not None
            assert isinstance(handler._engine, _OverseerBroadcastBridge)
            assert svc._overseer_broadcast_bridge is handler._engine
        finally:
            handler.cleanup()

    def test_bridge_noops_until_bound_then_forwards(self):
        from app.application.di.composition_root import _OverseerBroadcastBridge

        bridge = _OverseerBroadcastBridge()
        # Unbound → no-op (no exception)
        bridge.trigger_immediate_update("NIFTY")

        engine = MagicMock()
        bridge.bind(engine)
        bridge.trigger_immediate_update("NIFTY")
        engine.trigger_immediate_update.assert_called_once_with("NIFTY")

    def test_engine_binds_overseer_broadcast_bridge(self):
        from app.application.engine import TradingEngine
        from app.application.di.composition_root import _OverseerBroadcastBridge
        from app.application.services.trading_session import TradingSessionService

        bridge = _OverseerBroadcastBridge()
        session_service = MagicMock()
        session_service._overseer_broadcast_bridge = bridge

        container = MagicMock()
        container.resolve.side_effect = lambda t: (
            session_service if t is TradingSessionService else MagicMock()
        )

        engine = TradingEngine(container)
        assert bridge._target is engine
