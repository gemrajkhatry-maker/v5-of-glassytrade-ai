"""WebSocket game-loop handler — thin read-only viewer over QuantCoordinator.

The legacy engine path (TradingEngine + TradingSessionService) was deleted
in the backend swap. The greenfield QuantCoordinator is the single decision
brain, and this WS handler is a pure transport: it streams coordinator
snapshots to the frontend with delta compression.

Server-driven mode:
  1. Send config + history
  2. Send current full snapshot
  3. Loop: poll coordinator snapshot → delta compress → send
  4. Client ping -> pong; subscribe -> symbol_switched + re-enter
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, WebSocket, WebSocketDisconnect

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


@router.websocket("/ws/gameloop")
async def gameloop_ws(ws: WebSocket):
    logger.info("WebSocket connection attempt from %s", ws.client)
    try:
        await ws.accept()
        logger.info("WebSocket connection accepted")
    except Exception as e:
        logger.error("Failed to accept WebSocket connection: %s", e, exc_info=True)
        raise

    app = ws.scope.get("app")
    coordinator = getattr(getattr(app, "state", None), "coordinator", None)
    if coordinator is None:
        logger.error("QuantCoordinator not available from app.state")
        await _safe_send(ws, {"error": "QuantCoordinator not started yet"})
        await ws.close(code=1011)
        return

    try:
        while True:
            raw = await ws.receive_text()
            # Reject payloads > 1MB to prevent memory exhaustion
            if len(raw) > 1_048_576:
                await ws.send_json({"error": "Payload too large (max 1MB)"})
                continue
            data = json.loads(raw)

            # Server-driven mode: stream QuantCoordinator snapshots
            if "subscribe" in data:
                symbol = data["subscribe"]
                logger.info("WS viewer connected for %s", symbol)
                await _coordinator_viewer_loop(ws, coordinator, symbol)
                return

            # The legacy client-driven mode (tick/history) was removed — reject
            # anything that is not a subscribe so clients never hang silently.
            await _safe_send(
                ws,
                {"error": "Expected a subscribe payload; client-driven mode was removed"},
            )

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


async def _coordinator_listener(ws: WebSocket, commands: asyncio.Queue) -> None:
    """Read client messages for the greenfield viewer loop.

    NOTE: never writes to the WS here — commands are queued and the viewer
    loop replies, preserving single-writer semantics (concurrent WS writes
    cause broken pipe errors).
    """
    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)
            if data.get("unsubscribe"):
                await commands.put(("unsubscribe", None))
                return
            if data.get("ping"):
                await commands.put(("pong", None))
            if data.get("subscribe"):
                await commands.put(("subscribe", data["subscribe"]))
    except (WebSocketDisconnect, Exception):
        return


def _resolve_symbol(requested: str, available: list[str]) -> str | None:
    """Map a client-requested symbol to a live coordinator contract.

    Exact match wins; otherwise a base underlying (e.g. ``NIFTY``) resolves to
    the first scanned contract for that underlying (e.g. ``NIFTY 11 AUG 24550
    CALL``). Returns ``None`` when nothing matches.
    """
    if requested in available:
        return requested
    prefix = f"{requested.upper()} "
    for sym in available:
        if sym.upper().startswith(prefix):
            return sym
    return None


async def _wait_for_subscribe(
    ws: WebSocket, commands: asyncio.Queue, listener: asyncio.Task
) -> str | None:
    """Wait for the client to (re-)subscribe, answering pings meanwhile.

    Returns the newly requested symbol, or ``None`` when the client
    disconnected or sent an unsubscribe.
    """
    while True:
        if listener.done():
            return None
        try:
            kind, payload = await asyncio.wait_for(commands.get(), timeout=0.5)
        except asyncio.TimeoutError:
            continue
        if kind == "pong":
            if not await _safe_send(ws, {"type": "pong"}):
                return None
        elif kind == "subscribe":
            return payload
        elif kind == "unsubscribe":
            return None


async def _coordinator_viewer_loop(
    ws: WebSocket, coordinator, symbol: str
) -> None:
    """Greenfield viewer: streams QuantCoordinator snapshots via delta compression.

    Control protocol mirrors the legacy engine loop so the frontend sees the
    same ``server_mode`` messages:
      1. server_mode (exchange/interval/activeSymbols)
      2. llm_history_loaded (LLM decision history per symbol) — deliberately
         NOT ``history_loaded``: the frontend treats that status as chart
         candle data (the legacy protocol sent OHLC there). LLM decisions are
         raw analysis JSON with no OHLC shape, so they get their own status
         and are routed to the decision-history panel, never into the chart.
      3. full snapshot, then 0.5s delta-compressed snapshots
      4. client ping -> {"type": "pong"}; subscribe -> symbol_switched + re-enter

    The requested symbol is resolved against the coordinator's live contracts
    (base underlying -> first matching contract). An unknown symbol no longer
    closes the socket: the error is sent with the available symbols and the
    connection stays open waiting for a valid re-subscribe, so the frontend
    cannot spin in a reconnect loop.
    """
    from app.config import settings

    commands: asyncio.Queue = asyncio.Queue()
    listener = asyncio.create_task(_coordinator_listener(ws, commands))
    previous: str | None = None

    try:
        while True:
            symbols = coordinator.symbols()
            resolved = _resolve_symbol(symbol, symbols)
            if resolved is None:
                # Preserve the coordinator's engine-switch capability: a client
                # may request a specific new contract not in the live scan, in
                # which case the coordinator swaps its engine over to it.
                if previous is not None and previous in symbols:
                    try:
                        if coordinator.switch_symbol(previous, symbol):
                            resolved = symbol
                    except Exception:
                        logger.warning(
                            "coordinator.switch_symbol(%s, %s) failed",
                            previous,
                            symbol,
                            exc_info=True,
                        )
            if resolved is None:
                if not await _safe_send(
                    ws,
                    {
                        "error": f"symbol not found: {symbol}",
                        "availableSymbols": symbols,
                    },
                ):
                    return
                symbol = await _wait_for_subscribe(ws, commands, listener)
                if symbol is None:
                    return
                continue
            symbol = resolved
            previous = symbol

            # 1. Send config
            if not await _safe_send(
                ws,
                {
                    "status": "server_mode",
                    "symbol": symbol,
                    "activeSymbols": coordinator.symbols(),
                    "exchange": settings.DEFAULT_EXCHANGE,
                    "interval": settings.STREAM_INTERVAL,
                },
            ):
                return

            # 2. Send LLM decision history under its own status — this is NOT
            # candle history (the coordinator keeps no OHLC history in the
            # greenfield shell), so it must never ride the ``history_loaded``
            # status the frontend maps to chart data.
            history = coordinator.llm_history(symbol)
            if not await _safe_send(
                ws,
                {
                    "status": "llm_history_loaded",
                    "symbol": symbol,
                    "_symbol": symbol,
                    "history": list(history),
                    "count": len(history),
                },
            ):
                return

            # 3. Send current full snapshot
            previous_state: dict = dict(coordinator.snapshot(symbol))
            if not await _safe_send(ws, {**previous_state, "_type": "full"}):
                return

            # 4. Stream delta-compressed updates every 0.5s
            while True:
                if listener.done():
                    return
                await asyncio.sleep(0.5)

                switched: str | None = None
                while not commands.empty():
                    kind, payload = commands.get_nowait()
                    if kind == "pong":
                        if not await _safe_send(ws, {"type": "pong"}):
                            return
                    elif kind == "subscribe":
                        switched = payload
                    elif kind == "unsubscribe":
                        return
                if switched is not None:
                    if not await _safe_send(
                        ws, {"status": "symbol_switched", "symbol": switched}
                    ):
                        return
                    symbol = switched
                    break

                snap = coordinator.snapshot(symbol)
                delta = _compute_delta(previous_state, snap)
                if delta:
                    if not await _safe_send(ws, delta):
                        return
                    previous_state = dict(snap)
    finally:
        listener.cancel()
        try:
            await listener
        except (asyncio.CancelledError, Exception):
            pass
