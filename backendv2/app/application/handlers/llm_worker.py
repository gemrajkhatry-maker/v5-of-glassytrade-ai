"""LLM worker queue manager."""

from __future__ import annotations

import queue
import threading
import time


class LLMWorkerManager:
    """Manages per-symbol LLM worker queues."""

    def __init__(self):
        self._llm_queues: dict[str, queue.Queue] = {}
        self._worker_threads: dict[str, threading.Thread] = {}
        self._workers_lock = threading.Lock()

    def get_or_create_worker(self, symbol: str, worker_target) -> queue.Queue:
        with self._workers_lock:
            if symbol not in self._llm_queues:
                self._llm_queues[symbol] = queue.Queue(maxsize=10)
                thread = threading.Thread(
                    target=worker_target,
                    args=(symbol,),
                    daemon=True,
                    name=f"LLM-Worker-{symbol}",
                )
                self._worker_threads[symbol] = thread
                thread.start()
            return self._llm_queues[symbol]

    def shutdown_all(self):
        with self._workers_lock:
            for q in self._llm_queues.values():
                try:
                    q.put_nowait(None)
                except queue.Full:
                    pass

    def is_queue_full(self, symbol: str) -> bool:
        queue_obj = self._llm_queues.get(symbol)
        return queue_obj is not None and queue_obj.full()


def check_staleness(enqueue_time: float, threshold: float = 20.0) -> bool:
    return time.time() - enqueue_time > threshold
