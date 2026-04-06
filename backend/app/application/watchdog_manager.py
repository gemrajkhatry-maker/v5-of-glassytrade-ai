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

from app.config import settings
from app.application.utils import is_market_open

if TYPE_CHECKING:
    from app.application.stream_manager import StreamManager
from app.shared.timezones import IST

logger = logging.getLogger(__name__)



_GC_INTERVAL_SECS = 1800
_STALE_THRESHOLD_SECS = 60.0
_STALE_RECONNECT_SECS = 300.0  # 5 min — MCX options can be quiet for minutes between ticks


class WatchdogManager:
    """Manages SL/TP watchdog and stream health monitoring.
    
    This module encapsulates all watchdog logic, providing a single
    source of truth for position protection and stream monitoring.
    """

    def __init__(self, session_service, stream_manager: StreamManager):
        self._session_service = session_service
        self._stream_manager = stream_manager
        self._running = False
        self._active_symbols: list[str] = []

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
                    session = self._session_service.get_or_create_session(sym)
                    if not session:
                        continue

                    # Get last known LTP from cached state
                    cached_state = self._stream_manager._latest_states.get(sym, {}) if hasattr(self._stream_manager, '_latest_states') else {}
                    ltp = cached_state.get("ltp", 0)
                    if ltp <= 0:
                        continue

                    with session._lock:
                        open_positions = [
                            p for p in session.portfolio.positions if p.is_open
                        ]
                        if not open_positions:
                            continue

                        for pos in open_positions:
                            should_close, reason = pos.should_close(ltp)
                            if should_close:
                                logger.warning(
                                    "WATCHDOG: Force-closing %s %s @ %.2f "
                                    "(SL=%.2f, TP=%.2f, LTP=%.2f) — %s",
                                    pos.side, sym, pos.entry_price,
                                    pos.stop_loss, pos.take_profit, ltp, reason,
                                )
                                closed = session.portfolio.close_position(
                                    pos.id, ltp, f"WATCHDOG_{reason}",
                                )
                                if closed:
                                    # Persist trade close
                                    if self._session_service._storage:
                                        try:
                                            self._session_service._storage.delete_open_position(pos.id)
                                            self._session_service._storage.save_trade({
                                                "position_id": pos.id,
                                                "symbol": sym,
                                                "side": pos.side.value if hasattr(pos.side, 'value') else str(pos.side),
                                                "entry_price": pos.entry_price,
                                                "exit_price": ltp,
                                                "size": pos.size,
                                                "pnl": pos.pnl,
                                                "source": pos.source.value if hasattr(pos.source, 'value') else str(pos.source),
                                                "reason": f"WATCHDOG_{reason}",
                                                "opened_at": pos.entry_time,
                                                "closed_at": pos.exit_time,
                                            })
                                        except Exception:
                                            logger.debug("Watchdog: persistence failed", exc_info=True)
            except asyncio.CancelledError:
                break
            except Exception:
                logger.error("SL watchdog error", exc_info=True)
        logger.info("Watchdog: SL watchdog stopped")

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