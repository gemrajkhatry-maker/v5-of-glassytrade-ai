"""Unit tests for distributed tracing infrastructure."""

from __future__ import annotations

import threading
import time

import pytest

from app.core.tracing import (
    Span,
    SpanEvent,
    SpanKind,
    SpanStatus,
    TraceExporter,
    TraceStore,
    Tracer,
)


class TestSpan:
    def test_span_creation(self):
        span = Span(
            span_id="s1", trace_id="t1", parent_id=None,
            name="test", kind=SpanKind.INTERNAL, start_ns=100,
        )
        assert span.span_id == "s1"
        assert span.trace_id == "t1"
        assert span.parent_id is None
        assert span.name == "test"
        assert span.kind == SpanKind.INTERNAL
        assert span.end_ns == 0
        assert span.status == SpanStatus.UNSET

    def test_span_duration(self):
        span = Span(
            span_id="s1", trace_id="t1", parent_id=None,
            name="test", kind=SpanKind.INTERNAL, start_ns=100, end_ns=500,
        )
        assert span.duration_ns == 400
        assert span.duration_ms == 0.0004

    def test_span_duration_no_end(self):
        span = Span(
            span_id="s1", trace_id="t1", parent_id=None,
            name="test", kind=SpanKind.INTERNAL, start_ns=100,
        )
        assert span.duration_ns == 0

    def test_span_to_dict(self):
        span = Span(
            span_id="s1", trace_id="t1", parent_id=None,
            name="test", kind=SpanKind.INTERNAL, start_ns=100, end_ns=500,
            attributes={"key": "value"},
        )
        d = span.to_dict()
        assert d["span_id"] == "s1"
        assert d["duration_ns"] == 400
        assert d["attributes"]["key"] == "value"
        assert d["events"] == []

    def test_span_with_events(self):
        span = Span(
            span_id="s1", trace_id="t1", parent_id=None,
            name="test", kind=SpanKind.INTERNAL, start_ns=100, end_ns=500,
        )
        span.events.append(SpanEvent("error", timestamp_ns=300, attributes={"msg": "fail"}))
        d = span.to_dict()
        assert len(d["events"]) == 1
        assert d["events"][0]["name"] == "error"


class TestTraceStore:
    def test_add_and_query(self):
        store = TraceStore()
        span = Span("s1", "t1", None, "test", SpanKind.INTERNAL, 100, 500)
        store.add(span)
        assert store.count() == 1
        assert store.get_by_trace_id("t1") == [span]

    def test_get_by_span_id(self):
        store = TraceStore()
        span = Span("s1", "t1", None, "test", SpanKind.INTERNAL, 100, 500)
        store.add(span)
        assert store.get_by_span_id("s1") is span
        assert store.get_by_span_id("missing") is None

    def test_get_recent(self):
        store = TraceStore()
        for i in range(10):
            store.add(Span(f"s{i}", "t1", None, f"op{i}", SpanKind.INTERNAL, 100, 500))
        recent = store.get_recent(3)
        assert len(recent) == 3
        assert recent[-1].span_id == "s9"

    def test_max_spans_ring_buffer(self):
        store = TraceStore(max_spans=5)
        for i in range(10):
            store.add(Span(f"s{i}", "t1", None, f"op{i}", SpanKind.INTERNAL, 100, 500))
        assert store.count() == 5
        # Oldest 5 should be evicted
        assert store.get_by_span_id("s0") is None
        assert store.get_by_span_id("s9") is not None

    def test_clear(self):
        store = TraceStore()
        store.add(Span("s1", "t1", None, "test", SpanKind.INTERNAL, 100, 500))
        store.clear()
        assert store.count() == 0
        assert store.get_by_trace_id("t1") == []

    def test_multiple_traces(self):
        store = TraceStore()
        store.add(Span("s1", "t1", None, "op1", SpanKind.INTERNAL, 100, 500))
        store.add(Span("s2", "t2", None, "op2", SpanKind.INTERNAL, 100, 500))
        assert len(store.get_by_trace_id("t1")) == 1
        assert len(store.get_by_trace_id("t2")) == 1


