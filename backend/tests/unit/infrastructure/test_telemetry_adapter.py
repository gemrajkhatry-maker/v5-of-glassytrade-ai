"""The host telemetry adapter: quant's port → the counters /metrics serves."""

from __future__ import annotations

import inspect

from app.core.metrics import metrics
from app.infrastructure.telemetry import PrometheusTelemetry
from quant.contracts.ports.telemetry import ITelemetry


def _served(name: str, help_: str = "") -> float:
    """Read a counter exactly as backend/app/api/routers/observability.py does."""
    return metrics.counter(name, help_).value


def test_adapter_satisfies_the_port():
    """The host adapter is substitutable for the brain's interface."""
    assert isinstance(PrometheusTelemetry(), ITelemetry)


def test_record_tick_moves_the_served_counter():
    before = _served("ticks_processed_total")

    sink = PrometheusTelemetry()
    sink.record_tick()
    sink.record_tick()

    assert _served("ticks_processed_total") == before + 2


def test_record_decision_moves_the_served_decision_counters():
    before_eval = _served("decisions_evaluated_total")
    before_appr = _served("decisions_approved_total")
    before_blk = _served("decisions_blocked_total")

    sink = PrometheusTelemetry()
    sink.record_decision(approved=True)
    sink.record_decision(approved=False)

    assert _served("decisions_evaluated_total") == before_eval + 2
    assert _served("decisions_approved_total") == before_appr + 1
    assert _served("decisions_blocked_total") == before_blk + 1


def test_record_signal_moves_the_served_counter():
    before = _served("signals_generated_total")

    sink = PrometheusTelemetry()
    sink.record_signal("LONG")
    sink.record_signal("SHORT")

    assert _served("signals_generated_total") == before + 2


def test_counters_appear_in_the_prometheus_export():
    sink = PrometheusTelemetry()
    sink.record_tick()
    sink.record_signal("LONG")

    exported = metrics.to_prometheus()
    assert "ticks_processed_total" in exported
    assert "signals_generated_total" in exported


def test_adapter_depends_on_the_port_not_on_an_engine():
    """The adapter must not drag the runtime in behind it."""
    source = inspect.getsource(__import__("app.infrastructure.telemetry", fromlist=["x"]))

    assert "from quant.contracts.ports.telemetry import ITelemetry" in source
    assert "quant.runtime" not in source
    assert "quant.multi_engine" not in source
