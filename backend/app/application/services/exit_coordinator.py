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

from app.domain.ports.storage import IStorage
from app.domain.ports.broker import IBroker
from app.domain.trading.events import PositionClosed
from app.application.handlers.post_trade_analyst import PostTradeAnalyst
from app.core.async_boundary import ensure_sync_adapter_result
from app.shared.timezones import IST
from datetime import datetime


if TYPE_CHECKING:
    from app.application.handlers.llm_entry_handler import LLMEntryHandler
    from app.application.handlers.llm_overseer_handler import LLMOverseerHandler
    from app.application.handlers.trade_lifecycle_handler import TradeLifecycleHandler
    from app.application.services.session_state_manager import SessionStateManager
    from app.application.services.session_event_logger import SessionEventLogger
    from app.application.services.session_risk_coordinator import SessionRiskCoordinator

log = logging.getLogger(__name__)


# Stable int code per session phase for the RegimeDetector's int comparison.
# Deterministic across processes (unlike builtin hash()) so stop-out learning
# data is consistent between runs.
_SESSION_PHASE_CODES: dict[str, int] = {
    "PRE_OPEN": 0,
    "OPEN": 1,
    "MORNING": 2,
    "MIDDAY": 3,
    "AFTERNOON": 4,
    "LONDON": 5,
    "NY": 6,
    "POWER_HOUR": 7,
    "CLOSED": 8,
}


def _session_phase_num(phase: object) -> int:
    """Deterministic session-phase code: known phases map to fixed ints."""
    name = str(phase or "").strip().upper()
    if name in _SESSION_PHASE_CODES:
        return _SESSION_PHASE_CODES[name]
    # Deterministic fallback for unknown phase labels (no salted hash).
    return sum(ord(c) for c in name) % 10 if name else 0


class ExitCoordinator:
    """Handles exit callbacks and position lifecycle events.

    Single responsibility: manage what happens when positions are
    partially closed, stopped out, or fully closed.
    """

    def __init__(
        self,
        broker: IBroker,
        lifecycle_handler: TradeLifecycleHandler,
        event_logger: SessionEventLogger,
        overseer_handler: LLMOverseerHandler,
        state_manager: SessionStateManager,
        storage: IStorage | None,
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

    @staticmethod
    def _metadata_dict(metadata: object) -> dict:
        """Normalize metadata to a dict to avoid RuntimeError in heterogeneous callers."""
        return metadata if isinstance(metadata, dict) else {}

    def _resolve_position(
        self,
        symbol: str,
        position_or_id,
        session=None,
    ) -> tuple[object | None, str]:
        """Resolve a Position either directly or by id from tracked sessions."""
        if position_or_id is None:
            return None, symbol

        if hasattr(position_or_id, "id"):
            return position_or_id, symbol or str(getattr(position_or_id, "symbol", ""))

        if isinstance(position_or_id, str) and position_or_id:
            target_id = position_or_id
            sessions = []
            if session is not None:
                sessions = [session]
            else:
                sessions = list(self._state_manager.get_all_sessions().values())

            for sess in sessions:
                with sess._lock:
                    positions_snapshot = list(sess.portfolio.positions)
                for candidate in positions_snapshot:
                    if str(getattr(candidate, "id", "")) == target_id:
                        resolved_symbol = symbol or str(getattr(candidate, "symbol", ""))
                        return candidate, resolved_symbol

        return None, symbol

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
        position, symbol = self._resolve_position("", pos_id)

        if not position:
            log.warning("Partial exit received for missing position id=%s", pos_id)
            return

        if position:
            _metadata = self._metadata_dict(position.metadata)
            dhan_sl_id = _metadata.get("dhan_sl_order_id")
            if dhan_sl_id:
                try:
                    ensure_sync_adapter_result(
                        "broker.cancel_order",
                        self._broker.cancel_order,
                        dhan_sl_id,
                    )
                    if isinstance(position.metadata, dict):
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
            tick_trace_id=self._metadata_dict(position.metadata).get("tick_trace_id", ""),
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

    def on_stop_out(self, level: float, direction: str, symbol: str, exchange: str) -> None:
        """Handle stop out — record session phase for pattern learning."""
        from app.domain.fabio_ai.services.session_context import (
            get_session_info as _get_si,
        )

        now_ist = datetime.now(IST).strftime("%H:%M:%S")
        _market = exchange
        if _market in ("NFO", "BSE"):
            _market = "NSE"
        si = _get_si(timestamp=now_ist, market=_market)
        # si.phase is a session-phase identifier (e.g. "LONDON", "NY");
        # map it to a stable int so the RegimeDetector's int-comparison works.
        # NOTE: must be deterministic — builtin hash() is salted per-process
        # (PYTHONHASHSEED), which would make learning IDs differ across restarts.
        phase_num = _session_phase_num(si.phase)
        self._llm_handler.record_stop_out(level, direction, phase_num, symbol=symbol)

    def on_position_closed(self, symbol: str, position, session=None) -> None:
        """Handle full position close — learning, risk, persistence.

        Called directly from trading_session with the Position object
        (avoids PositionClosed event serialization issues).
        """
        if not symbol and not position:
            return
        pos, resolved_symbol = self._resolve_position(symbol, position, session=session)
        if not pos:
            log.warning("Full close received for missing position: %s", position)
            return
        if resolved_symbol:
            symbol = resolved_symbol

        # Cancel broker hardware SL
        _metadata = self._metadata_dict(pos.metadata)
        dhan_sl_id = _metadata.get("dhan_sl_order_id")
        if dhan_sl_id:
            try:
                ensure_sync_adapter_result(
                    "broker.cancel_order",
                    self._broker.cancel_order,
                    dhan_sl_id,
                )
                log.info(
                    "Scrubbed broker hardware SL %s for fully closed pos %s",
                    dhan_sl_id,
                    pos.id,
                )
            except Exception as e:
                log.error("Failed to scrub broker hardware SL %s: %s", dhan_sl_id, e)

        state_session = session or self._state_manager.get_or_create_session(symbol)

        # Learning
        state_session.learning.learn(pos)
        self._overseer_handler.reset_position_state()

        # Metrics from Position entity (ExitEngine is stateless)
        mp_metrics = self._lifecycle_handler.exit_engine.get_position_metrics(pos)
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
            tick_trace_id=self._metadata_dict(pos.metadata).get("tick_trace_id", ""),
            time_in_trade=time_in_trade,
            mfe=float(mp_metrics["mfe"]) if mp_metrics else 0,
            mae=float(mp_metrics["mae"]) if mp_metrics else 0,
            tick_count=int(mp_metrics["tick_count"]) if mp_metrics else 0,
            amt=state_session.last_amt,
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
                ensure_sync_adapter_result(
                    "storage.delete_open_position",
                    self._storage.delete_open_position,
                    pos.id,
                )
            except Exception:
                log.warning("Failed to delete persisted position — stale position may appear on restart", exc_info=True)
