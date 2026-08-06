"""State Snapshot Builder — DTO formatting for UI state snapshots.

Extracted from trading_session.py. Pure DTO formatting with no side effects.
Builds the state dict that the React dashboard consumes.
"""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.infrastructure.serialization.schemas import portfolio_to_dto

if TYPE_CHECKING:
    from app.domain.fabio_ai.services.exit_engine import ExitEngine as TradeManager
    from app.application.handlers.trade_lifecycle_handler import TradeLifecycleHandler


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
    with session._lock:
        ai_analysis = session.last_ai_analysis
        portfolio_dto = portfolio_to_dto(session.portfolio)

    rm = risk_coordinator._get_risk_manager(session.symbol)

    return {
        "_symbol": session.symbol,
        "portfolio": portfolio_dto,
        "amt": session.last_amt,
        "footprint": session.last_footprint,
        "genAIAnalysis": _camel_case_ai(ai_analysis),
        "overseerAction": (ai_analysis or {}).get("overseer_action", ""),
        "overseerReason": (ai_analysis or {}).get("overseer_reason", ""),
        "agentDecision": _agent_decision_dto(session),
        "riskState": {
            "halted": rm.is_halted,
            "haltReason": rm.halt_reason,
            "consecutiveLosses": rm.daily_state.consecutive_losses,
            "dailyPnl": rm.daily_state.realized_pnl,
            "driftAlert": rm._drift_alert,
            "driftMessage": rm._drift_message,
        },
    }


def _agent_decision_dto(session) -> dict | None:
    ad = getattr(session, "_agent_decision", None)
    if ad is None:
        return None
    return {
        "direction": ad.direction,
        "probability": round(ad.probability, 3),
        "regime": ad.regime,
        "timing": ad.timing,
        "sizeFraction": round(ad.size_fraction, 3),
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
    }


