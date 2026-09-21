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
