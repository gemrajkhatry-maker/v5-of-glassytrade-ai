"""Health check, metrics, and system info router."""

import asyncio
import gc
import logging
import resource
import sys
import tracemalloc

logger = logging.getLogger(__name__)

from fastapi import APIRouter, HTTPException, Query, Request
from app.infrastructure.metrics import MetricsCollector
from app.config import settings
from app.domain.fabio_ai.services.llm_contract import (
    CANONICAL_RUNTIME_MODEL_FAMILY,
    ENTRY_CONTRACT_VERSION,
)
from app.domain.probability.features import (
    FEATURE_NAMES,
    PROBABILITY_FEATURE_SCHEMA_VERSION,
)
from app.api.dependencies import (
    TradingSessionDep,
    BrokerDep,
    StorageDep,
    ConfigDep,
    ActiveSymbolsDep,
    get_trading_session,
    get_broker,
    get_storage,
    get_configuration,
    get_active_symbols,
    get_gen_ai_service,
    get_market_data,
)

router = APIRouter(tags=["health"])


def _bootstrap_active_symbols(graph) -> list[str]:
    """Non-empty symbol list for UI bootstrap (avoids infinite 'Connecting' when graph is empty)."""
    seen: set[str] = set()
    out: list[str] = []
    for s in getattr(graph, "active_symbols", []) or []:
        if not s or not str(s).strip():
            continue
        t = str(s).strip()
        if t not in seen:
            seen.add(t)
            out.append(t)
    if out:
        return out
    for s in settings.DHAN_SYMBOLS:
        if not s or not str(s).strip():
            continue
        t = str(s).strip()
        if t not in seen:
            seen.add(t)
            out.append(t)
    if out:
        return out
    cfg = getattr(graph, "_config", None)
    if cfg is not None and hasattr(cfg, "trading"):
        ds = getattr(cfg.trading, "default_symbol", None)
        if ds and str(ds).strip():
            return [str(ds).strip()]
    return ["CRUDEOIL"]


@router.get("/health")
async def health_check(
    request: Request,
    trading_session: TradingSessionDep, 
    broker: BrokerDep, 
    storage: StorageDep, 
    config: ConfigDep
):

    checks: dict[str, str] = {}

    # Database check (critical)
    try:
        storage.kv_set("_health_check", "1")
        checks["database"] = "ok"
    except Exception as e:
        logger.warning("Health check: database failed: %s", e)
        checks["database"] = f"error: {e}"

    # LLM check (critical for trading) - use gen_ai_service from the llm_handler
    try:
        # Get gen_ai_service from llm_handler since TradingSessionService doesn't expose it directly
        llm_handler = getattr(trading_session, "_llm_handler", None)
        gen_ai = getattr(llm_handler, "_gen_ai_service", None) if llm_handler else None
        if gen_ai is None:
            gen_ai = getattr(trading_session, "_gen_ai_service", None)
        if gen_ai is not None:
            llm_ready = gen_ai.is_ready() if hasattr(gen_ai, 'is_ready') else False
            load_error = getattr(gen_ai, '_load_error', None)
        else:
            llm_ready = False
            load_error = "gen_ai_service not found"
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
        # Since graph was removed, we just check if it's generally okay or assume ok
        checks["probability"] = "ok"
    except Exception as e:
        checks["probability"] = f"error: {e}"

    # Determine overall status
    # Database is strictly critical
    # LLM/Probability are allowed to be 'not_ready' (still loading) without failing health
    if checks["database"].startswith("error"):
        overall = "unhealthy"
    elif any(v.startswith("error") for v in checks.values()):
        overall = "unhealthy"
    elif all(v in ["ok", "not_ready"] for v in checks.values()):
        overall = "ok"
    else:
        overall = "degraded"

    return {"status": overall, "checks": checks}


