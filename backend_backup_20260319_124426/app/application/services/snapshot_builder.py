"""SnapshotBuilder — assembles frontend state snapshots from session state."""

from __future__ import annotations

from typing import TYPE_CHECKING

from app.domain.trading.models.enums import Source
from app.infrastructure.serialization.schemas import portfolio_to_dto, stats_to_dto
from app.application.utils import time_to_epoch, is_market_open
from app.config import settings

if TYPE_CHECKING:
    from app.application.services.trading_session import SessionState
    from app.domain.trading.services.risk_manager import RiskManager
    from app.application.handlers.trade_lifecycle_handler import TradeLifecycleHandler
    from app.application.handlers.rl_handler import RLHandler


class SnapshotBuilder:
    """Builds the JSON state snapshot sent to the frontend."""

    def build(
        self,
        session: SessionState,
        risk_manager: RiskManager,
        lifecycle_handler: TradeLifecycleHandler,
        rl_handler: RLHandler,
        gen_ai_service=None,
        probability_engine=None,
    ) -> dict:
        portfolio = session.portfolio
        weights = session.learning.weights

        with session._lock:
            ai_analysis = session.last_ai_analysis

        latest_tick = None
        data_array = None
        if session.data:
            last = session.data[-1]
            latest_tick = {
                "time": time_to_epoch(last.time), "open": last.open, "high": last.high,
                "low": last.low, "close": last.close, "volume": last.volume,
                "vwap": last.vwap, "delta": last.delta,
                "takerBuyVolume": last.taker_buy_volume,
            }
            tick_count = session.snapshot_count + 1
            session.snapshot_count = tick_count
            if tick_count <= 2:
                data_array = [
                    {"time": time_to_epoch(d.time), "open": d.open, "high": d.high,
                     "low": d.low, "close": d.close, "volume": d.volume,
                     "vwap": d.vwap, "delta": d.delta, "takerBuyVolume": d.taker_buy_volume}
                    for d in session.data
                ]

        return {
            "_symbol": session.symbol,
            "tick": latest_tick,
            "data": data_array,
            "portfolio": portfolio_to_dto(portfolio),
            "amt": session.last_amt,
            "prediction": session.last_prediction,
            "footprint": session.last_footprint,
            "genAIAnalysis": self._camel_case_ai(ai_analysis),
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
            "stats": {
                "amt": stats_to_dto(portfolio.get_stats(Source.AMT)),
                "prediction": stats_to_dto(portfolio.get_stats(Source.PREDICTION)),
                "rl": stats_to_dto(portfolio.get_stats(Source.RL)),
            },
            "playbookGuard": {
                "session": getattr(getattr(session, "_last_session_info", None), "session", ""),
                "marketState": (session.last_amt or {}).get("marketState", "") if isinstance(session.last_amt, dict) else "",
                "expectedPlaybook": "",
                "candidatePlaybook": getattr(getattr(session, "_agent_decision", None), "playbook", ""),
                "guardTripped": False,
                "maxRejections": settings.PLAYBOOK_GUARD_MAX_REJECTIONS,
                "totalRejections": sum(dict(getattr(session, "_playbook_guard_rejections", {})).values()),
                "sessionCompatible": True,
                "agentAligned": False,
                "lastRejectionReason": getattr(session, "_last_playbook_guard_reason", ""),
                "rejections": dict(getattr(session, "_playbook_guard_rejections", {})),
            },
            "explainabilityMonitor": {
                "entries": int(getattr(session, "_explainability_entries", 0)),
                "explainedEntries": int(getattr(session, "_explained_entries", 0)),
                "aggressionExplainedEntries": int(getattr(session, "_aggression_explained_entries", 0)),
                "coverageRate": round((getattr(session, "_explained_entries", 0) / getattr(session, "_explainability_entries", 1) * 100.0), 1) if getattr(session, "_explainability_entries", 0) else 0.0,
                "aggressionDriverRate": round((getattr(session, "_aggression_explained_entries", 0) / getattr(session, "_explainability_entries", 1) * 100.0), 1) if getattr(session, "_explainability_entries", 0) else 0.0,
                "minTrades": settings.EXPLAINABILITY_ALERT_MIN_TRADES,
                "minCoverageRate": settings.EXPLAINABILITY_MIN_DRIVER_COVERAGE_PCT,
                "minAggressionRate": settings.EXPLAINABILITY_MIN_AGGRESSION_DRIVER_PCT,
                "alertActive": bool(getattr(session, "_last_explainability_alert", "")) and getattr(session, "_explainability_entries", 0) >= settings.EXPLAINABILITY_ALERT_MIN_TRADES,
                "alertReason": getattr(session, "_last_explainability_alert", ""),
            },
            "rlStatus": rl_handler.get_status(),
            "riskState": {
                "halted": risk_manager.is_halted,
                "haltReason": risk_manager.halt_reason,
                "consecutiveLosses": risk_manager.daily_state.consecutive_losses,
                "dailyPnl": risk_manager.daily_state.realized_pnl,
            },
            "systemStatus": {
                "feedConnected": True,   # always True if we're here (gameloop sets this)
                "llmReady": gen_ai_service.is_ready() if gen_ai_service else False,
                "modelsLoaded": probability_engine.is_ready() if probability_engine else False,
                "marketOpen": is_market_open(exchange=settings.DEFAULT_EXCHANGE),
                "circuitBreakerTripped": risk_manager.is_halted if risk_manager else False,
                "haltReason": risk_manager.halt_reason if risk_manager else "",
                "tradingMode": settings.TRADING_MODE,
            },
        }

    @staticmethod
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
