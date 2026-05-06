"""WebSocket game-loop handler — read-only live-state viewer.

Frontend connects here to receive live engine state.  The engine continues
trading even when no viewer is connected.

Modes
-----
Server-driven (preferred):
  Client sends {"subscribe": "<SYMBOL>"} → server streams delta-compressed
  state updates until the client disconnects.

Client-driven (backward compat / local dev):
  Client sends {"tick": {...}} → server processes tick and replies with state.
"""

from __future__ import annotations

import asyncio
import copy
import json
import logging
import math
import time

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

from app.domain.trading.model.value_objects import OHLC, OrderBook, OrderBookLevel

router = APIRouter(prefix="/trading", tags=["websocket"])
logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

async def _safe_send(ws: WebSocket, data: dict) -> bool:
    """Send JSON to client; return False if the connection is gone."""
    try:
        await ws.send_json(data)
        return True
    except (WebSocketDisconnect, asyncio.TimeoutError) as exc:
        logger.debug("WS send failed (client disconnected): %s", type(exc).__name__)
        return False
    except RuntimeError as exc:
        logger.debug("WS send failed (runtime): %s", exc)
        return False
    except Exception as exc:  # noqa: BLE001
        logger.warning("WS send failed: %s — keys=%s", type(exc).__name__, list(data.keys())[:5])
        return False


def _deep_equal(a: object, b: object) -> bool:
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
    """Return only changed top-level keys (shallow delta compression)."""
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


def _parse_tick(raw: dict) -> OHLC:
    return OHLC(
        time=raw.get("time", ""),
        open=float(raw.get("open", 0)),
        high=float(raw.get("high", 0)),
        low=float(raw.get("low", 0)),
        close=float(raw.get("close", 0)),
        volume=float(raw.get("volume", 0)),
        vwap=float(raw.get("vwap", 0)),
        taker_buy_volume=float(raw.get("takerBuyVolume", 0)),
        delta=float(raw.get("delta", 0)),
    )


def _parse_order_book(raw: dict | None) -> OrderBook | None:
    if not raw:
        return None
    return OrderBook(
        bids=tuple(
            OrderBookLevel(price=float(b["price"]), quantity=float(b["quantity"]))
            for b in raw.get("bids", [])
        ),
        asks=tuple(
            OrderBookLevel(price=float(a["price"]), quantity=float(a["quantity"]))
            for a in raw.get("asks", [])
        ),
    )


def _validate_tick(tick: OHLC) -> str | None:
    for name in ("open", "high", "low", "close"):
        val = float(getattr(tick, name))
        if math.isnan(val) or math.isinf(val) or val <= 0:
            return f"Invalid tick: {name}={val}"
    vol = float(tick.volume)
    if math.isnan(vol) or math.isinf(vol) or vol < 0:
        return f"Invalid tick: volume={vol}"
    if float(tick.high) < float(tick.low):
        return f"Invalid tick: high ({tick.high}) < low ({tick.low})"
    return None


# ---------------------------------------------------------------------------
# WebSocket endpoint
# ---------------------------------------------------------------------------

@router.websocket("/ws/gameloop")
async def gameloop_ws(ws: WebSocket) -> None:
    logger.info("WS connection attempt from %s", ws.client)
    try:
        await ws.accept()
    except Exception as exc:
        logger.error("WS accept failed: %s", exc, exc_info=True)
        raise

    app = ws.scope.get("app")

    try:
        while True:
            raw = await ws.receive_text()
            if len(raw) > 1_048_576:
                await ws.send_json({"error": "Payload too large (max 1 MB)"})
                continue

            data = json.loads(raw)

            # ---- server-driven mode ----
            if "subscribe" in data:
                symbol = data["subscribe"]
                logger.info("WS viewer subscribing to %s", symbol)
                await _viewer_loop(ws, app, symbol)
                return

            # ---- client-driven mode (backward compat) ----
            symbol = data.get("symbol", "")

            history_raw = data.get("history")
            if history_raw and isinstance(history_raw, list):
                session_service = _get_session_service(app)
                if session_service is not None:
                    session = session_service.get_or_create_session(symbol)
                    if len(getattr(session, "data", [])) < 10:
                        candles: list[OHLC] = []
                        for h in history_raw[-500:]:
                            try:
                                candles.append(_parse_tick(h))
                            except (TypeError, ValueError):
                                continue
                        if candles:
                            session.data = candles
                    await ws.send_json(
                        {"status": "history_loaded", "count": len(history_raw)}
                    )
                else:
                    await ws.send_json({"status": "history_loaded", "count": 0})
                continue

            tick_raw = data.get("tick", {})
            try:
                tick = _parse_tick(tick_raw)
            except (TypeError, ValueError) as exc:
                await ws.send_json({"error": f"Invalid tick: {exc}"})
                continue

            err = _validate_tick(tick)
            if err:
                await ws.send_json({"error": err})
                continue

            order_book = _parse_order_book(data.get("orderBook"))
            session_service = _get_session_service(app)
            if session_service is None:
                await ws.send_json({"error": "Trading session not available"})
                continue

            state = await asyncio.to_thread(
                session_service.process_tick, symbol, tick, order_book
            )
            await ws.send_json(state)

    except WebSocketDisconnect:
        logger.debug("WS client disconnected gracefully")
    except json.JSONDecodeError as exc:
        logger.warning("Invalid JSON from WS client: %s", exc)
        try:
            await ws.send_json({"error": "Invalid JSON"})
            await ws.close(code=1003)
        except Exception:
            pass
    except OSError as exc:
        logger.warning("OS error in WS handler: %s", exc)
        try:
            await ws.close(code=1006)
        except Exception:
            pass
    except Exception:
        logger.error("Unexpected error in WS handler", exc_info=True)
        try:
            await ws.close(code=1011)
        except Exception:
            pass


