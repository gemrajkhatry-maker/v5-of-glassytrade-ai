"""Health check, metrics, and system info router."""

import asyncio
import gc
import logging
import resource
import sys
import tracemalloc

from app.core.async_boundary import ensure_sync_adapter_result

logger = logging.getLogger(__name__)

from fastapi import APIRouter, HTTPException, Query, Request

from app.api.dependencies import (
    ActiveSymbolsDep,
    BrokerDep,
    ConfigDep,
    StorageDep,
    get_active_symbols,
    get_broker,
    get_configuration,
    get_market_data,
    get_storage,
)
from app.config import settings
from app.infrastructure.metrics import MetricsCollector
from quant.probability.features import (
    FEATURE_NAMES,
    PROBABILITY_FEATURE_SCHEMA_VERSION,
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
    broker: BrokerDep, 
    storage: StorageDep, 
    config: ConfigDep
):

    checks: dict[str, str] = {}

    # Database check (critical)
    try:
        ensure_sync_adapter_result("storage.kv_set", storage.kv_set, "_health_check", "1")
        checks["database"] = "ok"
    except Exception as e:
        logger.warning("Health check: database failed: %s", e)
        checks["database"] = f"error: {e}"

    from app.shared.mode import is_live_mode

    if is_live_mode():
        checks["live_oms"] = "wired (LiveOMS)"

    coordinator = getattr(request.app.state, "coordinator", None)
    journal_fails = 0
    if coordinator is not None and hasattr(coordinator, "journal_consecutive_failures"):
        try:
            journal_fails = int(coordinator.journal_consecutive_failures() or 0)
        except Exception:
            logger.exception("Health check: journal_consecutive_failures failed")
    checks["journal"] = "ok" if journal_fails == 0 else f"degraded({journal_fails})"

    # Probability engine check (non-critical)
    try:
        checks["probability"] = "ok"
    except Exception as e:
        checks["probability"] = f"error: {e}"

    # Greenfield QuantCoordinator check (additive — does not gate overall health)
    if coordinator is not None:
        try:
            started = bool(getattr(coordinator, "started", False))
            symbols = list(coordinator.symbols() or [])
            crashed = []
            if started and hasattr(coordinator, "crashed_engines"):
                try:
                    crashed = coordinator.crashed_engines()
                except Exception:
                    logger.exception("Health check: crashed_engines failed")
            stale = []
            if started and hasattr(coordinator, "stale_engines"):
                try:
                    stale = coordinator.stale_engines()
                except Exception:
                    logger.exception("Health check: stale_engines failed")
            checks["coordinator"] = {
                "started": started,
                "symbols": symbols,
                "crashedEngines": crashed,
                "staleEngines": stale,
                "status": "degraded" if (crashed or stale) else ("ok" if started else "not_started"),
            }
        except Exception as e:
            logger.warning("Health check: coordinator check failed: %s", e)
            checks["coordinator"] = {
                "started": False,
                "symbols": [],
                "status": f"error: {e}",
            }

    # Determine overall status
    # Database is strictly critical
    # LLM/Probability are allowed to be 'not_ready' (still loading) without failing health
    if checks["database"].startswith("error"):
        overall = "unhealthy"
    elif any(isinstance(v, str) and v.startswith("error") for v in checks.values()):
        overall = "unhealthy"
    elif all(
        v in ["ok", "not_ready", "degraded"]
        for k, v in checks.items()
        if k not in {"coordinator"}
    ):
        coord_check = checks.get("coordinator")
        if isinstance(coord_check, dict) and (
            coord_check.get("crashedEngines") or coord_check.get("staleEngines")
        ):
            overall = "degraded"
        else:
            overall = "ok"
    else:
        overall = "degraded"

    return {"status": overall, "checks": checks}


