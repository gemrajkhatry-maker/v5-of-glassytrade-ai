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
from quant.contracts.value_objects import OHLC, OrderBook, OrderBookLevel

# Import delegated modules
from app.application.stream_manager import StreamManager
from app.application.candle_aggregator import CandleAggregator
from app.application.watchdog_manager import WatchdogManager
# New decomposed services
from app.application.services.tick_processor import TickProcessor
from app.application.services.state_broadcaster import StateBroadcaster
from app.application.services.engine_lifecycle import EngineLifecycle

from app.application.di.container import DIContainer
from quant.contracts.ports.market_data import IMarketData
from quant.contracts.ports.broker import IBroker
from app.application.services.trading_session import TradingSessionService

logger = logging.getLogger(__name__)

from quant.contracts.timezones import IST


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

    def __init__(self, container: DIContainer) -> None:
        self._container = container
        self._market_data = container.resolve(IMarketData)
        self._session_service = container.resolve(TradingSessionService)
        self._active_symbols: list[str] = []
        try:
            self._active_symbols = list(container.resolve(list))
        except Exception:
            pass

        # Wire the engine into the overseer's immediate-broadcast path.
        # The engine is constructed after the session service (main.py), so the
        # composition root injects a settable bridge — bind ourselves here.
        bridge = getattr(self._session_service, "_overseer_broadcast_bridge", None)
        if bridge is not None and hasattr(bridge, "bind"):
            bridge.bind(self)

        # Build futures routing (for AMT underlying feeds)
        from quant.amt.session.futures_provider import UnderlyingFuturesProvider
        self._underlying_futures_provider = UnderlyingFuturesProvider()
        self._fut_to_options, futures_roots = self._underlying_futures_provider.build_futures_routing(
            self._active_symbols
        )
        self._futures_symbol_set: frozenset[str] = frozenset(futures_roots)
        self._stream_symbols: list[str] = sorted(set(self._active_symbols) | set(futures_roots))

        # Active options are the active symbols minus futures roots
        self._active_option_symbols: frozenset[str] = frozenset(self._active_symbols)

        # Circuit breaker for tick processing
        self._circuit_breaker = PerEntityCircuitBreaker(
            failure_threshold=5,
            recovery_timeout=300.0,
        )

        # Per-symbol mutable state (kept for backward compatibility)
        self._current_depths: dict[str, dict] = {}
        self._last_process_times: dict[str, float] = {}

        # Real futures roots use their own aggregator (correct cumulative volume)
        self._futures_aggregator = CandleAggregator(interval=settings.STREAM_INTERVAL)

        # Create historical fetch callback for gap detection
        async def fetch_historical_callback(
            symbol: str,
            from_time,
            to_time,
        ):
            """Fetch historical candles for gap filling."""
            try:
                from quant.contracts.value_objects import OHLC
                from datetime import datetime

                # Get broker from market data adapter
                broker = self._market_data.get_broker()
                if not broker:
                    logger.warning("Broker not available for historical fetch")
                    return []

                # Resolve symbol to instrument
                instrument = self._market_data._make_instrument(symbol)

                # Fetch historical data
                df = await broker.get_historical_async(
                    instrument=instrument,
                    from_date=from_time,
                    to_date=to_time,
                    interval="1m",  # 1-minute candles
                    include_oi=False,
                )

                if df is None or df.empty:
                    logger.debug("No historical data for %s (%s to %s)", symbol, from_time, to_time)
                    return []

                # Convert DataFrame to OHLC list
                candles = []
                for timestamp, row in df.iterrows():
                    # Ensure timestamp is timezone-aware
                    if timestamp.tzinfo is None:
                        from quant.contracts.timezones import IST
                        timestamp = timestamp.replace(tzinfo=IST)

                    candle = OHLC(
                        time=timestamp.isoformat(),
                        open=float(row.get("open", 0)),
                        high=float(row.get("high", 0)),
                        low=float(row.get("low", 0)),
                        close=float(row.get("close", 0)),
                        volume=int(row.get("volume", 0)),
                    )
                    candles.append(candle)

                logger.info(
                    "Historical fetch: %s returned %d candles (%s to %s)",
                    symbol,
                    len(candles),
                    from_time.strftime("%H:%M:%S"),
                    to_time.strftime("%H:%M:%S"),
                )
                return candles

            except Exception as e:
                logger.error("Failed to fetch historical data for %s: %s", symbol, e, exc_info=True)
                return []

        # Delegated modules (existing)
        self._stream_manager = StreamManager(
            market_data=self._market_data,
            session_service=self._session_service,
            fetch_historical_callback=fetch_historical_callback,
        )
        self._candle_aggregator = CandleAggregator(interval=settings.STREAM_INTERVAL)

        # Enable Lee-Ready tick-level delta classification (audit P0-1).
        # Flag not yet exposed via Feature registry; default ON.
        use_lee_ready = True
        self._candle_aggregator.set_delta_mode(use_lee_ready)
        self._futures_aggregator.set_delta_mode(use_lee_ready)

        self._watchdog_manager = WatchdogManager(
            session_service=self._session_service,
            stream_manager=self._stream_manager,
        )

        # New decomposed services
        self._tick_processor = TickProcessor(
            candle_aggregator=self._candle_aggregator,
        )
        self._state_broadcaster = StateBroadcaster()
        self._lifecycle = EngineLifecycle(
            container=container,
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
        if symbol in self._active_option_symbols:
            self._candle_aggregator.initialize_symbol(symbol)
            self._tick_processor.initialize_symbol(symbol)
            self._state_broadcaster.initialize_symbol(symbol)
        if symbol in self._futures_symbol_set:
            self._futures_aggregator.initialize_symbol(symbol)

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
        )

        dhan_connect_state = [0.0]

        try:
            logger.info(
                "Engine: streaming live ticks for %d symbols (feed: %d incl. futures roots)",
                len(self._active_symbols),
                len(self._stream_symbols),
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
                ts = pkt.get("timestamp")
                if isinstance(ts, str):
                    now = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(
                        IST
                    )
                else:
                    now = datetime.now(IST)

                ltp = float(pkt.get("ltp", 0))
                if ltp <= 0:
                    continue

                vol = int(pkt.get("volume", 0))
                ltq = int(pkt.get("ltq", 0))
                oi = int(pkt.get("oi", 0))

                if vol < 0:
                    continue

                cum_buy = int(pkt.get("total_buy_qty", 0))
                cum_sell = int(pkt.get("total_sell_qty", 0))
                pkt_bids = pkt.get("depth_bids", [])
                pkt_asks = pkt.get("depth_asks", [])
                best_bid = pkt_bids[0].get("price", 0) if pkt_bids else 0.0
                best_ask = pkt_asks[0].get("price", 0) if pkt_asks else 0.0

                # Underlying futures roots: feed session buffers only (no option process_tick)
                if pkt_symbol in self._futures_symbol_set:
                    if pkt_symbol not in self._futures_aggregator._candle_states:
                        self._initialize_symbol_state(pkt_symbol)
                    if self._circuit_breaker.is_open(pkt_symbol):
                        continue
                    self._stream_manager.update_tick_time(pkt_symbol)
                    fut_ohlc = self._futures_aggregator.aggregate(
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
                    if fut_ohlc:
                        ferr = self._futures_aggregator.validate_tick(fut_ohlc)
                        if not ferr:
                            self._session_service.on_underlying_futures_candle(
                                pkt_symbol, fut_ohlc
                            )
                            self._circuit_breaker.record_success(pkt_symbol)
                        else:
                            self._circuit_breaker.record_failure(pkt_symbol)
                    continue

                if pkt_symbol not in self._candle_aggregator._candle_states:
                    self._initialize_symbol_state(pkt_symbol)

                if self._circuit_breaker.is_open(pkt_symbol):
                    continue

                self._stream_manager.update_tick_time(pkt_symbol)

                # OI tracking (delegated to TickProcessor)
                oi_data = self._tick_processor.track_oi(pkt_symbol, oi)

                # 5-level depth from packet (delegated to TickProcessor)
                current_book = self._current_depths.get(pkt_symbol, {}).get("book")
                updated_book = self._tick_processor.build_depth_from_packet(
                    pkt_symbol, current_book, pkt_bids, pkt_asks
                )
                if updated_book is not None:
                    self._current_depths[pkt_symbol]["book"] = updated_book

                # Footprint accumulator
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

                # Underlying buffers are updated from subscribed futures roots (see above)
                try:
                    state = await asyncio.to_thread(
                        self._session_service.process_tick,
                        pkt_symbol,
                        tick,
                        self._current_depths[pkt_symbol]["book"],
                        oi_data=oi_data,
                        underlying_tick=None,
                    )
                    state["tick"] = ohlc_to_dto(tick)
                    state["ltp"] = ltp
                    state["oi"] = oi
                    state["_symbol"] = pkt_symbol
                    state["depth"] = _depth_to_dto(
                        self._current_depths[pkt_symbol]["book"]
                    )

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
