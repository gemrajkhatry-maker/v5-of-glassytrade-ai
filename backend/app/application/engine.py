"""TradingEngine — runs independently of frontend WebSocket connections.

Delegates to focused modules:
  - StreamManager: Market data streaming
  - CandleAggregator: Tick-to-candle aggregation
  - WatchdogManager: SL/TP watchdog and stream health

Architecture:
  1. Backend starts trading on server startup (lifespan)
  2. Frontend WS is a read-only viewer of engine state
  3. Frontend disconnect does NOT affect trading
"""

from __future__ import annotations

import asyncio
import logging
import time
from datetime import datetime, timezone, timedelta
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

if TYPE_CHECKING:
    from app.api.dependencies import ServiceGraph

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


def _depth_to_dto(book: OrderBook | None) -> dict | None:
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

        # Per-symbol latest state snapshot (read by WS viewers)
        self._latest_states: dict[str, dict] = {}
        # Generation counter + condition for viewer notification
        self._generation: int = 0
        self._condition: asyncio.Condition = asyncio.Condition()
        self._last_notify_time: float = 0.0
        self._notify_scheduled: bool = False
        self._notify_task: asyncio.Task | None = None

        # Internal per-symbol mutable state
        self._current_depths: dict[str, dict] = {}
        self._last_process_times: dict[str, float] = {}
        self._prev_oi_values: dict[str, int] = {}

        self._circuit_breaker = PerEntityCircuitBreaker(
            failure_threshold=5,
            recovery_timeout=300.0,
        )

        # Delegated modules
        self._stream_manager = StreamManager(market_data=self._market_data)
        self._candle_aggregator = CandleAggregator(interval=settings.STREAM_INTERVAL)
        # Range bar builder — per-symbol, ATR-based range size
        self._range_builders: dict[str, RangeBarBuilder] = {}
        self._range_default_size: float = 3.0  # Default range size (points)
        self._watchdog_manager = WatchdogManager(
            session_service=self._session_service,
            stream_manager=self._stream_manager,
        )

        # Tasks
        self._stream_task: asyncio.Task | None = None
        self._watchdog_task: asyncio.Task | None = None
        self._stale_watchdog_task: asyncio.Task | None = None
        self._gc_task: asyncio.Task | None = None
        self._running = False
        self._engine_start_time: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Seed history and begin streaming. Called from lifespan."""
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
            self._current_depths[sym] = {"book": None}
            self._last_process_times[sym] = 0.0
            self._prev_oi_values[sym] = 0
            self._candle_aggregator.initialize_symbol(sym)

        self._engine_start_time = time.time()

        # ── Mid-Trade Recovery (Gap #8) ──
        # Recover open positions from DB on startup to survive crashes
        await self._recover_open_positions()

        # Seed historical data
        await self._seed_history()

        # Start streaming tasks
        self._stream_task = asyncio.create_task(self._tick_loop_forever())
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

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._running = False
        self._stream_manager.set_running(False)
        self._watchdog_manager.set_running(False)

        notify_task = getattr(self, "_notify_task", None)
        for task in (
            self._stream_task,
            self._watchdog_task,
            self._stale_watchdog_task,
            self._gc_task,
            notify_task,
        ):
            if task and not task.done():
                task.cancel()
        tasks = [
            t
            for t in (
                self._stream_task,
                self._watchdog_task,
                self._stale_watchdog_task,
                self._gc_task,
                notify_task,
            )
            if t
        ]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Trading engine stopped.")

    def get_latest_state(self, symbol: str) -> dict | None:
        """Read-only access for WS viewers.

        Returns a shallow copy of the state dict with a selective deep copy of
        only the mutable ``portfolio`` value (which contains Position objects).
        This avoids the overhead of deep-copying the entire state on every
        viewer poll while still preventing mutation of shared portfolio data.
        """
        state = self._latest_states.get(symbol)
        if state is None:
            return None
        import copy

        try:
            snapshot = dict(state)
            # Only deep-copy the portfolio (has mutable Position objects)
            if "portfolio" in snapshot:
                snapshot["portfolio"] = copy.deepcopy(snapshot["portfolio"])
            return snapshot
        except Exception:
            return copy.deepcopy(state)

    def get_all_latest_states(self) -> dict[str, dict]:
        """All symbol states for initial WS sync."""
        return dict(self._latest_states)

    def get_active_symbols(self) -> list[str]:
        return list(self._active_symbols)

    @property
    def generation(self) -> int:
        return self._generation

    async def wait_for_update(self, known_gen: int, timeout: float = 5.0) -> int:
        """Block until generation advances past known_gen. Returns new generation."""
        async with self._condition:
            try:
                await asyncio.wait_for(
                    self._condition.wait_for(lambda: self._generation > known_gen),
                    timeout=timeout,
                )
            except asyncio.TimeoutError:
                pass
            return self._generation

    def get_history(self, symbol: str) -> list[OHLC]:
        """Get seeded history for a symbol."""
        session = self._session_service.get_or_create_session(symbol)
        if session:
            return list(session.data)
        return []

    def get_depth(self, symbol: str) -> OrderBook | None:
        d = self._current_depths.get(symbol)
        return d["book"] if d else None

    # ------------------------------------------------------------------
    # History seeding
    # ------------------------------------------------------------------

    async def _seed_history(self) -> None:
        for i, sym in enumerate(self._active_symbols):
            if i > 0:
                await asyncio.sleep(1.0)
            try:
                history = await self._market_data.fetch_history(
                    sym,
                    settings.STREAM_INTERVAL,
                    500,
                )

                # Fallback for MCX options: broker API returns empty, load closed candles from DB
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

                    # Build initial state from last candle (skip full pipeline / LLM during seed)
                    if len(history) >= 1:
                        try:
                            last_candle = history[-1]
                            from app.infrastructure.serialization.schemas import (
                                ohlc_to_dto,
                            )

                            self._latest_states[sym] = {
                                "tick": ohlc_to_dto(last_candle),
                                "ltp": last_candle.close,
                                "_symbol": sym,
                                "status": "seeded",
                            }
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

    # ------------------------------------------------------------------
    # Mid-Trade Recovery (Gap #8)
    # ------------------------------------------------------------------

    async def _recover_open_positions(self) -> None:
        """Recover open positions from DB on startup to survive crashes.

        Loads all open positions from the open_positions table and restores
        them to the TradeManager so the engine can resume managing them
        without losing position context.

        Filters by current exchange — only recovers positions belonging to
        the active exchange (NSE or MCX) to prevent cross-exchange contamination.
        """
        storage = self._session_service._storage
        if not storage:
            logger.info("Engine: no storage available — skipping position recovery")
            return

        try:
            open_positions = storage.load_open_positions()
            if not open_positions:
                logger.info("Engine: no open positions to recover")
                return

            # Exchange-aware filtering
            registry = getattr(self._graph, "symbol_registry", None)
            current_exchange = getattr(self._graph.exchange_config, "exchange", "MCX")

            recovered = 0
            skipped = 0
            for pos_data in open_positions:
                symbol = pos_data.get("symbol", "")
                if not symbol:
                    continue

                # Skip positions from other exchanges
                if registry and registry.exchange_for(symbol) != current_exchange:
                    skipped += 1
                    logger.debug(
                        "Engine: skipping %s position recovery (current=%s): %s",
                        registry.exchange_for(symbol),
                        current_exchange,
                        symbol,
                    )
                    continue

                # Add symbol to active list if not already there
                if symbol not in self._active_symbols:
                    self._active_symbols.append(symbol)
                    self._current_depths[symbol] = {"book": None}
                    self._last_process_times[symbol] = 0.0
                    self._prev_oi_values[symbol] = 0
                    self._candle_aggregator.initialize_symbol(symbol)

                # Restore position to the session's portfolio
                try:
                    session = self._session_service.get_or_create_session(symbol)
                    position = session.portfolio.recover_position(pos_data)
                    if position:
                        # Register with TradeManager so overseer and lifecycle can manage it
                        from app.domain.trading.models.enums import Side
                        from app.domain.trading.models.entities import SignalType

                        side_str = (
                            "LONG"
                            if str(pos_data.get("side", "")).upper() == "LONG"
                            else "SHORT"
                        )
                        sig_type = (
                            SignalType.BUY if side_str == "LONG" else SignalType.SELL
                        )

                        # Build a minimal signal for registration
                        from app.domain.trading.models.entities import (
                            Signal as _Sig,
                            Source as _Src,
                        )
                        from decimal import Decimal

                        _ep = Decimal(str(pos_data.get("entry_price", 0)))
                        _sl = Decimal(str(pos_data.get("stop_loss", 0)))
                        _tp = Decimal(str(pos_data.get("take_profit", 0)))

                        recovered_signal = _Sig(
                            type=sig_type,
                            price=_ep,
                            reason="recovered_from_db",
                            source=_Src.LLM,
                            stop_loss=_sl,
                            take_profit=_tp,
                        )

                        self._session_service._lifecycle_handler.register_position(
                            symbol, position, recovered_signal
                        )

                        logger.info(
                            "Engine: recovered position %s for %s (side=%s, entry=%.2f, SL=%.2f, TP=%.2f) — registered with TradeManager",
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

    def _load_candles_from_db(self, symbol: str, limit: int = 500) -> list[OHLC]:
        """Load closed candles from SQLite.

        Uses a dict keyed by timestamp to deduplicate — handles old DB rows written
        per-tick before the candle-close-only write strategy was introduced.
        Rows are ordered ASC by time from query_ticks, so iterating keeps the last
        (most complete) row for each candle period.
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
                    continue
            # Explicit sort — ISO 8601 strings sort lexicographically = chronologically,
            # but guards against mixed timezone formats in older DB rows.
            return sorted(seen.values(), key=lambda x: x.time)[-limit:]
        except Exception:
            logger.debug(
                "Engine: failed to load candles from DB for %s", symbol, exc_info=True
            )
            return []

    # ------------------------------------------------------------------
    # Main tick loop
    # ------------------------------------------------------------------

    async def _tick_loop_forever(self) -> None:
        """Retry _tick_loop on stale/disconnect — keeps engine alive."""
        while self._running:
            await self._tick_loop()
            if self._running:
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
                if not self._running:
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
                    self._candle_aggregator.initialize_symbol(pkt_symbol)
                    self._current_depths[pkt_symbol] = {"book": None}
                    self._last_process_times[pkt_symbol] = 0.0

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

                # OI tracking
                prev_oi = self._prev_oi_values.get(pkt_symbol, 0)
                oi_change = oi - prev_oi if prev_oi > 0 else 0
                self._prev_oi_values[pkt_symbol] = oi
                oi_data = (
                    {
                        "oi": oi,
                        "oi_change": oi_change,
                        "oi_trend": "RISING"
                        if oi_change > 0
                        else ("FALLING" if oi_change < 0 else "FLAT"),
                    }
                    if oi > 0
                    else None
                )

                cum_buy = int(pkt.get("total_buy_qty", 0))
                cum_sell = int(pkt.get("total_sell_qty", 0))

                # 5-level depth from packet
                pkt_bids = pkt.get("depth_bids", [])
                pkt_asks = pkt.get("depth_asks", [])
                if pkt_bids or pkt_asks:
                    current_book = self._current_depths[pkt_symbol].get("book")
                    is_shallow = (
                        current_book is None
                        or len(current_book.bids) < 10
                        or len(current_book.asks) < 10
                    )

                    if is_shallow:
                        self._current_depths[pkt_symbol]["book"] = OrderBook(
                            bids=tuple(
                                OrderBookLevel(
                                    price=float(b.get("price", 0)),
                                    quantity=float(b.get("qty", 0)),
                                )
                                for b in pkt_bids
                            ),
                            asks=tuple(
                                OrderBookLevel(
                                    price=float(a.get("price", 0)),
                                    quantity=float(a.get("qty", 0)),
                                )
                                for a in pkt_asks
                            ),
                        )

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

                # Candle aggregation (delegated to CandleAggregator)
                tick = self._candle_aggregator.aggregate(
                    pkt_symbol,
                    now,
                    ltp,
                    vol,
                    cum_buy,
                    cum_sell,
                    oi,
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
                    await self._notify_viewers()
                    continue

                self._last_process_times[pkt_symbol] = now_time

                # Full process_tick
                try:
                    state = await asyncio.to_thread(
                        self._session_service.process_tick,
                        pkt_symbol,
                        tick,
                        self._current_depths[pkt_symbol]["book"],
                        oi_data=oi_data,
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

                    # Range bar builder (visualization only — no trading logic)
                    if pkt_symbol not in self._range_builders:
                        rb = RangeBarBuilder(
                            range_size=self._range_default_size,
                        )
                        self._range_builders[pkt_symbol] = rb
                        # Backfill from historical candles
                        self._backfill_range_bars(rb, pkt_symbol)
                    rb = self._range_builders[pkt_symbol]
                    rb.on_tick(
                        ltp=float(ltp),
                        timestamp=str(now),
                        buy_vol=float(tick.taker_buy_volume),
                        sell_vol=max(
                            0.0, float(tick.volume) - float(tick.taker_buy_volume)
                        ),
                    )
                    state["rangeBars"] = rb.to_dict()

                    self._latest_states[pkt_symbol] = state
                    await self._notify_viewers()
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
        msg: dict = {
            "tick": ohlc_to_dto(tick),
            "ltp": ltp,
            "oi": oi,
            "_symbol": symbol,
            "depth": _depth_to_dto(self._current_depths.get(symbol, {}).get("book")),
        }
        try:
            session = self._session_service.get_or_create_session(symbol)
            if session:
                if session.last_ai_analysis:
                    msg["genAIAnalysis"] = self._session_service._camel_case_ai(
                        session.last_ai_analysis
                    )
                if session.last_amt:
                    msg["amt"] = session.last_amt
                if hasattr(session, "_agent_decision") and session._agent_decision:
                    ad = session._agent_decision
                    msg["agentDecision"] = {
                        "direction": ad.direction,
                        "probability": ad.probability,
                        "regime": ad.regime,
                        "timing": ad.timing,
                        "sizeFraction": ad.size_fraction,
                        "slAdjust": ad.sl_adjust,
                        "tpAdjust": ad.tp_adjust,
                        "latencyUs": ad.latency_us,
                        "rationale": ad.rationale,
                    }
        except Exception:
            logger.debug("Exception handled silently", exc_info=True)
        # Merge into existing latest state (don't overwrite full process_tick fields)
        prev = self._latest_states.get(symbol, {})
        prev.update(msg)
        self._latest_states[symbol] = prev

    # ------------------------------------------------------------------
    # Viewer notification
    # ------------------------------------------------------------------

    async def _notify_viewers(self, force: bool = False) -> None:
        now = asyncio.get_event_loop().time()
        if not force and now - self._last_notify_time < 0.15:  # 150ms throttle
            if not self._notify_scheduled:
                self._notify_scheduled = True
                self._notify_task = asyncio.create_task(self._delayed_notify())
            return

        self._last_notify_time = now
        self._notify_scheduled = False
        async with self._condition:
            self._generation += 1
            self._condition.notify_all()

    async def _delayed_notify(self) -> None:
        await asyncio.sleep(0.15)
        await self._notify_viewers(force=True)

    def _backfill_range_bars(self, rb: RangeBarBuilder, symbol: str) -> None:
        """Backfill range bars from historical candle data.

        Generates synthetic ticks from each historical candle's OHLC
        so the range bar builder has initial data.
        """
        try:
            state = self._latest_states.get(symbol)
            if not state:
                return
            data = state.get("data", [])
            if not data:
                return

            # Process last 200 candles to seed range bars
            for candle in data[-200:]:
                ts = str(candle.get("time", ""))
                o = float(candle.get("open", 0))
                h = float(candle.get("high", 0))
                l = float(candle.get("low", 0))
                c = float(candle.get("close", 0))
                v = float(candle.get("volume", 0))
                tb = float(candle.get("takerBuyVolume", v / 2))

                if o <= 0 or h <= 0 or l <= 0 or c <= 0:
                    continue

                # Generate synthetic ticks: open → low → high → close
                # This ensures the range bar builder sees the full candle range
                ticks = [o]
                if l < o:
                    ticks.append(l)
                if h > o:
                    ticks.append(h)
                ticks.append(c)

                vol_per_tick = v / len(ticks) if ticks else 0
                buy_per_tick = tb / len(ticks) if ticks else 0
                sell_per_tick = (v - tb) / len(ticks) if ticks else 0

                for tick_price in ticks:
                    rb.on_tick(
                        ltp=tick_price,
                        timestamp=ts,
                        buy_vol=buy_per_tick,
                        sell_vol=sell_per_tick,
                    )
        except Exception:
            pass  # Non-critical