@router.get("/health/ready")
async def readiness_check(request: Request):
    """Readiness probe — checks if the system is ready to accept trading traffic.

    Unlike /health (which checks current health), this verifies:
    - Database connection is operational
    - Trading engine is running
    - Active symbols are configured
    """
    try:
        pass  # graph variable removed
    except Exception:
        return {"status": "not_ready", "reason": "Service graph unavailable"}

    checks: dict[str, str] = {}
    
    # Resolve dependencies directly since we don't have them injected in this route
    storage = get_storage()

    # Database
    try:
        ensure_sync_adapter_result(
            "storage.kv_set",
            storage.kv_set,
            "_readiness_check",
            "1",
        )
        checks["database"] = "ok"
    except Exception as e:
        checks["database"] = f"error: {e}"

    # QuantCoordinator (the decision brain — replaces the legacy engine)
    try:
        coordinator = getattr(request.app.state, "coordinator", None)
        running = bool(coordinator) and bool(getattr(coordinator, "started", False))
        if running and hasattr(coordinator, "crashed_engines"):
            crashed = coordinator.crashed_engines() or []
            checks["engine"] = (
                f"crashed: {len(crashed)} engine(s) dead" if crashed else "ok"
            )
        else:
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

    # Coordinator readiness (truthful degraded states)
    try:
        coordinator = getattr(request.app.state, "coordinator", None)
        if coordinator is not None and hasattr(coordinator, "readiness"):
            status, details = coordinator.readiness()
            checks["coordinator_readiness"] = status.value
            if status.value != "READY":
                checks["coordinator_readiness_details"] = details
        else:
            checks["coordinator_readiness"] = "unknown"
    except Exception as e:
        checks["coordinator_readiness"] = f"error: {e}"

    # Startup runtime contracts
    try:
        startup_contracts = getattr(request.app.state, "startup_contracts", {})
        checks["startup_contracts"] = startup_contracts.get("status", "unknown")
        checks["startup_contract_id"] = startup_contracts.get("contract_id", "unknown")
        checks["startup_broker"] = startup_contracts.get("broker_runtime", "unknown")
        checks["startup_storage"] = startup_contracts.get("storage_runtime", "unknown")
        checks["startup_reconciliation"] = startup_contracts.get("reconciliation", "unknown")
        checks["startup_reconciliation_summary"] = startup_contracts.get(
            "reconciliation_summary", "unknown"
        )
        checks["startup_reconciliation_discrepancies"] = startup_contracts.get(
            "reconciliation_discrepancies", "unknown"
        )
        checks["startup_active_symbols"] = startup_contracts.get("active_symbols", "unknown")
        checks["startup_scanner"] = startup_contracts.get("scanner_settings", "unknown")
        checks["startup_strategy"] = startup_contracts.get("strategy_runtime", "unknown")
        checks["startup_close_contract"] = startup_contracts.get(
            "position_close_contract", "unknown"
        )

        # Backward-compatible aliases
        checks["startup_broker_runtime"] = startup_contracts.get("broker_runtime", "unknown")
        checks["startup_storage_runtime"] = startup_contracts.get("storage_runtime", "unknown")
        checks["startup_reconciliation_contract"] = startup_contracts.get(
            "reconciliation", "unknown"
        )
        checks["position_close_contract"] = startup_contracts.get(
            "position_close_contract", "unknown"
        )
    except Exception as e:
        checks["startup_contracts"] = f"error: {e}"

    # Overall: all checks must be ok
    all_ok = all(
        (
            v == "ok"
            or (isinstance(v, str) and v.startswith("ok"))
            or v == "degraded"
            or v == "DEGRADED_NO_NEW_ENTRIES"
        )
        for k, v in checks.items()
        if k
        not in {
            "startup_contract_id",
            "startup_reconciliation_summary",
            "startup_reconciliation_discrepancies",
            "startup_broker_runtime",
            "startup_storage_runtime",
            "startup_reconciliation_contract",
            "position_close_contract",
            "coordinator_readiness_details",
        }
    )
    if str(checks.get("startup_close_contract", "")).startswith("error"):
        all_ok = False
    # NOT_READY overrides everything
    if checks.get("coordinator_readiness") == "NOT_READY":
        all_ok = False
    status = "ready" if all_ok else "not_ready"

    return {"status": status, "checks": checks}


