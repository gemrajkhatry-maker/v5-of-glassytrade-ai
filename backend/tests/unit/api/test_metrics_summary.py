"""B-6: /metrics/summary serves the counters that actually increment.

The dashboard reads decisions_evaluated / decisions_approved /
decisions_blocked / trades_executed from this endpoint — keys that were
absent (permanently 0 in the UI) while dead series like errors_total were
served instead.
"""

from __future__ import annotations

import app.api.routers.observability as observability
from app.core.metrics import MetricsRegistry


def _fresh(monkeypatch) -> MetricsRegistry:
    reg = object.__new__(MetricsRegistry)
    MetricsRegistry.__init__(reg)
    monkeypatch.setattr(observability, "metrics", reg)
    return reg


async def test_summary_serves_decision_and_trade_counters(monkeypatch):
    reg = _fresh(monkeypatch)
    reg.counter("ticks_processed_total", "").inc(7)
    reg.counter("decisions_evaluated_total", "").inc(3)
    reg.counter("decisions_approved_total", "").inc(1)
    reg.counter("decisions_blocked_total", "").inc(2)
    reg.counter("trades_executed_total", "").inc(1)

    body = await observability.metrics_summary(None)

    assert body["ticks_processed"] == 7
    assert body["decisions_evaluated"] == 3
    assert body["decisions_approved"] == 1
    assert body["decisions_blocked"] == 2
    assert body["trades_executed"] == 1


async def test_summary_does_not_serve_dead_series(monkeypatch):
    _fresh(monkeypatch)

    body = await observability.metrics_summary(None)

    assert "errors_total" not in body
    assert "pipeline_duration_avg" not in body
