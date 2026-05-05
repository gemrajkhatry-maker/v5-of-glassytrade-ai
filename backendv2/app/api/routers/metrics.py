"""Prometheus metrics endpoint for observability."""
from fastapi import APIRouter, Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from app.core.core_components import _metrics, _circuit_breaker

router = APIRouter()


@router.get("/metrics")
async def prometheus_metrics():
    """Prometheus metrics endpoint."""
    # Update circuit breaker metrics
    if _circuit_breaker.is_open:
        _metrics.gauge("circuit_breaker_state", 1)
    else:
        _metrics.gauge("circuit_breaker_state", 0)
    
    # Generate Prometheus exposition format
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )


@router.get("/health")
async def health_check():
    """Health check endpoint."""
    return {
        "status": "healthy",
        "metrics_snapshot": _metrics.snapshot()
    }