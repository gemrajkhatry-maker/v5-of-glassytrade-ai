"""Journal router — deterministic paper-trading journal endpoints.

Moved out of the former /ai router when the LLM layer was removed; the
trade journal is deterministic and unrelated to inference.
"""

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_trade_journal

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/journal", tags=["journal"])


@router.get("")
async def get_journal(
    date: Optional[str] = Query(None),
    run_id: Optional[str] = Query(None, alias="runId"),
    journal = Depends(get_trade_journal),
):
    """Returns journal entries for a given date (YYYY-MM-DD)."""
    return {"entries": journal.read_entries(date, run_id=run_id)}


@router.get("/trades")
async def get_journal_trades(
    date: Optional[str] = Query(None),
    run_id: Optional[str] = Query(None, alias="runId"),
    journal = Depends(get_trade_journal),
):
    """Returns completed trades (entry+exit pairs) for a given date."""
    return {"trades": journal.get_completed_trades(date, run_id=run_id)}


@router.get("/summary")
async def get_journal_summary(
    date: Optional[str] = Query(None),
    run_id: Optional[str] = Query(None, alias="runId"),
    journal = Depends(get_trade_journal),
):
    """Returns trade summary for a given date."""
    return journal.summary(date, run_id=run_id)


@router.get("/report")
async def get_journal_report(
    date: Optional[str] = Query(None),
    run_id: Optional[str] = Query(None, alias="runId"),
    journal = Depends(get_trade_journal),
):
    """Returns attribution and symbol-level report for a given date/run."""
    return journal.report(date, run_id=run_id)


@router.get("/compare")
async def get_journal_compare(
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    run_ids: Optional[str] = Query(None, alias="runIds"),
    journal = Depends(get_trade_journal),
):
    """Compare one or more runs across an inclusive date range."""
    parsed_run_ids = [item.strip() for item in run_ids.split(",")] if run_ids else None
    return journal.compare_runs(start_date=start, end_date=end, run_ids=parsed_run_ids)


@router.get("/promotion")
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
