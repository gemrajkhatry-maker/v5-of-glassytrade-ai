"""State Broadcaster — Assembles and broadcasts state snapshots over WebSocket.

Extracted from engine.py. Responsibilities:
- WebSocket state assembly
- Snapshot building for viewers
- Generation counter management
- Viewer notification with throttling
"""

from __future__ import annotations

import asyncio
import copy
import logging
import threading
from typing import TYPE_CHECKING, Any

from app.application.services.state_snapshot_builder import build_state_snapshot
from app.infrastructure.serialization.schemas import ohlc_to_dto

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)

# Throttle interval for viewer notifications (seconds)
_NOTIFY_THROTTLE_SECS = 0.15


class StateBroadcaster:
    """Assembles and broadcasts state snapshots over WebSocket.

    Handles:
    - Per-symbol latest state snapshots
    - Generation counter for viewer synchronization
    - Throttled notifications to prevent flooding
    - Thread-safe state updates
    """

    def __init__(self):
        """Initialize state broadcaster."""
        # Per-symbol latest state snapshot (read by WS viewers)
        self._latest_states: dict[str, dict] = {}

        # Generation counter + condition for viewer notification
        self._generation: int = 0
        self._condition: asyncio.Condition = asyncio.Condition()

        # Notification throttling
        self._last_notify_time: float = 0.0
        self._notify_scheduled: bool = False
        self._notify_task: asyncio.Task | None = None

        # Per-symbol locks for _latest_states read-modify-write protection
        self._state_locks: dict[str, threading.Lock] = {}

        # Event loop reference for cross-thread notifications
        self._loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def set_event_loop(self, loop: asyncio.AbstractEventLoop) -> None:
        """Set the event loop for cross-thread notifications.

        Args:
            loop: The running event loop
        """
        self._loop = loop

    # ------------------------------------------------------------------
    # State Access (for WS viewers)
    # ------------------------------------------------------------------

    def get_latest_state(self, symbol: str) -> dict | None:
        """Read-only access for WS viewers.

        Returns a shallow copy of the state dict with a selective deep copy of
        only the mutable ``portfolio`` value (which contains Position objects).
        This avoids the overhead of deep-copying the entire state on every
        viewer poll while still preventing mutation of shared portfolio data.

        Args:
            symbol: Trading symbol

        Returns:
            State dict copy or None if no state exists
        """
        lock = self._state_locks.get(symbol)
        state = self._latest_states.get(symbol)
        if state is None:
            return None

        if lock:
            with lock:
                state = self._latest_states.get(symbol)
                if state is None:
                    return None
                state = dict(state)
        else:
            state = dict(state)

        try:
            if "portfolio" in state:
                state["portfolio"] = copy.deepcopy(state["portfolio"])
            return state
        except Exception:
            return copy.deepcopy(state)

    def get_all_latest_states(self) -> dict[str, dict]:
        """All symbol states for initial WS sync.

        Returns:
            Dict of symbol -> state
        """
        return dict(self._latest_states)

    def set_state(self, symbol: str, state: dict) -> None:
        """Set state for a symbol (thread-safe).

        Args:
            symbol: Trading symbol
            state: State dict to set
        """
        lock = self._state_locks.setdefault(symbol, threading.Lock())
        with lock:
            # Deep copy nested mutable structures to avoid race conditions
            if "portfolio" in state:
                state = dict(state)
                state["portfolio"] = copy.deepcopy(state["portfolio"])
            if "amt" in state:
                state = dict(state)
                state["amt"] = copy.deepcopy(state["amt"])
            self._latest_states[symbol] = state

    def update_state(self, symbol: str, updates: dict) -> None:
        """Merge updates into existing state (thread-safe).

        Args:
            symbol: Trading symbol
            updates: Dict of fields to update
        """
        lock = self._state_locks.setdefault(symbol, threading.Lock())
        with lock:
            prev = self._latest_states.get(symbol, {})
            prev = dict(prev)
            prev.update(updates)
            self._latest_states[symbol] = prev

    # ------------------------------------------------------------------
    # Generation Counter
    # ------------------------------------------------------------------

    @property
    def generation(self) -> int:
        """Get current generation counter."""
        return self._generation

    async def wait_for_update(self, known_gen: int, timeout: float = 5.0) -> int:
        """Block until generation advances past known_gen.

        Args:
            known_gen: The generation the caller already knows
            timeout: Max wait time in seconds

        Returns:
            New generation value
        """
        async with self._condition:
            try:
                await asyncio.wait_for(
                    self._condition.wait_for(lambda: self._generation > known_gen),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                pass
            return self._generation

    # ------------------------------------------------------------------
    # Viewer Notification
    # ------------------------------------------------------------------

    async def notify_viewers(self, force: bool = False) -> None:
        """Notify all waiting viewers of a state update.

        Throttles notifications to prevent flooding clients.

        Args:
            force: If True, bypass throttling
        """
        now = asyncio.get_event_loop().time()
        if not force and now - self._last_notify_time < _NOTIFY_THROTTLE_SECS:
            if not self._notify_scheduled:
                self._notify_scheduled = True
                self._notify_task = asyncio.create_task(self._delayed_notify())
            return

        self._last_notify_time = now
        self._notify_scheduled = False
        async with self._condition:
            self._generation += 1
            self._condition.notify_all()

    async def _delayed_notify(self) -> None:
        """Delayed notification for throttling."""
        await asyncio.sleep(_NOTIFY_THROTTLE_SECS)
        await self.notify_viewers(force=True)

    def schedule_notification(self) -> None:
        """Schedule viewer notification from any thread.

        Uses the stored event loop reference to schedule notification
        from background threads.
        """
        if self._loop and not self._loop.is_closed():
            logger.info("Scheduling viewer notification via event loop")
            self._loop.call_soon_threadsafe(
                lambda: asyncio.create_task(self.notify_viewers(force=True))
            )
        else:
            logger.warning(
                "No event loop available for notification (loop=%s)", self._loop
            )

    # ------------------------------------------------------------------
    # Immediate Update Trigger (for cross-thread notifications)
    # ------------------------------------------------------------------

    def trigger_immediate_update(
        self,
        symbol: str,
        session,
        session_service,
        current_depth: dict,
        range_builder_dict: dict | None,
    ) -> None:
        """Build fresh state snapshot for symbol and notify all viewers.

        Thread-safe: can be called from background threads (e.g., overseer).
        Uses the same snapshot builder as the regular tick pipeline.

        Args:
            symbol: Trading symbol
            session: TradingSession instance
            session_service: TradingSessionService for dependencies
            current_depth: Current depth book dict
            range_builder_dict: Range bar dict for visualization
        """
        try:
            logger.info("trigger_immediate_update called for %s", symbol)
            if not session:
                logger.warning("No session for symbol %s", symbol)
                return

            # Build fresh snapshot using state_snapshot_builder
            state = build_state_snapshot(
                session,
                session_service._risk_coordinator,
                session_service._rl_handler,
                session_service._lifecycle_handler,
            )

            # Enrich with engine-specific fields

            # Get latest tick from session data
            try:
                last_tick = session.data[-1] if session.data else None
            except (KeyError, AttributeError) as e:
                logger.debug("Last tick retrieval failed: %s", e)
                last_tick = None

            if last_tick:
                try:
                    state["tick"] = ohlc_to_dto(last_tick)
                except (KeyError, AttributeError, TypeError) as e:
                    logger.debug("OHLC serialization failed: %s", e)
                    state["tick"] = {}
                state["ltp"] = float(last_tick.close)
            else:
                state["tick"] = {}
                state["ltp"] = getattr(session, "_last_price", 0.0)

            state["oi"] = getattr(session, "_last_oi", 0)
            state["_symbol"] = symbol
            # Lazy import to avoid circular dependency
            from app.application.engine import _depth_to_dto
            state["depth"] = _depth_to_dto(current_depth.get("book") if current_depth else None, symbol=symbol)

            # Range bars (visualization)
            if range_builder_dict:
                state["rangeBars"] = range_builder_dict

            # Update state (thread-safe)
            self.set_state(symbol, state)
            logger.info("Updated _latest_states for %s with fresh snapshot", symbol)

            # Notify WebSocket viewers
            self.schedule_notification()

        except (ConnectionError, RuntimeError, OSError) as e:
            logger.error("WebSocket notification failed: %s", e)

    def build_minimal_state(self, symbol: str, session) -> dict:
        """Fallback state builder with cached session data.

        Args:
            symbol: Trading symbol
            session: TradingSession instance

        Returns:
            Minimal state dict
        """
        return {
            "_symbol": symbol,
            "ltp": getattr(session, "_last_price", 0.0),
            "genAIAnalysis": getattr(session, "last_ai_analysis", None),
            "amt": getattr(session, "last_amt", None),
        }

    # ------------------------------------------------------------------
    # Symbol Management
    # ------------------------------------------------------------------

    def initialize_symbol(self, symbol: str) -> None:
        """Initialize state for a new symbol.

        Args:
            symbol: Trading symbol
        """
        self._state_locks.setdefault(symbol, threading.Lock())

    def remove_symbol(self, symbol: str) -> None:
        """Remove all state for a symbol.

        Args:
            symbol: Trading symbol
        """
        self._latest_states.pop(symbol, None)
        self._state_locks.pop(symbol, None)

    def clear_all_states(self) -> None:
        """Clear all states."""
        self._latest_states.clear()

    # ------------------------------------------------------------------
    # Cleanup
    # ------------------------------------------------------------------

    async def cancel_pending_notifications(self) -> None:
        """Cancel any pending notification tasks."""
        if self._notify_task and not self._notify_task.done():
            self._notify_task.cancel()
            try:
                await self._notify_task
            except asyncio.CancelledError:
                pass
