"""TradingEngine — runs independently of frontend WebSocket connections.

Extracts all trading logic (Dhan streaming, candle aggregation, process_tick,
footprint accumulation, OI tracking, Greeks refresh) from gameloop.py so that:
  1. Backend starts trading on server startup (lifespan)
  2. Frontend WS is a read-only viewer of engine state
  3. Frontend disconnect does NOT affect trading
"""

from __future__ import annotations

import asyncio
import gc
import logging
import math
import time
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

from shared.resilience import PerEntityCircuitBreaker
from app.config import settings
from app.application.utils import is_market_open
from app.domain.trading.models.value_objects import OHLC, OrderBook, OrderBookLevel
from app.domain.fabio_ai.services.footprint_analyzer import TickFootprintAccumulator

if TYPE_CHECKING:
    from app.api.dependencies import ServiceGraph

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))

_DHAN_CONNECT_COOLDOWN: float = 5.0
_MAX_STREAM_RETRIES = 10
_GC_INTERVAL_SECS = 1800
_STALE_THRESHOLD_SECS = 60.0
_STALE_RECONNECT_SECS = 300.0  # 5 min — MCX options can be quiet for minutes between ticks


class SymbolCircuitBreaker(PerEntityCircuitBreaker):
    """Backward-compat alias for tests — wraps PerEntityCircuitBreaker with old param names."""

    def __init__(self, max_failures: int = 5, cooldown_secs: float = 60.0) -> None:
        super().__init__(failure_threshold=max_failures, recovery_timeout=cooldown_secs)


def _new_candle_state() -> dict:
    return {
        "start": None, "open": 0, "high": 0, "low": 0, "close": 0,
        "volume": 0, "buy_volume": 0, "oi": 0, "vwap_num": 0, "vwap_den": 0,
        "prev_cum_vol": -1, "candle_vol": 0,
        "prev_cum_buy": -1, "prev_cum_sell": -1,
        "candle_buy_vol": 0, "candle_sell_vol": 0,
    }


def _interval_to_seconds(interval: str) -> int:
    unit = interval[-1]
    val = int(interval[:-1])
    if unit == "m":
        return val * 60
    elif unit == "h":
        return val * 3600
    elif unit == "d":
        return val * 86400
    return val * 60


def _validate_tick(tick: OHLC) -> str | None:
    for name, val in [("open", tick.open), ("high", tick.high),
                      ("low", tick.low), ("close", tick.close)]:
        if math.isnan(val) or math.isinf(val) or val <= 0:
            return f"Invalid tick: {name}={val}"
    if math.isnan(tick.volume) or math.isinf(tick.volume) or tick.volume < 0:
        return f"Invalid tick: volume={tick.volume}"
    if tick.high < tick.low:
        return f"Invalid tick: high ({tick.high}) < low ({tick.low})"
    return None


