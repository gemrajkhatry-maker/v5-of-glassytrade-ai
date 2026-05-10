"""Integration tests for TelemetryPipeline with distributed tracing."""

from __future__ import annotations

import time

import pytest

from app.core.tracing import SpanKind, Tracer
from app.runtime.pipeline.telemetry import TelemetryPipeline


class TestTelemetryWithoutTracer:
    def test_basic_functionality(self):
        """TelemetryPipeline works without tracer (backward compatible)."""
        tel = TelemetryPipeline()
        tel.start_span(1)
        time.sleep(0.001)
        tel.end_span("test_stage", 1)

        snap = tel.snapshot()
        assert "counters" in snap
        assert "latency_ns" in snap
        assert "tracing" not in snap

    def test_snapshot_without_tracer(self):
        tel = TelemetryPipeline()
        snap = tel.snapshot()
        assert snap["counters"] == {}
        assert snap["latency_ns"] == {}


class TestTelemetryWithTracer:
    def test_start_span_creates_trace_span(self):
        tracer = Tracer()
        tel = TelemetryPipeline(tracer=tracer)

        tel.start_span(42)
        assert tracer.current_span_id() is not None
        assert tracer.store.count() == 0  # not ended yet

    def test_end_span_completes_trace_span(self):
        tracer = Tracer()
        tel = TelemetryPipeline(tracer=tracer)

        tel.start_span(42)
        time.sleep(0.001)
        tel.end_span("my_stage", 42)

        assert tracer.store.count() == 1
        span = tracer.store.get_recent(1)[0]
        assert span.name == "tick:42"
        assert span.duration_ns > 0

    def test_snapshot_includes_tracing(self):
        tracer = Tracer()
        tel = TelemetryPipeline(tracer=tracer)

        tel.start_span(1)
        tel.end_span("stage_a", 1)
        tel.start_span(2)
        tel.end_span("stage_b", 2)

        snap = tel.snapshot()
        assert "tracing" in snap
        assert snap["tracing"]["span_count"] == 2
        assert snap["tracing"]["active_spans"] == 0

    def test_counters_still_work_with_tracer(self):
        tracer = Tracer()
        tel = TelemetryPipeline(tracer=tracer)

        tel.start_span(1)
        tel.end_span("stage_a", 1)
        tel.start_span(2)
        tel.end_span("stage_b", 2)

        snap = tel.snapshot()
        assert snap["counters"]["stage_a_events"] == 1
        assert snap["counters"]["stage_b_events"] == 1

    def test_latency_still_recorded_with_tracer(self):
        tracer = Tracer()
        tel = TelemetryPipeline(tracer=tracer)

        tel.start_span(1)
        time.sleep(0.002)
        tel.end_span("slow_stage", 1)

        snap = tel.snapshot()
        assert "slow_stage" in snap["latency_ns"]
        assert snap["latency_ns"]["slow_stage"]["count"] == 1
        assert snap["latency_ns"]["slow_stage"]["avg"] > 0

    def test_warmup_clears_tracer(self):
        tracer = Tracer()
        tel = TelemetryPipeline(tracer=tracer)

        tel.start_span(1)
        tel.end_span("stage", 1)
        assert tracer.store.count() == 1

        tel.warmup()
        assert tracer.store.count() == 0
        assert len(tel._tick_spans) == 0

    def test_multiple_ticks_produce_multiple_traces(self):
        tracer = Tracer()
        tel = TelemetryPipeline(tracer=tracer)

        for i in range(5):
            tel.start_span(i)
            tel.end_span(f"stage_{i}", i)

        assert tracer.store.count() == 5
        # Each tick gets its own trace_id
        trace_ids = set()
        for span in tracer.store.get_recent(5):
            trace_ids.add(span.trace_id)
        assert len(trace_ids) == 5

    def test_orphan_span_end_handles_gracefully(self):
        """Ending a span that was never started should not crash."""
        tracer = Tracer()
        tel = TelemetryPipeline(tracer=tracer)

        # End a span that was never started
        tel.end_span("nonexistent", 999)
        # Should not crash, no spans created
        assert tracer.store.count() == 0

    def test_start_span_without_end_cleanup(self):
        """If start_span is called but end_span is not, warmup should clean up."""
        tracer = Tracer()
        tel = TelemetryPipeline(tracer=tracer)

        tel.start_span(1)
        assert len(tel._tick_spans) == 1

        tel.warmup()
        assert len(tel._tick_spans) == 0
        # Active span in tracer should also be cleared
        assert tracer.current_span_id() is None

    def test_trace_summary_in_snapshot(self):
        tracer = Tracer()
        tel = TelemetryPipeline(tracer=tracer)

        for i in range(3):
            tel.start_span(i)
            tel.end_span(f"stage_{i}", i)

        snap = tel.snapshot()
        traces = snap["tracing"]["traces"]
        assert len(traces) == 3
        for trace_id, summary in traces.items():
            assert summary["span_count"] == 1
            assert "root_span" in summary
