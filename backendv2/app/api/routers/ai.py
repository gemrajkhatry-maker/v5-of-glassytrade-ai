"""AI analysis and command router for chat/config endpoints."""
from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, ConfigDict, Field

from app.api.dependencies import (
    get_active_symbols,
    get_gen_ai_service,
    get_storage,
    get_trade_journal,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/ai", tags=["ai"])

_SYMBOL_KEYWORDS = {
    "nifty": "NIFTY",
    "banknifty": "BANKNIFTY",
    "finnifty": "FINNIFTY",
    "crude": "CRUDEOIL",
    "crudeoil": "CRUDEOIL",
    "natural gas": "NATURALGAS",
    "gold": "GOLD",
    "silver": "SILVER",
}

_INTERVAL_KEYWORDS = {
    "15m": "15m",
    "1m": "1m",
    "5m": "5m",
    "1h": "1h",
    "4h": "4h",
    "1d": "1d",
}

_COLOR_KEYWORDS = {
    "red": "#ef4444",
    "green": "#10b981",
    "blue": "#3b82f6",
    "purple": "#8b5cf6",
    "cyan": "#06b6d4",
    "amber": "#f59e0b",
    "neon": "#39ff14",
    "pink": "#ec4899",
    "white": "#ffffff",
}


class MarketAnalysisRequest(BaseModel):
    ltp: float
    delta: Optional[float] = 0.0
    volume: Optional[float] = 0.0
    context: Optional[str] = "Neutral"
    key_level: Optional[str] = None
    aggression: Optional[str] = None


class CommandRequest(BaseModel):
    prompt: str
    currentConfig: dict[str, Any] = Field(default_factory=dict, alias="currentConfig")
    model_config = ConfigDict(populate_by_name=True)


def _analyze_market_payload(data: dict[str, Any]) -> dict[str, Any]:
    ltp = float(data.get("ltp", 0.0))
    delta = float(data.get("delta", 0.0))
    volume = float(data.get("volume", 0.0))
    context = str(data.get("context", "Neutral") or "Neutral")
    key_level = data.get("key_level")
    aggression = str(data.get("aggression", "")).lower()

    if delta > 0 and ltp > 0:
        direction = "LONG"
    elif delta < 0 and ltp > 0:
        direction = "SHORT"
    elif ltp > 0:
        direction = "NEUTRAL"
    else:
        direction = "NEUTRAL"

    pressure = "LOW"
    if volume > 0:
        pressure = "HIGH" if abs(delta) > volume else "MEDIUM" if abs(delta) > volume * 0.3 else "LOW"
    conf = 60 if abs(delta) > 0 else 55

    rationale = (
        f"{context} context, {pressure.lower()} pressure at {ltp:.2f}, "
        f"delta={delta:.2f}, volume={volume:.2f}"
    )
    if key_level:
        rationale += f", key level hint: {key_level}"
    if aggression:
        rationale += f", aggression: {aggression}"

    return {
        "direction": direction,
        "confidence": conf,
        "rationale": rationale,
        "raw_output": json.dumps(
            {"direction": direction, "confidence": conf, "rationale": rationale, "payload": data}
        ),
    }


def _parse_market_command(prompt: str) -> dict[str, Any]:
    text = prompt.lower().strip()
    config_updates: dict[str, Any] = {}
    messages: list[str] = []

    for keyword, sym in _SYMBOL_KEYWORDS.items():
        if keyword in text:
            config_updates["symbol"] = sym
            messages.append(f"Switched to {sym}")
            break

    for keyword, interval in _INTERVAL_KEYWORDS.items():
        if keyword in text:
            config_updates["interval"] = interval
            messages.append(f"Interval set to {interval}")
            break

    if "bull" in text:
        for kw, color in _COLOR_KEYWORDS.items():
            if kw in text:
                config_updates["bullColor"] = color
                messages.append(f"Bull color set to {kw}")
                break

    if "bear" in text:
        for kw, color in _COLOR_KEYWORDS.items():
            if kw in text:
                config_updates["bearColor"] = color
                messages.append(f"Bear color set to {kw}")
                break

    if "volume profile" in text:
        if "off" in text or "hide" in text:
            config_updates["showVolumeProfile"] = False
            config_updates["vpMode"] = "off"
            messages.append("Volume profile hidden")
        else:
            config_updates["showVolumeProfile"] = True
            config_updates["vpMode"] = "session"
            messages.append("Volume profile enabled")

    if "predictions" in text or "ghost" in text:
        show = "off" not in text and "hide" not in text
        config_updates["showPredictions"] = show
        messages.append(f"Predictions {'shown' if show else 'hidden'}")

    if "footprint" in text:
        messages.append("Switch to footprint mode using the tab at top-left")

    if not messages:
        messages.append(
            f'I understood: "{prompt}". Try commands like "show nifty", "set interval 5m", '
            "or " '"bull color cyan".'
        )

    return {
        "message": " | ".join(messages),
        "configUpdates": config_updates if config_updates else None,
        "action": "UPDATE_CONFIG" if config_updates else None,
    }


@router.post("/analyze")
async def analyze_market(
    req: MarketAnalysisRequest,
    service: Any = Depends(get_gen_ai_service),
):
    """Analyze single-point market input via LLM or fallback heuristics."""
    market_data = req.model_dump()
    if service is None:
        return _analyze_market_payload(market_data)
    try:
        analysis = service.analyze_market(market_data)
        if isinstance(analysis, dict):
            return {
                "direction": analysis.get("direction", "NEUTRAL"),
                "rationale": analysis.get("rationale", ""),
                "raw_output": analysis.get("raw_output", ""),
            }
    except Exception:
        logger.exception("ai/analyze failed; using fallback")
    return _analyze_market_payload(market_data)


@router.post("/command")
async def process_command(req: CommandRequest):
    """Parse natural-language chart/config command into config patches."""
    return _parse_market_command(req.prompt)


@router.get("/history")
async def get_decision_history(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    limit: int = Query(1000),
    storage=Depends(get_storage),
    active_symbols=Depends(get_active_symbols),
):
    """Return persisted LLM decision history from storage."""
    safe_limit = min(limit, 200)
    if storage is None or not hasattr(storage, "query_llm_decisions"):
        raise HTTPException(status_code=503, detail="Storage unavailable")

    try:
        rows = []
        if active_symbols:
            for symbol in active_symbols:
                rows.extend(storage.query_llm_decisions(symbol=symbol, start=start, end=end))
        else:
            rows = storage.query_llm_decisions(start=start, end=end)
        rows = sorted(rows, key=lambda item: str(item.get("created_at", "")), reverse=True)
        return {"decisions": rows[:safe_limit], "signal_decisions": []}
    except Exception as exc:
        raise HTTPException(status_code=500, detail=str(exc)) from exc


@router.get("/journal")
async def get_journal(
    date: Optional[str] = Query(None),
    run_id: Optional[str] = Query(None, alias="runId"),
    journal=Depends(get_trade_journal),
):
    """Return journal entries."""
    return journal.read_entries(date, run_id)


@router.get("/journal/trades")
async def get_journal_trades(
    date: Optional[str] = Query(None),
    run_id: Optional[str] = Query(None, alias="runId"),
    journal=Depends(get_trade_journal),
):
    return journal.get_completed_trades(date, run_id)


@router.get("/journal/summary")
async def get_journal_summary(
    date: Optional[str] = Query(None),
    run_id: Optional[str] = Query(None, alias="runId"),
    journal=Depends(get_trade_journal),
):
    return journal.summary(date, run_id)


@router.get("/journal/report")
async def get_journal_report(
    date: Optional[str] = Query(None),
    run_id: Optional[str] = Query(None, alias="runId"),
    journal=Depends(get_trade_journal),
):
    return journal.summary(date, run_id)


@router.get("/journal/compare")
async def get_journal_compare(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    run_ids: Optional[str] = Query(None, alias="runIds"),
    journal=Depends(get_trade_journal),
):
    parsed_run_ids = [item.strip() for item in run_ids.split(",")] if run_ids else None
    return journal.compare_runs(start_date=start, end_date=end, run_ids=parsed_run_ids)


@router.get("/journal/promotion")
async def get_journal_promotion(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    run_ids: Optional[str] = Query(None, alias="runIds"),
    min_trades: int = Query(20, alias="minTrades"),
    min_expectancy: float = Query(0.0, alias="minExpectancy"),
    min_profit_factor: float = Query(1.1, alias="minProfitFactor"),
    max_drawdown: float = Query(10.0, alias="maxDrawdown"),
    min_trading_days: int = Query(3, alias="minTradingDays"),
    max_symbol_concentration_pct: float = Query(
        70.0, alias="maxSymbolConcentrationPct"
    ),
    require_multi_session: bool = Query(True, alias="requireMultiSession"),
    min_thesis_completion_rate: float = Query(95.0, alias="minThesisCompletionRate"),
    min_playbook_purity_rate: float = Query(95.0, alias="minPlaybookPurityRate"),
    max_playbook_session_misuse_rate: float = Query(
        0.0, alias="maxPlaybookSessionMisuseRate"
    ),
    min_feature_driver_coverage_rate: float = Query(
        90.0, alias="minFeatureDriverCoverageRate"
    ),
    min_aggression_driver_rate: float = Query(75.0, alias="minAggressionDriverRate"),
    journal=Depends(get_trade_journal),
):
    return journal.assess_promotion(
        start_date=start,
        end_date=end,
        run_ids=run_ids.split(",") if run_ids else None,
        min_trades=min_trades,
        min_expectancy=min_expectancy,
        min_profit_factor=min_profit_factor,
        max_drawdown=max_drawdown,
        min_trading_days=min_trading_days,
        max_symbol_concentration_pct=max_symbol_concentration_pct,
        require_multi_session=require_multi_session,
        min_thesis_completion_rate=min_thesis_completion_rate,
        min_playbook_purity_rate=min_playbook_purity_rate,
        max_playbook_session_misuse_rate=max_playbook_session_misuse_rate,
        min_feature_driver_coverage_rate=min_feature_driver_coverage_rate,
        min_aggression_driver_rate=min_aggression_driver_rate,
    )

