"""TradingEngine — runs independently of frontend WebSocket connections.

Extracts all trading logic (Dhan streaming, candle aggregation, process_tick,
footprint accumulation, OI tracking, Greeks refresh) from gameloop.py so that:
  1. Backend starts trading on server startup (lifespan)
  2. Frontend WS is a read-only viewer of engine state
  3. Frontend disconnect does NOT affect trading
"""

from __future__ import annotations

import asyncio
import copy
import gc
import logging
import math
import time
from datetime import datetime, timezone, timedelta
from typing import TYPE_CHECKING

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
_STALE_RECONNECT_SECS = 60.0


class SymbolCircuitBreaker:
    """Per-symbol circuit breaker — isolates bad symbols from crashing the stream."""

    def __init__(self, max_failures: int = 5, cooldown_secs: float = 60):
        self._failures: dict[str, int] = {}
        self._open_until: dict[str, float] = {}
        self._max = max_failures
        self._cooldown = cooldown_secs

    def record_failure(self, symbol: str) -> None:
        self._failures[symbol] = self._failures.get(symbol, 0) + 1
        if self._failures[symbol] >= self._max:
            self._open_until[symbol] = time.time() + self._cooldown
            logger.warning("Circuit OPEN for %s (%d failures, cooldown %ds)",
                           symbol, self._failures[symbol], self._cooldown)

    def record_success(self, symbol: str) -> None:
        self._failures.pop(symbol, None)
        self._open_until.pop(symbol, None)

    def is_open(self, symbol: str) -> bool:
        deadline = self._open_until.get(symbol, 0)
        if deadline and time.time() < deadline:
            return True
        if deadline:
            self._open_until.pop(symbol, None)
            self._failures[symbol] = self._max - 1
        return False


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
        self._last_greeks_times: dict[str, float] = {}
        self._prev_oi_values: dict[str, int] = {}
        self._tick_counts: dict[str, int] = {}
        self._last_tick_times: dict[str, float] = {}

        self._circuit_breaker = SymbolCircuitBreaker()
        self._interval_secs = _interval_to_seconds(settings.STREAM_INTERVAL)

        # Tasks
        self._stream_task: asyncio.Task | None = None
        self._depth_task: asyncio.Task | None = None
        self._running = False

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

        # Seed historical data
        await self._seed_history()
        # Load initial Greeks
        await self._load_greeks()

        # Start streaming tasks
        self._stream_task = asyncio.create_task(self._tick_loop_forever())
        self._depth_task = asyncio.create_task(self._depth_20_loop())

        logger.info("Trading engine started for %d symbols: %s",
                     len(self._active_symbols), self._active_symbols)

    async def stop(self) -> None:
        """Graceful shutdown."""
        self._running = False
        notify_task = getattr(self, '_notify_task', None)
        for task in (self._stream_task, self._depth_task, notify_task):
            if task and not task.done():
                task.cancel()
        tasks = [t for t in (self._stream_task, self._depth_task, notify_task) if t]
        if tasks:
            await asyncio.gather(*tasks, return_exceptions=True)
        logger.info("Trading engine stopped.")

    def get_latest_state(self, symbol: str) -> dict | None:
        """Read-only access for WS viewers. Returns a snapshot (deep copy)."""
        state = self._latest_states.get(symbol)
        if state is None:
            return None
        import copy
        try:
            return copy.deepcopy(state)
        except Exception:
            return dict(state)

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
                if history:
                    session = self._session_service.get_or_create_session(sym)
                    if len(session.data) < 10:
                        session.data = history
                        logger.info("Engine: seeded %d candles for %s", len(history), sym)

                    # Run initial process_tick for AMT analysis
                    if len(history) >= 20:
                        try:
                            last_candle = history[-1]
                            state = await asyncio.to_thread(
                                self._session_service.process_tick, sym, last_candle, None,
                            )
                            from app.infrastructure.serialization.schemas import ohlc_to_dto
                            state["tick"] = ohlc_to_dto(last_candle)
                            state["ltp"] = last_candle.close
                            state["_symbol"] = sym
                            self._latest_states[sym] = state
                            logger.info("Engine: initial process_tick done for %s", sym)
                        except Exception:
                            logger.debug("Engine: initial process_tick failed for %s", sym, exc_info=True)
            except Exception:
                logger.warning("Engine: history fetch failed for %s", sym, exc_info=True)

    async def _load_greeks(self) -> None:
        for sym in self._active_symbols:
            try:
                greeks = self._market_data.get_greeks(sym)
                if greeks:
                    session = self._session_service.get_or_create_session(sym)
                    session._greeks = greeks
                    self._last_greeks_times[sym] = asyncio.get_event_loop().time()
                    logger.info("Engine: Greeks loaded for %s", sym)
            except Exception:
                logger.debug("Engine: Greeks fetch failed for %s", sym, exc_info=True)

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
        last_stale_check = time.time()
        last_any_tick_time = time.time()
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

                # Stale-data watchdog — if no ticks for too long, force a
                # reconnect inside _stream_with_reconnect (don't break outer loop).
                now_stale = time.time()
                if now_stale - last_stale_check > 15:
                    last_stale_check = now_stale
                    if now_stale - last_any_tick_time > _STALE_RECONNECT_SECS:
                        logger.warning("Engine: STALE — no ticks for %.0fs, reconnecting",
                                       now_stale - last_any_tick_time)
                        # Reset timer so the fresh connection isn't immediately killed
                        last_any_tick_time = time.time()
                        break

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
                last_any_tick_time = self._last_tick_times[pkt_symbol]

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

                # Greeks refresh every 60s
                last_greeks = self._last_greeks_times.get(pkt_symbol, 0.0)
                if now_time - last_greeks > 60:
                    try:
                        greeks = self._market_data.get_greeks(pkt_symbol)
                        if greeks:
                            sess = self._session_service.get_or_create_session(pkt_symbol)
                            sess._greeks = greeks
                            self._last_greeks_times[pkt_symbol] = now_time
                    except Exception:
                        pass

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
            if candle_vol > 5000:
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
            if tick_buy > 5000:
                tick_buy = 0
            if tick_sell > 5000:
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
    # Depth-20 background stream
    # ------------------------------------------------------------------

    async def _depth_20_loop(self) -> None:
        if not hasattr(self._market_data, 'stream_depth_20'):
            return
        if settings.DEFAULT_EXCHANGE not in ("NSE", "NFO", "BSE"):
            return
        while self._running:
            try:
                logger.info("Engine: depth-20 starting for %d symbols", len(self._active_symbols))
                async for md in self._market_data.stream_depth_20(self._active_symbols):
                    if not self._running:
                        break
                    sym = getattr(md, 'symbol', self._active_symbols[0] if self._active_symbols else "")
                    if sym not in self._current_depths:
                        continue
                    levels = getattr(md, 'levels', [])
                    side = getattr(md, 'side', '')
                    if not levels:
                        continue
                    book = self._current_depths[sym].get("book")
                    new_levels = tuple(
                        OrderBookLevel(price=float(lv.price), quantity=float(lv.quantity))
                        for lv in levels
                    )
                    if side == "bid":
                        self._current_depths[sym]["book"] = OrderBook(
                            bids=new_levels,
                            asks=book.asks if book else (),
                        )
                    elif side == "ask":
                        self._current_depths[sym]["book"] = OrderBook(
                            bids=book.bids if book else (),
                            asks=new_levels,
                        )
                logger.info("Engine: depth-20 stream ended, reconnecting...")
            except asyncio.CancelledError:
                raise
            except Exception:
                logger.warning("Engine: depth-20 disconnected, retrying in 10s", exc_info=True)
            await asyncio.sleep(10)

    # ------------------------------------------------------------------
    # Stream with reconnect
    # ------------------------------------------------------------------

    async def _stream_with_reconnect(self, connect_state: list[float]):
        consecutive_failures = 0
        while self._running:
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
