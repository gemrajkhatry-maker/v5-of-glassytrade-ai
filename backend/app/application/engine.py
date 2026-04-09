"""TradingEngine — runs independently of frontend WebSocket connections.

Delegates to focused modules:
  - StreamManager: Market data streaming
  - CandleAggregator: Tick-to-candle aggregation
  - WatchdogManager: SL/TP watchdog and stream health
  - TickProcessor: Tick processing and OI tracking
  - StateBroadcaster: WebSocket state assembly and broadcast
  - EngineLifecycle: Startup, shutdown, recovery

Architecture:
  1. Backend starts trading on server startup (lifespan)
  2. Frontend WS is a read-only viewer of engine state
  3. Frontend disconnect does NOT affect trading
"""

from __future__ import annotations

import asyncio
import copy
import logging
import time
import threading
from datetime import datetime
from typing import TYPE_CHECKING

from shared.resilience import PerEntityCircuitBreaker
from app.config import settings
from app.application.utils import is_market_open
from app.domain.trading.models.value_objects import OHLC, OrderBook, OrderBookLevel

# Import delegated modules
from app.application.stream_manager import StreamManager
from app.application.candle_aggregator import CandleAggregator
from app.application.range_bar_builder import RangeBarBuilder
from app.application.watchdog_manager import WatchdogManager
from app.domain.services.underlying_futures_provider import UnderlyingFuturesProvider

# New decomposed services
from app.application.services.tick_processor import TickProcessor
from app.application.services.state_broadcaster import StateBroadcaster
from app.application.services.engine_lifecycle import EngineLifecycle

if TYPE_CHECKING:
    from app.api.dependencies import ServiceGraph

logger = logging.getLogger(__name__)

from app.shared.timezones import IST


def _depth_to_dto(book: OrderBook | None) -> dict | None:
    """Convert OrderBook to DTO dict for JSON serialization."""
    if not book:
        return None
    return {
        "bids": [
            {"price": float(l.price), "quantity": float(l.quantity)}
            for l in book.bids[:20]
        ],
        "asks": [
            {"price": float(l.price), "quantity": float(l.quantity)}
            for l in book.asks[:20]
        ],
    }


