"""Telemetry stage for runtime observability."""

from __future__ import annotations

from collections import deque
import logging
import time

from app.runtime.pipeline import StageMetrics
from app.runtime.pipeline.base import PipelineStageBase
from app.runtime.pipeline.events import PipelineEvent

logger = logging.getLogger(__name__)


class TelemetryPipeline(PipelineStageBase):
    """Capture stage timings and basic counters."""

    @property
    def stage_name(self) -> str:
        return "TelemetryPipeline"

    def __init__(self, tracer=None):
        self._counters: dict[str, int] = {}
        self._latencies_ns: dict[str, deque[int]] = {}
        self._started_ns: dict[int, int] = {}
        self._started_tracer_span_ids: dict[int, str] = {}
        self._tick_spans: dict[int, str] = {}
        self._metrics = StageMetrics(stage_name=self.stage_name)
        self._tracer = tracer

    @property
    def metrics(self) -> StageMetrics:
        return self._metrics

    def start_span(self, span_id: int) -> None:
        self._started_ns[span_id] = time.perf_counter_ns()
        if self._tracer is not None:
            span = self._tracer.start_span(name=f"tick:{span_id}")
            if span is not None:
                self._started_tracer_span_ids[span_id] = span.span_id
                self._tick_spans[span_id] = span.span_id

    def end_span(self, stage_name: str, span_id: int) -> None:
        start = self._started_ns.pop(span_id, None)
        elapsed = 0
        if start is not None:
            elapsed = time.perf_counter_ns() - start
            latencies = self._latencies_ns.setdefault(stage_name, deque(maxlen=2048))
            latencies.append(elapsed)
            self._counters[f"{stage_name}_events"] = self._counters.get(f"{stage_name}_events", 0) + 1
        if self._tracer is not None:
            tracer_span_id = self._started_tracer_span_ids.pop(span_id, None)
            if tracer_span_id is not None:
                self._tracer.end_span(tracer_span_id)
        self._tick_spans.pop(span_id, None)

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
        snap = {
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
        if self._tracer is not None:
            spans_by_trace: dict = {}
            for span in self._tracer.store._spans:
                if span.trace_id not in spans_by_trace:
                    spans_by_trace[span.trace_id] = []
                spans_by_trace[span.trace_id].append(span)

            traces = {}
            for trace_id, trace_spans in spans_by_trace.items():
                root_span = next((s for s in trace_spans if s.parent_id is None), trace_spans[0])
                traces[trace_id] = {
                    "span_count": len(trace_spans),
                    "root_span": root_span.to_dict(),
                }

            snap["tracing"] = {
                "span_count": self._tracer.store.count(),
                "active_spans": 1 if self._tracer.current_span_id() is not None else 0,
                "traces": traces,
            }
        return snap

    def warmup(self) -> None:
        self._counters = {}
        self._latencies_ns = {}
        self._started_ns = {}
        self._started_tracer_span_ids = {}
        self._metrics.reset()
        if self._tracer is not None:
            self._tracer.store.clear()
            for span_id in list(self._tracer._active_spans.keys()):
                self._tracer.end_span(span_id)
        self._tick_spans = {}

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
