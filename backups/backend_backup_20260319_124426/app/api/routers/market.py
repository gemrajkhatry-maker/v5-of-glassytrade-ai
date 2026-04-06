"""Market data router — REST endpoints for market data."""

from fastapi import APIRouter, Depends, Query

from app.api.dependencies import get_market_data
from app.domain.ports.market_data import MarketDataPort
from app.infrastructure.serialization.schemas import ohlc_to_dto

router = APIRouter(prefix="/market", tags=["market"])


@router.get("/scan")
async def scan_market(
    limit: int = Query(6, ge=1, le=20),
    market_data: MarketDataPort = Depends(get_market_data),
):
    candidates = await market_data.scan_candidates(limit)
    return {"candidates": candidates}


@router.get("/history/{symbol}")
async def get_history(
    symbol: str,
    interval: str = Query("5m"),
    limit: int = Query(500, ge=1, le=1000),
    market_data: MarketDataPort = Depends(get_market_data),
):
    data = await market_data.fetch_history(symbol, interval, limit)
    return {"data": [ohlc_to_dto(d) for d in data]}


@router.get("/orderbook/{symbol}")
async def get_orderbook(
    symbol: str,
    market_data: MarketDataPort = Depends(get_market_data),
):
    ob = await market_data.fetch_order_book(symbol)
    if ob is None:
        return {"orderBook": None}
    return {
        "orderBook": {
            "bids": [{"price": b.price, "quantity": b.quantity} for b in ob.bids],
            "asks": [{"price": a.price, "quantity": a.quantity} for a in ob.asks],
        }
    }