class TradingEngine:
    """Standalone trading engine — streams market data and runs the full pipeline.

    Lifecycle:
        engine = TradingEngine(graph)
        await engine.start()   # called from FastAPI lifespan
        ...
        await engine.stop()    # called on shutdown

    Frontend WS viewers call:
        engine.get_latest_state(symbol)
        await engine.wait_for_update(known_generation)
    """

    def __init__(self, graph: ServiceGraph) -> None:
        self._graph = graph
        self._market_data = graph.market_data
        self._session_service = graph.trading_session
        self._active_symbols: list[str] = graph.active_symbols

        # Circuit breaker for tick processing
        self._circuit_breaker = PerEntityCircuitBreaker(
            failure_threshold=5,
            recovery_timeout=300.0,
        )

        # Per-symbol mutable state (kept for backward compatibility)
        self._current_depths: dict[str, dict] = {}
        self._last_process_times: dict[str, float] = {}

        # Underlying futures provider — maps option symbols → futures for AMT analysis
        self._underlying_provider = UnderlyingFuturesProvider()
        self._underlying_aggregator = CandleAggregator(interval="5m")
        self._underlying_ticks: dict[str, OHLC] = {}

        # Delegated modules (existing)
        self._stream_manager = StreamManager(market_data=self._market_data)
        self._candle_aggregator = CandleAggregator(interval=settings.STREAM_INTERVAL)
        self._watchdog_manager = WatchdogManager(
            session_service=self._session_service,
            stream_manager=self._stream_manager,
        )

        # New decomposed services
        self._tick_processor = TickProcessor(
            candle_aggregator=self._candle_aggregator,
            range_default_size=3.0,
        )
        self._state_broadcaster = StateBroadcaster()
        self._lifecycle = EngineLifecycle(
            graph=graph,
            stream_manager=self._stream_manager,
            watchdog_manager=self._watchdog_manager,
            state_broadcaster=self._state_broadcaster,
            tick_processor=self._tick_processor,
        )
        self._lifecycle.set_candle_aggregator(self._candle_aggregator)

        # Event loop reference for cross-thread notifications
        self._loop: asyncio.AbstractEventLoop | None = None

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Seed history and begin streaming. Called from lifespan."""
        # Capture the event loop for cross-thread notifications
        self._loop = asyncio.get_running_loop()
        self._state_broadcaster.set_event_loop(self._loop)

        # Start lifecycle (recovery, seeding, and background tasks)
        await self._lifecycle.startup(
            tick_loop_coro=self._tick_loop_forever(),
            initialize_symbol_state=self._initialize_symbol_state,
        )

    async def stop(self) -> None:
        """Graceful shutdown."""
        await self._lifecycle.shutdown()
        await self._state_broadcaster.cancel_pending_notifications()

    def _initialize_symbol_state(self, symbol: str) -> None:
        """Initialize per-symbol state for a new symbol."""
        self._current_depths[symbol] = {"book": None}
        self._last_process_times[symbol] = 0.0
        self._candle_aggregator.initialize_symbol(symbol)
        self._tick_processor.initialize_symbol(symbol)
        self._state_broadcaster.initialize_symbol(symbol)

    def get_latest_state(self, symbol: str) -> dict | None:
        """Read-only access for WS viewers."""
        return self._state_broadcaster.get_latest_state(symbol)

    def get_all_latest_states(self) -> dict[str, dict]:
        """All symbol states for initial WS sync."""
        return self._state_broadcaster.get_all_latest_states()

    def get_active_symbols(self) -> list[str]:
        """Get list of active symbols."""
        return list(self._active_symbols)

    @property
    def generation(self) -> int:
        """Get current generation counter."""
        return self._state_broadcaster.generation

    async def wait_for_update(self, known_gen: int, timeout: float = 5.0) -> int:
        """Block until generation advances past known_gen."""
        return await self._state_broadcaster.wait_for_update(known_gen, timeout)

    def get_history(self, symbol: str) -> list[OHLC]:
        """Get seeded history for a symbol."""
        session = self._session_service.get_or_create_session(symbol)
        if session:
            try:
                return sorted(session.data, key=lambda x: x.time)
            except Exception:
                return list(session.data)
        return []

    def get_depth(self, symbol: str) -> OrderBook | None:
        """Get current order book depth for a symbol."""
        d = self._current_depths.get(symbol)
        return d["book"] if d else None

    # ------------------------------------------------------------------
    # Immediate update trigger (for cross-thread notifications)
    # ------------------------------------------------------------------

    def trigger_immediate_update(self, symbol: str) -> None:
        """Build fresh state snapshot for symbol and notify all viewers.

        Thread-safe: can be called from background threads (e.g., overseer).
        """
        session = self._session_service.get_or_create_session(symbol)
        self._state_broadcaster.trigger_immediate_update(
            symbol=symbol,
            session=session,
            session_service=self._session_service,
            current_depth=self._current_depths.get(symbol, {}),
            range_builder_dict=self._tick_processor.get_range_builder_dict(symbol),
        )

    # ------------------------------------------------------------------
    # Main tick loop
    # ------------------------------------------------------------------

    async def _tick_loop_forever(self) -> None:
        """Retry _tick_loop on stale/disconnect — keeps engine alive."""
        while self._lifecycle.running:
            await self._tick_loop()
            if self._lifecycle.running:
                logger.info("Engine: tick loop restarting after disconnect...")
                await asyncio.sleep(2)

    async def _tick_loop(self) -> None:
        """Stream ticks from Dhan, aggregate candles, run process_tick."""
        from app.infrastructure.serialization.schemas import (
            ohlc_to_dto,
            footprint_to_dto,
        )

        dhan_connect_state = [0.0]

        try:
            logger.info(
                "Engine: streaming live ticks for %d symbols", len(self._active_symbols)
            )
            async for pkt in self._stream_manager.stream_with_reconnect(
                dhan_connect_state
            ):
                if not self._lifecycle.running:
                    break

                if pkt.get("_stream_dead"):
                    logger.error("Engine: market data connection lost after retries")
                    break

                if not is_market_open(exchange=settings.DEFAULT_EXCHANGE):
                    continue

                # Demux
                pkt_symbol = pkt.get(
                    "symbol", self._active_symbols[0] if self._active_symbols else ""
                )
                if pkt_symbol not in self._candle_aggregator._candle_states:
                    self._initialize_symbol_state(pkt_symbol)

                if self._circuit_breaker.is_open(pkt_symbol):
                    continue

                self._stream_manager.update_tick_time(pkt_symbol)

                ltp = float(pkt.get("ltp", 0))
                if ltp <= 0:
                    continue

                ts = pkt.get("timestamp")
                if isinstance(ts, str):
                    now = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(
                        IST
                    )
                else:
                    now = datetime.now(IST)

                vol = int(pkt.get("volume", 0))
                ltq = int(pkt.get("ltq", 0))
                oi = int(pkt.get("oi", 0))

                if vol < 0:
                    continue

                # OI tracking (delegated to TickProcessor)
                oi_data = self._tick_processor.track_oi(pkt_symbol, oi)

                cum_buy = int(pkt.get("total_buy_qty", 0))
                cum_sell = int(pkt.get("total_sell_qty", 0))

                # 5-level depth from packet (delegated to TickProcessor)
                pkt_bids = pkt.get("depth_bids", [])
                pkt_asks = pkt.get("depth_asks", [])
                current_book = self._current_depths.get(pkt_symbol, {}).get("book")
                updated_book = self._tick_processor.build_depth_from_packet(
                    pkt_symbol, current_book, pkt_bids, pkt_asks
                )
                if updated_book is not None:
                    self._current_depths[pkt_symbol]["book"] = updated_book

                # Footprint accumulator
                best_bid = pkt_bids[0].get("price", 0) if pkt_bids else 0.0
                best_ask = pkt_asks[0].get("price", 0) if pkt_asks else 0.0
                if ltq > 0:
                    candle_t = self._candle_aggregator._candle_start(now)
                    self._candle_aggregator.update_footprint(
                        pkt_symbol,
                        ltp,
                        ltq,
                        float(best_bid),
                        float(best_ask),
                        candle_t,
                    )

                # Candle aggregation
                tick = self._candle_aggregator.aggregate(
                    pkt_symbol,
                    now,
                    ltp,
                    vol,
                    cum_buy,
                    cum_sell,
                    oi,
                    best_bid=float(best_bid),
                    best_ask=float(best_ask),
                )
                if tick is None:
                    continue

                error = self._candle_aggregator.validate_tick(tick)
                if error:
                    continue

                # Throttle process_tick to max once per 500ms per symbol
                now_time = asyncio.get_event_loop().time()
                elapsed = now_time - self._last_process_times.get(pkt_symbol, 0)

                if elapsed < 0.5:
                    # Still update latest state with cached analysis for viewers
                    self._update_throttled_state(pkt_symbol, tick, ltp, oi, ohlc_to_dto)
                    await self._state_broadcaster.notify_viewers()
                    continue

                self._last_process_times[pkt_symbol] = now_time

                # Dual feed: aggregate underlying futures for AMT analysis
                mapping = self._underlying_provider.get_mapping(pkt_symbol)
                underlying_tick = None
                if mapping:
                    ut_sym = mapping.underlying_symbol
                    underlying_tick = self._underlying_aggregator.aggregate(
                        ut_sym,
                        now,
                        ltp,
                        vol,
                        cum_buy,
                        cum_sell,
                        oi,
                        best_bid=float(best_bid),
                        best_ask=float(best_ask),
                    )
                    if underlying_tick:
                        self._underlying_ticks[ut_sym] = underlying_tick

                # Full process_tick — pass underlying futures for AMT
                try:
                    state = await asyncio.to_thread(
                        self._session_service.process_tick,
                        pkt_symbol,
                        tick,
                        self._current_depths[pkt_symbol]["book"],
                        oi_data=oi_data,
                        underlying_tick=underlying_tick,
                    )
                    state["tick"] = ohlc_to_dto(tick)
                    state["ltp"] = ltp
                    state["oi"] = oi
                    state["_symbol"] = pkt_symbol
                    state["depth"] = _depth_to_dto(
                        self._current_depths[pkt_symbol]["book"]
                    )

                    # Overlay footprint
                    session = self._session_service.get_or_create_session(pkt_symbol)
                    if session:
                        real_fp = self._candle_aggregator.get_footprint(pkt_symbol)
                        if real_fp:
                            session.last_footprint = {
                                k: footprint_to_dto(v) for k, v in real_fp.items()
                            }
                            state["footprint"] = session.last_footprint

                    # Range bar builder (delegated to TickProcessor)
                    rb = self._tick_processor.get_or_create_range_builder(pkt_symbol)
                    # Backfill if new
                    if len(rb._bars) == 0 and session and session.data:
                        self._tick_processor.backfill_range_bars(
                            pkt_symbol, session.data
                        )
                    range_dict = self._tick_processor.update_range_bar(
                        pkt_symbol, ltp, str(now), tick
                    )
                    if range_dict:
                        state["rangeBars"] = range_dict

                    self._state_broadcaster.set_state(pkt_symbol, state)
                    await self._state_broadcaster.notify_viewers()
                    self._circuit_breaker.record_success(pkt_symbol)
                except Exception:
                    self._circuit_breaker.record_failure(pkt_symbol)
                    logger.error(
                        "Engine: tick processing error for %s",
                        pkt_symbol,
                        exc_info=True,
                    )

        except asyncio.CancelledError:
            logger.info("Engine: tick loop cancelled")
        except Exception:
            logger.error("Engine: tick loop crashed", exc_info=True)

    # ------------------------------------------------------------------
    # Throttled state update (between full process_tick calls)
    # ------------------------------------------------------------------

    def _update_throttled_state(
        self, symbol: str, tick: OHLC, ltp: float, oi: int, ohlc_to_dto
    ) -> None:
        """Update latest state with current tick + cached analysis (no process_tick)."""
        session = self._session_service.get_or_create_session(symbol)
        msg = self._tick_processor.build_throttled_state(
            symbol=symbol,
            tick=tick,
            ltp=ltp,
            oi=oi,
            current_depth=self._current_depths.get(symbol, {}).get("book"),
            session=session,
            session_service=self._session_service,
            ohlc_to_dto=ohlc_to_dto,
        )
        # Merge into existing latest state
        self._state_broadcaster.update_state(symbol, msg)
