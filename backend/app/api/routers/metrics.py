"""Metrics endpoint — exposes observability data.

Provides gate rejection rates, latency percentiles, and session health
for the React dashboard and monitoring tools.
"""

from __future__ import annotations

from fastapi import APIRouter
from app.domain.services.gate_rejection_tracker import GateRejectionTracker
from app.domain.services.latency_tracker import LatencyTracker

router = APIRouter(prefix="/v1/metrics", tags=["metrics"])

# Module-level singletons — injected via set_trackers()
_gate_tracker: GateRejectionTracker | None = None
_latency_tracker: LatencyTracker | None = None


def set_trackers(
    gate_tracker: GateRejectionTracker,
    latency_tracker: LatencyTracker,
) -> None:
    """Set tracker instances (called from DI container init)."""
    global _gate_tracker, _latency_tracker
    _gate_tracker = gate_tracker
    _latency_tracker = latency_tracker


@router.get("/gates")
async def gate_rejection_metrics():
    """Gate rejection rates per symbol, per gate."""

    if not _gate_tracker:
        return {"error": "Gate tracker not initialized"}
    return _gate_tracker.get_summary()


@router.get("/latency")
async def latency_metrics():
    """Tick-to-signal latency percentiles per symbol."""

    if not _latency_tracker:
        return {"error": "Latency tracker not initialized"}
    return _latency_tracker.get_summary()


@router.get("/session-health")
async def session_health_metrics():
    """Combined session health snapshot."""
    result = {}
    if _gate_tracker:
        result["gates"] = _gate_tracker.get_summary()
    if _latency_tracker:
        result["latency"] = _latency_tracker.get_summary()
    return result
