"""WebSocket game-loop handler.

Receives tick data from the frontend, processes it through the full
event-driven pipeline (analysis → signal → risk → broker → portfolio),
and returns the updated state snapshot.
"""

from __future__ import annotations

import asyncio
import json
import traceback

from fastapi import APIRouter, WebSocket, WebSocketDisconnect, Depends

from app.api.dependencies import get_trading_session
from app.application.services.trading_session import TradingSessionService
from app.domain.trading.models.value_objects import OHLC, OrderBook, OrderBookLevel

router = APIRouter(prefix="/trading", tags=["trading"])


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

            # Parse tick
            tick_raw = data.get("tick", {})
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
