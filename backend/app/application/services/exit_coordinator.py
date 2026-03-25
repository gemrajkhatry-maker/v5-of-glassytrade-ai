"""Exit Coordinator — handles exit callbacks and position lifecycle events.

Extracted from TradingSessionService to separate exit concerns:
- Partial exit handling (broker SL cancellation, logging)
- Stop out handling (session phase tracking)
- Position closed handling (learning, risk recording, persistence)

This class is injected into TradingSessionService and called via callbacks.
"""

from __future__ import annotations

import logging
from typing import TYPE_CHECKING

from app.domain.ports.storage import StoragePort
from app.domain.ports.broker import BrokerPort
from app.domain.trading.events import PositionClosed
from app.application.handlers.post_trade_analyst import PostTradeAnalyst

if TYPE_CHECKING:
    from app.application.handlers.llm_entry_handler import LLMEntryHandler
    from app.application.handlers.llm_overseer_handler import LLMOverseerHandler
    from app.application.handlers.trade_lifecycle_handler import TradeLifecycleHandler
    from app.application.services.session_state_manager import SessionStateManager
    from app.application.services.session_event_logger import SessionEventLogger
    from app.application.services.session_risk_coordinator import SessionRiskCoordinator

log = logging.getLogger(__name__)


class ExitCoordinator:
    """Handles exit callbacks and position lifecycle events.

    Single responsibility: manage what happens when positions are
    partially closed, stopped out, or fully closed.
    """

    def __init__(
        self,
        broker: BrokerPort,
        lifecycle_handler: TradeLifecycleHandler,
        event_logger: SessionEventLogger,
        overseer_handler: LLMOverseerHandler,
        state_manager: SessionStateManager,
        storage: StoragePort | None,
        llm_handler: LLMEntryHandler,
        risk_coordinator: SessionRiskCoordinator,
        post_trade_analyst: PostTradeAnalyst | None = None,
    ) -> None:
        self._broker = broker
        self._lifecycle_handler = lifecycle_handler
        self._event_logger = event_logger
        self._overseer_handler = overseer_handler
        self._state_manager = state_manager
        self._storage = storage
        self._llm_handler = llm_handler
        self._risk_coordinator = risk_coordinator
        self._post_trade_analyst = post_trade_analyst

    def on_partial_exit(
        self,
        pos_id: str,
        side: str,
        entry_price: float,
        exit_price: float,
        partial_pct: float,
        size_closed: float,
        size_remaining: float,
        realized_pnl: float,
    ) -> None:
        """Handle partial exit — cancel broker SL and log."""
        symbol = ""
        position = None
        for sym, sess in self._state_manager.get_all_sessions().items():
            for p in sess.portfolio.positions:
                if p.id == pos_id:
                    symbol = sym
                    position = p
                    break
            if symbol:
                break

        if position:
            dhan_sl_id = (position.metadata or {}).get("dhan_sl_order_id")
            if dhan_sl_id:
                try:
                    self._broker.cancel_order(dhan_sl_id)
                    position.metadata.pop("dhan_sl_order_id", None)
                    log.info(
                        "Scrubbed broker hardware SL %s for partially closed pos %s",
                        dhan_sl_id,
                        pos_id,
                    )
                except Exception as e:
                    log.error(
                        "Failed to scrub broker hardware SL %s: %s", dhan_sl_id, e
                    )

        self._event_logger.log_partial_exit(
            symbol=symbol,
            position_id=pos_id,
            side=side,
            entry_price=entry_price,
            exit_price=exit_price,
            partial_pct=partial_pct,
            size_closed=size_closed,
            size_remaining=size_remaining,
            realized_pnl=realized_pnl,
        )
        log.info(
            "Journal: PARTIAL_EXIT pos=%s side=%s %d→%d @ %.2f pnl=%.2f",
            pos_id,
            side,
            size_closed,
            size_remaining,
            exit_price,
            realized_pnl,
        )

    def on_stop_out(self, level: float, direction: str, exchange: str) -> None:
        """Handle stop out — record session phase for pattern learning."""
        from app.domain.fabio_ai.services.session_context import (
            get_session_info as _get_si,
        )
        from datetime import datetime, timezone, timedelta

        ist = timezone(timedelta(hours=5, minutes=30))
        now_ist = datetime.now(ist).strftime("%H:%M:%S")
        _market = exchange
        if _market in ("NFO", "BSE"):
            _market = "NSE"
        si = _get_si(timestamp=now_ist, market=_market)
        self._llm_handler.record_stop_out(level, direction, si.phase)

    def on_position_closed(self, symbol: str, position) -> None:
        """Handle full position close — learning, risk, persistence.

        Called directly from trading_session with the Position object
        (avoids PositionClosed event serialization issues).
        """
        if not position:
            return
        pos = position

        # Cancel broker hardware SL
        dhan_sl_id = (pos.metadata or {}).get("dhan_sl_order_id")
        if dhan_sl_id:
            try:
                self._broker.cancel_order(dhan_sl_id)
                log.info(
                    "Scrubbed broker hardware SL %s for fully closed pos %s",
                    dhan_sl_id,
                    pos.id,
                )
            except Exception as e:
                log.error("Failed to scrub broker hardware SL %s: %s", dhan_sl_id, e)

        session = self._state_manager.get_or_create_session(symbol)

        # Record consistency
        try:
            from app.application.handlers.position_consistency import (
                record_position_consistency,
            )

            record_position_consistency(
                session.portfolio,
                self._lifecycle_handler.trade_manager,
                symbol,
                context="post_close",
            )
        except Exception:
            log.debug("Position consistency check failed", exc_info=True)

        # Learning
        session.learning.learn(pos)
        self._overseer_handler.reset_position_state()

        # Metrics from TradeManager
        mp_metrics = self._lifecycle_handler.trade_manager.get_position_metrics(pos.id)
        time_in_trade = 0.0
        if pos.exit_time and pos.entry_time:
            try:
                from datetime import datetime as _dt

                _exit = _dt.fromisoformat(pos.exit_time.replace("Z", "+00:00"))
                _entry = _dt.fromisoformat(pos.entry_time.replace("Z", "+00:00"))
                time_in_trade = (_exit - _entry).total_seconds()
            except Exception:
                time_in_trade = (
                    float(mp_metrics["tick_count"]) * 0.5 if mp_metrics else 0.0
                )

        # Log exit
        self._event_logger.log_exit(
            symbol=symbol,
            position=pos,
            time_in_trade=time_in_trade,
            mfe=float(mp_metrics["mfe"]) if mp_metrics else 0,
            mae=float(mp_metrics["mae"]) if mp_metrics else 0,
            tick_count=int(mp_metrics["tick_count"]) if mp_metrics else 0,
            amt=session.last_amt,
        )

        # Post-trade LLM analysis (non-blocking)
        if self._post_trade_analyst:
            try:
                self._post_trade_analyst.analyze(
                    symbol=symbol,
                    entry_price=float(pos.entry_price),
                    exit_price=float(pos.exit_price) if pos.exit_price else 0,
                    side=pos.side,
                    pnl=float(pos.pnl) if pos.pnl else 0,
                    hold_time_seconds=time_in_trade,
                    close_reason=getattr(pos, "close_reason", "UNKNOWN"),
                )
            except Exception:
                log.debug("Post-trade analysis fire failed", exc_info=True)

        # Record successful exit
        if pos.pnl and pos.pnl > 0:
            self._llm_handler.record_successful_exit(symbol=symbol)

        # Session risk
        srm = self._risk_coordinator.get_session_risk_manager(symbol)
        srm.record_trade(pos.pnl)

        log.info(
            "SessionRisk: tier=%s sl_pct=%.4f pnl=%.2f wins=%d losses=%d",
            srm.risk_tier.value,
            srm.stop_loss_pct,
            srm.session_pnl,
            srm.consecutive_wins,
            srm.consecutive_losses,
        )

        self._risk_coordinator.persist_risk_state(symbol)

        # Persist
        if self._storage:
            try:
                self._storage.delete_open_position(event.position.id)
            except Exception:
                log.debug("Failed to delete persisted position", exc_info=True)
