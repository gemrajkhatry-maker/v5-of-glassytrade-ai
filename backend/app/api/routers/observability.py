"""Enhanced metrics endpoint with structured logging and Prometheus export."""

from fastapi import APIRouter, Request
from app.core.metrics import metrics
from app.core.startup_telemetry import RUNBOOK, crash_summary, startup_snapshot, unresolved_count

router = APIRouter(prefix="/metrics", tags=["metrics"])


def _counter_value(name: str) -> float:
    """Read a counter without creating its family (absent series reads 0)."""
    if name not in metrics._metrics:
        return 0.0
    return metrics.counter(name, "").value


@router.get("/")
async def prometheus_metrics(request: Request):
    """Export all metrics in Prometheus format."""
    return metrics.to_prometheus()


@router.get("/summary")
async def metrics_summary(request: Request):
    """Return metrics summary as JSON for dashboard."""
    return {
        "ticks_processed": _counter_value("ticks_processed_total"),
        "signals_generated": _counter_value("signals_generated_total"),
        "decisions_evaluated": _counter_value("decisions_evaluated_total"),
        "decisions_approved": _counter_value("decisions_approved_total"),
        "decisions_blocked": _counter_value("decisions_blocked_total"),
        "trades_executed": _counter_value("trades_executed_total"),
        "startup": startup_snapshot(),
        "crash_summary": crash_summary(),
        "startup_unresolved_symbols": unresolved_count(),
    }


@router.get("/startup")
async def startup_telemetry(request: Request):
    """Return startup lifecycle snapshot and runbook hints."""
    return startup_snapshot()


@router.get("/startup/runbook")
async def startup_runbook(request: Request):
    """Return startup failure categories and operator actions."""
    return {"runbook": RUNBOOK}