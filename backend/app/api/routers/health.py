"""Health check, metrics, and system info router."""

import gc
import logging
import resource
import sys
import tracemalloc

logger = logging.getLogger(__name__)

from fastapi import APIRouter
from app.infrastructure.metrics import MetricsCollector
from app.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    from app.api.dependencies import get_service_graph
    graph = get_service_graph()

    checks: dict[str, str] = {}

    # Database check (critical)
    try:
        graph.storage.kv_set("_health_check", "1")
        checks["database"] = "ok"
    except Exception as e:
        logger.warning("Health check: database failed: %s", e)
        checks["database"] = f"error: {e}"

    # LLM check (critical for trading)
    try:
        llm_ready = graph.llm_inference.is_ready() if hasattr(graph.llm_inference, 'is_ready') else False
        load_error = getattr(graph.llm_inference, '_load_error', None)
        if llm_ready:
            checks["llm"] = "ok"
        elif load_error:
            checks["llm"] = f"error: {load_error}"
        else:
            checks["llm"] = "not_ready"
    except Exception as e:
        logger.warning("Health check: llm check failed: %s", e)
        checks["llm"] = f"error: {e}"

    # Probability engine check (non-critical)
    try:
        prob_ready = graph.probability_engine.is_ready() if hasattr(graph.probability_engine, 'is_ready') else False
        checks["probability"] = "ok" if prob_ready else "not_ready"
    except Exception as e:
        checks["probability"] = f"error: {e}"

    # Determine overall status
    critical = [checks["database"], checks["llm"]]
    if any(v.startswith("error") for v in critical):
        overall = "unhealthy"
    elif all(v == "ok" for v in checks.values()):
        overall = "ok"
    else:
        overall = "degraded"

    return {"status": overall, "checks": checks}


@router.get("/v1/metrics")
async def metrics():
    """Return current pipeline metrics."""
    return MetricsCollector().snapshot()


@router.post("/system/halt")
async def system_halt():
    """Emergency kill switch — immediately halt all trading."""
    from app.api.dependencies import get_service_graph
    graph = get_service_graph()
    graph.trading_session._risk_manager.halt_trading()
    return {"status": "halted"}


@router.post("/system/resume")
async def system_resume():
    """Clear the emergency kill switch and resume trading."""
    from app.api.dependencies import get_service_graph
    graph = get_service_graph()
    graph.trading_session._risk_manager.resume_trading()
    return {"status": "resumed"}


@router.get("/system/risk-state")
async def system_risk_state():
    """Return current risk manager state."""
    from app.api.dependencies import get_service_graph
    graph = get_service_graph()
    rm = graph.trading_session._risk_manager
    ds = rm.daily_state
    daily_dd = 0.0
    if ds.peak_equity > 0:
        daily_dd = (ds.peak_equity - ds.current_equity) / ds.peak_equity
    return {
        "halted": rm.is_halted,
        "haltReason": rm.halt_reason,
        "dailyDrawdownPct": round(daily_dd, 6),
        "consecutiveLosses": ds.consecutive_losses,
        "peakEquity": ds.peak_equity,
        "currentEquity": ds.current_equity,
        "driftAlert": rm._drift_alert,
        "driftMessage": rm._drift_message,
    }


@router.get("/system/config")
async def system_config():
    """Return backend configuration for frontend auto-detection."""
    from app.api.dependencies import get_service_graph
    graph = get_service_graph()
    llm_ready = graph.llm_inference.is_ready() if hasattr(graph.llm_inference, 'is_ready') else False
    prob_ready = graph.probability_engine.is_ready() if hasattr(graph.probability_engine, 'is_ready') else False

    return {
        "dataSource": "DHAN",
        "exchange": settings.DEFAULT_EXCHANGE,
        "defaultSymbol": graph.active_symbols[0] if graph.active_symbols else settings.DEFAULT_SYMBOL,
        "activeSymbols": graph.active_symbols,
        "symbols": settings.DHAN_SYMBOLS,
        "interval": settings.STREAM_INTERVAL,
        "tradingMode": settings.TRADING_MODE,
        "llmReady": llm_ready,
        "probabilityReady": prob_ready,
        "serverDriven": bool(settings.DHAN_CLIENT_ID),
    }


@router.get("/debug/memory")
async def debug_memory():
    """Return process memory and GC stats for debugging leaks."""
    rusage = resource.getrusage(resource.RUSAGE_SELF)
    gc_stats = gc.get_stats()

    result = {
        # macOS ru_maxrss is bytes, Linux is KB
        "rss_mb": round(rusage.ru_maxrss / ((1024 * 1024) if sys.platform == "darwin" else 1024), 2),
        "gc_stats": [
            {
                "collections": s["collections"],
                "collected": s["collected"],
                "uncollectable": s["uncollectable"],
            }
            for s in gc_stats
        ],
        "gc_objects": len(gc.get_objects()),
    }

    if tracemalloc.is_tracing():
        current, peak = tracemalloc.get_traced_memory()
        result["tracemalloc_current_mb"] = round(current / (1024 * 1024), 2)
        result["tracemalloc_peak_mb"] = round(peak / (1024 * 1024), 2)

    return result