# ---------------------------------------------------------------------------
# Server-driven viewer loop
# ---------------------------------------------------------------------------

async def _viewer_loop(ws: WebSocket, app, symbol: str) -> None:
    """Stream live delta-compressed engine state to a read-only viewer."""
    orchestrator = getattr(getattr(app, "state", None), "orchestrator", None)
    if orchestrator is None:
        await _safe_send(ws, {"error": "Runtime orchestrator not available"})
        return

    active_symbols = _resolve_active_symbols(orchestrator, symbol)
    primary = active_symbols[0] if active_symbols else symbol

    if not await _safe_send(
        ws,
        {
            "status": "server_mode",
            "symbol": primary,
            "activeSymbols": active_symbols,
        },
    ):
        return

    # Send history for all symbols
    for sym in active_symbols:
        history = _get_history(orchestrator, sym)
        if history:
            if not await _safe_send(
                ws,
                {
                    "status": "history_loaded",
                    "symbol": sym,
                    "_symbol": sym,
                    "history": history[-500:],
                    "count": len(history),
                },
            ):
                continue

    # Send current snapshots
    for sym in active_symbols:
        state = _get_latest_state(orchestrator, sym)
        if state and not await _safe_send(ws, {**state, "_type": "full"}):
            break

    # Stream updates
    client_task = asyncio.create_task(_drain_client(ws))
    previous: dict[str, dict] = {}
    keyframe_times: dict[str, float] = {}
    last_data_ts = time.time()
    sends = 0

    try:
        while True:
            if client_task.done():
                break

            # Non-blocking poll: wait up to 5 s for new engine generation
            new_state_available = await asyncio.to_thread(
                _wait_for_new_state, orchestrator, 5.0
            )

            if not new_state_available:
                if time.time() - last_data_ts > 60:
                    logger.warning("WS viewer: engine stale >60s, disconnecting")
                    break
                if not await _safe_send(ws, {"pong": True}):
                    break
                continue

            last_data_ts = time.time()
            send_ok = True

            for sym in active_symbols:
                state = _get_latest_state(orchestrator, sym)
                if not state:
                    continue
                now = time.time()
                # Force keyframe every 30 s for resilience
                if now - keyframe_times.get(sym, 0) > 30:
                    if not await _safe_send(ws, {**state, "_type": "full"}):
                        send_ok = False
                        break
                    snap = dict(state)
                    for deep_key in ("portfolio", "amt"):
                        if deep_key in snap:
                            snap[deep_key] = copy.deepcopy(snap[deep_key])
                    previous[sym] = snap
                    keyframe_times[sym] = now
                else:
                    delta = _compute_delta(previous.get(sym), state)
                    if delta:
                        if not await _safe_send(ws, delta):
                            send_ok = False
                            break
                        snap = dict(state)
                        for deep_key in ("portfolio", "amt"):
                            if deep_key in snap:
                                snap[deep_key] = copy.deepcopy(snap[deep_key])
                        previous[sym] = snap
                sends += 1

            if not send_ok:
                break

    except asyncio.CancelledError:
        logger.debug("WS viewer loop cancelled")
    except Exception:
        logger.error("WS viewer loop error", exc_info=True)
    finally:
        client_task.cancel()
        try:
            await client_task
        except (asyncio.CancelledError, Exception):
            pass
        logger.info("WS viewer disconnected after %d updates — engine continues", sends)


async def _drain_client(ws: WebSocket) -> None:
    """Silently drain inbound messages during server-driven streaming."""
    try:
        while True:
            raw = await ws.receive_text()
            try:
                data = json.loads(raw)
                if data.get("unsubscribe"):
                    return
            except json.JSONDecodeError:
                pass
    except (WebSocketDisconnect, Exception):
        return


# ---------------------------------------------------------------------------
# Orchestrator integration helpers
# ---------------------------------------------------------------------------

def _get_session_service(app):
    state = getattr(app, "state", None)
    if state is None:
        return None
    return (
        getattr(state, "trading_session", None)
        or getattr(state, "session_service", None)
    )


def _resolve_active_symbols(orchestrator, fallback: str) -> list[str]:
    try:
        symbols = orchestrator.get_active_symbols()
        return symbols if symbols else [fallback]
    except Exception:
        return [fallback]


def _get_history(orchestrator, sym: str) -> list | None:
    try:
        return orchestrator.get_history(sym)
    except Exception:
        return None


def _get_latest_state(orchestrator, sym: str) -> dict | None:
    try:
        return orchestrator.get_latest_state(sym)
    except Exception:
        return None


def _wait_for_new_state(orchestrator, timeout: float) -> bool:
    """Blocking poll for orchestrator state change (runs in thread)."""
    try:
        gen_before = getattr(orchestrator, "generation", 0)
        deadline = time.time() + timeout
        while time.time() < deadline:
            gen_now = getattr(orchestrator, "generation", 0)
            if gen_now != gen_before:
                return True
            time.sleep(0.05)
        return False
    except Exception:
        return False
