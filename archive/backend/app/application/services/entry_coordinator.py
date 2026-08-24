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
from decimal import Decimal
from typing import TYPE_CHECKING

from app.core.async_boundary import ensure_sync_adapter_result
from app.domain.ops.self_healing import get_shared_fallback_buffer
from quant.contracts.ports.storage import IStorage
from quant.contracts.ports.broker import IBroker
from quant.contracts.constants import MIN_GRADE_SCORE_THRESHOLD
from quant.execution.risk_sizing import RiskSizingEngine, SizingResult

if TYPE_CHECKING:
    from app.application.handlers.trade_lifecycle_handler import TradeLifecycleHandler
    from app.application.services.session_state_manager import SessionStateManager
    from app.application.services.session_event_logger import SessionEventLogger
    from app.application.services.session_state_manager import SessionState
    from quant.contracts.entities import Signal

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
        db_fallback=None,
    ) -> None:
        self._broker = broker
        self._lifecycle_handler = lifecycle_handler
        self._event_logger = event_logger
        self._storage = storage
        self._risk_coordinator = risk_coordinator
        self._option_selector = option_selector
        self._state_manager = state_manager
        self._sizing_engine = sizing_engine or RiskSizingEngine()
        # Always own a fallback queue, including direct/unit construction. The
        # application injects the session-owned queue so shutdown can flush all
        # writes through one lifecycle owner.
        self._db_fallback = db_fallback or get_shared_fallback_buffer(storage)

    def flush_persistence(self) -> int:
        """Flush this coordinator's fallback queue for direct callers.

        TradingSessionService normally owns and injects the shared queue. This
        method preserves a safe lifecycle boundary for standalone construction.
        """
        if self._storage is None or not self._db_fallback.buffer_size:
            return 0
        return self._db_fallback.try_flush(self._storage)

    @staticmethod
    def _init_scale_prices(position, sig) -> None:
        """Initialize 40/30/30 scale-in trigger prices on a fresh position.

        The ScaleManager advances steps only when the confirm/breakout prices
        are non-zero.  Defaults: step 2 confirms at 50% of the reward distance,
        step 3 breaks out at 80% of the reward distance (both inside the TP so
        the adds can actually trigger before take-profit closes the position).
        """
        try:
            entry = float(position.entry_price)
            sl = float(position.stop_loss)
            tp = float(position.take_profit)
            is_buy = bool(getattr(sig, "is_buy", True))
            # Reward must be in the direction of the trade for a valid scale plan.
            reward = (tp - entry) if is_buy else (entry - tp)
            if sl <= 0 or reward <= 0:
                return
            confirm = entry + reward * 0.5 if is_buy else entry - reward * 0.5
            breakout = entry + reward * 0.8 if is_buy else entry - reward * 0.8
            position.scale_confirm_price = Decimal(str(confirm))
            position.scale_breakout_price = Decimal(str(breakout))
            log.info(
                "Scale-in initialized for %s: confirm=%.2f breakout=%.2f",
                position.id, confirm, breakout,
            )
        except Exception:
            log.debug("Scale-in price initialization failed (non-critical)", exc_info=True)

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
        from quant.decision.trade_thesis import validate_trade_thesis

        # Guard: confluence grade score must meet minimum threshold.
        # Each signal that has traversed an AMT analysis carries a grade_score
        # (0–6) in metadata.  Signals below the floor are blocked even if they
        # passed the earlier boolean gates.
        _raw_meta = getattr(sig, "metadata", None) or {}
        meta = _raw_meta if isinstance(_raw_meta, dict) else {}
        _tick_trace_id = str(meta.get("tick_trace_id", ""))
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
                tick_trace_id=_tick_trace_id,
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
                tick_trace_id=_tick_trace_id,
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

        # Persistence must remain durable while opening new positions. If
        # both SQLite and the local spool failed, keep managing existing
        # positions but fail closed for new entries.
        if getattr(self._db_fallback, "durability_degraded", False) is True:
            log.critical(
                "Entry blocked for %s: persistence durability is degraded (%s)",
                symbol,
                self._db_fallback.durability_status.get("last_error", "unknown"),
            )
            return

        with session._lock:
            if not self._risk_coordinator.validate_entry(
                symbol, sig, session.portfolio
            ):
                log.info("Signal rejected by risk manager")
                _ad = getattr(session, "_agent_decision", None)
                self._event_logger.log_rejection(
                    symbol=symbol,
                    reason="risk_manager",
                    tick_trace_id=_tick_trace_id,
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
        position = ensure_sync_adapter_result(
            "broker.execute_order",
            self._broker.execute_order,
            sig,
            session.portfolio,
            symbol,
        )

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
            # Initialize 40/30/30 scale-in trigger prices so check_scale_in can
            # fire.  Step 2 (confirm) = 50% of the way to target, step 3
            # (breakout) = 80%.  Without these, the ScaleManager's triggers
            # stay 0 and the plan never advances past the 40% initial leg.
            self._init_scale_prices(position, sig)
            # Track entry LVN for pyramid adds (FR-09)
            if sig.metadata and "entry_lvn" in sig.metadata:
                position.entry_lvns = [sig.metadata["entry_lvn"]]
            _meta = sig.metadata or {}
            self._event_logger.log_position_event(
                position_id=position.id,
                symbol=symbol,
                event_type="OPENED",
                tick_trace_id=_tick_trace_id,
                event_time=position.entry_time,
                side=position.side.value
                if hasattr(position.side, "value")
                else str(position.side),
                entry_price=position.entry_price,
                stop_loss=position.stop_loss,
                take_profit=position.take_profit,
                session_id=_meta.get("session_id", ""),
                sequence=_meta.get("sequence", 0),
                correlation_id=_meta.get("correlation_id", ""),
                causation_id=_meta.get("causation_id", ""),
                source=_meta.get("source", ""),
            )
            _ad = getattr(session, "_agent_decision", None)
            decision_source, attribution = self._event_logger._decision_attribution(
                sig, _ad
            )
            self._event_logger.log_entry(
                symbol=symbol,
                position=position,
                signal=sig,
                tick_trace_id=_tick_trace_id,
                agent_decision=_ad,
                amt=session.last_amt,
            )
        if position and self._storage:
            try:
                ensure_sync_adapter_result(
                    "storage.save_open_position",
                    self._storage.save_open_position,
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
                        "tick_trace_id": _tick_trace_id,
                    },
                )
            except Exception:
                # The position is already live in the in-memory portfolio. Do
                # not roll back broker state on a database outage; queue the
                # exact payload for the session's retry/flush owner.
                if self._db_fallback is not None:
                    self._db_fallback.buffer_write(
                        "save_open_position",
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
                            "tick_trace_id": _tick_trace_id,
                        },
                    )
                log.warning("Failed to persist open position — position may be lost on restart", exc_info=True)
