"""FastAPI runtime control and event streaming API."""

from __future__ import annotations

from datetime import datetime
from typing import List
import asyncio
import json

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from sse_starlette.sse import EventSourceResponse

from app.application.commands.trading_commands import UpdateTick
from app.application.handlers.update_tick_handler import UpdateTickHandler
from app.infrastructure.messaging.event_bus import EventBus
from app.infrastructure.serialization import AMTAnalysisDTO, OHLCDataDTO, RuntimeControlRequest
from app.runtime.feeds import LiveFeed
from app.runtime.orchestrator import RuntimeOrchestrator
from app.domain.amt.service.amt_analyzer import (
    build_volume_profile,
    calculate_vwap,
    detect_absorptions,
    generate_triple_a_signal,
)


app = FastAPI(
    title="GlassyTrade AI BackendV2 API",
    description="Runtime control API",
    version="2.0.0",
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

event_bus = EventBus()
orchestrator = RuntimeOrchestrator()
connected_clients: List[asyncio.Queue] = []


@app.get("/")
async def root():
    return {"message": "GlassyTrade AI BackendV2", "version": "2.0.0"}


@app.get("/api/health")
async def health_check():
    return {
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "active_sessions": len(orchestrator._sessions),
    }


@app.get("/api/stream")
async def stream_events(request: Request):
    async def event_generator():
        queue: asyncio.Queue = asyncio.Queue()
        connected_clients.append(queue)
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    event_data = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield {"event": "update", "data": json.dumps(event_data)}
                except asyncio.TimeoutError:
                    yield {"event": "heartbeat", "data": json.dumps({"timestamp": datetime.utcnow().isoformat()})}
        finally:
            if queue in connected_clients:
                connected_clients.remove(queue)

    return EventSourceResponse(event_generator())


@app.post("/api/tick")
async def process_tick(tick: OHLCDataDTO):
    if not tick.symbol:
        raise HTTPException(status_code=400, detail="symbol is required")

    cmd = UpdateTick(
        symbol=tick.symbol,
        timestamp=float(tick.timestamp or datetime.utcnow().timestamp()),
        price=tick.close,
        volume=tick.volume,
    )
    handler = UpdateTickHandler(event_bus=event_bus)
    handler.handle(cmd)

    event_data = {
        "type": "tick",
        "symbol": cmd.symbol,
        "price": cmd.price,
        "timestamp": datetime.utcnow().isoformat(),
    }
    for queue in connected_clients:
        await queue.put(event_data)

    return {"status": "processed", "symbol": cmd.symbol}


@app.post("/api/analyze")
async def analyze_market(data: list[OHLCDataDTO]):
    bars = [
        {
            "open": d.open,
            "high": d.high,
            "low": d.low,
            "close": d.close,
            "volume": d.volume,
            "buyVolume": float(d.takerBuyVolume or 0.0) or d.volume / 2,
            "sellVolume": d.volume - (float(d.takerBuyVolume or 0.0) or d.volume / 2),
            "bar_index": i,
        }
        for i, d in enumerate(data)
    ]

    vp = build_volume_profile(bars, bucket_size=50.0)
    vwap, _, _, _, _ = calculate_vwap(bars)
    absorptions = detect_absorptions(bars)
    signal = generate_triple_a_signal(bars, absorptions, vp, vwap)

    return AMTAnalysisDTO(
        marketState="BULLISH" if signal.type == "LONG" else "BEARISH",
        poc=vp.poc,
        valueAreaHigh=vp.vah,
        valueAreaLow=vp.val,
        signal=None if signal.type == "NO_TRADE" else signal,
    )


@app.get("/api/positions")
async def get_positions():
    positions = []
    for session in orchestrator._sessions.values():
        portfolios = session._position.snapshot() if hasattr(session._position, "snapshot") else {}
        for symbol, portfolio in portfolios.items():
            positions.append(
                {
                    "session": str(id(session)),
                    "symbol": symbol,
                    "equity": float(getattr(portfolio, "equity", 0.0)),
                    "open_positions": [
                        {
                            "id": getattr(p, "id", None),
                            "symbol": getattr(p, "symbol", None),
                            "side": getattr(getattr(p, "side", None), "name", None),
                            "size": float(getattr(p, "size", 0.0)),
                            "entry_price": float(getattr(p, "entry_price", 0.0)),
                        }
                        for p in getattr(portfolio, "positions", [])
                    ],
                }
            )
    return {"sessions": positions}


@app.post("/api/runtime/start")
async def runtime_start(request: RuntimeControlRequest):
    orchestrator.create_live_session(
        session_id=request.session_id,
        feed=LiveFeed(symbols=request.symbols, strict_symbol_mode=True),
        symbols=request.symbols,
    )
    orchestrator.start(request.session_id)
    return {"status": "started", "session_id": request.session_id, "mode": "live"}


@app.post("/api/runtime/stop/{session_id}")
async def runtime_stop(session_id: str):
    if not orchestrator.stop(session_id):
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}")
    return {"status": "stopped", "session_id": session_id}


@app.get("/api/runtime/{session_id}/state")
async def runtime_state(session_id: str):
    session = orchestrator.get_session(session_id)
    if session is None:
        raise HTTPException(status_code=404, detail=f"session not found: {session_id}")
    return {"session_id": session_id, "running": session.is_running}


@app.post("/api/runtime/{session_id}/run_once")
async def runtime_run_once(session_id: str, max_ticks: int = 100):
    events = orchestrator.run_once(session_id=session_id, max_ticks=max_ticks)
    for event in events:
        event_data = _serialize_event(event)
        for queue in connected_clients:
            await queue.put(event_data)
    return {"session_id": session_id, "event_count": len(events)}


def _serialize_event(event: object) -> dict:
    if hasattr(event, "__dict__"):
        data = dict(getattr(event, "__dict__"))
    else:
        data = {"value": str(event)}
    data.setdefault("type", type(event).__name__)
    data.setdefault("event_type", data.get("type"))
    return data