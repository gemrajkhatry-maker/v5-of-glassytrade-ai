"""Adapter: the brain's telemetry port → the Prometheus registry.

``quant`` counts the bars it evaluates and the signals it emits through
:class:`~quant.contracts.ports.telemetry.ITelemetry` and imports nothing from
here. This is the host half: it turns those calls into the ``ticks_processed``
and ``signals_generated`` counters served by ``GET /metrics/`` (text) and
``GET /metrics/summary`` (JSON) — before this adapter existed both were
declared and permanently 0.

Counters are resolved through the registry on each call rather than captured
at import time, so the writer and the reader in ``observability.py`` always
land on the same family even after the registry is reset (test-only) or
re-created.
"""

from __future__ import annotations

from app.core.metrics import metrics
from quant.contracts.ports.telemetry import ITelemetry


class PrometheusTelemetry(ITelemetry):
    """Count quant activity in the Prometheus registry.

    ``signals_generated_total`` is an unlabeled counter, so a signal's
    direction is counted in the total and not bucketed; the port still carries
    it for hosts that want the split.
    """

    def record_tick(self) -> None:
        metrics.counter("ticks_processed_total", "Total ticks processed").inc()

    def record_decision(self, approved: bool) -> None:
        metrics.counter(
            "decisions_evaluated_total", "Total entry decisions evaluated"
        ).inc()
        split = (
            ("decisions_approved_total", "Entry decisions that passed gates")
            if approved
            else ("decisions_blocked_total", "Entry decisions blocked by gates")
        )
        metrics.counter(split[0], split[1]).inc()

    def record_signal(self, direction: str) -> None:
        metrics.counter("signals_generated_total", "Signals generated").inc()
