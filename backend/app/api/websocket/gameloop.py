"""WebSocket game-loop handler.

Server-driven mode: Backend streams ticks from Dhan, processes them,
and pushes state snapshots to the frontend.
"""

from __future__ import annotations

import asyncio
import json
import logging
import math
import traceback

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.domain.trading.models.value_objects import OHLC, OrderBook, OrderBookLevel

router = APIRouter(prefix="/trading", tags=["trading"])
logger = logging.getLogger(__name__)

# Track the active server-driven stream task so we can cancel it on frontend reload
_active_stream_task: asyncio.Task | None = None
# Global cooldown: prevent rapid-fire Dhan WS connections from frontend reconnect loop
_last_dhan_connect_time: float = 0.0
_DHAN_CONNECT_COOLDOWN: float = 5.0  # min seconds between Dhan WS connection attempts


def _validate_tick(tick: OHLC) -> str | None:
    """Return an error string if tick data is invalid, else None."""
    for name, val in [("open", tick.open), ("high", tick.high),
                      ("low", tick.low), ("close", tick.close)]:
        if math.isnan(val) or math.isinf(val) or val <= 0:
            return f"Invalid tick: {name}={val}, must be > 0 and finite"
    if math.isnan(tick.volume) or math.isinf(tick.volume) or tick.volume < 0:
        return f"Invalid tick: volume={tick.volume}, must be >= 0 and finite"
    if tick.high < tick.low:
        return f"Invalid tick: high ({tick.high}) < low ({tick.low})"
    return None


def _parse_tick(tick_raw: dict) -> OHLC:
    """Parse a raw tick dict into an OHLC value object."""
    return OHLC(
        time=tick_raw.get("time", ""),
        open=float(tick_raw.get("open", 0)),
        high=float(tick_raw.get("high", 0)),
        low=float(tick_raw.get("low", 0)),
        close=float(tick_raw.get("close", 0)),
        volume=float(tick_raw.get("volume", 0)),
        vwap=float(tick_raw.get("vwap", 0)),
        taker_buy_volume=float(tick_raw.get("takerBuyVolume", 0)),
        delta=float(tick_raw.get("delta", 0)),
    )


def _parse_order_book(ob_raw: dict | None) -> OrderBook | None:
    """Parse a raw order book dict into an OrderBook value object."""
    if not ob_raw:
        return None
    return OrderBook(
        bids=tuple(
            OrderBookLevel(price=float(b["price"]), quantity=float(b["quantity"]))
            for b in ob_raw.get("bids", [])
        ),
        asks=tuple(
            OrderBookLevel(price=float(a["price"]), quantity=float(a["quantity"]))
            for a in ob_raw.get("asks", [])
        ),
    )


@router.websocket("/ws/gameloop")
async def gameloop_ws(ws: WebSocket):
    await ws.accept()

    from app.api.dependencies import get_service_graph
    graph = get_service_graph()
    session_service = graph.trading_session

    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)

            # --- Server-driven mode: backend streams Dhan data ---
            if "subscribe" in data:
                global _active_stream_task
                symbol = data["subscribe"]
                # Cancel any previous stream to avoid duplicate WS connections
                if _active_stream_task and not _active_stream_task.done():
                    logger.info("Cancelling previous stream before new subscribe")
                    _active_stream_task.cancel()
                    try:
                        await _active_stream_task
                    except (asyncio.CancelledError, Exception):
                        pass
                    # Give Dhan time to release the old connection slot
                    await asyncio.sleep(2.0)
                logger.info("Server-driven mode: subscribing to %s via Dhan", symbol)
                _active_stream_task = asyncio.current_task()
                await _server_driven_loop(ws, graph, session_service, symbol)
                return  # Loop ended (client disconnect or error)

            # --- Client-driven mode (backward compat) ---
            symbol = data.get("symbol", "")

            # Handle bulk history init message
            history_raw = data.get("history")
            if history_raw and isinstance(history_raw, list):
                session = session_service.get_or_create_session(symbol)
                if len(session.data) < 10:
                    candles = []
                    for h in history_raw[-500:]:
                        try:
                            candles.append(_parse_tick(h))
                        except (TypeError, ValueError):
                            continue
                    if candles:
                        session.data = candles
                        logger.info("Seeded %d historical candles for %s", len(candles), symbol)
                await ws.send_json({"status": "history_loaded", "count": len(session.data) if history_raw else 0})
                continue

            # Parse and validate tick
            tick_raw = data.get("tick", {})
            try:
                tick = _parse_tick(tick_raw)
            except (TypeError, ValueError) as e:
                await ws.send_json({"error": f"Invalid tick data: {e}"})
                continue

            error = _validate_tick(tick)
            if error:
                await ws.send_json({"error": error})
                continue

            order_book = _parse_order_book(data.get("orderBook"))

            state = await asyncio.to_thread(
                session_service.process_tick, symbol, tick, order_book
            )
            await ws.send_json(state)

    except WebSocketDisconnect:
        pass
    except Exception:
        traceback.print_exc()
        try:
            await ws.close()
        except Exception:
            pass


