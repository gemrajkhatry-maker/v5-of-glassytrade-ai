"""Telemetry stage for runtime observability."""

from __future__ import annotations

from collections import deque
import logging
import time

from app.runtime.pipeline import StageMetrics
from app.runtime.pipeline.events import PipelineEvent

logger = logging.getLogger(__name__)


class TelemetryPipeline:
    """Capture stage timings and basic counters."""

    def __init__(self):
        self._counters: dict[str, int] = {}
        self._latencies_ns: dict[str, deque[int]] = {}
        self._started_ns: dict[int, int] = {}
        self._metrics = StageMetrics(stage_name="TelemetryPipeline")

    @property
    def metrics(self) -> StageMetrics:
        return self._metrics

    def start_span(self, span_id: int) -> None:
        self._started_ns[span_id] = time.perf_counter_ns()

    def end_span(self, stage_name: str, span_id: int) -> None:
        start = self._started_ns.pop(span_id, None)
        if start is None:
            return
        elapsed = time.perf_counter_ns() - start
        latencies = self._latencies_ns.setdefault(stage_name, deque(maxlen=2048))
        latencies.append(elapsed)
        self._counters[f"{stage_name}_events"] = self._counters.get(f"{stage_name}_events", 0) + 1

    @staticmethod
    def _percentile(values: list[int], ratio: float) -> int:
        if not values:
            return 0
        sorted_values = sorted(values)
        if len(sorted_values) == 1:
            return int(sorted_values[0])
        index = int((len(sorted_values) - 1) * ratio)
        index = max(0, min(index, len(sorted_values) - 1))
        return int(sorted_values[index])

    def process(self, event: PipelineEvent | object) -> list[PipelineEvent | object]:
        self._metrics.record(0)
        return []

    def snapshot(self) -> dict[str, dict]:
        return {
            "counters": dict(self._counters),
            "latency_ns": {
                key: {
                    "count": len(values),
                    "avg": sum(values) / len(values) if values else 0.0,
                    "p95": self._percentile(list(values), 0.95),
                }
                for key, values in self._latencies_ns.items()
            },
        }

    def warmup(self) -> None:
        self._counters = {}
        self._latencies_ns = {}
        self._started_ns = {}
        self._metrics.reset()

    def teardown(self) -> None:
        self.warmup()

    def reset(self) -> None:
        self.warmup()

    def restore(self, payload: dict[str, dict]) -> None:
        self._counters = {}
        self._latencies_ns = {}
        self._started_ns = {}
        if not isinstance(payload, dict):
            return
        counters = payload.get("counters")
        if isinstance(counters, dict):
            self._counters = {str(k): int(v) for k, v in counters.items() if isinstance(v, int)}

        latency_payload = payload.get("latency_ns")
        if isinstance(latency_payload, dict):
            for key, metrics in latency_payload.items():
                if not isinstance(key, str) or not isinstance(metrics, dict):
                    continue
                count = metrics.get("count")
                avg = metrics.get("avg")
                p95 = metrics.get("p95")
                if isinstance(count, int) and count > 0:
                    samples = deque(maxlen=2048)
                    for index in range(count):
                        samples.append(int(avg) if isinstance(avg, (int, float)) else 0)
                    if isinstance(p95, (int, float)) and count > 0:
                        samples[-1] = int(p95)
                    self._latencies_ns[key] = samples
