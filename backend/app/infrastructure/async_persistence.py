"""Async Persistence Bus — offloads storage writes to a background thread.

Wraps any StoragePort and queues all write operations for asynchronous execution,
removing SQLite I/O latency from the real-time trading hot path.

Usage:
    bus = AsyncPersistenceBus(storage)
    bus.start()
    bus.save_tick("SYM", {...})     # returns immediately
    bus.save_trade({...})           # returns immediately
    bus.stop()                      # flushes pending + joins thread
"""

from __future__ import annotations

import logging
import queue
import threading
from typing import Any, Callable

logger = logging.getLogger(__name__)


class AsyncPersistenceBus:
    """Background thread that drains a write queue and flushes to StoragePort."""

    def __init__(self, storage: Any, max_queue_size: int = 5000) -> None:
        self._storage = storage
        self._queue: queue.Queue[tuple[str, tuple, dict] | None] = queue.Queue(
            maxsize=max_queue_size,
        )
        # Priority queue for critical writes (trade/position persistence).
        # Drained FIRST in the worker loop so these are never starved by tick volume.
        self._critical_queue: queue.Queue[tuple[str, tuple, dict]] = queue.Queue(
            maxsize=100,
        )
        self._thread: threading.Thread | None = None
        self._running = False
        self._dropped = 0

    # ------------------------------------------------------------------
    # Public write API (non-blocking, called from hot path)
    # ------------------------------------------------------------------

    def save_tick(self, symbol: str, tick_data: dict[str, Any]) -> None:
        self._enqueue("save_tick", (symbol, tick_data), {})

    def save_trade(self, trade_data: dict[str, Any]) -> None:
        self._enqueue_critical("save_trade", (trade_data,), {})

    def save_llm_decision(self, decision_data: dict[str, Any]) -> None:
        self._enqueue("save_llm_decision", (decision_data,), {})

    def save_performance_snapshot(self, snapshot: dict[str, Any]) -> None:
        self._enqueue("save_performance_snapshot", (snapshot,), {})

    def save_open_position(self, position: dict[str, Any]) -> None:
        self._enqueue_critical("save_open_position", (position,), {})

    def delete_open_position(self, position_id: str) -> None:
        self._enqueue_critical("delete_open_position", (position_id,), {})

    def save_position_event(self, event: dict[str, Any]) -> None:
        self._enqueue_critical("save_position_event", (event,), {})

    def save_session_profile(self, profile_data: dict[str, Any]) -> None:
        self._enqueue("save_session_profile", (profile_data,), {})

    def save_npoc(self, underlying: str, session_date: str, poc_price: float) -> None:
        self._enqueue("save_npoc", (underlying, session_date, poc_price), {})

    def mark_npoc_filled(
        self, underlying: str, session_date: str, filled_at: str
    ) -> None:
        self._enqueue("mark_npoc_filled", (underlying, session_date, filled_at), {})

    # ------------------------------------------------------------------
    # Passthrough read API (synchronous — reads must be consistent)
    # ------------------------------------------------------------------

    def query_ticks(self, *args, **kwargs):
        return self._storage.query_ticks(*args, **kwargs)

    def query_trades(self, *args, **kwargs):
        return self._storage.query_trades(*args, **kwargs)

    def query_llm_decisions(self, *args, **kwargs):
        return self._storage.query_llm_decisions(*args, **kwargs)

    def query_signal_decisions(self, *args, **kwargs):
        return self._storage.query_signal_decisions(*args, **kwargs)

    def load_open_positions(self):
        return self._storage.load_open_positions()

    def get_previous_session_profile(self, *args, **kwargs):
        return self._storage.get_previous_session_profile(*args, **kwargs)

    def get_recent_trades(self, *args, **kwargs):
        return self._storage.get_recent_trades(*args, **kwargs)

    def query_position_events(self, *args, **kwargs):
        return self._storage.query_position_events(*args, **kwargs)

    def get_active_npocs(self, underlying: str):
        return self._storage.get_active_npocs(underlying)

    # Forward kv_set/kv_get if available
    def kv_set(self, key: str, value: str) -> None:
        self._enqueue("kv_set", (key, value), {})

    def kv_get(self, key: str) -> str | None:
        if hasattr(self._storage, "kv_get"):
            return self._storage.kv_get(key)
        return None

    # ------------------------------------------------------------------
    # Lifecycle
    # ------------------------------------------------------------------

    def start(self) -> None:
        if self._running:
            return
        self._running = True
        self._thread = threading.Thread(
            target=self._worker,
            name="PersistenceBus",
            daemon=True,
        )
        self._thread.start()
        logger.info("AsyncPersistenceBus started")

    def stop(self, timeout: float = 5.0) -> None:
        """Flush pending writes and stop the worker thread."""
        if not self._running:
            return
        self._running = False
        self._queue.put(None)  # sentinel
        if self._thread:
            self._thread.join(timeout=timeout)
        # Safety net: drain any critical writes that survived the worker shutdown
        remaining: list[tuple[str, tuple, dict]] = []
        self._drain_critical(remaining)
        if remaining:
            logger.info(
                "AsyncPersistenceBus: flushing %d critical writes after worker stop",
                len(remaining),
            )
            self._execute_batch(remaining)
        if self._dropped > 0:
            logger.warning(
                "AsyncPersistenceBus: dropped %d writes due to full queue",
                self._dropped,
            )
        logger.info(
            "AsyncPersistenceBus stopped (pending=%d, critical_pending=%d)",
            self._queue.qsize(),
            self._critical_queue.qsize(),
        )

    @property
    def pending_count(self) -> int:
        return self._critical_queue.qsize() + self._queue.qsize()

    @property
    def dropped_count(self) -> int:
        return self._dropped

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    # Methods whose drops are critical (trade/position data loss)
    _CRITICAL_METHODS = frozenset(
        {
            "save_trade",
            "save_open_position",
            "delete_open_position",
            "save_position_event",
        }
    )

    def _enqueue_critical(self, method: str, args: tuple, kwargs: dict) -> None:
        """Route to the priority critical queue; fall back to the main queue."""
        try:
            self._critical_queue.put_nowait((method, args, kwargs))
        except queue.Full:
            # Critical queue full — try the main queue as fallback
            self._enqueue(method, args, kwargs)

    def _enqueue(self, method: str, args: tuple, kwargs: dict) -> None:
        try:
            self._queue.put_nowait((method, args, kwargs))
        except queue.Full:
            self._dropped += 1
            if method in self._CRITICAL_METHODS:
                logger.error(
                    "AsyncPersistenceBus: queue full, dropping CRITICAL write %s (%d total dropped)",
                    method,
                    self._dropped,
                )
            else:
                logger.warning(
                    "AsyncPersistenceBus: queue full, dropping write %s (%d total dropped)",
                    method,
                    self._dropped,
                )

    def _drain_critical(self, batch: list[tuple[str, tuple, dict]]) -> None:
        """Drain all pending items from the critical queue into *batch*."""
        while True:
            try:
                batch.append(self._critical_queue.get_nowait())
            except queue.Empty:
                break

    def _execute_batch(self, batch: list[tuple[str, tuple, dict]]) -> None:
        """Execute every item in *batch* against the underlying storage."""
        for method_name, args, kwargs in batch:
            try:
                method = getattr(self._storage, method_name, None)
                if method:
                    method(*args, **kwargs)
            except Exception:
                logger.error(
                    "AsyncPersistenceBus: %s failed", method_name, exc_info=True
                )

    def _worker(self) -> None:
        """Drain writes from both queues and flush to storage.

        The critical queue is always drained first so that trade and position
        writes are never starved by high-frequency tick volume.
        """
        batch: list[tuple[str, tuple, dict]] = []
        while (
            self._running or not self._critical_queue.empty() or not self._queue.empty()
        ):
            try:
                # 1. Always drain the critical queue first (non-blocking)
                self._drain_critical(batch)

                # 2. Wait briefly for a main-queue item (or wake up to re-check critical)
                try:
                    item = self._queue.get(timeout=0.5)
                    if item is None:
                        # Sentinel received — drain any remaining critical writes and exit
                        self._drain_critical(batch)
                        self._execute_batch(batch)
                        batch.clear()
                        break
                    batch.append(item)
                except queue.Empty:
                    pass

                # 3. Drain up to 50 more items from main queue for batch efficiency
                for _ in range(50):
                    try:
                        item = self._queue.get_nowait()
                        if item is None:
                            # Sentinel in middle of drain — flush and exit
                            self._drain_critical(batch)
                            self._execute_batch(batch)
                            batch.clear()
                            return
                        batch.append(item)
                    except queue.Empty:
                        break

                # 4. Execute the combined batch
                self._execute_batch(batch)
                batch.clear()

            except ValueError:
                logger.error("AsyncPersistenceBus worker error", exc_info=True)
                batch.clear()
