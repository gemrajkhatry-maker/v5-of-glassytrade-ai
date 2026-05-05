"""Throughput and latency guardrails for the telemetry ring buffer."""

from app.runtime.pipeline import telemetry as telemetry_module
from app.runtime.pipeline.telemetry import TelemetryPipeline
import pytest


def test_latency_samples_remain_bounded_under_load(monkeypatch: pytest.MonkeyPatch) -> None:
    telemetry = TelemetryPipeline()
    clock = {"tick": 0}

    def _fake_clock() -> int:
        clock["tick"] += 250
        return clock["tick"]

    monkeypatch.setattr(telemetry_module.time, "perf_counter_ns", _fake_clock)

    for span_id in range(5000):
        telemetry.start_span(span_id)
        telemetry.end_span("SessionRuntime", span_id)

    snapshot = telemetry.snapshot()
    assert snapshot["latency_ns"]["SessionRuntime"]["count"] == 2048
    assert snapshot["latency_ns"]["SessionRuntime"]["avg"] == 250.0
    assert snapshot["latency_ns"]["SessionRuntime"]["p95"] == 250
