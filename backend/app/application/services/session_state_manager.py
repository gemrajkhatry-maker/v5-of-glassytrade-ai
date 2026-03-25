"""Session State Manager — Manages per-symbol session state.

Responsibilities:
- Session creation and retrieval
- State persistence
- Session cleanup
- Playbook guard management
- Explainability tracking
"""

from __future__ import annotations

import logging
import threading
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

from app.config import settings

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC, OrderBook
    from app.domain.trading.models.aggregates import Portfolio
    from app.domain.fabio_ai.services.learning_engine import LearningEngine

logger = logging.getLogger(__name__)


@dataclass
class SessionState:
    """Mutable per-symbol state."""

    symbol: str = ""
    data: list[OHLC] = field(default_factory=list)
    order_book: OrderBook | None = None
    portfolio: Portfolio = field(
        default_factory=lambda: __import__(
            "app.domain.trading.models.aggregates", fromlist=["Portfolio"]
        ).Portfolio.create_default()
    )
    learning: LearningEngine = field(
        default_factory=lambda: __import__(
            "app.domain.fabio_ai.services.learning_engine", fromlist=["LearningEngine"]
        ).LearningEngine()
    )

    # Cached latest results for query access
    last_amt: dict | None = None
    last_prediction: dict | None = None
    last_footprint: dict | None = None
    last_ai_analysis: dict | None = None

    def update_ai_analysis(self, **kwargs) -> None:
        """Single source of truth for updating AI analysis state.

        All locations that write to last_ai_analysis should use this method
        instead of direct assignment, ensuring consistent merging.
        """
        if self.last_ai_analysis is None:
            self.last_ai_analysis = {}
        self.last_ai_analysis.update(kwargs)

    # Thread safety lock for portfolio reads/writes AND throttle flags
    _lock: threading.Lock = field(default_factory=threading.Lock)

    # LLM throttling state — MUST be accessed under _lock
    _last_ai_time: float = 0
    _ai_running: bool = False

    # Overseer throttling state — MUST be accessed under _lock
    _last_overseer_time: float = 0
    _overseer_running: bool = False

    # Last entry time — for minimum gap between entries
    _last_entry_time: float = 0

    # Pending signal from LLM worker thread — drained on next process_tick
    # This ensures portfolio mutations always happen on the main thread.
    _pending_signal: tuple | None = None  # (symbol, Signal) or None

    # Idempotency: track executed signal IDs to prevent duplicate position openings
    _executed_signal_ids: set = field(default_factory=set)

    # Track last candle time — LLM only fires on new candle boundaries
    _last_candle_time: str = ""

    # Live structural guard telemetry for frontend/runtime QA
    _playbook_guard_rejections: dict[str, int] = field(default_factory=dict)
    _last_playbook_guard_reason: str = ""
    _playbook_guard_day: str = ""
    _explainability_entries: int = 0
    _explained_entries: int = 0
    _aggression_explained_entries: int = 0
    _last_explainability_alert: str = ""
    _explainability_day: str = ""


