"""Health check and metrics router."""

from fastapi import APIRouter
from app.infrastructure.metrics import MetricsCollector

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    return {"status": "ok", "service": "glassytrade-ai-backend"}


@router.get("/v1/metrics")
async def metrics():
    """Return current pipeline metrics."""
    return MetricsCollector().snapshot()