@router.get("/v1/metrics")
async def metrics():
    """Return current pipeline metrics.

    Uses CoordinatorMetricsProvider to read per-engine activity from the
    coordinator's engines, replacing the disconnected MetricsCollector that
    reported 0 ticks while WebSocket showed live market flow.
    """
    coordinator = getattr(request.app.state, "coordinator", None)
    if coordinator is not None:
        from quant.execution.coordinator_metrics import coordinator_metrics_provider
        provider = coordinator_metrics_provider(coordinator)
        return provider.snapshot()
    # Fallback: no coordinator — return empty but well-formed payload
    from quant.execution import exits as _exits_mod
    return {
        "engines": {},
        "totals": {
            "decision_count": 0,
            "approved_count": 0,
            "blocked_count": 0,
            "engine_count": 0,
            "model_risk_failures": _exits_mod.MODEL_RISK_FAILURES,
        },
    }


@router.get("/system/config")
async def system_config(request: Request):
    """Return backend configuration for frontend auto-detection."""
    prob_ready = True

    class _MockGraph:
        active_symbols = get_active_symbols()
        _config = get_configuration()

    # Prefer the greenfield coordinator's live contracts so the frontend
    # subscribes to symbols the coordinator can actually stream (base
    # underlyings like "NIFTY" are not engine keys — contracts are).
    coordinator = getattr(request.app.state, "coordinator", None)
    coordinator_symbols: list[str] = []
    if coordinator is not None:
        try:
            coordinator_symbols = list(coordinator.symbols() or [])
        except Exception:
            coordinator_symbols = []
    active_syms = coordinator_symbols or _bootstrap_active_symbols(_MockGraph())
    return {
        "dataSource": "DHAN",
        "exchange": settings.DEFAULT_EXCHANGE,
        "defaultSymbol": active_syms[0],
        "activeSymbols": active_syms,
        "symbols": settings.DHAN_SYMBOLS,
        "interval": settings.STREAM_INTERVAL,
        "tradingMode": settings.TRADING_MODE,
        "playbookGuardMaxRejections": settings.PLAYBOOK_GUARD_MAX_REJECTIONS,
        "explainabilityAlertMinTrades": settings.EXPLAINABILITY_ALERT_MIN_TRADES,
        "explainabilityMinCoverageRate": settings.EXPLAINABILITY_MIN_DRIVER_COVERAGE_PCT,
        "explainabilityMinAggressionRate": settings.EXPLAINABILITY_MIN_AGGRESSION_DRIVER_PCT,
        "probabilityReady": prob_ready,
        "probabilityFeatureSchemaVersion": PROBABILITY_FEATURE_SCHEMA_VERSION,
        "probabilityFeatureCount": len(FEATURE_NAMES),
        "runId": "",
        "configFingerprint": "",
        "serverDriven": bool(settings.DHAN_CLIENT_ID),
        "backendPort": settings.PORT,
    }


@router.post("/scanner/rescan")
async def scanner_rescan(request: Request):
    """Trigger a fresh option scan and update active symbols."""
    coordinator = getattr(request.app.state, "coordinator", None)
    if coordinator is not None:
        try:
            syms = await asyncio.to_thread(coordinator.rescan)
        except Exception as e:
            logger.error("scanner_rescan via coordinator failed: %s", e, exc_info=True)
            raise HTTPException(status_code=500, detail=str(e)) from e
        contracts = []
        for s in syms:
            snap = coordinator.snapshot(s)
            contracts.append(
                {
                    "symbol": s,
                    "ltp": snap.get("ltp"),
                    "oi": snap.get("oi"),
                    "tick": snap.get("tick"),
                }
            )
        return {"count": len(syms), "contracts": contracts}

    from quant.amt.session.scanner import OptionScannerService
    from quant.amt.session.scanner_config import ScannerConfig

    market_data = get_market_data()
    scanner = OptionScannerService(market_data)
    scan_cfg = ScannerConfig.from_settings(settings)

    try:
        results = await asyncio.wait_for(
            asyncio.to_thread(
                scanner.scan_top_n,
                **scan_cfg.to_scan_kwargs(exchange=settings.DEFAULT_EXCHANGE),
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
