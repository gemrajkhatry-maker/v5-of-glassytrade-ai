"""Prometheus metrics endpoint for observability."""
from fastapi import APIRouter, Request, Response
from prometheus_client import generate_latest, CONTENT_TYPE_LATEST
from app.core.circuit_breaker import CircuitBreaker
from app.core.metrics import MetricsRegistry

try:
    from app.core.cost_tracker import get_cost_tracker
    _HAS_COST_TRACKING = True
except ImportError:
    _HAS_COST_TRACKING = False

router = APIRouter()


@router.get("/metrics")
async def prometheus_metrics(request: Request):
    """Prometheus metrics endpoint."""
    container = request.app.state.container
    metrics: MetricsRegistry = container.resolve(MetricsRegistry)
    cb: CircuitBreaker = container.resolve(CircuitBreaker)

    # Update circuit breaker metrics
    metrics.gauge("circuit_breaker_state", 1 if cb.is_open else 0)

    # Add cost tracking metrics as gauges
    if _HAS_COST_TRACKING:
        try:
            costs = get_cost_tracker().snapshot()
            metrics.gauge("llm_total_tokens", costs["llm"]["total_tokens"])
            metrics.gauge("llm_cloud_calls", costs["llm"]["cloud_calls"])
            metrics.gauge("llm_local_calls", costs["llm"]["local_calls"])
            metrics.gauge("broker_api_total_calls", costs["broker_api"]["total_calls"])
            metrics.gauge("broker_api_rate_limits", costs["broker_api"]["rate_limit_hits"])
            metrics.gauge("trade_total_cost_rs", costs["trades"]["total_cost_rs"])
            metrics.gauge("trade_count", costs["trades"]["count"])
        except Exception:
            pass

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

    result = {
        "status": "healthy",
        "metrics_snapshot": metrics.snapshot()
    }

    # Add cost breakdown
    if _HAS_COST_TRACKING:
        try:
            result["costs"] = get_cost_tracker().snapshot()
        except Exception:
            result["costs"] = {"error": "Cost tracking unavailable"}

    return result