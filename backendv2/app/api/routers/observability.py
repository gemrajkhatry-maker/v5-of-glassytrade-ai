"""Observability endpoints for circuit-breakers and startup telemetry."""
from __future__ import annotations

from datetime import datetime

from fastapi import APIRouter, Request

from app.core.circuit_breaker import CircuitBreaker
from app.core.metrics import MetricsRegistry

router = APIRouter(prefix="/metrics", tags=["observability"])


def _to_dict(obj: object) -> dict:
    if hasattr(obj, "__dict__"):
        return dict(obj.__dict__)
    return {}


def _startup_snapshot(metrics: MetricsRegistry) -> dict:
    return {
        "status": "unknown",
        "timestamp": datetime.utcnow().isoformat(),
        "details": {"metrics": metrics.snapshot()},
    }


def _circuit_state_payload(circuit: object) -> dict:
    return {
        "state": getattr(circuit.state, "name", str(getattr(circuit, "_state", "UNKNOWN"))),
        "is_open": bool(getattr(circuit, "is_open", False)),
        "details": _to_dict(circuit),
    }


@router.get("/summary")
async def metrics_summary(request: Request):
    container = request.app.state.container
    metrics: MetricsRegistry = container.resolve(MetricsRegistry)
    
    snapshot = metrics.snapshot()
    return {
        "ticks_processed": snapshot.get("counters", {}).get("ticks_processed_total", 0),
        "signals_generated": snapshot.get("counters", {}).get("signals_generated_total", 0),
        "errors_total": snapshot.get("counters", {}).get("errors_total", 0),
        "pipeline_duration_avg": 0,
        "startup": _startup_snapshot(metrics),
        "startup_unresolved_symbols": 0,
    }


@router.get("/circuit-breakers")
async def circuit_breakers(request: Request):
    container = request.app.state.container
    cb: CircuitBreaker = container.resolve(CircuitBreaker)
    
    payload = _circuit_state_payload(cb)
    return {"amt": payload, "session": payload}


@router.get("/startup")
async def startup_telemetry(request: Request):
    container = request.app.state.container
    metrics: MetricsRegistry = container.resolve(MetricsRegistry)
    
    return _startup_snapshot(metrics)


@router.get("/startup/runbook")
async def startup_runbook(request: Request):
    del request
    return {
        "runbook": [
            {
                "category": "infrastructure",
                "action": "check startup logs and retry.",
            }
        ]
    }

