"""FastAPI REST API with SSE streaming for backendv2."""
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
from sse_starlette.sse import EventSourceResponse
from datetime import datetime
from decimal import Decimal
from typing import List
import asyncio
import json

from app.domain.trading.model.entities import Position
from app.domain.trading.model.enums import Side, PositionStatus
from app.domain.amt.model.amt_models import Signal
from app.application.commands.trading_commands import UpdateTick
from app.infrastructure.adapters.infrastructure_adapters import (
    SQLiteStorage, SQLiteConfig, BinanceMarketDataAdapter
)
from app.infrastructure.messaging.event_bus import EventBus
from app.domain.shared.event.domain_events import DomainEvent
from app.infrastructure.serialization.schemas import OHLCDataDTO, AMTAnalysisDTO, PortfolioDTO
from app.api.routers import metrics


# Initialize FastAPI app
app = FastAPI(
    title="GlassyTrade AI BackendV2 API",
    description="Clean Architecture trading platform API",
    version="2.0.0"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Initialize infrastructure
event_bus = EventBus()
storage = SQLiteStorage(SQLiteConfig(db_path="backendv2.db"))
market_data = BinanceMarketDataAdapter(testnet=True)

# SSE client connections
connected_clients: List[asyncio.Queue] = []


@app.get("/")
async def root():
    """Root endpoint."""
    return {"message": "GlassyTrade AI BackendV2", "version": "2.0.0"}


@app.get("/api/stream")
async def stream_events(request: Request):
    """SSE endpoint for real-time events."""
    
    async def event_generator():
        queue = asyncio.Queue()
        connected_clients.append(queue)
        
        try:
            while True:
                if await request.is_disconnected():
                    break
                
                try:
                    # Wait for event with timeout
                    event_data = await asyncio.wait_for(queue.get(), timeout=1.0)
                    yield {
                        "event": "update",
                        "data": json.dumps(event_data)
                    }
                except asyncio.TimeoutError:
                    # Send heartbeat
                    yield {
                        "event": "heartbeat",
                        "data": json.dumps({"timestamp": datetime.now().isoformat()})
                    }
        finally:
            connected_clients.remove(queue)
    
    return EventSourceResponse(event_generator())


@app.post("/api/tick")
async def process_tick(tick: OHLCDataDTO):
    """Process a market tick and broadcast to SSE clients."""
    cmd = UpdateTick(
        symbol="BTCUSDT",
        timestamp=datetime.now().timestamp(),
        price=tick.close,
        volume=tick.volume
    )
    
    # Process tick
    from app.application.handlers.update_tick_handler import UpdateTickHandler
    handler = UpdateTickHandler(event_bus=event_bus)
    handler.handle(cmd)
    
    # Broadcast to SSE clients
    event_data = {
        "type": "tick",
        "symbol": cmd.symbol,
        "price": cmd.price,
        "timestamp": datetime.now().isoformat()
    }
    
    for queue in connected_clients:
        await queue.put(event_data)
    
    return {"status": "processed", "symbol": cmd.symbol}


@app.post("/api/analyze")
async def analyze_market(data: list[OHLCDataDTO]):
    """Analyze market data and generate signals."""
    bars = [
        {
            'open': d.open,
            'high': d.high,
            'low': d.low,
            'close': d.close,
            'volume': d.volume,
            'buyVolume': getattr(d, 'takerBuyVolume', 0) or d.volume / 2,
            'sellVolume': d.volume - (getattr(d, 'takerBuyVolume', 0) or d.volume / 2),
            'bar_index': i
        }
        for i, d in enumerate(data)
    ]
    
    from app.domain.amt.service.amt_analyzer import (
        build_volume_profile, calculate_vwap, detect_absorptions, generate_triple_a_signal
    )
    
    vp = build_volume_profile(bars, bucket_size=50.0)
    vwap, _, _, _, _ = calculate_vwap(bars)
    absorptions = detect_absorptions(bars)
    signal = generate_triple_a_signal(bars, absorptions, vp, vwap)
    
    result = AMTAnalysisDTO(
        marketState="BULLISH" if signal.type == "LONG" else "BEARISH",
        poc=vp.poc,
        valueAreaHigh=vp.vah,
        valueAreaLow=vp.val,
        signal=signal if signal.type != "NO_TRADE" else None
    )
    
    # Broadcast signal to SSE clients
    if signal.type != "NO_TRADE":
        signal_data = {
            "type": "signal",
            "direction": signal.type,
            "entry": signal.entry,
            "sl": signal.sl,
            "tp": signal.tp,
            "confidence": signal.confidence
        }
        for queue in connected_clients:
            await queue.put(signal_data)
    
    return result


@app.get("/api/positions")
async def get_positions():
    """Get all positions."""
    return PortfolioDTO(
        balance=10000.0,
        equity=10000.0,
        leverage=1,
        positions=[]
    )


@app.get("/health")
async def health_check():
    """Health check endpoint."""
    return {"status": "healthy", "timestamp": datetime.now().isoformat()}


# Include routers
app.include_router(metrics.router, prefix="/api")


# Startup event
@app.on_event("startup")
async def startup_event():
    """Initialize on startup."""
    print("BackendV2 API started")


if __name__ == "__main__":
    import uvicorn
    uvicorn.run(app, host="0.0.0.0", port=8000)