"""Runtime orchestrator and session registry."""

from __future__ import annotations

import logging
from typing import Any
from collections import defaultdict
import threading
from contextlib import suppress

from app.runtime.feeds import FeedSource
from app.runtime.contracts import RuntimeSessionState
from app.runtime.orchestrator.session import SessionRuntime
from app.domain.shared.port.storage import IStorage

logger = logging.getLogger(__name__)


class RuntimeOrchestrator:
    """Manage deterministic sessions and symbol-scoped runtime lifecycles."""

    def __init__(self, storage: IStorage | None = None):
        self._sessions: dict[str, SessionRuntime] = {}
        self._storage = storage
        self._strategy_registry: dict[str, dict[str, dict[str, Any]]] = defaultdict(dict)
        self._broker_registry: dict[str, object] = {}
        self._session_states: dict[str, RuntimeSessionState] = {}
        self._session_lock_by_id: dict[str, threading.Lock] = {}
        self._generation = 0

    @property
    def generation(self) -> int:
        return self._generation

    def create_live_session(
        self, session_id: str, feed: FeedSource, symbols: list[str],
    ) -> SessionRuntime:
        return self.start_session(session_id=session_id, feed=feed, symbols=symbols)

    def start_session(
        self, session_id: str, feed: FeedSource, symbols: list[str],
    ) -> SessionRuntime:
        lock = self._session_lock_by_id.setdefault(session_id, threading.Lock())
        with lock:
            old_session = self._sessions.get(session_id)
            if old_session is not None:
                with suppress(Exception):
                    old_session.stop()
                with suppress(Exception):
                    old_session.teardown()
                with suppress(Exception):
                    del self._strategy_registry[session_id]
                self._broker_registry.pop(session_id, None)
                self._session_states.pop(session_id, None)
            session = SessionRuntime(feed=feed, symbols=symbols, storage=self._storage)
            self._sessions[session_id] = session
            self._session_states[session_id] = RuntimeSessionState.NEW
            return session

    def get_session_state(self, session_id: str) -> RuntimeSessionState | None:
        session = self.get_session(session_id)
        if session is None:
            return None
        state = self._session_states.get(session_id)
        if state is not None:
            return state
        if getattr(session, "session_state", None) is not None:
            return session.session_state
        return RuntimeSessionState.STOPPED

    def register_strategy(
        self,
        session_id: str,
        symbol: str,
        strategy_id: str,
        handler,
        *,
        priority: int = 100,
        replace: bool = False,
    ) -> None:
        session = self.get_session(session_id)
        if session is None:
            logger.warning("Cannot register strategy for missing session_id=%s", session_id)
            return
        session.register_strategy(
            symbol=symbol,
            strategy_id=strategy_id,
            handler=handler,
            priority=priority,
            replace=replace,
        )
        self._strategy_registry[session_id][f"{symbol}:{strategy_id}"] = {
            "symbol": symbol,
            "strategy_id": strategy_id,
            "handler": handler,
            "priority": priority,
            "replace": replace,
        }

    def bind_broker(self, session_id: str, broker: object) -> None:
        session = self.get_session(session_id)
        if session is None:
            logger.warning("Cannot bind broker for missing session_id=%s", session_id)
            return
        state = self.get_session_state(session_id)
        if state in {RuntimeSessionState.STOPPING, RuntimeSessionState.FAILED}:
            raise RuntimeError(f"Cannot bind broker while session in state={state.value}")
        session.bind_broker(broker)
        self._broker_registry[session_id] = broker

    def get_session(self, session_id: str) -> SessionRuntime | None:
        return self._sessions.get(session_id)

    def start(self, session_id: str) -> bool:
        session = self.get_session(session_id)
        if session is None:
            return False
        session.start()
        self._session_states[session_id] = session.session_state
        return True

    def stop(self, session_id: str) -> bool:
        session = self.get_session(session_id)
        if session is None:
            return False
        session.stop()
        self._session_states[session_id] = RuntimeSessionState.STOPPED
        return True

    def run_once(self, session_id: str, max_ticks: int | None = None) -> list[object]:
        session = self._sessions.get(session_id)
        if session is None:
            return []
        before = session.event_count
        events = session.run_once(max_ticks=max_ticks)
        after = session.event_count
        if after > before:
            self._generation += (after - before)
        return events

    def get_active_symbols(self) -> list[str]:
        symbols = []
        for session in self._sessions.values():
            for symbol in session.symbols:
                if symbol not in symbols:
                    symbols.append(symbol)
        return symbols

    def get_history(self, sym: str) -> list[dict[str, object]] | None:
        for session in self._sessions.values():
            if sym in session.symbols:
                return session.get_history(sym, max_points=500)
        return None

    def get_latest_state(self, sym: str) -> dict | None:
        for session in self._sessions.values():
            if sym in session.symbols:
                return session.snapshot(symbol=sym)
        return None

    def teardown_all(self) -> None:
        for session in list(self._sessions.values()):
            try:
                session.teardown()
            except Exception:
                logger.exception("Session teardown failed")
        self._sessions.clear()
        self._strategy_registry.clear()
        self._broker_registry.clear()
        self._session_states.clear()
        self._session_lock_by_id.clear()
