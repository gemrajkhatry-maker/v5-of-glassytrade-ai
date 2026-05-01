"""LLM worker module - extracted from llm_entry_handler.py.

Handles per-symbol LLM worker threads and request processing.
"""

from __future__ import annotations

import logging
import queue
import threading
import time
from typing import Any

logger = logging.getLogger(__name__)


class LLMWorkerManager:
    """Manages per-symbol LLM worker threads."""

    def __init__(self):
        self._llm_queues: dict[str, queue.Queue] = {}
        self._worker_threads: dict[str, threading.Thread] = {}
        self._workers_lock = threading.Lock()

    def get_or_create_worker(self, symbol: str, worker_target: Any) -> queue.Queue:
        """Get or create a worker queue for the given symbol."""
        with self._workers_lock:
            if symbol not in self._llm_queues:
                self._llm_queues[symbol] = queue.Queue(maxsize=10)
                wt = threading.Thread(
                    target=worker_target, args=(symbol,),
                    daemon=True, name=f"LLM-Worker-{symbol}",
                )
                self._worker_threads[symbol] = wt
                wt.start()
            return self._llm_queues[symbol]

    def shutdown_all(self):
        """Shutdown all worker threads."""
        with self._workers_lock:
            for q in self._llm_queues.values():
                try:
                    q.put_nowait(None)
                except queue.Full:
                    pass

    def is_queue_full(self, symbol: str) -> bool:
        """Check if queue is full for given symbol."""
        q = self._llm_queues.get(symbol)
        return q is not None and q.full()


def check_staleness(enqueue_time: float, threshold: float = 20.0) -> bool:
    """Check if a queued item is too stale to process."""
    return time.time() - enqueue_time > threshold