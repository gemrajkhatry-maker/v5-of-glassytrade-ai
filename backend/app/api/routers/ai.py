"""AI analysis router — market analysis via fine-tuned LLM."""

import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel, Field

from app.api.dependencies import get_active_symbols, get_gen_ai_service, get_storage, get_trade_journal
from app.domain.fabio_ai.services.generative_ai_service import GenerativeAIService
from app.infrastructure.storage.database import SQLiteStorageAdapter

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ai", tags=["ai"])


class MarketAnalysisRequest(BaseModel):
    ltp: float
    delta: Optional[float] = 0.0
    volume: Optional[float] = 0.0
    context: Optional[str] = "Neutral"
    key_level: Optional[str] = None
    aggression: Optional[str] = None


@router.post("/analyze")
async def analyze_market(
    req: MarketAnalysisRequest,
    service: GenerativeAIService = Depends(get_gen_ai_service),
):
    """Analyzes market data using the fine-tuned Nanbeige model (Fabio Logic)."""
    market_data = req.model_dump()
    analysis = service.analyze_market(market_data)

    return {
        "direction": analysis["direction"],
        "rationale": analysis["rationale"],
        "raw_output": analysis.get("raw_output", ""),
    }


class CommandRequest(BaseModel):
    prompt: str
    current_config: dict[str, Any] = Field(alias="currentConfig", default={})
    model_config = {"populate_by_name": True}


# Chart command keywords → config updates
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


@router.post("/command")
async def process_command(req: CommandRequest):
    """Process natural-language chart/config commands from the frontend chat overlay."""
    prompt = req.prompt.lower().strip()
    config_updates: dict[str, Any] = {}
    messages: list[str] = []

    # Symbol switching
    for kw, sym in _SYMBOL_KEYWORDS.items():
        if kw in prompt:
            config_updates["symbol"] = sym
            messages.append(f"Switched to {sym}")
            break

    # Interval switching
    for kw, interval in _INTERVAL_KEYWORDS.items():
        if kw in prompt:
            config_updates["interval"] = interval
            messages.append(f"Interval set to {interval}")
            break

    # Color changes
    if "bull" in prompt:
        for kw, color in _COLOR_KEYWORDS.items():
            if kw in prompt:
                config_updates["bullColor"] = color
                messages.append(f"Bull color set to {kw}")
                break
    if "bear" in prompt:
        for kw, color in _COLOR_KEYWORDS.items():
            if kw in prompt:
                config_updates["bearColor"] = color
                messages.append(f"Bear color set to {kw}")
                break

    # Toggle features
    if "volume profile" in prompt:
        if "off" in prompt or "hide" in prompt:
            config_updates["showVolumeProfile"] = False
            config_updates["vpMode"] = "off"
            messages.append("Volume profile hidden")
        else:
            config_updates["showVolumeProfile"] = True
            config_updates["vpMode"] = "session"
            messages.append("Volume profile enabled")

    if "predictions" in prompt or "ghost" in prompt:
        show = "off" not in prompt and "hide" not in prompt
        config_updates["showPredictions"] = show
        messages.append(f"Predictions {'shown' if show else 'hidden'}")

    if "footprint" in prompt:
        messages.append("Switch to footprint mode using the tab at top-left")

    if not messages:
        messages.append(
            f"I understood: \"{req.prompt}\". Try commands like 'show nifty', 'set interval 5m', or 'bull color cyan'."
        )

    return {
        "message": " | ".join(messages),
        "configUpdates": config_updates if config_updates else None,
        "action": "UPDATE_CONFIG" if config_updates else None,
    }


@router.get("/history")
async def get_decision_history(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    limit: int = Query(1000),
    storage: SQLiteStorageAdapter = Depends(get_storage),
    active_symbols: list[str] = Depends(get_active_symbols),
):
    """Returns persisted decision history from SQLite — LLM decisions + signal decisions."""
    # Cap limit to prevent massive responses
    safe_limit = min(limit, 200)
    llm_rows = storage.query_llm_decisions(
        start=start, end=end, symbols=active_symbols if active_symbols else None
    )
    # Cap LLM rows too
    if len(llm_rows) > safe_limit:
        llm_rows = llm_rows[-safe_limit:]
    signal_rows = storage.query_signal_decisions(
        symbol=active_symbols[0] if active_symbols else None,
        limit=safe_limit,
    )
    return {"decisions": llm_rows, "signal_decisions": signal_rows}


@router.get("/journal")
async def get_journal(
    date: Optional[str] = Query(None),
    run_id: Optional[str] = Query(None, alias="runId"),
    journal = Depends(get_trade_journal),
):
    """Returns journal entries for a given date (YYYY-MM-DD)."""
    return {"entries": journal.read_entries(date, run_id=run_id)}


@router.get("/journal/trades")
async def get_journal_trades(
    date: Optional[str] = Query(None),
    run_id: Optional[str] = Query(None, alias="runId"),
    journal = Depends(get_trade_journal),
):
    """Returns completed trades (entry+exit pairs) for a given date."""
    return {"trades": journal.get_completed_trades(date, run_id=run_id)}


@router.get("/journal/summary")
async def get_journal_summary(
    date: Optional[str] = Query(None),
    run_id: Optional[str] = Query(None, alias="runId"),
    journal = Depends(get_trade_journal),
):
    """Returns trade summary for a given date."""
    return journal.summary(date, run_id=run_id)


@router.get("/journal/report")
async def get_journal_report(
    date: Optional[str] = Query(None),
    run_id: Optional[str] = Query(None, alias="runId"),
    journal = Depends(get_trade_journal),
):
    """Returns attribution and symbol-level report for a given date/run."""
    return journal.report(date, run_id=run_id)


@router.get("/journal/compare")
async def get_journal_compare(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    run_ids: Optional[str] = Query(None, alias="runIds"),
    journal = Depends(get_trade_journal),
):
    """Compare one or more runs across an inclusive date range."""
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
    journal = Depends(get_trade_journal),
):
    """Assess whether one or more paper-trading runs are ready for promotion."""
    parsed_run_ids = [item.strip() for item in run_ids.split(",")] if run_ids else None
    return journal.assess_promotion(
        start_date=start,
        end_date=end,
        run_ids=parsed_run_ids,
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
