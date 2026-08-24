from __future__ import annotations

import asyncio
from types import SimpleNamespace
from unittest.mock import Mock

from app.application.services.engine_lifecycle import EngineLifecycle
from app.domain.ops.self_healing import DBFallbackBuffer


def test_engine_lifecycle_flushes_session_persistence_before_shutdown_returns():
    session = SimpleNamespace(
        _storage=None,
        flush_persistence=Mock(return_value=2),
        _state_manager=SimpleNamespace(get_all_sessions=lambda: {}),
        _exchange="MCX",
    )
    container = Mock()
    container.resolve.side_effect = lambda interface: session
    stream = Mock()
    watchdog = Mock()
    lifecycle = EngineLifecycle(
        container=container,
        stream_manager=stream,
        watchdog_manager=watchdog,
        state_broadcaster=Mock(),
        tick_processor=Mock(),
    )
    lifecycle._stream_task = None
    lifecycle._watchdog_task = None
    lifecycle._stale_watchdog_task = None
    lifecycle._reconciliation_task = None
    lifecycle._gc_task = None

    asyncio.run(lifecycle.shutdown())

    session.flush_persistence.assert_called_once_with()


def test_trading_session_flushes_queued_write_before_storage_close():
    from app.application.services.trading_session import TradingSessionService

    order: list[str] = []

    class Storage:
        def save_trade(self, payload):
            order.append(f"save:{payload['position_id']}")

        def close(self):
            order.append("close")

    storage = Storage()
    fallback = DBFallbackBuffer()
    fallback.buffer_write("save_trade", {"position_id": "before-close"})

    service = object.__new__(TradingSessionService)
    service._storage = storage
    service._db_fallback = fallback
    service._llm_handler = SimpleNamespace(cleanup=lambda: order.append("llm-cleanup"))
    service._overseer_handler = SimpleNamespace(cleanup=lambda: order.append("overseer-cleanup"))

    service.cleanup()
    storage.close()

    assert order == ["save:before-close", "llm-cleanup", "overseer-cleanup", "close"]
    assert fallback.buffer_size == 0


def test_entry_coordinator_exposes_standalone_persistence_flush_contract():
    from app.application.services.entry_coordinator import EntryCoordinator

    coordinator = object.__new__(EntryCoordinator)
    coordinator._storage = None
    coordinator._db_fallback = SimpleNamespace(buffer_size=0)
    assert coordinator.flush_persistence() == 0


def test_trading_session_exposes_reentrant_persistence_flush_contract():
    from app.application.services.trading_session import TradingSessionService

    service = object.__new__(TradingSessionService)
    service._storage = None
    service._db_fallback = SimpleNamespace(buffer_size=0)
    assert service.flush_persistence() == 0
