"""Prometheus metrics endpoint for observability."""
from fastapi import APIRouter, Request, Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from app.core.circuit_breaker import CircuitBreaker
from app.core.metrics import MetricsRegistry

router = APIRouter()


@router.get("/metrics")
async def prometheus_metrics(request: Request):
    """Prometheus metrics endpoint."""
    container = request.app.state.container
    metrics: MetricsRegistry = container.resolve(MetricsRegistry)
    cb: CircuitBreaker = container.resolve(CircuitBreaker)
    
    # Update circuit breaker metrics
    metrics.gauge("circuit_breaker_state", 1 if cb.is_open else 0)
    
    # Generate Prometheus exposition format
    return Response(
        content=generate_latest(),
        media_type=CONTENT_TYPE_LATEST
    )


@router.get("/snapshot")
async def health_check(request: Request):
    """Compatibility endpoint for metrics snapshot."""
    container = request.app.state.container
    metrics: MetricsRegistry = container.resolve(MetricsRegistry)
    
    return {
        "status": "healthy",
        "metrics_snapshot": metrics.snapshot()
    }