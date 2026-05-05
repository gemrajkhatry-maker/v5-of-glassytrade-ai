"""Session State Manager — manages per-symbol session state.

Ported from backend/app/application/services/session_state_manager.py (444L).
Thread-safe session creation, eviction, playbook guard, explainability tracking.
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

from app.domain.trading.model.value_objects import OHLC, OrderBook
from app.domain.trading.model.aggregates import Portfolio

if TYPE_CHECKING:
    from app.domain.trading.event_store import EventStore

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class SessionState:
    """Mutable per-symbol state."""
    symbol: str = ""
    data: list[OHLC] = field(default_factory=list)
    order_book: OrderBook | None = None
    portfolio: Portfolio = field(default_factory=lambda: Portfolio.create_default())
    last_amt: dict | None = None
    last_prediction: dict | None = None
    last_footprint: dict | None = None
    last_ai_analysis: dict | None = None

    def update_ai_analysis(self, **kwargs) -> None:
        if self.last_ai_analysis is None:
            self.last_ai_analysis = {}
        self.last_ai_analysis.update(kwargs)

    _lock: threading.RLock = field(default_factory=threading.RLock)
    _last_ai_time: float = 0
    _ai_running: bool = False
    _last_overseer_time: float = 0
    _overseer_running: bool = False
    _last_entry_time: float = 0
    _pending_signal: tuple | None = None
    _executed_signal_ids: set = field(default_factory=set)
    _last_candle_time: str = ""
    _last_tick_time: float = 0
    _playbook_guard_rejections: dict = field(default_factory=dict)
    _last_playbook_guard_reason: str = ""
    _playbook_guard_day: str = ""
    _explainability_entries: int = 0
    _explained_entries: int = 0
    _aggression_explained_entries: int = 0
    _last_explainability_alert: str = ""
    _explainability_day: str = ""
    _prior_profile: dict | None = None
    _prior_print_levels: list = field(default_factory=list)


class SessionStateManager:
    """Manages per-symbol session state with thread-safe operations."""

    def __init__(self, storage: EventStore | None = None):
        self._sessions: dict[str, SessionState] = {}
        self._session_creation_lock = threading.Lock()
        self._storage = storage
        self._eviction_interval = 3600
        self._last_eviction_check = time.time()
        self._idle_timeout = 86400  # 24h

    def get_or_create_session(self, symbol: str) -> SessionState:
        """Get or create session for symbol."""
        self._evict_idle_sessions()
        if symbol not in self._sessions:
            with self._session_creation_lock:
                if symbol not in self._sessions:
                    session = SessionState(symbol=symbol)
                    session.last_ai_analysis = {
                        "direction": "FLAT", "rationale": "Waiting for data.",
                        "confidence": "Low",
                    }
                    if self._storage:
                        try:
                            prior = self._storage.get_previous_session_profile(symbol)
                            if prior:
                                session._prior_profile = prior
                        except Exception:
                            logger.debug("Failed to load prior profile", exc_info=True)
                    self._sessions[symbol] = session
        return self._sessions[symbol]

    def _evict_idle_sessions(self) -> None:
        now = time.time()
        if now - self._last_eviction_check < self._eviction_interval:
            return
        self._last_eviction_check = now
        to_evict = []
        for sym, session in self._sessions.items():
            has_open = any(p.status == p.status.OPEN for p in session.portfolio.positions)
            if not has_open and (now - session._last_tick_time) > self._idle_timeout:
                to_evict.append(sym)
        for sym in to_evict:
            del self._sessions[sym]
            logger.info("Evicted idle session: %s", sym)

    def reset_playbook_guard(self, symbol: str | None = None) -> dict:
        targets = [symbol] if symbol else list(self._sessions.keys())
        reset = []
        for t in targets:
            s = self._sessions.get(t)
            if s:
                s._playbook_guard_rejections.clear()
                s._last_playbook_guard_reason = ""
                reset.append(t)
        return {"resetSymbols": reset, "count": len(reset)}

    def get_session_count(self) -> int:
        return len(self._sessions)

    def get_all_sessions(self) -> dict[str, SessionState]:
        return dict(self._sessions)
