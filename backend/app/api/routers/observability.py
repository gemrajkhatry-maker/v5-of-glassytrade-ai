"""Enhanced metrics endpoint with structured logging and Prometheus export."""

from fastapi import APIRouter, Request
from app.core.metrics import metrics
from app.core.logging import get_correlation_id
from app.core.circuit_breaker import get_amt_circuit, get_session_circuit

router = APIRouter(prefix="/metrics", tags=["metrics"])


@router.get("/")
async def prometheus_metrics(request: Request):
    """Export all metrics in Prometheus format."""
    return metrics.to_prometheus()


@router.get("/summary")
async def metrics_summary(request: Request):
    """Return metrics summary as JSON for dashboard."""
    return {
        "ticks_processed": metrics.counter("ticks_processed_total", "").value if metrics._metrics.get("ticks_processed_total") else 0,
        "signals_generated": metrics.counter("signals_generated_total", "").value if metrics._metrics.get("signals_generated_total") else 0,
        "errors_total": metrics.counter("errors_total", "").value if metrics._metrics.get("errors_total") else 0,
        "pipeline_duration_avg": metrics.histogram("amt_pipeline_duration_seconds", "")._sum / max(metrics.histogram("amt_pipeline_duration_seconds", "")._count, 1) if metrics._metrics.get("amt_pipeline_duration_seconds") else 0,
    }


@router.get("/circuit-breakers")
async def circuit_breakers(request: Request):
    """Return circuit breaker states."""
    return {
        "amt": get_amt_circuit().get_metrics(),
        "session": get_session_circuit().get_metrics(),
    }