class TestTracer:
    def test_start_and_end_span(self):
        tracer = Tracer()
        span = tracer.start_span("test_op")
        assert span.span_id is not None
        assert span.trace_id is not None
        assert span.parent_id is None
        assert span.start_ns > 0
        assert span.end_ns == 0

        ended = tracer.end_span(span.span_id)
        assert ended is not None
        assert ended.end_ns > 0
        assert ended.status == SpanStatus.OK

    def test_parent_child_relationship(self):
        tracer = Tracer()
        parent = tracer.start_span("parent")
        child = tracer.start_span("child")
        assert child.parent_id == parent.span_id
        assert child.trace_id == parent.trace_id

        tracer.end_span(child.span_id)
        tracer.end_span(parent.span_id)

        # Both should be in store
        spans = tracer.store.get_by_trace_id(parent.trace_id)
        assert len(spans) == 2

    def test_end_nonexistent_span(self):
        tracer = Tracer()
        result = tracer.end_span("nonexistent")
        assert result is None

    def test_add_event(self):
        tracer = Tracer()
        span = tracer.start_span("test_op")
        tracer.add_event(span.span_id, "error", {"msg": "fail"})
        tracer.end_span(span.span_id)

        stored = tracer.store.get_by_span_id(span.span_id)
        assert stored is not None
        assert len(stored.events) == 1
        assert stored.events[0].name == "error"

    def test_set_attribute(self):
        tracer = Tracer()
        span = tracer.start_span("test_op")
        tracer.set_attribute(span.span_id, "symbol", "NIFTY")
        tracer.end_span(span.span_id)

        stored = tracer.store.get_by_span_id(span.span_id)
        assert stored is not None
        assert stored.attributes["symbol"] == "NIFTY"

    def test_current_span_id_tracking(self):
        tracer = Tracer()
        assert tracer.current_span_id() is None

        p = tracer.start_span("parent")
        assert tracer.current_span_id() == p.span_id

        c = tracer.start_span("child")
        assert tracer.current_span_id() == c.span_id

        tracer.end_span(c.span_id)
        assert tracer.current_span_id() == p.span_id

        tracer.end_span(p.span_id)
        assert tracer.current_span_id() is None

    def test_explicit_trace_id(self):
        tracer = Tracer()
        span = tracer.start_span("test", trace_id="my-trace-123")
        assert span.trace_id == "my-trace-123"

    def test_explicit_parent_id(self):
        tracer = Tracer()
        span = tracer.start_span("test", parent_id="parent-123")
        assert span.parent_id == "parent-123"

    def test_snapshot(self):
        tracer = Tracer()
        s1 = tracer.start_span("op1")
        tracer.end_span(s1.span_id)
        s2 = tracer.start_span("op2")
        tracer.end_span(s2.span_id)

        snap = tracer.snapshot()
        assert snap["span_count"] == 2
        assert snap["active_spans"] == 0
        assert len(snap["traces"]) >= 1

    def test_clear(self):
        tracer = Tracer()
        tracer.start_span("test")
        tracer.clear()
        assert tracer.store.count() == 0
        assert tracer.current_span_id() is None
        assert tracer.get_active_span() is None

    def test_get_active_span(self):
        tracer = Tracer()
        assert tracer.get_active_span() is None
        span = tracer.start_span("test")
        assert tracer.get_active_span() is span
        tracer.end_span(span.span_id)
        assert tracer.get_active_span() is None


class TestTraceExporter:
    def test_to_dict(self):
        spans = [Span("s1", "t1", None, "test", SpanKind.INTERNAL, 100, 500)]
        result = TraceExporter.to_dict(spans)
        assert len(result) == 1
        assert result[0]["span_id"] == "s1"

    def test_to_trace_summary(self):
        spans = [
            Span("s1", "t1", None, "root", SpanKind.INTERNAL, 100, 600),
            Span("s2", "t1", "s1", "child", SpanKind.INTERNAL, 200, 500),
            Span("s3", "t2", None, "other", SpanKind.INTERNAL, 100, 300),
        ]
        summary = TraceExporter.to_trace_summary(spans)
        assert "t1" in summary
        assert summary["t1"]["span_count"] == 2
        assert summary["t1"]["root_span"] == "root"
        assert summary["t1"]["total_duration_ns"] == 800

    def test_trace_summary_error_status(self):
        spans = [
            Span("s1", "t1", None, "root", SpanKind.INTERNAL, 100, 600, status=SpanStatus.ERROR),
        ]
        summary = TraceExporter.to_trace_summary(spans)
        assert summary["t1"]["status"] == "ERROR"

    def test_to_json(self):
        spans = [Span("s1", "t1", None, "test", SpanKind.INTERNAL, 100, 500)]
        json_str = TraceExporter.to_json(spans)
        assert '"span_id": "s1"' in json_str
        assert '"trace_id": "t1"' in json_str


class TestTracerThreadSafety:
    def test_concurrent_span_creation(self):
        tracer = Tracer()
        results: list[Span] = []

        def create_span(i: int):
            s = tracer.start_span(f"op-{i}")
            time.sleep(0.001)
            tracer.end_span(s.span_id)
            results.append(s)

        threads = [threading.Thread(target=create_span, args=(i,)) for i in range(10)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert tracer.store.count() == 10