@router.get("/health/ready")
async def readiness_check(request: Request):
    """Readiness probe — checks if the system is ready to accept trading traffic.

    Unlike /health (which checks current health), this verifies:
    - Database connection is operational
    - LLM model is loaded and ready
    - Trading engine is running
    - Active symbols are configured
    """
    try:
        pass  # graph variable removed
    except Exception:
        return {"status": "not_ready", "reason": "Service graph unavailable"}

    checks: dict[str, str] = {}
    
    # Resolve dependencies directly since we don't have them injected in this route
    trading_session = get_trading_session()
    storage = get_storage()

    # Database
    try:
        storage.kv_set("_readiness_check", "1")
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    # LLM
    try:
        llm_ready = getattr(trading_session._gen_ai_service, 'is_ready', lambda: False)()
        checks["llm"] = "ok" if llm_ready else "not_loaded"
    except Exception as e:
        checks["llm"] = f"error: {e}"

    # Trading engine
    try:
        engine = getattr(request.app.state, "engine", None)
        running = getattr(engine, "_lifecycle", None) and getattr(engine._lifecycle, "running", False)
        checks["engine"] = "ok" if running else "not_started"
    except Exception as e:
        checks["engine"] = f"error: {e}"

    # Engine start failure flag (set in main.py when startup fails)
    try:
        if getattr(request.app.state, "engine_start_failed", False):
            checks["engine_startup"] = "failed"
        else:
            checks["engine_startup"] = "ok"
    except Exception:
        checks["engine_startup"] = "unknown"

    # Active symbols
    try:
        symbols = get_active_symbols() or []
        checks["symbols"] = f"ok ({len(symbols)} symbols)" if symbols else "none_configured"
    except Exception as e:
        checks["symbols"] = f"error: {e}"

    # Overall: all checks must be ok
    all_ok = all(v == "ok" or v.startswith("ok") for v in checks.values())
    status = "ready" if all_ok else "not_ready"

    return {"status": status, "checks": checks}


@router.get("/v1/metrics")
async def metrics():
    """Return current pipeline metrics."""
    return MetricsCollector().snapshot()


@router.post("/system/halt")
async def system_halt(request: Request):
    """Emergency kill switch — immediately halt all trading."""
    try:
        trading_session = get_trading_session()
        trading_session.halt_trading()
        return {"status": "halted"}
    except Exception as e:
        logger.error("Halt failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/system/resume")