async def _server_driven_loop(
    ws: WebSocket, graph, session_service, symbol: str,
) -> None:
    """Server-driven streaming: real-time ticks + depth from Dhan via WebSocket.

    Data flow:
      1. Seed chart with 500 historical candles (fetch_history)
      2. Subscribe to stream_full() → tick-level LTP/OHLC/OI + 5-level depth
      3. Aggregate ticks into candles per STREAM_INTERVAL
      4. Push state snapshots + live tick to frontend on every tick
    """
    from app.config import settings
    from app.application.utils import is_market_open
    from app.infrastructure.serialization.schemas import ohlc_to_dto
    from datetime import datetime, timezone, timedelta

    IST = timezone(timedelta(hours=5, minutes=30))

    market_data = graph.market_data
    active_symbol = graph.active_symbol or symbol

    # Send initial config to frontend
    await ws.send_json({
        "status": "server_mode",
        "symbol": active_symbol,
        "exchange": settings.DEFAULT_EXCHANGE,
        "interval": settings.STREAM_INTERVAL,
    })

    # Seed historical data
    try:
        history = await market_data.fetch_history(
            active_symbol, settings.STREAM_INTERVAL, 500,
        )
        if history:
            session = session_service.get_or_create_session(active_symbol)
            if len(session.data) < 10:
                session.data = history
                logger.info("Server-driven: seeded %d candles for %s", len(history), active_symbol)
            await ws.send_json({
                "status": "history_loaded",
                "symbol": active_symbol,
                "history": [ohlc_to_dto(c) for c in history[-500:]],
                "count": len(history),
            })
        # Run one process_tick on last candle so AMT analysis is available
        # even when market is closed (frontend needs amtAnalysis to render)
        if history and len(history) >= 20:
            try:
                last_candle = history[-1]
                state = await asyncio.to_thread(
                    session_service.process_tick, active_symbol, last_candle, None,
                )
                state["tick"] = ohlc_to_dto(last_candle)
                state["ltp"] = last_candle.close
                await ws.send_json(state)
                logger.info("Server-driven: initial process_tick sent for %s", active_symbol)
            except Exception:
                logger.debug("Server-driven: initial process_tick failed", exc_info=True)
    except Exception:
        logger.warning("Server-driven: history fetch failed", exc_info=True)

    # Fetch Greeks once for the option contract (before streaming starts)
    last_greeks_time: float = 0.0
    try:
        greeks = market_data.get_greeks(active_symbol)
        if greeks:
            session = session_service.get_or_create_session(active_symbol)
            session._greeks = greeks
            last_greeks_time = asyncio.get_event_loop().time()
            logger.info("Greeks loaded: delta=%.3f gamma=%.5f theta=%.2f iv=%.1f%%",
                        greeks["delta"], greeks["gamma"], greeks["theta"], greeks.get("iv", 0))
    except Exception:
        logger.debug("Greeks fetch failed (non-critical)", exc_info=True)

    # --- Shared mutable state for depth & candle aggregation ---
    current_depth: dict = {"book": None}  # latest OrderBook

    # Candle aggregation state — interval in seconds
    _INTERVAL_SECS = _interval_to_seconds(settings.STREAM_INTERVAL)

    def _candle_start(ts: datetime) -> datetime:
        """Floor timestamp to current candle boundary."""
        epoch = int(ts.timestamp())
        floored = epoch - (epoch % _INTERVAL_SECS)
        return datetime.fromtimestamp(floored, tz=IST)

    # Current building candle
    candle_state: dict = {
        "start": None, "open": 0, "high": 0, "low": 0, "close": 0,
        "volume": 0, "buy_volume": 0, "oi": 0, "vwap_num": 0, "vwap_den": 0,
        "prev_cum_vol": -1, "candle_vol": 0,  # -1 = uninitialized (first tick seeds base)
        "prev_cum_buy": -1, "prev_cum_sell": -1,  # cumulative buy/sell qty from Dhan
        "candle_buy_vol": 0, "candle_sell_vol": 0,  # per-candle real buy/sell volume
    }
    last_process_time: float = 0.0  # throttle process_tick to once per second

    # Real tick-level footprint accumulator
    from app.domain.fabio_ai.services.footprint_analyzer import TickFootprintAccumulator
    fp_accumulator = TickFootprintAccumulator()

    # Create a task to listen for client messages (e.g. unsubscribe)
    client_task = asyncio.create_task(_listen_for_client(ws))

    # --- Depth-20 background task (NSE/NFO only) ---
    depth_20_active = {"active": False}

    async def _stream_depth_20():
        """Subscribe to 20-level depth and update current_depth["book"]."""
        if not hasattr(market_data, 'stream_depth_20'):
            return
        if settings.DEFAULT_EXCHANGE not in ("NSE", "NFO", "BSE"):
            return
        try:
            logger.info("Depth-20: starting subscription for %s", active_symbol)
            async for md in market_data.stream_depth_20([active_symbol]):
                levels = getattr(md, 'levels', [])
                side = getattr(md, 'side', '')
                if not levels:
                    continue
                book = current_depth.get("book")
                new_levels = tuple(
                    OrderBookLevel(price=float(lv.price), quantity=float(lv.quantity))
                    for lv in levels
                )
                if side == "bid":
                    current_depth["book"] = OrderBook(
                        bids=new_levels,
                        asks=book.asks if book else (),
                    )
                elif side == "ask":
                    current_depth["book"] = OrderBook(
                        bids=book.bids if book else (),
                        asks=new_levels,
                    )
                depth_20_active["active"] = True
        except asyncio.CancelledError:
            raise
        except Exception:
            logger.debug("Depth-20 stream ended", exc_info=True)

    depth_task = asyncio.create_task(_stream_depth_20())

    # --- Main tick streaming loop (stream_full gives ticks + 5-level depth) ---
    try:
        logger.info("Server-driven: streaming live ticks for %s", active_symbol)
        tick_count = 0
        async for pkt in _stream_with_reconnect(market_data, [active_symbol]):
            if client_task.done():
                break

            if not is_market_open(exchange=settings.DEFAULT_EXCHANGE):
                continue

            tick_count += 1
            if tick_count == 1:
                logger.info("First live tick: ltp=%s vol=%s oi=%s",
                            pkt.get("ltp"), pkt.get("volume"), pkt.get("oi"))

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
            cum_buy = int(pkt.get("total_buy_qty", 0))
            cum_sell = int(pkt.get("total_sell_qty", 0))

            # Build 5-level depth from FULL packet into OrderBook
            pkt_bids = pkt.get("depth_bids", [])
            pkt_asks = pkt.get("depth_asks", [])
            if pkt_bids or pkt_asks:
                current_depth["book"] = OrderBook(
                    bids=tuple(
                        OrderBookLevel(price=float(b.get("price", 0)), quantity=float(b.get("qty", 0)))
                        for b in pkt_bids
                    ),
                    asks=tuple(
                        OrderBookLevel(price=float(a.get("price", 0)), quantity=float(a.get("qty", 0)))
                        for a in pkt_asks
                    ),
                )

            # Feed real tick to footprint accumulator
            _best_bid = pkt_bids[0].get("price", 0) if pkt_bids else 0.0
            _best_ask = pkt_asks[0].get("price", 0) if pkt_asks else 0.0
            if ltq > 0:
                _candle_t = _candle_start(now)
                fp_accumulator.on_tick(ltp, ltq, float(_best_bid), float(_best_ask),
                                       _candle_t.isoformat() if _candle_t else "")

            # --- Aggregate into candle ---
            c_start = _candle_start(now)
            cs = candle_state
            # Per-candle volume from cumulative (Dhan sends cumulative daily vol).
            # First tick: seed the baseline (don't dump full day's volume into candle).
            # On stream reconnect: cumulative volume may jump (new base) — cap delta
            # to avoid a single candle getting thousands of phantom volume.
            if cs["prev_cum_vol"] < 0:
                # First tick ever — seed baseline, no volume for this tick
                cs["prev_cum_vol"] = vol
                candle_vol = 0
            elif vol < cs["prev_cum_vol"]:
                # Reconnect: cumulative reset — seed new baseline
                logger.info("Stream reconnect detected: cum_vol %d < prev %d, resetting", vol, cs["prev_cum_vol"])
                cs["prev_cum_vol"] = vol
                candle_vol = 0
            else:
                candle_vol = vol - cs["prev_cum_vol"]
                # Sanity cap: single tick should not contribute more than 5000 volume
                # (protects against cumulative jump on reconnect where vol > prev)
                if candle_vol > 5000:
                    logger.warning("Volume spike capped: %d → 0 (likely cumulative jump)", candle_vol)
                    cs["prev_cum_vol"] = vol
                    candle_vol = 0
                else:
                    cs["prev_cum_vol"] = vol

            # Per-tick buy/sell volume from cumulative totals (same pattern as volume)
            if cs["prev_cum_buy"] < 0:
                # First tick — seed baselines, no buy/sell volume for this tick
                cs["prev_cum_buy"] = cum_buy
                cs["prev_cum_sell"] = cum_sell
                tick_buy = 0
                tick_sell = 0
            elif cum_buy < cs["prev_cum_buy"] or cum_sell < cs["prev_cum_sell"]:
                # Reconnect: cumulative reset — seed new baselines
                cs["prev_cum_buy"] = cum_buy
                cs["prev_cum_sell"] = cum_sell
                tick_buy = 0
                tick_sell = 0
            else:
                tick_buy = cum_buy - cs["prev_cum_buy"]
                tick_sell = cum_sell - cs["prev_cum_sell"]
                # Sanity cap matching volume spike guard
                if tick_buy > 5000:
                    tick_buy = 0
                if tick_sell > 5000:
                    tick_sell = 0
                cs["prev_cum_buy"] = cum_buy
                cs["prev_cum_sell"] = cum_sell

            if cs["start"] is None or c_start != cs["start"]:
                # New candle boundary
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

            # Compute delta from real buy/sell volume (Dhan total_buy_qty / total_sell_qty)
            _cv = cs["candle_vol"]
            _cbuy = cs["candle_buy_vol"]
            _csell = cs["candle_sell_vol"]
            if _cbuy > 0 or _csell > 0:
                # Real delta from Dhan cumulative buy/sell quantities
                _delta = float(_cbuy - _csell)
                _buy_vol = float(_cbuy)
            else:
                # Fallback: OHLC body-ratio proxy when buy/sell data unavailable
                _spread = cs["high"] - cs["low"]
                if _spread > 0 and _cv > 0:
                    _body_ratio = (cs["close"] - cs["open"]) / _spread
                    _delta = _body_ratio * _cv
                else:
                    _delta = 0.0
                _buy_vol = max(0.0, (_cv + _delta) / 2)

            tick = OHLC(
                time=cs["start"].isoformat(),
                open=cs["open"],
                high=cs["high"],
                low=cs["low"],
                close=cs["close"],
                volume=float(_cv),
                vwap=vwap,
                taker_buy_volume=_buy_vol,
                delta=_delta,
            )

            error = _validate_tick(tick)
            if error:
                continue

            # Throttle process_tick to max once per 500ms (LLM + VP are expensive)
            elapsed = asyncio.get_event_loop().time() - last_process_time
            if elapsed < 0.5:
                # Still send raw tick to frontend for chart update.
                # Include cached AMT + agentDecision so UI stays current between full ticks.
                msg: dict = {
                    "tick": ohlc_to_dto(tick),
                    "ltp": ltp,
                    "oi": oi,
                    "depth": _depth_to_dto(current_depth["book"]),
                    "_symbol": active_symbol,
                }
                try:
                    _session = session_service._sessions.get(active_symbol)
                    if _session:
                        if _session.last_ai_analysis:
                            msg["genAIAnalysis"] = session_service._camel_case_ai(_session.last_ai_analysis)
                        if _session.last_amt:
                            msg["amt"] = _session.last_amt
                        if hasattr(_session, '_agent_decision') and _session._agent_decision:
                            ad = _session._agent_decision
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
                    pass  # non-critical — just skip cached data in throttled tick
                await ws.send_json(msg)
                continue

            last_process_time = asyncio.get_event_loop().time()

            # Refresh Greeks every 60 seconds (not on every tick — too expensive)
            if last_process_time - last_greeks_time > 60:
                try:
                    greeks = market_data.get_greeks(active_symbol)
                    if greeks:
                        _sess = session_service.get_or_create_session(active_symbol)
                        _sess._greeks = greeks
                        last_greeks_time = last_process_time
                        logger.debug("Greeks refreshed: theta=%.2f iv=%.1f%%",
                                     greeks["theta"], greeks.get("iv", 0))
                except Exception:
                    logger.debug("Greeks refresh failed (non-critical)", exc_info=True)

            try:
                state = await asyncio.to_thread(
                    session_service.process_tick, active_symbol, tick,
                    current_depth["book"],
                )
                state["tick"] = ohlc_to_dto(tick)
                state["ltp"] = ltp
                state["oi"] = oi
                state["depth"] = _depth_to_dto(current_depth["book"])
                state["depth20Active"] = depth_20_active["active"]
                # Overlay real tick-level footprint onto session
                _session = session_service._sessions.get(active_symbol)
                if _session:
                    from app.infrastructure.serialization.schemas import footprint_to_dto
                    real_fp = fp_accumulator.get_all()
                    if real_fp:
                        _session.last_footprint = {k: footprint_to_dto(v) for k, v in real_fp.items()}
                        state["footprint"] = _session.last_footprint
                await ws.send_json(state)
            except Exception:
                logger.error("Server-driven: tick processing error", exc_info=True)

    except asyncio.CancelledError:
        logger.info("Server-driven: stream cancelled (new connection or shutdown)")
    except Exception:
        logger.warning("Server-driven: stream ended", exc_info=True)
    finally:
        client_task.cancel()
        depth_task.cancel()


