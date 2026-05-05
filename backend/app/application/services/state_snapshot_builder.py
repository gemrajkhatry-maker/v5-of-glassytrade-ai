"""State Snapshot Builder — DTO formatting for UI state snapshots.

Extracted from trading_session.py. Pure DTO formatting with no side effects.
Builds the state dict that the React dashboard consumes.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING, Any

from app.config import settings
from app.domain.trading.models.enums import MarketStateCodec, Source
from app.infrastructure.serialization.schemas import portfolio_to_dto, stats_to_dto

if TYPE_CHECKING:
    from app.domain.fabio_ai.services.exit_engine import ExitEngine as TradeManager
    from app.application.handlers.trade_lifecycle_handler import TradeLifecycleHandler

log = logging.getLogger(__name__)


def compute_cumulative_deltas(candles: list) -> list:
    """Compute cumulative volume delta (CVD) from candle data.

    Business logic: running delta sum for each candle.
    This replaces frontend computation with backend single source of truth.

    Args:
        candles: List of OHLC candle objects with delta field

    Returns:
        List of cumulative delta values (integers)
    """
    running_delta = 0
    result = []
    for c in candles:
        try:
            delta = float(getattr(c, "delta", 0) or 0)
            running_delta += delta
            result.append(int(running_delta))
        except (TypeError, ValueError):
            result.append(0)
    return result


def build_state_snapshot(
    session,
    risk_coordinator,
    rl_handler,
    lifecycle_handler: "TradeLifecycleHandler | None" = None,
) -> dict:
    """Build the state snapshot dict for the UI dashboard.

    Args:
        session: TradingSession instance
        risk_coordinator: RiskCoordinator instance
        rl_handler: RLHandler instance
        lifecycle_handler: TradeLifecycleHandler for getting managed positions
    """
    weights = session.learning.weights

    with session._lock:
        ai_analysis = session.last_ai_analysis
        portfolio_dto = portfolio_to_dto(session.portfolio)
        llm_stats = stats_to_dto(session.portfolio.get_stats(Source.LLM))
        agent_stats = stats_to_dto(session.portfolio.get_stats(Source.AGENT))
        stats_by_source = {
            "amt": stats_to_dto(session.portfolio.get_stats(Source.AMT)),
            "prediction": stats_to_dto(session.portfolio.get_stats(Source.PREDICTION)),
            "rl": stats_to_dto(session.portfolio.get_stats(Source.RL)),
            "llm": llm_stats,
            "agent": agent_stats,
        }

    rm = risk_coordinator._get_risk_manager(session.symbol)

    return {
        "_symbol": session.symbol,
        "portfolio": portfolio_dto,
        "amt": session.last_amt,
        "prediction": session.last_prediction,
        "footprint": session.last_footprint,
        "cumulative_deltas": compute_cumulative_deltas(session.data),
        "genAIAnalysis": _camel_case_ai(ai_analysis),
        "overseerAction": (ai_analysis or {}).get("overseer_action", ""),
        "overseerReason": (ai_analysis or {}).get("overseer_reason", ""),
        "modelWeights": {
            "trend": weights.trend,
            "momentum": weights.momentum,
            "delta": weights.delta,
            "orderBook": weights.order_book,
            "volatility": weights.volatility,
        },
        "generation": session.learning.generation,
        "stats": llm_stats,
        "statsBySource": stats_by_source,
        "agentDecision": _agent_decision_dto(session),
        "playbookGuard": _playbook_guard_status(session, risk_coordinator),
        "explainabilityMonitor": _explainability_status(session),
        "rlStatus": rl_handler.get_status(),
        "riskState": {
            "halted": rm.is_halted,
            "haltReason": rm.halt_reason,
            "consecutiveLosses": rm.daily_state.consecutive_losses,
            "dailyPnl": rm.daily_state.realized_pnl,
            "driftAlert": rm._drift_alert,
            "driftMessage": rm._drift_message,
        },
    }


def _playbook_guard_status(session, risk_coordinator) -> dict:
    session_info = getattr(session, "_last_session_info", None)
    agent = getattr(session, "_agent_decision", None)
    amt = session.last_amt or {}
    market_state = str(amt.get("marketState", ""))
    expected = _expected_playbook_for(session_info, market_state)
    candidate = getattr(agent, "playbook", "") if agent is not None else ""
    session_name = getattr(session_info, "session", "")
    session_compatible = expected != "" or not session_name

    from app.application.services.session_state_manager import SessionStateManager

    state_mgr = getattr(risk_coordinator, "_state_manager", None)

    return {
        "session": session_name,
        "marketState": market_state,
        "expectedPlaybook": expected,
        "candidatePlaybook": candidate,
        "guardTripped": state_mgr._playbook_guard_tripped(session)
        if state_mgr
        else False,
        "maxRejections": settings.PLAYBOOK_GUARD_MAX_REJECTIONS,
        "totalRejections": state_mgr._playbook_guard_total(session) if state_mgr else 0,
        "sessionCompatible": session_compatible,
        "agentAligned": (candidate == expected) if candidate and expected else False,
        "lastRejectionReason": getattr(session, "_last_playbook_guard_reason", ""),
        "rejections": dict(getattr(session, "_playbook_guard_rejections", {})),
    }


def _expected_playbook_for(session_info, market_state: str) -> str:
    if not session_info:
        return ""
    if MarketStateCodec.is_imbalanced(market_state) and getattr(
        session_info, "allow_trend", False
    ):
        return "imbalance_continuation"
    if MarketStateCodec.is_balanced(market_state) and getattr(
        session_info, "allow_reversion", False
    ):
        return "return_to_value"
    return ""


def _explainability_status(session) -> dict:
    total = getattr(session, "_explainability_entries", 0)
    explained = getattr(session, "_explained_entries", 0)
    aggression = getattr(session, "_aggression_explained_entries", 0)
    coverage_rate = round((explained / total * 100.0), 1) if total else 0.0
    aggression_rate = round((aggression / total * 100.0), 1) if total else 0.0
    min_trades = settings.EXPLAINABILITY_ALERT_MIN_TRADES
    alert = getattr(session, "_last_explainability_alert", "")
    return {
        "entries": total,
        "explainedEntries": explained,
        "aggressionExplainedEntries": aggression,
        "coverageRate": coverage_rate,
        "aggressionDriverRate": aggression_rate,
        "minTrades": min_trades,
        "minCoverageRate": settings.EXPLAINABILITY_MIN_DRIVER_COVERAGE_PCT,
        "minAggressionRate": settings.EXPLAINABILITY_MIN_AGGRESSION_DRIVER_PCT,
        "alertActive": bool(alert) and total >= min_trades,
        "alertReason": alert,
    }


def _agent_decision_dto(session) -> dict | None:
    ad = getattr(session, "_agent_decision", None)
    if ad is None:
        return None
    return {
        "direction": ad.direction,
        "probability": round(ad.probability, 3),
        "regime": ad.regime,
        "playbook": getattr(ad, "playbook", ""),
        "featureDrivers": list(getattr(ad, "feature_drivers", ())),
        "timing": ad.timing,
        "sizeFraction": round(ad.size_fraction, 3),
        "slAdjust": round(ad.sl_adjust, 2),
        "tpAdjust": round(ad.tp_adjust, 2),
        "latencyUs": ad.latency_us,
        "rationale": ad.rationale,
    }


def _camel_case_ai(data: dict | None) -> dict | None:
    if not data:
        return data
    return {
        "direction": data.get("direction", "FLAT"),
        "rationale": data.get("rationale", ""),
        "confidence": data.get("confidence", "Medium"),
        "inputPrompt": data.get("input_prompt", ""),
        "rawOutput": data.get("raw_output", ""),
        "marketState": data.get("market_state", "Unknown"),
        "aggression": data.get("aggression", ""),
        "quantProbability": data.get("quant_probability", 0.0),
        "quantDirection": data.get("quant_direction", ""),
        "llmStatus": data.get("llm_status", "AVAILABLE"),
    }