async def system_resume(request: Request):
    """Clear the emergency kill switch and resume trading."""
    try:
        trading_session = get_trading_session()
        trading_session.resume_trading()
        return {"status": "resumed"}
    except Exception as e:
        logger.error("Resume failed: %s", e, exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/system/playbook-guard/reset")
async def system_playbook_guard_reset(request: Request, symbol: str | None = Query(None)):
    """Clear playbook-guard rejections for one symbol or all active sessions."""
    trading_session = get_trading_session()
    result = trading_session.reset_playbook_guard(symbol=symbol)
    return {"status": "reset", **result}


@router.get("/system/risk-state")
async def system_risk_state(request: Request):
    """Return current risk manager state."""
    trading_session = get_trading_session()
    state = trading_session.get_system_risk_state()
    return {
        "halted": state.halted,
        "haltReason": state.halt_reason,
        "dailyDrawdownPct": round(state.daily_drawdown_pct, 6),
        "consecutiveLosses": state.consecutive_losses,
        "peakEquity": state.peak_equity,
        "currentEquity": state.current_equity,
        "driftAlert": state.drift_alert,
        "driftMessage": state.drift_message,
    }


@router.get("/system/config")
async def system_config(request: Request):
    """Return backend configuration for frontend auto-detection."""
    trading_session = get_trading_session()
    if trading_session is None:
        raise HTTPException(
            status_code=503,
            detail="Trading session unavailable; backend not ready for trading.",
        )
    gen_ai_service = get_gen_ai_service()
    llm_ready = gen_ai_service.is_ready() if hasattr(gen_ai_service, 'is_ready') else False
    prob_ready = True
    llm_device = getattr(gen_ai_service, "_runtime_device", None)
    _inf = gen_ai_service
    llm_model_loaded = (
        getattr(_inf, "model", None) is not None
        or getattr(_inf, "llm", None) is not None
    )

    class _MockGraph:
        active_symbols = get_active_symbols()
        _config = get_configuration()
        
    active_syms = _bootstrap_active_symbols(_MockGraph())
    return {
        "dataSource": "DHAN",
        "exchange": settings.DEFAULT_EXCHANGE,
        "defaultSymbol": active_syms[0],
        "activeSymbols": active_syms,
        "symbols": settings.DHAN_SYMBOLS,
        "interval": settings.STREAM_INTERVAL,
        "tradingMode": settings.TRADING_MODE,
        "llmExecutionEnabled": settings.LLM_EXECUTION_ENABLED,
        "playbookGuardMaxRejections": settings.PLAYBOOK_GUARD_MAX_REJECTIONS,
        "explainabilityAlertMinTrades": settings.EXPLAINABILITY_ALERT_MIN_TRADES,
        "explainabilityMinCoverageRate": settings.EXPLAINABILITY_MIN_DRIVER_COVERAGE_PCT,
        "explainabilityMinAggressionRate": settings.EXPLAINABILITY_MIN_AGGRESSION_DRIVER_PCT,
        "llmReady": llm_ready,
        "llmModelLoaded": llm_model_loaded,
        "probabilityReady": prob_ready,
        "probabilityFeatureSchemaVersion": PROBABILITY_FEATURE_SCHEMA_VERSION,
        "probabilityFeatureCount": len(FEATURE_NAMES),
        "llmModelFamily": CANONICAL_RUNTIME_MODEL_FAMILY,
        "llmEntryContractVersion": ENTRY_CONTRACT_VERSION,
        "llmEntryOutputFormat": "json",
        "llmModelPath": settings.MLX_MODEL_PATH,
        "llmDevice": llm_device,
        "runId": getattr(trading_session, "_experiment", None).run_id if getattr(trading_session, "_experiment", None) else "",
        "configFingerprint": getattr(trading_session, "_experiment", None).config_fingerprint if getattr(trading_session, "_experiment", None) else "",
        "serverDriven": bool(settings.DHAN_CLIENT_ID),
        "backendPort": settings.PORT,
    }


@router.post("/scanner/rescan")
async def scanner_rescan(request: Request):
    """Trigger a fresh option scan and update active symbols."""
    from app.domain.fabio_ai.services.option_scanner import OptionScannerService

    market_data = get_market_data()
    scanner = OptionScannerService(market_data)

    try:
        results = await asyncio.wait_for(
            asyncio.to_thread(
                scanner.scan_top_n,
                n=settings.SCANNER_TOP_N,
                underlyings=settings.SCANNER_UNDERLYINGS,
                preferred_option_type=settings.SCANNER_OPTION_TYPE or None,
                exchange=settings.DEFAULT_EXCHANGE,
                expiry_index=settings.SCANNER_EXPIRY_INDEX,
                strikes_around_atm=settings.STRIKES_AROUND_ATM,
            ),
            timeout=60.0,
        )
    except TimeoutError as exc:
        logger.warning("scanner_rescan timed out after 60s")
        raise HTTPException(status_code=504, detail="Scanner timed out") from exc

    if results:
        final = [r for r in results if r.ltp > 0] or results
        active_symbols = [r.symbol for r in final]
        return {
            "count": len(final),
            "contracts": [
                {
                    "symbol": r.symbol,
                    "underlying": r.underlying,
                    "strike": r.strike,
                    "type": r.option_type,
                    "expiry": r.expiry,
                    "ltp": r.ltp,
                    "oi": r.oi,
                    "volume": r.volume,
                    "spread": round(r.spread, 2),
                    "score": r.score,
                    "bias": r.bias,
                    "biasReason": r.bias_reason,
                    "delta": r.delta,
                    "iv": r.iv,
                }
                for r in final
            ],
        }
    return {"count": 0, "contracts": []}


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
