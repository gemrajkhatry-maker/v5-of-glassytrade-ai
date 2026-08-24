"""Session Event Logger — Handles event logging.

Responsibilities:
- Position event logging
- Trade journal logging
- Explainability tracking
- Forward test logging
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING
from uuid import uuid4

from app.core.async_boundary import ensure_sync_adapter_result
from app.application.services.trade_journal import TradeJournal
from app.application.services.experiment_context import build_experiment_context
from quant.contracts.utils import safe_side as _safe_side

if TYPE_CHECKING:
    from quant.contracts.entities import Position, Signal
    from quant.contracts.ports.storage import IStorage

logger = logging.getLogger(__name__)


class SessionEventLogger:
    """Handles session event logging.
    
    This module encapsulates all event logging logic, providing a single
    source of truth for event logging across the codebase.
    """

    def __init__(self, storage: IStorage | None = None):
        self._storage = storage
        self._experiment = build_experiment_context()
        self._journal = TradeJournal(experiment=self._experiment)
        self._forward_logger = None
        
        try:
            from app.application.services.forward_test_logger import ForwardTestLogger
            self._forward_logger = ForwardTestLogger(experiment=self._experiment)
        except Exception:
            logger.debug("Forward test logger not available", exc_info=True)

    def log_position_event(
        self,
        *,
        position_id: str,
        symbol: str,
        event_type: str,
        event_time: str = "",
        **extra,
    ) -> None:
        """Persist append-only lifecycle events for audit.

        Args:
            position_id: Position identifier
            symbol: Trading symbol
            event_type: Event type (OPENED, CLOSED, PARTIAL_EXIT, etc.)
            event_time: Event timestamp
            **extra: Additional event data
        """
        if not self._storage or not hasattr(self._storage, "save_position_event"):
            return
        try:
            payload = {
                "event_id": extra.pop("event_id", str(uuid4())),
                "position_id": position_id,
                "symbol": symbol,
                "event_type": event_type,
                "event_time": event_time,
                "session_id": extra.pop("session_id", ""),
                "sequence": extra.pop("sequence", 0),
                "correlation_id": extra.pop("correlation_id", ""),
                "causation_id": extra.pop("causation_id", ""),
                "source": extra.pop("source", extra.pop("event_source", "")),
            }
            payload.update(extra)
            ensure_sync_adapter_result(
                "storage.save_position_event",
                self._storage.save_position_event,
                payload,
            )
        except Exception:
            logger.debug("Failed to persist position event %s for %s", event_type, position_id, exc_info=True)

    def log_entry(
        self,
        symbol: str,
        position: Position,
        signal: Signal,
        tick_trace_id: str = "",
        agent_decision=None,
        amt: dict | None = None,
        **extra,
    ) -> None:
        """Log a position entry.
        
        Args:
            symbol: Trading symbol
            position: Position object
            signal: Trade signal
            agent_decision: Agent decision (optional)
            amt: AMT analysis result (optional)
            **extra: Additional entry data
        """
        _meta = signal.metadata or {}
        _is_agent = _meta.get("agent_entry", False)
        _ad = agent_decision
        
        decision_source, attribution = self._decision_attribution(signal, _ad)
        
        self._journal.log_entry(
            symbol=symbol,
            position_id=position.id,
            tick_trace_id=tick_trace_id,
            side=_safe_side(position.side),
            entry_price=position.entry_price,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            amt=amt,
            agent_direction=_ad.direction if _ad else "",
            agent_regime=_ad.regime if _ad else "",
            agent_feature_drivers=getattr(_ad, "feature_drivers", ()) if _ad else (),
            probability_long=_meta.get("probability", 0.0) if _is_agent and signal.is_buy else (_ad.probability if _ad and _ad.direction == "LONG" else 0.0),
            probability_short=_meta.get("probability", 0.0) if _is_agent and not signal.is_buy else (_ad.probability if _ad and _ad.direction == "SHORT" else 0.0),
            llm_direction="" if _is_agent else ("BUY" if signal.is_buy else "SELL"),
            llm_rationale=signal.reason[:200] if signal.reason else "",
            decision_source=decision_source,
            attribution=attribution,
            trade_thesis=(signal.metadata or {}).get("trade_thesis"),
        )

    def log_exit(
        self,
        symbol: str,
        position: Position,
        tick_trace_id: str = "",
        time_in_trade: float = 0.0,
        mfe: float = 0.0,
        mae: float = 0.0,
        tick_count: int = 0,
        amt: dict | None = None,
        **extra,
    ) -> None:
        """Log a position exit.
        
        Args:
            symbol: Trading symbol
            position: Position object
            time_in_trade: Time in trade (seconds)
            mfe: Maximum favorable excursion
            mae: Maximum adverse excursion
            tick_count: Number of ticks in trade
            amt: AMT analysis result (optional)
            **extra: Additional exit data
        """
        self._journal.log_exit(
            symbol=symbol,
            position_id=position.id,
            tick_trace_id=tick_trace_id,
            side=_safe_side(position.side),
            entry_price=position.entry_price,
            exit_price=position.exit_price or position.entry_price,
            exit_reason=position.close_reason or "UNKNOWN",
            pnl=position.pnl,
            time_in_trade_s=time_in_trade,
            mfe=mfe,
            mae=mae,
            tick_count=tick_count,
            entry_timestamp=position.entry_time,
            amt=amt,
            decision_source="lifecycle",
            attribution="managed_exit",
        )

    def log_partial_exit(
        self,
        symbol: str,
        position_id: str,
        side: str,
        entry_price: float,
        exit_price: float,
        partial_pct: float,
        size_closed: float,
        size_remaining: float,
        realized_pnl: float,
        tick_trace_id: str = "",
        **extra,
    ) -> None:
        """Log a partial exit.
        
        Args:
            symbol: Trading symbol
            position_id: Position identifier
            side: Position side
            entry_price: Entry price
            exit_price: Exit price
            partial_pct: Partial exit percentage
            size_closed: Size closed
            size_remaining: Size remaining
            realized_pnl: Realized PnL
            **extra: Additional partial exit data
        """
        self._journal.log_partial_exit(
            symbol=symbol,
            position_id=position_id,
            tick_trace_id=tick_trace_id,
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            partial_pct=partial_pct,
            size_closed=size_closed,
            size_remaining=size_remaining,
            realized_pnl=realized_pnl,
            decision_source="lifecycle",
            attribution="managed_exit",
        )
        
        if self._forward_logger:
            self._forward_logger.log_partial_exit(
                symbol=symbol,
                position_id=position_id,
                partial_pct=partial_pct,
                size_closed=size_closed,
                size_remaining=size_remaining,
                exit_price=exit_price,
                realized_pnl=realized_pnl,
                exit_reason="PARTIAL_TAKE_PROFIT",
                attribution="managed_exit",
            )

    def log_break_even_triggered(
        self,
        *,
        symbol: str,
        position: Position,
        pnl: float,
        time_in_trade_s: float,
        tick_trace_id: str = "",
        reason: str = "",
        amt: dict | None = None,
    ) -> None:
        """Log a breakeven move event for a managed position."""
        self._journal.log_break_even_move(
            symbol=symbol,
            position_id=position.id,
            tick_trace_id=tick_trace_id,
            side=_safe_side(position.side),
            entry_price=float(position.entry_price),
            stop_loss=float(position.stop_loss),
            pnl=pnl,
            time_in_trade_s=time_in_trade_s,
            amt=amt,
            reason=reason,
        )

    def log_signal(
        self,
        symbol: str,
        amt: dict | None = None,
        llm_direction: str = "",
        llm_confidence: str = "",
        llm_rationale: str = "",
        agent_direction: str = "",
        agent_regime: str = "",
        agent_feature_drivers: tuple[str, ...] | list[str] | None = None,
        probability_long: float = 0.0,
        probability_short: float = 0.0,
        decision_source: str = "llm",
        attribution: str = "llm_only",
        **extra,
    ) -> None:
        """Log a trade signal.
        
        Args:
            symbol: Trading symbol
            amt: AMT analysis result (optional)
            llm_direction: LLM direction
            llm_confidence: LLM confidence
            llm_rationale: LLM rationale
            agent_direction: Agent direction
            agent_regime: Agent regime
            agent_feature_drivers: Agent feature drivers
            probability_long: Long probability
            probability_short: Short probability
            decision_source: Decision source
            attribution: Attribution
            **extra: Additional signal data
        """
        self._journal.log_signal(
            symbol=symbol,
            amt=amt,
            llm_direction=llm_direction,
            llm_confidence=llm_confidence,
            llm_rationale=llm_rationale,
            agent_direction=agent_direction,
            agent_regime=agent_regime,
            agent_feature_drivers=agent_feature_drivers,
            probability_long=probability_long,
            probability_short=probability_short,
            decision_source=decision_source,
            attribution=attribution,
        )

    def log_rejection(
        self,
        symbol: str,
        reason: str,
        amt: dict | None = None,
        llm_direction: str = "",
        **extra,
    ) -> None:
        """Log a trade rejection.
        
        Args:
            symbol: Trading symbol
            reason: Rejection reason
            amt: AMT analysis result (optional)
            llm_direction: LLM direction
            **extra: Additional rejection data
        """
        self._journal.log_rejection(
            symbol=symbol,
            reason=reason,
            amt=amt,
            llm_direction=llm_direction,
            **extra,
        )

    @staticmethod
    def _decision_attribution(signal, agent_decision) -> tuple[str, str]:
        """Classify the decision source for experiment reporting.
        
        Args:
            signal: Trade signal
            agent_decision: Agent decision
        
        Returns:
            Tuple of (decision_source, attribution)
        """
        meta = getattr(signal, "metadata", None) or {}
        if meta.get("agent_entry"):
            direction = "LONG" if getattr(signal, "is_buy", False) else "SHORT"
            if agent_decision and getattr(agent_decision, "direction", "") == direction:
                return "quant", "quant_only"
            return "quant", "quant_only"
        if agent_decision and getattr(agent_decision, "direction", "FLAT") != "FLAT":
            signal_direction = "LONG" if getattr(signal, "is_buy", False) else "SHORT"
            if agent_decision.direction == signal_direction:
                return "llm", "llm_plus_quant_agree"
            return "llm", "llm_override_quant"
        return "llm", "llm_only"