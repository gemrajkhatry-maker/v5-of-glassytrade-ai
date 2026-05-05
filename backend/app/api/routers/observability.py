"""Enhanced metrics endpoint with structured logging and Prometheus export."""

from fastapi import APIRouter, Request
from app.core.metrics import metrics
from app.core.logging import get_correlation_id
from app.core.circuit_breaker import get_amt_circuit, get_session_circuit
from app.core.startup_telemetry import RUNBOOK, crash_summary, startup_snapshot, unresolved_count

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/")
async def prometheus_metrics(request: Request):
    """Export all metrics in Prometheus format."""
    return metrics.to_prometheus()


@router.get("/summary")
async def metrics_summary(request: Request):
    """Return metrics summary as JSON for dashboard."""
    pipeline_hist = metrics.histogram("amt_pipeline_duration_seconds", "")
    pipeline_hist_count = pipeline_hist.count
    return {
        "ticks_processed": metrics.counter("ticks_processed_total", "").value if metrics._metrics.get("ticks_processed_total") else 0,
        "signals_generated": metrics.counter("signals_generated_total", "").value if metrics._metrics.get("signals_generated_total") else 0,
        "errors_total": metrics.counter("errors_total", "").value if metrics._metrics.get("errors_total") else 0,
        "pipeline_duration_avg": (
            pipeline_hist.sum_val / pipeline_hist_count
            if pipeline_hist_count
            else 0
        ),
        "startup": startup_snapshot(),
        "crash_summary": crash_summary(),
        "startup_unresolved_symbols": unresolved_count(),
    }


@router.get("/circuit-breakers")
async def circuit_breakers(request: Request):
    """Return circuit breaker states."""
    return {
        "amt": get_amt_circuit().get_metrics(),
        "session": get_session_circuit().get_metrics(),
    }


@router.get("/startup")
async def startup_telemetry(request: Request):
    """Return startup lifecycle snapshot and runbook hints."""
    return startup_snapshot()


@router.get("/startup/runbook")
async def startup_runbook(request: Request):
    """Return startup failure categories and operator actions."""
    return {"runbook": RUNBOOK}