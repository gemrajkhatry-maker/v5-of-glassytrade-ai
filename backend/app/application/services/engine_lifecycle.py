"""Engine Lifecycle — Manages engine startup, shutdown, and recovery.

Extracted from engine.py. Responsibilities:
- Engine startup orchestration
- Graceful shutdown
- Position recovery from DB
- Historical data seeding
- Health checks
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime
from typing import TYPE_CHECKING

from app.config import settings
from app.domain.trading.models.value_objects import OHLC

if TYPE_CHECKING:
    from app.api.dependencies import ServiceGraph
    from app.application.stream_manager import StreamManager
    from app.application.watchdog_manager import WatchdogManager
    from app.application.services.state_broadcaster import StateBroadcaster
    from app.application.services.tick_processor import TickProcessor

logger = logging.getLogger(__name__)


class EngineLifecycle:
    """Manages engine startup, shutdown, watchdog, and recovery.

    Handles:
    - Initializing all delegated modules
    - Position recovery from DB on startup
    - Historical data seeding
    - Graceful shutdown orchestration
    """

    def __init__(
        self,
        graph: "ServiceGraph",
        stream_manager: "StreamManager",
        watchdog_manager: "WatchdogManager",
        state_broadcaster: "StateBroadcaster",
        tick_processor: "TickProcessor",
    ):
        """Initialize engine lifecycle manager.

        Args:
            graph: Service graph with dependencies
            stream_manager: Stream manager for market data
            watchdog_manager: Watchdog manager for SL/TP and health
            state_broadcaster: State broadcaster for WS updates
            tick_processor: Tick processor for market data processing
        """
        self._graph = graph
        self._market_data = graph.market_data
        self._session_service = graph.trading_session
        self._active_symbols: list[str] = graph.active_symbols

        self._stream_manager = stream_manager
        self._watchdog_manager = watchdog_manager
        self._state_broadcaster = state_broadcaster
        self._tick_processor = tick_processor

        # Tasks managed by lifecycle
        self._stream_task: asyncio.Task | None = None
        self._watchdog_task: asyncio.Task | None = None
        self._stale_watchdog_task: asyncio.Task | None = None
        self._gc_task: asyncio.Task | None = None

        self._running = False
        self._engine_start_time: float = 0.0

        # Candle aggregator reference for seeding
        self._candle_aggregator = None

    def set_candle_aggregator(self, aggregator) -> None:
        """Set candle aggregator reference.

        Args:
            aggregator: CandleAggregator instance
        """
        self._candle_aggregator = aggregator

    # ------------------------------------------------------------------
    # Startup
    # ------------------------------------------------------------------

    async def startup(
        self,
        tick_loop_coro,
        initialize_symbol_state: callable,
    ) -> None:
        """Start the engine lifecycle.

        Args:
            tick_loop_coro: Coroutine for the main tick loop
            initialize_symbol_state: Callback to initialize per-symbol state
        """
        if self._running:
            return
        self._running = True

        # Initialize delegated modules
        self._stream_manager.set_active_symbols(self._active_symbols)
        self._stream_manager.set_running(True)
        self._watchdog_manager.set_active_symbols(self._active_symbols)
        self._watchdog_manager.set_running(True)

        # Initialize per-symbol state
        for sym in self._active_symbols:
            initialize_symbol_state(sym)

        self._engine_start_time = time.time()

        # Recover open positions from DB
        await self._recover_open_positions(initialize_symbol_state)

        # Seed historical data
        await self._seed_history()

        # Start background tasks
        self._stream_task = asyncio.create_task(tick_loop_coro)
        self._watchdog_task = asyncio.create_task(
            self._watchdog_manager.sl_watchdog_loop()
        )
        self._stale_watchdog_task = asyncio.create_task(
            self._watchdog_manager.stale_stream_watchdog()
        )
        self._gc_task = asyncio.create_task(self._watchdog_manager.gc_loop())

        logger.info(
            "Trading engine started for %d symbols: %s",
            len(self._active_symbols),
            self._active_symbols,
        )

    # ------------------------------------------------------------------
    # Shutdown
    # ------------------------------------------------------------------

    async def shutdown(self) -> None:
        """Graceful shutdown of all tasks."""
        self._running = False
        self._stream_manager.set_running(False)
        self._watchdog_manager.set_running(False)

        # Cancel all tasks
        for task in (
            self._stream_task,
            self._watchdog_task,
            self._stale_watchdog_task,
            self._gc_task,
        ):
            if task and not task.done():
                task.cancel()

        # Wait for all tasks to complete
        tasks = [
            t
            for t in (
                self._stream_task,
                self._watchdog_task,
                self._stale_watchdog_task,
                self._gc_task,
            )
            if t
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)

        logger.info("Trading engine stopped.")

    # ------------------------------------------------------------------
    # Health Check
    # ------------------------------------------------------------------

    def health_check(self) -> dict:
        """Get health status of the engine.

        Returns:
            Dict with health status info
        """
        uptime = time.time() - self._engine_start_time if self._engine_start_time else 0
        return {
            "running": self._running,
            "uptime_seconds": uptime,
            "active_symbols": len(self._active_symbols),
            "stream_task_running": self._stream_task is not None and not self._stream_task.done(),
            "watchdog_task_running": self._watchdog_task is not None and not self._watchdog_task.done(),
        }

    @property
    def running(self) -> bool:
        """Check if engine is running."""
        return self._running

    @property
    def start_time(self) -> float:
        """Get engine start time."""
        return self._engine_start_time

    # ------------------------------------------------------------------
    # Position Recovery
    # ------------------------------------------------------------------

    async def _recover_open_positions(
        self, initialize_symbol_state: callable
    ) -> None:
        """Recover open positions from DB on startup to survive crashes.

        Loads all open positions from the open_positions table and restores
        them to the TradeManager so the engine can resume managing them
        without losing position context.

        Filters by current exchange — only recovers positions belonging to
        the active exchange (NSE or MCX) to prevent cross-exchange contamination.

        If CLEAR_POSITIONS_ON_RESTART is True (default), all stale positions
        are cleared before recovery to ensure a fresh start.

        Args:
            initialize_symbol_state: Callback to initialize per-symbol state
        """
        storage = self._session_service._storage
        if not storage:
            logger.info("Engine: no storage available — skipping position recovery")
            return

        # Clear stale positions on restart (safety for options — prevents overnight holds)
        if settings.CLEAR_POSITIONS_ON_RESTART:
            cleared_count = storage.clear_all_open_positions()
            if cleared_count > 0:
                logger.info(
                    "STARTUP: Cleared %d stale positions (CLEAR_POSITIONS_ON_RESTART=True)",
                    cleared_count,
                )
            # No positions to recover after clearing
            return

        try:
            open_positions = storage.load_open_positions()
            if not open_positions:
                logger.info("Engine: no open positions to recover")
                return

            # Exchange-aware filtering
            current_exchange = getattr(self._graph.exchange_config, "exchange", "MCX")

            recovered = 0
            skipped = 0
            for pos_data in open_positions:
                symbol = pos_data.get("symbol", "")
                if not symbol:
                    continue

                # Skip positions from other exchanges
                _nse_underlyings = {"NIFTY", "BANKNIFTY", "FINNIFTY"}
                _underlying = symbol.split(" ")[0].upper() if symbol else ""
                _symbol_exchange = "NSE" if _underlying in _nse_underlyings else "MCX"
                if _symbol_exchange != current_exchange:
                    skipped += 1
                    logger.debug(
                        "Engine: skipping %s position recovery (current=%s): %s",
                        _symbol_exchange,
                        current_exchange,
                        symbol,
                    )
                    continue

                # Add symbol to active list if not already there
                if symbol not in self._active_symbols:
                    self._active_symbols.append(symbol)
                    initialize_symbol_state(symbol)

                # Restore position to the session's portfolio
                try:
                    session = self._session_service.get_or_create_session(symbol)
                    position = session.portfolio.recover_position(pos_data)
                    if position:
                        # Initialize partition state for exit management
                        self._session_service._lifecycle_handler.initialize_partition_state(
                            position.id
                        )

                        logger.info(
                            "Engine: recovered position %s for %s (side=%s, entry=%.2f, SL=%.2f, TP=%.2f)",
                            pos_data.get("id", "?"),
                            symbol,
                            pos_data.get("side", "?"),
                            pos_data.get("entry_price", 0),
                            pos_data.get("stop_loss", 0),
                            pos_data.get("take_profit", 0),
                        )
                        recovered += 1
                except Exception as e:
                    logger.error(
                        "Engine: failed to recover position %s for %s: %s",
                        pos_data.get("id", "?"),
                        symbol,
                        e,
                    )

            if recovered > 0:
                logger.info(
                    "Engine: recovered %d open positions (skipped %d from other exchanges)",
                    recovered,
                    skipped,
                )
            else:
                logger.info(
                    "Engine: no positions recovered for %s (skipped %d)",
                    current_exchange,
                    skipped,
                )

        except Exception as e:
            logger.error("Engine: position recovery failed: %s", e, exc_info=True)

    # ------------------------------------------------------------------
    # History Seeding
    # ------------------------------------------------------------------

    async def _seed_history(self) -> None:
        """Seed historical data for all active symbols."""
        for i, sym in enumerate(self._active_symbols):
            if i > 0:
                await asyncio.sleep(1.0)
            try:
                history = await self._market_data.fetch_history(
                    sym,
                    settings.STREAM_INTERVAL,
                    500,
                )

                # Fallback for MCX options: broker API returns empty, load from DB
                if not history:
                    history = self._load_candles_from_db(sym, limit=500)
                    if history:
                        logger.info(
                            "Engine: seeded %d candles for %s from local DB",
                            len(history),
                            sym,
                        )

                if history:
                    session = self._session_service.get_or_create_session(sym)
                    if len(session.data) < 10:
                        session.data = history
                        logger.info(
                            "Engine: seeded %d candles for %s", len(history), sym
                        )

                    # Build initial state from last candle
                    if len(history) >= 1:
                        try:
                            last_candle = history[-1]
                            from app.infrastructure.serialization.schemas import (
                                ohlc_to_dto,
                            )

                            self._state_broadcaster.set_state(
                                sym,
                                {
                                    "tick": ohlc_to_dto(last_candle),
                                    "ltp": last_candle.close,
                                    "_symbol": sym,
                                    "status": "seeded",
                                },
                            )
                            logger.info(
                                "Engine: initial seed done for %s (skipped LLM)", sym
                            )
                        except Exception:
                            logger.debug(
                                "Engine: initial seed failed for %s", sym, exc_info=True
                            )
            except Exception:
                logger.warning(
                    "Engine: history fetch failed for %s", sym, exc_info=True
                )

    def _load_candles_from_db(self, symbol: str, limit: int = 500) -> list[OHLC]:
        """Load closed candles from SQLite.

        Uses a dict keyed by timestamp to deduplicate — handles old DB rows written
        per-tick before the candle-close-only write strategy was introduced.

        Args:
            symbol: Trading symbol
            limit: Maximum candles to return

        Returns:
            List of OHLC candles sorted by time
        """
        storage = self._session_service._storage
        if not storage:
            return []
        try:
            rows = storage.query_ticks(symbol, limit=limit * 20)
            seen: dict[str, OHLC] = {}
            for row in rows:
                t = row["time"]
                if not t:
                    continue
                try:
                    seen[t] = OHLC(
                        time=t,
                        open=float(row["open"] or 0),
                        high=float(row["high"] or 0),
                        low=float(row["low"] or 0),
                        close=float(row["close"] or 0),
                        volume=float(row["volume"] or 0),
                        delta=float(row["delta"] or 0),
                    )
                except Exception:
                    continue  # Skip rows with non-numeric fields
            # Sort by time
            return sorted(seen.values(), key=lambda x: x.time)[-limit:]
        except Exception:
            logger.debug(
                "Engine: failed to load candles from DB for %s", symbol, exc_info=True
            )
            return []

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------

    @property
    def stream_task(self) -> asyncio.Task | None:
        """Get the stream task."""
        return self._stream_task

    @property
    def watchdog_task(self) -> asyncio.Task | None:
        """Get the watchdog task."""
        return self._watchdog_task

    @property
    def stale_watchdog_task(self) -> asyncio.Task | None:
        """Get the stale watchdog task."""
        return self._stale_watchdog_task

    @property
    def gc_task(self) -> asyncio.Task | None:
        """Get the GC task."""
        return self._gc_task
