"""Health check, metrics, and system info router."""

from fastapi import APIRouter
from app.infrastructure.metrics import MetricsCollector
from app.config import settings

router = APIRouter(tags=["health"])


@router.get("/health")
async def health_check():
    return {"status": "ok", "service": "glassytrade-ai-backend"}


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
        "defaultSymbol": graph.active_symbol,
        "symbols": settings.DHAN_SYMBOLS,
        "interval": settings.STREAM_INTERVAL,
        "tradingMode": settings.TRADING_MODE,
        "llmReady": llm_ready,
        "probabilityReady": prob_ready,
        "serverDriven": bool(settings.DHAN_CLIENT_ID),
    }