def _interval_to_seconds(interval: str) -> int:
    """Convert interval string like '5m', '1h' to seconds."""
    unit = interval[-1]
    val = int(interval[:-1])
    if unit == "m":
        return val * 60
    elif unit == "h":
        return val * 3600
    elif unit == "d":
        return val * 86400
    return val * 60  # default minutes


def _depth_to_dto(book: OrderBook | None) -> dict | None:
    """Convert OrderBook to JSON-serializable dict for frontend."""
    if not book:
        return None
    return {
        "bids": [{"price": l.price, "quantity": l.quantity} for l in book.bids[:20]],
        "asks": [{"price": l.price, "quantity": l.quantity} for l in book.asks[:20]],
    }


async def _stream_with_reconnect(market_data, symbols: list[str]):
    """Wrap stream_full() with infinite retry and exponential backoff.

    Never gives up — the frontend reconnect loop will cancel via CancelledError
    if a new subscribe arrives.  Backoff caps at 60s to avoid hammering Dhan
    with HTTP 429.

    Dhan allows max 5 concurrent WS connections per token.  The WS client
    has its own internal reconnect (30 attempts with exponential backoff).
    This outer loop only fires when the inner reconnect is fully exhausted.
    A global cooldown prevents multiple frontend reconnects from hammering
    Dhan simultaneously.
    """
    global _last_dhan_connect_time
    consecutive_failures = 0
    while True:
        # Enforce global cooldown to avoid rapid-fire Dhan connections
        now = asyncio.get_event_loop().time()
        since_last = now - _last_dhan_connect_time
        if since_last < _DHAN_CONNECT_COOLDOWN:
            wait_for = _DHAN_CONNECT_COOLDOWN - since_last
            logger.info("Dhan connect cooldown: waiting %.1fs", wait_for)
            await asyncio.sleep(wait_for)
        _last_dhan_connect_time = asyncio.get_event_loop().time()

        try:
            async for pkt in market_data.stream_full(symbols):
                consecutive_failures = 0  # reset on successful data
                yield pkt
            # Generator exhausted cleanly — reconnect
            logger.info("Stream ended cleanly, reconnecting...")
        except asyncio.CancelledError:
            raise  # propagate cancellation
        except Exception as e:
            consecutive_failures += 1
            # Exponential backoff: 5, 10, 20, 40, 60, 60, 60...
            wait = min(5 * (2 ** (consecutive_failures - 1)), 60)
            logger.warning(
                "Stream disconnected (attempt %d), reconnecting in %ds: %s",
                consecutive_failures, wait, e,
            )
            await asyncio.sleep(wait)


async def _listen_for_client(ws: WebSocket) -> None:
    """Listen for client messages during server-driven mode."""
    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)
            if data.get("unsubscribe"):
                return
    except (WebSocketDisconnect, Exception):
        return
