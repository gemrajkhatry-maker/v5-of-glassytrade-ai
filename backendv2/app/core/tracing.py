"""Distributed tracing infrastructure for backendv2.

Lightweight in-memory tracing with span context, parent-child relationships,
and trace export. Designed for pipeline observability.
"""

from __future__ import annotations

import threading
import time
import uuid
from collections import defaultdict, deque
from dataclasses import dataclass, field
from enum import Enum
from typing import Any


class SpanKind(str, Enum):
    INTERNAL = "INTERNAL"
    SERVER = "SERVER"
    CLIENT = "CLIENT"
    PRODUCER = "PRODUCER"
    CONSUMER = "CONSUMER"


class SpanStatus(str, Enum):
    UNSET = "UNSET"
    OK = "OK"
    ERROR = "ERROR"


@dataclass
class SpanEvent:
    """A timestamped event within a span."""
    name: str
    timestamp_ns: int
    attributes: dict[str, Any] = field(default_factory=dict)


@dataclass
class Span:
    """A single operation span within a trace."""
    span_id: str
    trace_id: str
    parent_id: str | None
    name: str
    kind: SpanKind
    start_ns: int
    end_ns: int = 0
    status: SpanStatus = SpanStatus.UNSET
    attributes: dict[str, Any] = field(default_factory=dict)
    events: list[SpanEvent] = field(default_factory=list)

    @property
    def duration_ns(self) -> int:
        return self.end_ns - self.start_ns if self.end_ns else 0

    @property
    def duration_ms(self) -> float:
        return self.duration_ns / 1_000_000

    def to_dict(self) -> dict[str, Any]:
        return {
            "span_id": self.span_id,
            "trace_id": self.trace_id,
            "parent_id": self.parent_id,
            "name": self.name,
            "kind": self.kind.value,
            "start_ns": self.start_ns,
            "end_ns": self.end_ns,
            "duration_ns": self.duration_ns,
            "status": self.status.value,
            "attributes": dict(self.attributes),
            "events": [
                {"name": e.name, "timestamp_ns": e.timestamp_ns, "attributes": e.attributes}
                for e in self.events
            ],
        }


class TraceStore:
    """In-memory span store with ring buffer and query capabilities."""

    def __init__(self, max_spans: int = 10000):
        self._lock = threading.RLock()
        self._max_spans = max_spans
        self._spans: deque[Span] = deque(maxlen=max_spans)
        self._by_trace: dict[str, list[Span]] = defaultdict(list)

    def add(self, span: Span) -> None:
        with self._lock:
            self._spans.append(span)
            self._by_trace[span.trace_id].append(span)

    def get_by_trace_id(self, trace_id: str) -> list[Span]:
        with self._lock:
            return list(self._by_trace.get(trace_id, []))

    def get_by_span_id(self, span_id: str) -> Span | None:
        with self._lock:
            for span in self._spans:
                if span.span_id == span_id:
                    return span
            return None

    def get_recent(self, limit: int = 100) -> list[Span]:
        with self._lock:
            return list(self._spans)[-limit:]

    def count(self) -> int:
        with self._lock:
            return len(self._spans)

    def clear(self) -> None:
        with self._lock:
            self._spans.clear()
            self._by_trace.clear()


class TraceExporter:
    """Export traces to various formats."""

    @staticmethod
    def to_dict(spans: list[Span]) -> list[dict[str, Any]]:
        return [s.to_dict() for s in spans]

    @staticmethod
    def to_trace_summary(spans: list[Span]) -> dict[str, Any]:
        """Summarize spans by trace_id."""
        traces: dict[str, dict[str, Any]] = {}
        for span in spans:
            tid = span.trace_id
            if tid not in traces:
                traces[tid] = {
                    "trace_id": tid,
                    "span_count": 0,
                    "total_duration_ns": 0,
                    "root_span": None,
                    "status": SpanStatus.UNSET.value,
                }
            traces[tid]["span_count"] += 1
            traces[tid]["total_duration_ns"] += span.duration_ns
            if span.parent_id is None:
                traces[tid]["root_span"] = span.name
            if span.status == SpanStatus.ERROR:
                traces[tid]["status"] = SpanStatus.ERROR.value
        return traces

    @staticmethod
    def to_json(spans: list[Span]) -> str:
        import json
        return json.dumps(TraceExporter.to_dict(spans), indent=2, default=str)


class Tracer:
    """Create and manage spans with parent-child relationships."""

    def __init__(self, store: TraceStore | None = None):
        self._lock = threading.RLock()
        self._store = store or TraceStore()
        self._active_spans: dict[str, Span] = {}  # span_id -> Span (in-progress)
        self._current_span_id: str | None = None  # for implicit parent chaining
        self._trace_counter = 0

    @property
    def store(self) -> TraceStore:
        return self._store

    def _new_trace_id(self) -> str:
        self._trace_counter += 1
        return uuid.uuid4().hex[:16]

    def _new_span_id(self) -> str:
        return uuid.uuid4().hex[:12]

    def start_span(
        self,
        name: str,
        kind: SpanKind = SpanKind.INTERNAL,
        trace_id: str | None = None,
        parent_id: str | None = None,
        attributes: dict[str, Any] | None = None,
    ) -> Span:
        with self._lock:
            if parent_id is None:
                parent_id = self._current_span_id

            # Inherit trace_id from parent if not explicitly provided
            if trace_id is None and parent_id is not None:
                parent_span = self._active_spans.get(parent_id)
                if parent_span is not None:
                    trace_id = parent_span.trace_id

            if trace_id is None:
                trace_id = self._new_trace_id()

            span = Span(
                span_id=self._new_span_id(),
                trace_id=trace_id,
                parent_id=parent_id,
                name=name,
                kind=kind,
                start_ns=time.perf_counter_ns(),
                attributes=dict(attributes) if attributes else {},
            )
            self._active_spans[span.span_id] = span
            self._current_span_id = span.span_id
            return span

    def end_span(self, span_id: str, status: SpanStatus = SpanStatus.OK) -> Span | None:
        with self._lock:
            span = self._active_spans.pop(span_id, None)
            if span is None:
                return None
            span.end_ns = time.perf_counter_ns()
            span.status = status
            self._store.add(span)

            # Restore parent as current
            if span.parent_id and span.parent_id in self._active_spans:
                self._current_span_id = span.parent_id
            elif self._current_span_id == span_id:
                self._current_span_id = None

            return span

    def add_event(self, span_id: str, name: str, attributes: dict[str, Any] | None = None) -> None:
        with self._lock:
            span = self._active_spans.get(span_id)
            if span is not None:
                span.events.append(SpanEvent(
                    name=name,
                    timestamp_ns=time.perf_counter_ns(),
                    attributes=dict(attributes) if attributes else {},
                ))

    def set_attribute(self, span_id: str, key: str, value: Any) -> None:
        with self._lock:
            span = self._active_spans.get(span_id)
            if span is not None:
                span.attributes[key] = value

    def current_span_id(self) -> str | None:
        with self._lock:
            return self._current_span_id

    def get_active_span(self) -> Span | None:
        with self._lock:
            if self._current_span_id:
                return self._active_spans.get(self._current_span_id)
            return None

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            recent = self._store.get_recent(50)
            return {
                "span_count": self._store.count(),
                "active_spans": len(self._active_spans),
                "traces": TraceExporter.to_trace_summary(recent),
            }

    def clear(self) -> None:
        with self._lock:
            self._active_spans.clear()
            self._current_span_id = None
            self._store.clear()