class SessionStateManager:
    """Manages per-symbol session state.

    This module encapsulates all session state management logic, providing
    a single source of truth for session state across the codebase.
    """

    def __init__(self, storage=None):
        self._sessions: dict[str, SessionState] = {}
        self._session_creation_lock = threading.Lock()
        self._storage = storage

        # Session eviction — prevent unbounded memory growth
        self._session_eviction_interval = 3600  # check every hour
        self._last_eviction_check = time.time()
        self._session_idle_timeout = 86400  # 24 hours

    def get_or_create_session(self, symbol: str) -> SessionState:
        """Get or create a session for the symbol.

        Args:
            symbol: Trading symbol

        Returns:
            SessionState for the symbol
        """
        self._evict_idle_sessions()
        if symbol not in self._sessions:
            with self._session_creation_lock:
                if symbol not in self._sessions:  # double-check after acquiring lock
                    new_session = SessionState(symbol=symbol)
                    new_session.last_ai_analysis = {
                        "direction": "FLAT",
                        "rationale": "Waiting for first LLM call.",
                        "confidence": "Low",
                        "input_prompt": "",
                        "raw_output": "",
                    }
                    # Load prior session profile for gap analysis
                    if self._storage:
                        try:
                            _market = settings.DEFAULT_EXCHANGE
                            prior = self._storage.get_previous_session_profile(
                                symbol, _market
                            )
                            if prior:
                                new_session._prior_profile = prior
                                # Extract prior session print levels for cross-session
                                # structural level persistence (Gap #10)
                                new_session._prior_print_levels = [
                                    p["price"] for p in prior.get("print_levels", [])
                                ]
                                logger.info(
                                    "Loaded prior session profile for %s: POC=%.1f VAH=%.1f VAL=%.1f print_levels=%d",
                                    symbol,
                                    prior.get("poc", 0),
                                    prior.get("vah", 0),
                                    prior.get("val", 0),
                                    len(new_session._prior_print_levels),
                                )
                        except Exception:
                            logger.debug(
                                "Failed to load prior session profile", exc_info=True
                            )

                    self._sessions[symbol] = new_session
        return self._sessions[symbol]

    def _evict_idle_sessions(self) -> None:
        """Remove sessions idle for > 24 hours with no open positions."""
        now = time.time()
        if now - self._last_eviction_check < self._session_eviction_interval:
            return
        self._last_eviction_check = now
        to_evict = []
        for symbol, session in self._sessions.items():
            last_tick = getattr(session, "_last_tick_time", 0)
            has_positions = (
                any(p.status == "OPEN" for p in session.portfolio.positions)
                if hasattr(session, "portfolio")
                else False
            )
            if not has_positions and (now - last_tick) > self._session_idle_timeout:
                to_evict.append(symbol)
        for symbol in to_evict:
            del self._sessions[symbol]
            logger.info("Evicted idle session: %s", symbol)

    @staticmethod
    def _session_day_from_timestamp(timestamp: str) -> str:
        """Get session day from timestamp.

        Args:
            timestamp: ISO timestamp string

        Returns:
            Session day string (YYYY-MM-DD)
        """
        ist = timezone(timedelta(hours=5, minutes=30))
        try:
            stripped = str(timestamp).strip()
            if (
                stripped.replace(".", "", 1).lstrip("-").isdigit()
                and "T" not in stripped
                and len(stripped) >= 9
            ):
                dt = datetime.fromtimestamp(float(stripped), tz=timezone.utc)
            else:
                dt = datetime.fromisoformat(stripped.replace("Z", "+00:00"))
        except Exception:
            return datetime.now(ist).date().isoformat()
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(ist).date().isoformat()

    @staticmethod
    def _record_playbook_guard_rejection(session: SessionState, reason: str) -> None:
        """Record a playbook guard rejection.

        Args:
            session: Session state
            reason: Rejection reason
        """
        session._playbook_guard_rejections[reason] = (
            session._playbook_guard_rejections.get(reason, 0) + 1
        )
        session._last_playbook_guard_reason = reason

    @staticmethod
    def _playbook_guard_total(session: SessionState) -> int:
        """Get total playbook guard rejections.

        Args:
            session: Session state

        Returns:
            Total rejection count
        """
        return sum(getattr(session, "_playbook_guard_rejections", {}).values())

    @staticmethod
    def _playbook_guard_tripped(session: SessionState) -> bool:
        """Check if playbook guard is tripped.

        Args:
            session: Session state

        Returns:
            True if guard is tripped
        """
        return (
            SessionStateManager._playbook_guard_total(session)
            >= settings.PLAYBOOK_GUARD_MAX_REJECTIONS
        )

    def _reset_playbook_guard_state(self, session: SessionState, symbol: str) -> None:
        """Reset playbook guard state.

        Args:
            session: Session state
            symbol: Trading symbol
        """
        session._playbook_guard_rejections.clear()
        session._last_playbook_guard_reason = ""

    @staticmethod
    def _reset_explainability_state(session: SessionState) -> None:
        """Reset explainability state.

        Args:
            session: Session state
        """
        session._explainability_entries = 0
        session._explained_entries = 0
        session._aggression_explained_entries = 0
        session._last_explainability_alert = ""

    @staticmethod
    def _has_aggression_feature_driver(
        feature_drivers: tuple[str, ...] | list[str] | None,
    ) -> bool:
        """Check if feature drivers include aggression.

        Args:
            feature_drivers: Feature driver list

        Returns:
            True if aggression feature driver is present
        """
        if not feature_drivers:
            return False
        return any(
            str(driver or "").startswith(("orderflow:", "aggression:", "liquidity:"))
            for driver in feature_drivers
        )

    def _record_explainability_entry(
        self, session: SessionState, feature_drivers: tuple[str, ...] | list[str] | None
    ) -> None:
        """Record an explainability entry.

        Args:
            session: Session state
            feature_drivers: Feature driver list
        """
        session._explainability_entries += 1
        if feature_drivers:
            session._explained_entries += 1
        if self._has_aggression_feature_driver(feature_drivers):
            session._aggression_explained_entries += 1

        min_trades = settings.EXPLAINABILITY_ALERT_MIN_TRADES
        if session._explainability_entries < min_trades:
            session._last_explainability_alert = ""
            return

        coverage = (
            (session._explained_entries / session._explainability_entries * 100.0)
            if session._explainability_entries
            else 0.0
        )
        aggression = (
            (
                session._aggression_explained_entries
                / session._explainability_entries
                * 100.0
            )
            if session._explainability_entries
            else 0.0
        )
        if coverage < settings.EXPLAINABILITY_MIN_DRIVER_COVERAGE_PCT:
            session._last_explainability_alert = "LOW_FEATURE_DRIVER_COVERAGE"
            return
        if aggression < settings.EXPLAINABILITY_MIN_AGGRESSION_DRIVER_PCT:
            session._last_explainability_alert = "LOW_AGGRESSION_DRIVER_RATE"
            return
        session._last_explainability_alert = ""

    def _maybe_reset_symbol_state(
        self, session: SessionState, symbol: str, tick_time: str
    ) -> None:
        """Reset symbol state on new session day.

        Args:
            session: Session state
            symbol: Trading symbol
            tick_time: Tick timestamp
        """
        day_key = self._session_day_from_timestamp(tick_time)
        if not session._playbook_guard_day:
            session._playbook_guard_day = day_key
        if not session._explainability_day:
            session._explainability_day = day_key
        if (
            session._playbook_guard_day == day_key
            and session._explainability_day == day_key
        ):
            return
        session._playbook_guard_day = day_key
        session._explainability_day = day_key
        self._reset_playbook_guard_state(session, symbol)
        self._reset_explainability_state(session)
        logger.info(
            "Reset runtime QA state for %s on new session day %s", symbol, day_key
        )

    def reset_playbook_guard(self, symbol: str | None = None) -> dict:
        """Clear playbook-guard rejections for one symbol or all active sessions.

        Args:
            symbol: Trading symbol (optional, resets all if None)

        Returns:
            Reset result dictionary
        """
        reset_symbols: list[str] = []
        targets = [symbol] if symbol else list(self._sessions.keys())
        for target in targets:
            session = self._sessions.get(target)
            if session is None:
                continue
            self._reset_playbook_guard_state(session, target)
            session._playbook_guard_day = (
                datetime.now(timezone(timedelta(hours=5, minutes=30)))
                .date()
                .isoformat()
            )
            self._reset_explainability_state(session)
            session._explainability_day = session._playbook_guard_day
            reset_symbols.append(target)
        return {
            "resetSymbols": reset_symbols,
            "count": len(reset_symbols),
        }

    def get_all_sessions(self) -> dict[str, SessionState]:
        """Get all active sessions.

        Returns:
            Dictionary of symbol to SessionState
        """
        return dict(self._sessions)

    def get_session_count(self) -> int:
        """Get count of active sessions.

        Returns:
            Number of active sessions
        """
        return len(self._sessions)