def _depth_to_dto(book: OrderBook | None) -> dict | None:
    if not book:
        return None
    return {
        "bids": [{"price": float(l.price), "quantity": float(l.quantity)} for l in book.bids[:20]],
        "asks": [{"price": float(l.price), "quantity": float(l.quantity)} for l in book.asks[:20]],
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
        self._candle_states: dict[str, dict] = {}
        self._current_depths: dict[str, dict] = {}
        self._fp_accumulators: dict[str, TickFootprintAccumulator] = {}
        self._last_process_times: dict[str, float] = {}
        self._prev_oi_values: dict[str, int] = {}
        self._tick_counts: dict[str, int] = {}
        self._last_tick_times: dict[str, float] = {}

        self._circuit_breaker = PerEntityCircuitBreaker(
            failure_threshold=5, 
            recovery_timeout=_STALE_RECONNECT_SECS
        )
        self._interval_secs = _interval_to_seconds(settings.STREAM_INTERVAL)

        # Tasks
        self._stream_task: asyncio.Task | None = None
        self._depth_task: asyncio.Task | None = None
        self._watchdog_task: asyncio.Task | None = None
        self._stale_watchdog_task: asyncio.Task | None = None
        self._running = False
        self._last_any_tick_time: float = time.time()

        # Polling fallback — set True by stale watchdog when WS gives no data
        # (e.g. Dhan WS doesn't stream MCX OPTFUT binary frames)
        self._polling_mode: bool = False
        self._engine_start_time: float = 0.0

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    async def start(self) -> None:
        """Seed history and begin streaming. Called from lifespan."""
        if self._running:
            return
        self._running = True

        # Initialize per-symbol state
        for sym in self._active_symbols:
            self._candle_states[sym] = _new_candle_state()
            self._current_depths[sym] = {"book": None}
            self._fp_accumulators[sym] = TickFootprintAccumulator()
            self._last_process_times[sym] = 0.0
            self._tick_counts[sym] = 0
            self._last_tick_times[sym] = time.time()

        self._engine_start_time = time.time()

        # Seed historical data
        await self._seed_history()

        # Start streaming tasks
        self._stream_task = asyncio.create_task(self._tick_loop_forever())
        self._watchdog_task = asyncio.create_task(self._sl_watchdog_loop())
        self._stale_watchdog_task = asyncio.create_task(self._stale_stream_watchdog())

        logger.info("Trading engine started for %d symbols: %s",
                     len(self._active_symbols), self._active_symbols)

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._running = False
        notify_task = getattr(self, '_notify_task', None)
        for task in (self._stream_task, self._watchdog_task, self._stale_watchdog_task, notify_task):
            if task and not task.done():
                task.cancel()
        tasks = [t for t in (self._stream_task, self._watchdog_task, self._stale_watchdog_task, notify_task) if t]
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
        session = self._session_service._sessions.get(symbol)
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
                    sym, settings.STREAM_INTERVAL, 500,
                )

                # Fallback for MCX options: broker API returns empty, load closed candles from DB
                if not history:
                    history = self._load_candles_from_db(sym, limit=500)
                    if history:
                        logger.info("Engine: seeded %d candles for %s from local DB", len(history), sym)

                if history:
                    session = self._session_service.get_or_create_session(sym)
                    if len(session.data) < 10:
                        session.data = history
                        logger.info("Engine: seeded %d candles for %s", len(history), sym)

                    # Build initial state from last candle (skip full pipeline / LLM during seed)
                    if len(history) >= 1:
                        try:
                            last_candle = history[-1]
                            from app.infrastructure.serialization.schemas import ohlc_to_dto
                            self._latest_states[sym] = {
                                "tick": ohlc_to_dto(last_candle),
                                "ltp": last_candle.close,
                                "_symbol": sym,
                                "status": "seeded",
                            }
                            logger.info("Engine: initial seed done for %s (skipped LLM)", sym)
                        except Exception:
                            logger.debug("Engine: initial seed failed for %s", sym, exc_info=True)
            except Exception:
                logger.warning("Engine: history fetch failed for %s", sym, exc_info=True)

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
                        time=t, open=float(row["open"] or 0),
                        high=float(row["high"] or 0), low=float(row["low"] or 0),
                        close=float(row["close"] or 0), volume=float(row["volume"] or 0),
                        delta=float(row["delta"] or 0),
                    )
                except Exception:
                    continue
            # Explicit sort — ISO 8601 strings sort lexicographically = chronologically,
            # but guards against mixed timezone formats in older DB rows.
            return sorted(seen.values(), key=lambda x: x.time)[-limit:]
        except Exception:
            logger.debug("Engine: failed to load candles from DB for %s", symbol, exc_info=True)
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
        from app.infrastructure.serialization.schemas import ohlc_to_dto, footprint_to_dto

        last_gc_time = time.time()
        self._last_any_tick_time = time.time()
        dhan_connect_state = [0.0]

        try:
            logger.info("Engine: streaming live ticks for %d symbols", len(self._active_symbols))
            async for pkt in self._stream_with_reconnect(dhan_connect_state):
                if not self._running:
                    break

                if pkt.get("_stream_dead"):
                    logger.error("Engine: market data connection lost after retries")
                    break

                if not is_market_open(exchange=settings.DEFAULT_EXCHANGE):
                    continue

                # Demux
                pkt_symbol = pkt.get("symbol", self._active_symbols[0] if self._active_symbols else "")
                if pkt_symbol not in self._candle_states:
                    self._candle_states[pkt_symbol] = _new_candle_state()
                    self._current_depths[pkt_symbol] = {"book": None}
                    self._last_process_times[pkt_symbol] = 0.0
                    self._fp_accumulators[pkt_symbol] = TickFootprintAccumulator()
                    self._tick_counts[pkt_symbol] = 0

                if self._circuit_breaker.is_open(pkt_symbol):
                    continue

                self._last_tick_times[pkt_symbol] = time.time()
                self._last_any_tick_time = self._last_tick_times[pkt_symbol]

                self._tick_counts[pkt_symbol] = self._tick_counts.get(pkt_symbol, 0) + 1
                if self._tick_counts[pkt_symbol] == 1:
                    logger.info("Engine: first live tick for %s: ltp=%s", pkt_symbol, pkt.get("ltp"))

                ltp = float(pkt.get("ltp", 0))
                if ltp <= 0:
                    continue

                ts = pkt.get("timestamp")
                if isinstance(ts, str):
                    now = datetime.fromisoformat(ts.replace("Z", "+00:00")).astimezone(IST)
                else:
                    now = datetime.now(IST)

                vol = int(pkt.get("volume", 0))
                ltq = int(pkt.get("ltq", 0))
                oi = int(pkt.get("oi", 0))

                if math.isnan(ltp) or math.isinf(ltp) or ltp <= 0:
                    continue
                if vol < 0 or math.isnan(vol) or math.isinf(vol):
                    continue

                # OI tracking
                prev_oi = self._prev_oi_values.get(pkt_symbol, 0)
                oi_change = oi - prev_oi if prev_oi > 0 else 0
                self._prev_oi_values[pkt_symbol] = oi
                oi_data = {"oi": oi, "oi_change": oi_change, "oi_trend": "RISING" if oi_change > 0 else ("FALLING" if oi_change < 0 else "FLAT")} if oi > 0 else None

                cum_buy = int(pkt.get("total_buy_qty", 0))
                cum_sell = int(pkt.get("total_sell_qty", 0))

                # 5-level depth from packet
                pkt_bids = pkt.get("depth_bids", [])
                pkt_asks = pkt.get("depth_asks", [])
                if pkt_bids or pkt_asks:
                    # Fabio's Depth 20 Fix: Only overwrite if existing book is empty or shallow.
                    # This prevents the 100ms-throttled 5-level data from the tick stream
                    # from nuking the high-resolution 20-level data from the background stream.
                    current_book = self._current_depths[pkt_symbol].get("book")
                    is_shallow = (
                        current_book is None or 
                        len(current_book.bids) < 10 or 
                        len(current_book.asks) < 10
                    )
                    
                    if is_shallow:
                        self._current_depths[pkt_symbol]["book"] = OrderBook(
                            bids=tuple(
                                OrderBookLevel(price=float(b.get("price", 0)), quantity=float(b.get("qty", 0)))
                                for b in pkt_bids
                            ),
                            asks=tuple(
                                OrderBookLevel(price=float(a.get("price", 0)), quantity=float(a.get("qty", 0)))
                                for a in pkt_asks
                            ),
                        )

                # Footprint accumulator
                best_bid = pkt_bids[0].get("price", 0) if pkt_bids else 0.0
                best_ask = pkt_asks[0].get("price", 0) if pkt_asks else 0.0
                if ltq > 0:
                    candle_t = self._candle_start(now)
                    self._fp_accumulators[pkt_symbol].on_tick(
                        ltp, ltq, float(best_bid), float(best_ask),
                        candle_t.isoformat() if candle_t else "",
                    )

                # Candle aggregation
                tick = self._aggregate_candle(pkt_symbol, now, ltp, vol, cum_buy, cum_sell, oi)
                if tick is None:
                    continue

                error = _validate_tick(tick)
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
                        self._session_service.process_tick, pkt_symbol, tick,
                        self._current_depths[pkt_symbol]["book"],
                        oi_data=oi_data,
                    )
                    state["tick"] = ohlc_to_dto(tick)
                    state["ltp"] = ltp
                    state["oi"] = oi
                    state["_symbol"] = pkt_symbol
                    state["depth"] = _depth_to_dto(self._current_depths[pkt_symbol]["book"])

                    # Overlay footprint
                    session = self._session_service._sessions.get(pkt_symbol)
                    if session:
                        real_fp = self._fp_accumulators[pkt_symbol].get_all()
                        if real_fp:
                            session.last_footprint = {k: footprint_to_dto(v) for k, v in real_fp.items()}
                            state["footprint"] = session.last_footprint

                    self._latest_states[pkt_symbol] = state
                    await self._notify_viewers()
                    self._circuit_breaker.record_success(pkt_symbol)
                except Exception:
                    self._circuit_breaker.record_failure(pkt_symbol)
                    logger.error("Engine: tick processing error for %s", pkt_symbol, exc_info=True)

                # Periodic GC
                now_wall = time.time()
                if now_wall - last_gc_time >= _GC_INTERVAL_SECS:
                    collected = await asyncio.to_thread(gc.collect, 0)
                    logger.info("Engine: GC collected %d objects", collected)
                    last_gc_time = now_wall

        except asyncio.CancelledError:
            logger.info("Engine: tick loop cancelled")
        except Exception:
            logger.error("Engine: tick loop crashed", exc_info=True)

    # ------------------------------------------------------------------
    # Candle aggregation
    # ------------------------------------------------------------------

    def _candle_start(self, ts: datetime) -> datetime:
        epoch = int(ts.timestamp())
        floored = epoch - (epoch % self._interval_secs)
        return datetime.fromtimestamp(floored, tz=IST)

    def _aggregate_candle(
        self, symbol: str, now: datetime, ltp: float,
        vol: int, cum_buy: int, cum_sell: int, oi: int,
    ) -> OHLC | None:
        cs = self._candle_states[symbol]
        c_start = self._candle_start(now)

        # Volume from cumulative
        if cs["prev_cum_vol"] < 0:
            cs["prev_cum_vol"] = vol
            candle_vol = 0
        elif vol < cs["prev_cum_vol"]:
            cs["prev_cum_vol"] = vol
            candle_vol = 0
        else:
            candle_vol = vol - cs["prev_cum_vol"]
            # Contextual spike cap: >5% of cumulative likely means session reset
            vol_cap = max(10000, cs["prev_cum_vol"] * 0.05) if cs["prev_cum_vol"] > 0 else 10000
            if candle_vol > vol_cap:
                cs["prev_cum_vol"] = vol
                candle_vol = 0
            else:
                cs["prev_cum_vol"] = vol

        # Buy/sell from cumulative
        if cs["prev_cum_buy"] < 0:
            cs["prev_cum_buy"] = cum_buy
            cs["prev_cum_sell"] = cum_sell
            tick_buy = 0
            tick_sell = 0
        elif cum_buy < cs["prev_cum_buy"] or cum_sell < cs["prev_cum_sell"]:
            cs["prev_cum_buy"] = cum_buy
            cs["prev_cum_sell"] = cum_sell
            tick_buy = 0
            tick_sell = 0
        else:
            tick_buy = cum_buy - cs["prev_cum_buy"]
            tick_sell = cum_sell - cs["prev_cum_sell"]
            # Contextual cap: >5% of cumulative = likely session reset
            buy_sell_total = max(cs["prev_cum_buy"], 1) + max(cs["prev_cum_sell"], 1)
            bs_cap = max(10000, buy_sell_total * 0.05)
            if tick_buy > bs_cap:
                tick_buy = 0
            if tick_sell > bs_cap:
                tick_sell = 0
            cs["prev_cum_buy"] = cum_buy
            cs["prev_cum_sell"] = cum_sell

        if cs["start"] is None or c_start != cs["start"]:
            cs["start"] = c_start
            cs["open"] = ltp
            cs["high"] = ltp
            cs["low"] = ltp
            cs["close"] = ltp
            cs["candle_vol"] = candle_vol
            cs["candle_buy_vol"] = tick_buy
            cs["candle_sell_vol"] = tick_sell
            cs["buy_volume"] = 0
            cs["oi"] = oi
            cs["vwap_num"] = ltp * candle_vol
            cs["vwap_den"] = candle_vol
        else:
            cs["high"] = max(cs["high"], ltp)
            cs["low"] = min(cs["low"], ltp)
            cs["close"] = ltp
            cs["candle_vol"] += candle_vol
            cs["candle_buy_vol"] += tick_buy
            cs["candle_sell_vol"] += tick_sell
            cs["oi"] = oi
            cs["vwap_num"] += ltp * candle_vol
            cs["vwap_den"] += candle_vol

        vwap = cs["vwap_num"] / cs["vwap_den"] if cs["vwap_den"] > 0 else ltp

        cv = cs["candle_vol"]
        cbuy = cs["candle_buy_vol"]
        csell = cs["candle_sell_vol"]
        if cbuy > 0 or csell > 0:
            delta = float(cbuy - csell)
            buy_vol = float(cbuy)
        else:
            spread = cs["high"] - cs["low"]
            if spread > 0 and cv > 0:
                body_ratio = (cs["close"] - cs["open"]) / spread
                delta = body_ratio * cv
            else:
                delta = 0.0
            buy_vol = max(0.0, (cv + delta) / 2)

        return OHLC(
            time=cs["start"].isoformat(),
            open=cs["open"],
            high=cs["high"],
            low=cs["low"],
            close=cs["close"],
            volume=float(cv),
            vwap=vwap,
            taker_buy_volume=buy_vol,
            delta=delta,
        )

    # ------------------------------------------------------------------
    # Throttled state update (between full process_tick calls)
    # ------------------------------------------------------------------

    def _update_throttled_state(self, symbol: str, tick: OHLC, ltp: float, oi: int, ohlc_to_dto) -> None:
        """Update latest state with current tick + cached analysis (no process_tick)."""
        msg: dict = {
            "tick": ohlc_to_dto(tick),
            "ltp": ltp,
            "oi": oi,
            "_symbol": symbol,
            "depth": _depth_to_dto(self._current_depths.get(symbol, {}).get("book")),
        }
        try:
            session = self._session_service._sessions.get(symbol)
            if session:
                if session.last_ai_analysis:
                    msg["genAIAnalysis"] = self._session_service._camel_case_ai(session.last_ai_analysis)
                if session.last_amt:
                    msg["amt"] = session.last_amt
                if hasattr(session, '_agent_decision') and session._agent_decision:
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
            pass
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

    # ------------------------------------------------------------------
    # SL Watchdog — independent of tick stream
    # ------------------------------------------------------------------

    async def _sl_watchdog_loop(self) -> None:
        """Independent SL/TP watchdog running every 1 second.

        Protects positions even when the tick stream is disconnected
        (e.g., during WebSocket reconnect, network jitter, or exchange gaps).
        Uses the last known LTP cached in ``_last_tick_times`` and
        ``_latest_states`` to evaluate SL/TP boundaries.
        """
        logger.info("Engine: SL watchdog started")
        while self._running:
            try:
                await asyncio.sleep(1.0)
                for sym in list(self._active_symbols):
                    session = self._session_service._sessions.get(sym)
                    if not session:
                        continue

                    # Get last known LTP from cached state
                    cached_state = self._latest_states.get(sym, {})
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
                                    # Unregister from trade manager
                                    try:
                                        self._session_service._record_position_consistency(
                                            session, sym, context="watchdog_close",
                                        )
                                    except Exception:
                                        pass
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
        logger.info("Engine: SL watchdog stopped")

    # ------------------------------------------------------------------
    # Stale-stream watchdog — independent of tick iteration
    # ------------------------------------------------------------------

    async def _stale_stream_watchdog(self) -> None:
        """Detect hung market data streams and force reconnect or switch to polling.

        Runs independently of the tick loop so it fires even when
        ``async for pkt in stream_full()`` is blocked waiting forever.

        Strategy:
        - If no tick has EVER arrived within _WS_POLL_FALLBACK_SECS of engine start
          and market is open → WS feed is dead (e.g. MCX OPTFUT broker limitation).
          Switch permanently to REST LTP polling.
        - Otherwise, for stale streams (tick gap > _STALE_RECONNECT_SECS), cancel
          the stream task so _stream_with_reconnect triggers a WS reconnect.
        """
        _WS_POLL_FALLBACK_SECS = 60.0   # Give WS 60s to deliver first tick
        logger.info("Engine: stale-stream watchdog started")
        _ever_checked_fallback = False

        while self._running:
            try:
                await asyncio.sleep(15)
                if not is_market_open(exchange=settings.DEFAULT_EXCHANGE):
                    continue

                gap = time.time() - self._last_any_tick_time
                uptime = time.time() - self._engine_start_time

                # --- Polling fallback: switch once if WS never delivers data ---
                if (
                    not _ever_checked_fallback
                    and not self._polling_mode
                    and uptime > _WS_POLL_FALLBACK_SECS
                    and all(self._tick_counts.get(s, 0) == 0 for s in self._active_symbols)
                ):
                    _ever_checked_fallback = True
                    logger.warning(
                        "Engine: WS produced ZERO ticks after %.0fs — "
                        "switching permanently to REST polling fallback (MCX OPTFUT)",
                        uptime,
                    )
                    self._polling_mode = True
                    self._last_any_tick_time = time.time()
                    # Cancel dead WS stream task and await its cleanup
                    if self._stream_task and not self._stream_task.done():
                        self._stream_task.cancel()
                        try:
                            await self._stream_task
                        except (asyncio.CancelledError, Exception):
                            pass
                    # Restart stream task — will immediately enter polling branch
                    if self._running:
                        self._stream_task = asyncio.create_task(self._tick_loop_forever())
                        logger.info("Engine: stream task restarted in REST polling mode")
                    continue

                # --- Normal stale: reconnect WS (stream produced data before) ---
                if not self._polling_mode and gap > _STALE_RECONNECT_SECS:
                    logger.warning(
                        "Engine: STALE — no ticks for %.0fs, cancelling stream task", gap
                    )
                    self._last_any_tick_time = time.time()
                    if self._stream_task and not self._stream_task.done():
                        self._stream_task.cancel()

            except asyncio.CancelledError:
                break
            except Exception:
                logger.error("Stale-stream watchdog error", exc_info=True)
        logger.info("Engine: stale-stream watchdog stopped")


    # ------------------------------------------------------------------
    # Stream with reconnect
    # ------------------------------------------------------------------

    async def _stream_with_reconnect(self, connect_state: list[float]):
        consecutive_failures = 0
        while self._running:
            # -----------------------------------------------------------------
            # Polling fallback path (MCX OPTFUT — WS never sends binary frames)
            # -----------------------------------------------------------------
            if self._polling_mode:
                logger.info("Engine: using REST polling fallback (polling_mode=True)")
                try:
                    async for pkt in self._market_data.stream_poll(
                        self._active_symbols, poll_interval=3.0
                    ):
                        consecutive_failures = 0
                        yield pkt
                    # stream_poll only exits if running=False
                except asyncio.CancelledError:
                    raise
                except Exception as e:
                    logger.warning("Engine: polling error, retrying in 5s: %s", e)
                    await asyncio.sleep(5)
                continue

            # -----------------------------------------------------------------
            # Normal WS streaming path
            # -----------------------------------------------------------------
            now = asyncio.get_event_loop().time()
            since_last = now - connect_state[0]
            if since_last < _DHAN_CONNECT_COOLDOWN:
                await asyncio.sleep(_DHAN_CONNECT_COOLDOWN - since_last)
            connect_state[0] = asyncio.get_event_loop().time()

            try:
                async for pkt in self._market_data.stream_full(self._active_symbols):
                    consecutive_failures = 0
                    yield pkt
                logger.info("Engine: stream ended cleanly, reconnecting...")
            except asyncio.CancelledError:
                raise
            except Exception as e:
                consecutive_failures += 1
                if consecutive_failures >= _MAX_STREAM_RETRIES:
                    logger.error("Engine: stream failed %d times — giving up", consecutive_failures)
                    yield {"_stream_dead": True}
                    return
                wait = min(5 * (2 ** (consecutive_failures - 1)), 60)
                logger.warning("Engine: stream disconnected (attempt %d/%d), retry in %ds: %s",
                               consecutive_failures, _MAX_STREAM_RETRIES, wait, e)
                await asyncio.sleep(wait)
