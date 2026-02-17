"""WebSocket game-loop handler.

Receives tick data from the frontend, processes it through the full
event-driven pipeline (analysis → signal → risk → broker → portfolio),
and returns the updated state snapshot.
"""

from __future__ import annotations

import asyncio
import json
import math
import traceback

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends

from app.api.dependencies import get_trading_session
from app.application.services.trading_session import TradingSessionService
from app.domain.trading.models.value_objects import OHLC, OrderBook, OrderBookLevel

router = APIRouter(prefix="/trading", tags=["trading"])


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


@router.websocket("/ws/gameloop")
async def gameloop_ws(ws: WebSocket):
    await ws.accept()

    # Get the trading session from DI
    from app.api.dependencies import get_service_graph
    graph = get_service_graph()
    session_service = graph.trading_session

    try:
        while True:
            raw = await ws.receive_text()
            data = json.loads(raw)

            symbol = data.get("symbol", "BTCUSDT")

            # Handle bulk history init message
            history_raw = data.get("history")
            if history_raw and isinstance(history_raw, list):
                session = session_service.get_or_create_session(symbol)
                if len(session.data) < 10:  # Only seed if backend has little data
                    candles = []
                    for h in history_raw[-500:]:  # Cap at 500 candles
                        try:
                            candles.append(OHLC(
                                time=h.get("time", ""),
                                open=float(h.get("open", 0)),
                                high=float(h.get("high", 0)),
                                low=float(h.get("low", 0)),
                                close=float(h.get("close", 0)),
                                volume=float(h.get("volume", 0)),
                                vwap=float(h.get("vwap", 0)),
                                taker_buy_volume=float(h.get("takerBuyVolume", 0)),
                                delta=float(h.get("delta", 0)),
                            ))
                        except (TypeError, ValueError):
                            continue
                    if candles:
                        session.data = candles
                        import logging
                        logging.getLogger(__name__).info(
                            "Seeded %d historical candles for %s", len(candles), symbol
                        )
                await ws.send_json({"status": "history_loaded", "count": len(session.data) if history_raw else 0})
                continue

            # Parse tick with validation
            tick_raw = data.get("tick", {})
            try:
                tick = OHLC(
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
            except (TypeError, ValueError) as e:
                await ws.send_json({"error": f"Invalid tick data: {e}"})
                continue

            error = _validate_tick(tick)
            if error:
                await ws.send_json({"error": error})
                continue

            # Parse optional order book
            ob_raw = data.get("orderBook")
            order_book = None
            if ob_raw:
                order_book = OrderBook(
                    bids=tuple(
                        OrderBookLevel(price=float(b["price"]), quantity=float(b["quantity"]))
                        for b in ob_raw.get("bids", [])
                    ),
                    asks=tuple(
                        OrderBookLevel(price=float(a["price"]), quantity=float(a["quantity"]))
                        for a in ob_raw.get("asks", [])
                    ),
                )

            # Process through the full pipeline — run in thread pool to avoid blocking
            state = await asyncio.to_thread(
                session_service.process_tick, symbol, tick, order_book
            )

            await ws.send_json(state)

    except WebSocketDisconnect:
        pass
    except Exception as e:
        traceback.print_exc()
        try:
            await ws.close()
        except Exception:
            pass
