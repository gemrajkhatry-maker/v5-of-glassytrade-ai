"""WebSocket game-loop handler — thin read-only viewer.

Frontend connects here to receive live state from the TradingEngine.
The engine runs independently; disconnecting a viewer does NOT stop trading.

Server-driven mode:
  1. Send config + history
  2. Send current snapshot
  3. Loop: wait for engine update → delta compress → send

Client-driven mode (backward compat) kept for local dev.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import math
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.domain.trading.models.value_objects import OHLC, OrderBook, OrderBookLevel
from app.shared.depth_dto import order_book_to_dto

router = APIRouter(prefix="/trading", tags=["trading"])
logger = logging.getLogger(__name__)


async def _safe_send(ws: WebSocket, data: dict) -> bool:
    try:
        await ws.send_json(data)
        return True
    except (WebSocketDisconnect, asyncio.TimeoutError) as e:
        logger.debug("WS send failed (client disconnected): %s", type(e).__name__)
        return False
    except RuntimeError as e:
        # Session closed or invalid state
        logger.debug("WS send failed (runtime): %s", e)
        return False
    except Exception as e:
        logger.warning(
            "WS send failed: %s (keys=%s)", type(e).__name__, list(data.keys())[:5]
        )
        return False


def _deep_equal(a: object, b: object) -> bool:
    """Deep equality check for nested dicts/lists used in delta compression."""
    if type(a) is not type(b):
        return False
    if isinstance(a, dict):
        if len(a) != len(b):
            return False
        return all(k in b and _deep_equal(v, b[k]) for k, v in a.items())
    if isinstance(a, (list, tuple)):
        if len(a) != len(b):
            return False
        return all(_deep_equal(x, y) for x, y in zip(a, b))
    return a == b


def _compute_delta(prev: dict | None, current: dict) -> dict:
    if prev is None:
        return current
    delta: dict = {"_symbol": current.get("_symbol", ""), "_type": "delta"}
    changed = False
    for key, value in current.items():
        if key.startswith("_"):
            continue
        if not _deep_equal(prev.get(key), value):
            delta[key] = value
            changed = True
    return delta if changed else {}





def _parse_tick(tick_raw: dict) -> OHLC:
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


def _validate_tick(tick: OHLC) -> str | None:
    for name, val in [
        ("open", tick.open),
        ("high", tick.high),
        ("low", tick.low),
        ("close", tick.close),
    ]:
        if math.isnan(val) or math.isinf(val) or val <= 0:
            return f"Invalid tick: {name}={val}"
    if math.isnan(tick.volume) or math.isinf(tick.volume) or tick.volume < 0:
        return f"Invalid tick: volume={tick.volume}"
    if tick.high < tick.low:
        return f"Invalid tick: high ({tick.high}) < low ({tick.low})"
    return None


@router.websocket("/ws/gameloop")
async def gameloop_ws(ws: WebSocket):
    logger.info("WebSocket connection attempt from %s", ws.client)
    try:
        await ws.accept()
        logger.info("WebSocket connection accepted")
    except Exception as e:
        logger.error("Failed to accept WebSocket connection: %s", e, exc_info=True)
        raise

    # Use services from app state (the ones with the started engine)
    app = ws.scope.get("app")
    if app and hasattr(app.state, "trading_session"):
        session_service = app.state.trading_session
        logger.info("Using services from app.state (DI container)")
    else:
        raise RuntimeError("Trading session not available from app.state")

    try:
        while True:
            raw = await ws.receive_text()
            # Reject payloads > 1MB to prevent memory exhaustion
            if len(raw) > 1_048_576:
                await ws.send_json({"error": "Payload too large (max 1MB)"})
                continue
            data = json.loads(raw)

            # --- Server-driven mode: read from TradingEngine ---
            if "subscribe" in data:
                symbol = data["subscribe"]
                logger.info("WS viewer connected for %s", symbol)
                await _viewer_loop(ws, app.state, symbol)
                return

            # --- Client-driven mode (backward compat) ---
            symbol = data.get("symbol", "")

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
                        with session._lock:
                            session.data = candles
                await ws.send_json(
                    {
                        "status": "history_loaded",
                        "count": len(session.data) if history_raw else 0,
                    }
                )
                continue

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
        logger.debug("WebSocket client disconnected gracefully")
    except json.JSONDecodeError as e:
        logger.warning("Invalid JSON received from client: %s", e)
        try:
            await ws.send_json({"error": "Invalid JSON format"})
            await ws.close(code=1003)  # Unsupported Data
        except Exception:
            pass  # Client already disconnected, nothing to do
    except OSError as e:
        # Network errors, pipe errors, etc.
        logger.warning("OS error in WS handler: %s", e)
        try:
            await ws.close(code=1006)  # Abnormal closure
        except Exception:
            pass  # Socket may already be closed
    except Exception:
        logger.error("Unexpected error in WS handler", exc_info=True)
        try:
            await ws.close(code=1011)  # Internal error
        except Exception:
            pass  # Socket may already be closed


async def _viewer_loop(ws: WebSocket, app_state, symbol: str) -> None:
    """Read-only viewer: streams engine state to frontend via delta compression."""
    from app.config import settings
    from app.infrastructure.serialization.schemas import ohlc_to_dto

    engine = getattr(app_state, "engine", None)
    if engine is None:
        # Fallback: engine not yet started — tell frontend to retry
        logger.warning("Trading engine not available, sending error to frontend")
        await _safe_send(ws, {"error": "Trading engine not started yet"})
        return

    logger.info("Viewer loop: engine available, getting active symbols")
    active_symbols = engine.get_active_symbols()
    if not active_symbols:
        active_symbols = [symbol]
    primary_symbol = active_symbols[0]
    logger.info("Viewer loop: active_symbols=%s, primary=%s", active_symbols, primary_symbol)

    # 1. Send config
    if not await _safe_send(
        ws,
        {
            "status": "server_mode",
            "symbol": primary_symbol,
            "activeSymbols": active_symbols,
            "exchange": settings.DEFAULT_EXCHANGE,
            "interval": settings.STREAM_INTERVAL,
        },
    ):
        return

    # 2. Send history for all symbols
    for sym in active_symbols:
        history = engine.get_history(sym)
        if history:
            if not await _safe_send(
                ws,
                {
                    "status": "history_loaded",
                    "symbol": sym,
                    "_symbol": sym,
                    "history": [ohlc_to_dto(c) for c in history[-500:]],
                    "count": len(history),
                },
            ):
                continue

    # 3. Send current snapshot for all symbols
    for sym in active_symbols:
        state = engine.get_latest_state(sym)
        if state:
            if not await _safe_send(ws, {**state, "_type": "full"}):
                continue

    # 4. Stream updates via generation-based polling
    client_task = asyncio.create_task(_listen_for_client(ws))
    previous_states: dict[str, dict] = {}
    keyframe_times: dict[str, float] = {}
    known_gen = engine.generation
    _send_count = 0

    logger.info(
        "Viewer loop: entering polling (gen=%d, symbols=%d)",
        known_gen,
        len(active_symbols),
    )

    try:
        last_data_time = time.time()
        while True:
            if client_task.done():
                logger.info("Viewer loop: client task done, exiting")
                break

            # Wait for engine to produce new data
            new_gen = await engine.wait_for_update(known_gen, timeout=5.0)
            if new_gen == known_gen:
                # Engine hasn't produced new data — check for stale engine
                if time.time() - last_data_time > 60:
                    logger.warning(
                        "Viewer loop: engine stale for >60s (gen=%d), disconnecting client",
                        known_gen,
                    )
                    break
                if not await _safe_send(ws, {"pong": True}):
                    break
                continue  # No new data — loop back and check client_task
            known_gen = new_gen
            last_data_time = time.time()

            # Send updated states for all symbols
            send_ok = True
            for sym in active_symbols:
                state = engine.get_latest_state(sym)
                if not state:
                    continue

                now_kf = time.time()
                if now_kf - keyframe_times.get(sym, 0) > 30:
                    if not await _safe_send(ws, {**state, "_type": "full"}):
                        send_ok = False
                        break
                    # Shallow copy + selective deep copy of mutable portfolio and amt
                    _snap = dict(state)
                    if "portfolio" in _snap:
                        _snap["portfolio"] = copy.deepcopy(_snap["portfolio"])
                    if "amt" in _snap:
                        _snap["amt"] = copy.deepcopy(_snap["amt"])
                    previous_states[sym] = _snap
                    keyframe_times[sym] = now_kf
                else:
                    delta = _compute_delta(previous_states.get(sym), state)
                    if delta:
                        if not await _safe_send(ws, delta):
                            send_ok = False
                            break
                        # Shallow copy + selective deep copy of mutable portfolio and amt
                        _snap = dict(state)
                        if "portfolio" in _snap:
                            _snap["portfolio"] = copy.deepcopy(_snap["portfolio"])
                        if "amt" in _snap:
                            _snap["amt"] = copy.deepcopy(_snap["amt"])
                        previous_states[sym] = _snap
                _send_count += 1
            if not send_ok:
                logger.warning(
                    "Viewer loop: send failed after %d successful sends", _send_count
                )
                break
    except asyncio.CancelledError:
        logger.debug("Viewer loop cancelled (client disconnect)")
    except asyncio.TimeoutError as e:
        logger.warning("Viewer loop timeout waiting for engine update: %s", e)
    except OSError as e:
        # Network errors during streaming
        logger.warning("Viewer loop OS error: %s", e)
    except RuntimeError as e:
        # Engine state errors
        logger.warning("Viewer loop runtime error: %s", e)
    except Exception:
        logger.error("Unexpected error in viewer loop", exc_info=True)
    finally:
        client_task.cancel()
        try:
            await client_task
        except (asyncio.CancelledError, Exception):
            pass
        logger.info(
            "WS viewer disconnected (sent %d updates) — engine continues trading",
            _send_count,
        )


async def _listen_for_client(ws: WebSocket) -> None:
    """Listen for client messages during server-driven mode.

    NOTE: Do NOT send responses here — concurrent writes to the same WS
    from multiple coroutines cause broken pipe errors. The viewer loop
    handles keepalive via its own pong messages.
    """
    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)
            if data.get("unsubscribe"):
                return
            # ping is handled passively — viewer loop sends pong on its own schedule
    except (WebSocketDisconnect, Exception):
        return
