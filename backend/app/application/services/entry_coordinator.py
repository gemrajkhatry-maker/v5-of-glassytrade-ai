"""Entry Coordinator — handles signal execution and position opening.

Extracted from TradingSessionService to separate entry concerns:
- Signal validation (thesis, risk, duplicate check)
- Option selection enrichment
- Broker execution
- Initialize partition state for exit management
- PositionOpened event publishing
- Persistence

This class is injected into TradingSessionService and called from _on_tick
when the gate pipeline passes.
"""

from __future__ import annotations

import logging
import time
from typing import TYPE_CHECKING

from app.domain.ports.storage import IStorage
from app.domain.ports.broker import IBroker
from app.domain.constants import MIN_GRADE_SCORE_THRESHOLD
from app.domain.services.risk_sizing_engine import RiskSizingEngine, SizingResult

if TYPE_CHECKING:
    from app.application.handlers.trade_lifecycle_handler import TradeLifecycleHandler
    from app.application.services.session_state_manager import SessionStateManager
    from app.application.services.session_event_logger import SessionEventLogger
    from app.application.services.session_state_manager import SessionState
    from app.domain.trading.models.entities import Signal

log = logging.getLogger(__name__)

class EntryCoordinator:
    """Handles signal execution and position opening.

    Single responsibility: take a validated signal and execute it through
    the broker, register with TradeManager, and persist.
    """

    def __init__(
        self,
        broker: IBroker,
        lifecycle_handler: TradeLifecycleHandler,
        event_logger: SessionEventLogger,
        storage: IStorage | None,
        risk_coordinator,
        option_selector,
        state_manager: SessionStateManager,
        sizing_engine: RiskSizingEngine | None = None,
    ) -> None:
        self._broker = broker
        self._lifecycle_handler = lifecycle_handler
        self._event_logger = event_logger
        self._storage = storage
        self._risk_coordinator = risk_coordinator
        self._option_selector = option_selector
        self._state_manager = state_manager
        self._sizing_engine = sizing_engine or RiskSizingEngine()

    def execute_signal(self, symbol: str, sig: Signal, session: SessionState) -> None:
        """Execute a trade signal — MUST run on main thread or under lock.

        Steps:
        1. Validate trade thesis
        2. Check duplicate signal ID
        3. Validate risk (via RiskCoordinator)
        4. Enrich with option selection
        5. Execute via broker
        6. Register with TradeManager
        7. Publish PositionOpened event
        8. Persist to storage
        """
        from app.domain.fabio_ai.services.trade_thesis import validate_trade_thesis

        # Guard: confluence grade score must meet minimum threshold.
        # Each signal that has traversed an AMT analysis carries a grade_score
        # (0–6) in metadata.  Signals below the floor are blocked even if they
        # passed the earlier boolean gates.
        meta = getattr(sig, "metadata", None) or {}
        grade_score = meta.get("grade_score")
        if grade_score is not None and grade_score < MIN_GRADE_SCORE_THRESHOLD:
            log.warning(
                "Signal rejected by gate confluence floor: grade_score=%d (threshold=%d)",
                grade_score,
                MIN_GRADE_SCORE_THRESHOLD,
            )
            _ad = getattr(session, "_agent_decision", None)
            decision_source, attribution = self._event_logger._decision_attribution(
                sig, _ad
            )
            self._event_logger.log_rejection(
                symbol=symbol,
                reason=f"CONFLUENCE_GRADE_{grade_score}",
                amt=session.last_amt,
                llm_direction="BUY" if sig.is_buy else "SELL",
                agent_direction=_ad.direction if _ad else "",
                agent_regime=_ad.regime if _ad else "",
                agent_feature_drivers=getattr(_ad, "feature_drivers", ())
                if _ad
                else (),
                decision_source=decision_source,
                attribution=attribution,
                trade_thesis=meta.get("trade_thesis"),
            )
            return

        thesis = meta.get("trade_thesis")
        thesis_valid, thesis_reason = validate_trade_thesis(thesis)
        if not thesis_valid:
            log.info("Signal rejected by trade thesis gate: %s", thesis_reason)
            _ad = getattr(session, "_agent_decision", None)
            decision_source, attribution = self._event_logger._decision_attribution(
                sig, _ad
            )
            self._event_logger.log_rejection(
                symbol=symbol,
                reason=f"THESIS_{thesis_reason.upper()}",
                amt=session.last_amt,
                llm_direction="BUY" if sig.is_buy else "SELL",
                agent_direction=_ad.direction if _ad else "",
                agent_regime=_ad.regime if _ad else "",
                agent_feature_drivers=getattr(_ad, "feature_drivers", ())
                if _ad
                else (),
                decision_source=decision_source,
                attribution=attribution,
                trade_thesis=thesis,
            )
            return

        sig_id = getattr(sig, "signal_id", None)
        if sig_id:
            with session._lock:
                if getattr(session, "_last_executed_signal_id", None) == sig_id:
                    log.debug("Duplicate signal_id %s — skipping", sig_id)
                    return
                session._last_executed_signal_id = sig_id

        log.info(
            "Signal received: %s @ %.2f (SL=%.2f, TP=%.2f, source=%s, id=%s)",
            sig.type,
            sig.price,
            sig.stop_loss,
            sig.take_profit,
            sig.source,
            sig_id,
        )

        with session._lock:
            if not self._risk_coordinator.validate_entry(
                symbol, sig, session.portfolio
            ):
                log.info("Signal rejected by risk manager")
                _ad = getattr(session, "_agent_decision", None)
                self._event_logger.log_rejection(
                    symbol=symbol,
                    reason="risk_manager",
                    amt=session.last_amt,
                    llm_direction="BUY" if sig.is_buy else "SELL",
                    agent_direction=_ad.direction if _ad else "",
                    agent_regime=_ad.regime if _ad else "",
                    agent_feature_drivers=getattr(_ad, "feature_drivers", ())
                    if _ad
                    else (),
                    decision_source="quant"
                    if (getattr(sig, "metadata", None) or {}).get("agent_entry")
                    else "llm",
                    attribution=self._event_logger._decision_attribution(sig, _ad)[1],
                    trade_thesis=(getattr(sig, "metadata", None) or {}).get(
                        "trade_thesis"
                    ),
                )
                return

        # Enrich signal with option selection
        try:
            _clean = symbol.replace("NSE:", "").replace("MCX:", "").strip()
            underlying = _clean.split("-")[0].split(" ")[0]
            direction = "LONG" if sig.is_buy else "SHORT"

            # ALWAYS use underlying futures price — never option premium
            _underlying_price = getattr(sig, "price", 0)
            if hasattr(session, "_underlying_data") and session._underlying_data:
                _underlying_candle = session._underlying_data[-1]
                _underlying_price = float(getattr(_underlying_candle, "close", 0))

            selected_strike = self._option_selector.select_strike(
                spot_price=_underlying_price,
                direction=direction,
                underlying=underlying,
            )
            if sig.metadata is None:
                sig.metadata = {}
            sig.metadata["option_strike"] = selected_strike
            _sym_upper = symbol.upper()
            if "CALL" in _sym_upper or "CE" in _sym_upper:
                sig.metadata["option_type"] = "CE"
            elif "PUT" in _sym_upper or "PE" in _sym_upper:
                sig.metadata["option_type"] = "PE"
            else:
                sig.metadata["option_type"] = "CE"
            sig.metadata["option_underlying"] = underlying
            sig.metadata["option_lot_size"] = self._option_selector._lot_size_for(
                underlying
            )
            log.info(
                "Option selection: %s %s %d",
                underlying,
                sig.metadata["option_type"],
                selected_strike,
            )
        except Exception:
            log.warning("Option selection failed — falling back to default strike", exc_info=True)

        # Execute order (network I/O — outside lock to avoid blocking all readers)
        position = self._broker.execute_order(sig, session.portfolio, symbol)

        if position:
            # Mark entry time under lock (fast operation)
            with session._lock:
                session._last_entry_time = time.time()

        if position:
            if (sig.metadata or {}).get("agent_entry"):
                self._state_manager._record_explainability_entry(
                    session,
                    getattr(
                        getattr(session, "_agent_decision", None), "feature_drivers", ()
                    ),
                )
            # Initialize partition exit state for P1/P2/P3 management
            # Position already has lifecycle fields set by Position.from_signal()
            self._lifecycle_handler.initialize_partition_state(position.id, symbol)
            # Track scale step for 40/30/30 execution plan
            position.scale_step = 1  # First entry of scale-in plan
            # Track entry LVN for pyramid adds (FR-09)
            if sig.metadata and "entry_lvn" in sig.metadata:
                position.entry_lvns = [sig.metadata["entry_lvn"]]
            self._event_logger.log_position_event(
                position_id=position.id,
                symbol=symbol,
                event_type="OPENED",
                event_time=position.entry_time,
                side=position.side.value
                if hasattr(position.side, "value")
                else str(position.side),
                entry_price=position.entry_price,
                stop_loss=position.stop_loss,
                take_profit=position.take_profit,
                source=position.source.value
                if hasattr(position.source, "value")
                else str(position.source),
            )
            _meta = sig.metadata or {}
            _ad = getattr(session, "_agent_decision", None)
            decision_source, attribution = self._event_logger._decision_attribution(
                sig, _ad
            )
            self._event_logger.log_entry(
                symbol=symbol,
                position=position,
                signal=sig,
                agent_decision=_ad,
                amt=session.last_amt,
            )
            if self._storage:
                try:
                    self._storage.save_open_position(
                        {
                            "id": position.id,
                            "symbol": symbol,
                            "side": position.side.value
                            if hasattr(position.side, "value")
                            else str(position.side),
                            "entry_price": position.entry_price,
                            "size": position.size,
                            "stop_loss": position.stop_loss,
                            "take_profit": position.take_profit,
                            "source": position.source.value
                            if hasattr(position.source, "value")
                            else str(position.source),
                            "opened_at": position.entry_time,
                        }
                    )
                except Exception:
                    log.warning("Failed to persist open position — position may be lost on restart", exc_info=True)
