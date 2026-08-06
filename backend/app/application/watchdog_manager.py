"""Watchdog Manager — Handles SL/TP watchdog and stream health monitoring.

Responsibilities:
- Independent SL/TP watchdog (runs even when stream is disconnected)
- Stale stream detection and reconnection
- Polling fallback management
- Position consistency checking
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

from app.core.async_boundary import ensure_sync_adapter_result
from app.config import settings
from app.application.utils import is_market_open
from quant.contracts.utils import safe_side as _safe_side
from app.domain.ops.position_reconciliation import PositionReconciliationEngine, ReconciliationIssue
from quant.contracts.timezones import IST
from app.shared.mode import is_live_mode

logger = logging.getLogger(__name__)



_GC_INTERVAL_SECS = 1800
_STALE_THRESHOLD_SECS = 60.0
_STALE_RECONNECT_SECS = 300.0  # 5 min — MCX options can be quiet for minutes between ticks


class WatchdogManager:
    """Manages SL/TP watchdog and stream health monitoring.
    
    This module encapsulates all watchdog logic, providing a single
    source of truth for position protection and stream monitoring.
    """

    def __init__(
        self,
        session_service,
        stream_manager: "StreamManager",
        state_broadcaster: "StateBroadcaster" | None = None,
    ):
        self._session_service = session_service
        self._stream_manager = stream_manager
        self._state_broadcaster = state_broadcaster
        self._running = False
        self._active_symbols: list[str] = []
        self._reconciliation_engine = PositionReconciliationEngine()

    def set_active_symbols(self, symbols: list[str]) -> None:
        """Set active symbols for watchdog monitoring.
        
        Args:
            symbols: List of symbols to monitor
        """
        self._active_symbols = symbols

    def set_running(self, running: bool) -> None:
        """Set running state.
        
        Args:
            running: Whether watchdogs are running
        """
        self._running = running

    async def sl_watchdog_loop(self) -> None:
        """Independent SL/TP watchdog running every 1 second.

        Protects positions even when the tick stream is disconnected
        (e.g., during WebSocket reconnect, network jitter, or exchange gaps).
        Uses the last known LTP cached in stream_manager to evaluate SL/TP boundaries.
        """
        logger.info("Watchdog: SL watchdog started")
        while self._running:
            try:
                await asyncio.sleep(1.0)
                for sym in list(self._active_symbols):
                    self._sl_check_symbol(sym)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.error("SL watchdog error", exc_info=True)
        logger.info("Watchdog: SL watchdog stopped")

    def _sl_check_symbol(self, symbol: str) -> None:
        """Check one symbol's open positions against the last cached LTP.

        Force-closes any position breaching SL/TP. Closes are routed through
        the same dedup + lifecycle helper as the tick path
        (``TradingSessionService._record_and_persist_closed_trade``) so risk
        recording, exit-coordinator learning/post-trade and storage persistence
        run exactly once per position and a single ``trades`` row is written.
        """
        session = self._session_service.get_or_create_session(symbol)
        if not session:
            return

        cached_state = (
            self._state_broadcaster.get_latest_state(symbol)
            if self._state_broadcaster
            else None
        ) or {}
        ltp = cached_state.get("ltp", 0)
        if ltp <= 0:
            return

        closed: list = []
        with session._lock:
            open_positions = [
                p for p in session.portfolio.positions if p.is_open
            ]
            for pos in open_positions:
                should_close, reason = pos.should_close(ltp)
                if not should_close:
                    continue
                logger.warning(
                    "WATCHDOG: Force-closing %s %s @ %.2f "
                    "(SL=%.2f, TP=%.2f, LTP=%.2f) — %s",
                    pos.side, symbol, pos.entry_price,
                    pos.stop_loss, pos.take_profit, ltp, reason,
                )
                closed_pos = session.portfolio.close_position(
                    pos.id, ltp, f"WATCHDOG_{reason}",
                )
                if closed_pos:
                    closed_pos.close_reason = f"WATCHDOG_{reason}"
                    closed.append((closed_pos, reason))

        for closed_pos, reason in closed:
            try:
                self._session_service._record_and_persist_closed_trade(
                    symbol, closed_pos, session,
                )
            except Exception:
                logger.error(
                    "Watchdog: lifecycle finalize failed for %s", closed_pos.id,
                    exc_info=True,
                )

    async def reconciliation_loop(self) -> None:
        """Periodic position reconciliation loop (every 30 seconds in live mode)."""
        logger.info("Watchdog: reconciliation loop started")
        while self._running:
            try:
                await asyncio.sleep(30)
                if not self._running or not is_live_mode():
                    continue

                broker = getattr(self._session_service, "_broker", None)
                if not broker or not hasattr(broker, "get_positions"):
                    continue

                storage = getattr(self._session_service, "_storage", None)
                state_manager = getattr(self._session_service, "_state_manager", None)
                if not state_manager:
                    continue

                sessions = state_manager.get_all_sessions()
                internal_positions = {}
                internal_lookup: dict[str, str] = {}
                for sym, session in sessions.items():
                    for pos in session.portfolio.positions:
                        if not pos.is_open:
                            continue
                        internal_positions[pos.id] = pos
                        internal_lookup[pos.id] = sym

                broker_positions = await asyncio.to_thread(
                    broker.get_positions
                )
                normalized_broker = self._normalize_broker_positions(broker_positions)
                results = self._reconciliation_engine.reconcile(
                    internal_positions=internal_positions,
                    broker_positions=normalized_broker,
                )
                for result in results:
                    if result.issue == ReconciliationIssue.GHOST_POSITION:
                        symbol = result.internal_symbol or internal_lookup.get(result.internal_id, "")
                        if not symbol:
                            continue
                        session = sessions.get(symbol)
                        if not session:
                            continue
                        self._handle_ghost_position(symbol, session, result.internal_id, storage)
                    elif result.issue == ReconciliationIssue.MISSING_POSITION:
                        logger.warning(
                            "Reconciliation: missing broker position %s (broker qty=%.2f)",
                            result.broker_symbol,
                            result.broker_qty,
                        )
                    elif result.issue == ReconciliationIssue.QUANTITY_MISMATCH:
                        logger.warning(
                            "Reconciliation: qty mismatch internal=%s (%s) broker=%s (%s)",
                            result.internal_symbol,
                            result.internal_qty,
                            result.broker_symbol,
                            result.broker_qty,
                        )
            except asyncio.CancelledError:
                break
            except Exception:
                logger.error("Position reconciliation error", exc_info=True)
        logger.info("Watchdog: reconciliation loop stopped")

    def _normalize_broker_positions(self, positions: list[object]) -> list[dict]:
        """Normalize broker-specific position objects into dicts."""
        normalized: list[dict] = []
        for raw in positions or []:
            if isinstance(raw, dict):
                symbol = (
                    raw.get("trading_symbol")
                    or raw.get("symbol")
                    or ""
                )
                net_qty = raw.get("netQty", raw.get("quantity", 0))
                order_id = raw.get("orderId", "")
            else:
                symbol = (
                    getattr(raw, "trading_symbol", "")
                    or getattr(raw, "symbol", "")
                    or getattr(getattr(raw, "instrument", None), "symbol", "")
                )
                net_qty = (
                    getattr(raw, "netQty", None)
                    if getattr(raw, "netQty", None) is not None
                    else getattr(raw, "net_qty", None)
                )
                if net_qty is None:
                    net_qty = getattr(raw, "quantity", 0)
                order_id = getattr(raw, "orderId", "")
            try:
                net_qty_f = float(net_qty or 0)
            except (TypeError, ValueError):
                net_qty_f = 0.0
            normalized.append(
                {
                    "trading_symbol": symbol,
                    "netQty": net_qty_f,
                    "quantity": net_qty_f,
                    "orderId": str(order_id),
                }
            )
        return normalized

    def _get_ltp(self, symbol: str) -> float:
        """Get latest LTP for symbol from state broadcaster."""
        if not self._state_broadcaster:
            return 0.0
        state = self._state_broadcaster.get_latest_state(symbol) or {}
        ltp = state.get("ltp", 0.0)
        try:
            return float(ltp)
        except (TypeError, ValueError):
            return 0.0

    def _handle_ghost_position(
        self,
        symbol: str,
        session,
        position_id: str,
        storage,
    ) -> None:
        """Auto-close internally when broker does not report an open position."""
        ltp = self._get_ltp(symbol)
        if ltp <= 0:
            for pos in session.portfolio.positions:
                if pos.id == position_id and getattr(pos, "entry_price", None) is not None:
                    ltp = float(pos.entry_price)
                    break
            if ltp <= 0:
                return
        closed = session.portfolio.close_position(position_id, ltp, "RECONCILIATION_GHOST")
        if not closed:
            return

        exit_coordinator = getattr(self._session_service, "_exit_coordinator", None)
        if exit_coordinator:
            try:
                exit_coordinator.on_position_closed(symbol, closed, session=session)
            except Exception:
                logger.debug("Failed to run exit coordinator for ghost close", exc_info=True)

        if storage is not None:
            try:
                ensure_sync_adapter_result(
                    "storage.delete_open_position",
                    storage.delete_open_position,
                    position_id,
                )
                ensure_sync_adapter_result(
                    "storage.save_trade",
                    storage.save_trade,
                    {
                        "position_id": closed.id,
                        "symbol": symbol,
                        "side": _safe_side(closed.side),
                        "entry_price": closed.entry_price,
                        "exit_price": ltp,
                        "size": closed.size,
                        "pnl": closed.pnl,
                        "source": closed.source.value
                        if hasattr(closed.source, "value")
                        else str(closed.source),
                        "reason": "RECONCILIATION_GHOST",
                        "opened_at": closed.entry_time,
                        "closed_at": closed.exit_time,
                    },
                )
                logger.info("Watchdog: reconciled ghost close for %s (%s)", symbol, position_id)
            except Exception:
                logger.error(
                    "Watchdog: failed to persist reconciliation close for %s", position_id,
                    exc_info=True,
                )

    async def stale_stream_watchdog(self) -> None:
        """Detect hung market data streams and force reconnect or switch to polling.

        Runs independently of the tick loop so it fires even when
        ``async for pkt in stream_full()`` is blocked waiting forever.

        Strategy:
        - If no tick has EVER arrived within 60s of engine start
          and market is open → WS feed is dead (e.g. MCX OPTFUT broker limitation).
          Switch permanently to REST LTP polling.
        - Otherwise, for stale streams (tick gap > 5 min), cancel
          the stream task so _stream_with_reconnect triggers a WS reconnect.
        """
        _WS_POLL_FALLBACK_SECS = 60.0   # Give WS 60s to deliver first tick
        logger.info("Watchdog: stale-stream watchdog started")
        _ever_checked_fallback = False

        while self._running:
            try:
                await asyncio.sleep(15)
                if not is_market_open(exchange=settings.DEFAULT_EXCHANGE):
                    continue

                # --- Polling fallback: switch once if WS never delivers data ---
                if (
                    not _ever_checked_fallback
                    and not self._stream_manager.is_polling_mode()
                    and self._stream_manager.should_switch_to_polling()
                ):
                    _ever_checked_fallback = True
                    self._stream_manager.switch_to_polling()
                    continue

                # --- Normal stale: reconnect WS (stream produced data before) ---
                if not self._stream_manager.is_polling_mode() and self._stream_manager.is_stale(_STALE_RECONNECT_SECS):
                    logger.warning(
                        "Watchdog: STALE — no ticks for %.0fs, cancelling stream task",
                        _STALE_RECONNECT_SECS,
                    )
                    self._stream_manager.reset_staleness()

            except asyncio.CancelledError:
                break
            except Exception:
                logger.error("Stale-stream watchdog error", exc_info=True)
        logger.info("Watchdog: stale-stream watchdog stopped")

    async def gc_loop(self) -> None:
        """Periodic garbage collection loop.
        
        Runs every 30 minutes to prevent memory leaks in long-running sessions.
        """
        logger.info("Watchdog: GC loop started")
        last_gc_time = time.time()
        
        while self._running:
            try:
                await asyncio.sleep(60)  # Check every minute
                now_wall = time.time()
                if now_wall - last_gc_time >= _GC_INTERVAL_SECS:
                    import gc
                    collected = await asyncio.to_thread(gc.collect, 0)
                    logger.info("Watchdog: GC collected %d objects", collected)
                    last_gc_time = now_wall
            except asyncio.CancelledError:
                break
            except Exception:
                logger.error("GC loop error", exc_info=True)
        logger.info("Watchdog: GC loop stopped")