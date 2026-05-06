"""Persistence stage for tick-level and lifecycle audit records."""

from __future__ import annotations

from collections import deque
import logging
import time

from app.domain.shared.port.storage import IStorage
from app.infrastructure.storage.database import SQLiteStorageAdapter
from app.runtime.pipeline import StageMetrics
from app.runtime.pipeline.events import PipelineEvent, as_pipeline_payload

logger = logging.getLogger(__name__)


class EventPersistence:
    """Persist selected events to storage without impacting hot-path latency."""

    def __init__(self, storage: IStorage | None = None, batch_size: int = 50, buffer_limit: int = 2048):
        self._storage: IStorage = storage or SQLiteStorageAdapter()
        self._buffer_limit = max(1, buffer_limit)
        self._batch_size = max(1, batch_size)
        self._buffer: deque[dict] = deque(maxlen=self._buffer_limit)
        self._dropped_events = 0
        self._flush_count = 0
        self._flush_failures = 0
        self._last_tick_written_ns = 0.0
        self._metrics = StageMetrics(stage_name="EventPersistence")
        self._flush_interval_ns = 5_000_000_000
        self._last_flush_ns = time.perf_counter_ns()

    @property
    def metrics(self) -> StageMetrics:
        return self._metrics

    def process(self, event: PipelineEvent | object) -> list[PipelineEvent | object]:
        if self._storage is None:
            return []
        try:
            payload = self._serialize(event)
            if payload is None:
                return []
            before_size = len(self._buffer)
            self._buffer.append(payload)
            if len(self._buffer) == self._buffer.maxlen and before_size == self._buffer.maxlen:
                self._dropped_events += 1

            if (
                len(self._buffer) >= self._batch_size
                or self._flush_due()
            ):
                self._flush_locked()
            self._metrics.record(0)
            return []
        except Exception:
            self._metrics.record_error()
            logger.exception("Persistence failed")
            return []

    def flush(self) -> None:
        self._flush_locked()

    def _serialize(self, event: object) -> dict | None:
        try:
            payload = as_pipeline_payload(event)  # type: ignore[arg-type]
        except TypeError:
            return None

        event_type = str(payload.get("type", "")).lower()
        if event_type == "tick":
            data = dict(payload)
            data["time"] = str(int(data.get("timestamp", 0)))
            data["open"] = float(data.get("price", 0.0))
            data["high"] = float(data.get("price", 0.0))
            data["low"] = float(data.get("price", 0.0))
            data["close"] = float(data.get("price", 0.0))
            data["volume"] = float(data.get("volume", 0.0))
            data["delta"] = 0.0
            data["symbol"] = str(data.get("symbol", ""))
            payload = data

        return {
            "type": payload.get("type", ""),
            "symbol": payload.get("symbol", ""),
            "data": payload,
        }

    def warmup(self) -> None:
        self._buffer.clear()
        self._dropped_events = 0
        self._flush_count = 0
        self._flush_failures = 0
        self._last_flush_ns = time.perf_counter_ns()
        self._last_tick_written_ns = 0.0
        self._metrics.reset()

    def teardown(self) -> None:
        self.flush()
        self._metrics.reset()

    def reset(self) -> None:
        self._buffer.clear()
        self._dropped_events = 0
        self._flush_count = 0
        self._flush_failures = 0
        self._last_flush_ns = time.perf_counter_ns()
        self._last_tick_written_ns = 0.0
        self._metrics.reset()

    def snapshot(self) -> dict[str, list[dict]]:
        return {
            "buffer": list(self._buffer),
            "buffer_limit": self._buffer_limit,
            "batch_size": self._batch_size,
            "dropped_events": self._dropped_events,
            "flush_count": self._flush_count,
            "flush_failures": self._flush_failures,
            "last_flush_ns": self._last_flush_ns,
            "last_tick_written_ns": self._last_tick_written_ns,
        }

    def restore(self, payload: dict[str, list[dict]]) -> None:
        if not isinstance(payload, dict):
            return
        buffer_payload = payload.get("buffer")
        if isinstance(buffer_payload, list):
            self._buffer = deque(
                [row for row in buffer_payload if isinstance(row, dict)],
                maxlen=self._buffer_limit,
            )
        else:
            self._buffer.clear()
        buffer_limit = payload.get("buffer_limit")
        if isinstance(buffer_limit, int) and buffer_limit > 0:
            self._buffer_limit = max(1, buffer_limit)
            self._buffer = deque(self._buffer, maxlen=self._buffer_limit)
        batch_size = payload.get("batch_size")
        if isinstance(batch_size, int) and batch_size > 0:
            self._batch_size = batch_size
        dropped = payload.get("dropped_events")
        if isinstance(dropped, int):
            self._dropped_events = dropped
        last_flush_ns = payload.get("last_flush_ns")
        if isinstance(last_flush_ns, (int, float)):
            self._last_flush_ns = float(last_flush_ns)
        flush_count = payload.get("flush_count")
        if isinstance(flush_count, int):
            self._flush_count = flush_count
        flush_failures = payload.get("flush_failures")
        if isinstance(flush_failures, int):
            self._flush_failures = flush_failures
        last_tick_written_ns = payload.get("last_tick_written_ns")
        if isinstance(last_tick_written_ns, (int, float)):
            self._last_tick_written_ns = float(last_tick_written_ns)

    def _flush_due(self) -> bool:
        now = time.perf_counter_ns()
        if now - self._last_flush_ns >= self._flush_interval_ns:
            return True
        return False

    def _flush_locked(self) -> None:
        if not self._buffer:
            self._last_flush_ns = time.perf_counter_ns()
            return
        try:
            to_flush = list(self._buffer)
            for row in to_flush:
                event_type = str(row.get("type", ""))
                if event_type.lower() == "tick":
                    self._storage.save_tick(row["symbol"], row["data"])
            flush_method = getattr(self._storage, "_flush_ticks", None)
            if callable(flush_method):
                flush_method()
            elif hasattr(self._storage, "_flush_ticks_unlocked"):
                getattr(self._storage, "_flush_ticks_unlocked")()
            self._buffer.clear()
            self._last_tick_written_ns = time.perf_counter_ns()
            self._flush_count += 1
            self._last_flush_ns = time.perf_counter_ns()
        except Exception:
            self._flush_failures += 1
            self._metrics.record_error()
            logger.exception("Persistence flush failed")
