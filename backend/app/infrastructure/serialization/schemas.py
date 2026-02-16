"""Pydantic DTOs for API serialization — separate from domain models.

These DTOs handle camelCase aliasing for the frontend JSON contract and
provide converters to/from domain objects.  The API layer (routers) uses
these exclusively; the domain layer never imports Pydantic.
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field


# ---------------------------------------------------------------------------
# Enums (mirrored for OpenAPI docs)
# ---------------------------------------------------------------------------

class MessageRoleDTO(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


# ---------------------------------------------------------------------------
# Market Data DTOs
# ---------------------------------------------------------------------------

class OHLCDataDTO(BaseModel):
    time: str
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float = 0.0
    taker_buy_volume: float = Field(alias="takerBuyVolume", default=0.0)
    delta: float = 0.0

    model_config = {"populate_by_name": True}


class OrderBookLevelDTO(BaseModel):
    price: float
    quantity: float


class OrderBookDTO(BaseModel):
    bids: list[OrderBookLevelDTO] = []
    asks: list[OrderBookLevelDTO] = []


# ---------------------------------------------------------------------------
# AMT DTOs
# ---------------------------------------------------------------------------

class VolumeProfileLevelDTO(BaseModel):
    price: float
    volume: float = 0.0
    buy_volume: float = Field(alias="buyVolume", default=0.0)
    sell_volume: float = Field(alias="sellVolume", default=0.0)

    model_config = {"populate_by_name": True}


class AggressivePrintDTO(BaseModel):
    price: float
    time: str
    volume: float
    delta: float
    side: str


class TradeSignalDTO(BaseModel):
    type: str
    price: float
    reason: str
    stop_loss: float = Field(alias="stopLoss", default=0.0)
    take_profit: float = Field(alias="takeProfit", default=0.0)
    timestamp: str = ""
    setup: str = ""
    source: str = ""
    metadata: Optional[dict[str, Any]] = None

    model_config = {"populate_by_name": True}


class AMTAnalysisDTO(BaseModel):
    market_state: str = Field(alias="marketState", default="BALANCED")
    poc: float = 0
    value_area_high: float = Field(alias="valueAreaHigh", default=0)
    value_area_low: float = Field(alias="valueAreaLow", default=0)
    lvns: list[float] = []
    hvns: list[float] = []
    aggression: float = 0
    signal: Optional[TradeSignalDTO] = None
    setup: Optional[str] = None
    profile: list[VolumeProfileLevelDTO] = []
    aggressive_prints: list[AggressivePrintDTO] = Field(alias="aggressivePrints", default=[])

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# AI / Prediction DTOs
# ---------------------------------------------------------------------------

class ModelWeightsDTO(BaseModel):
    trend: float = 0.40
    momentum: float = 0.25
    delta: float = 0.15
    order_book: float = Field(alias="orderBook", default=0.15)
    volatility: float = 0.05

    model_config = {"populate_by_name": True}


class FactorBreakdownDTO(BaseModel):
    trend: float = 0
    momentum: float = 0
    delta: float = 0
    order_book: float = Field(alias="orderBook", default=0)
    volatility: float = 0

    model_config = {"populate_by_name": True}


class AIAnalysisDTO(BaseModel):
    sentiment: str = "NEUTRAL"
    confidence: float = 0
    long_term_trend: str = Field(alias="longTermTrend", default="SIDEWAYS")
    volatility_score: float = Field(alias="volatilityScore", default=0)
    quant_score: float = Field(alias="quantScore", default=0)
    projected_price: float = Field(alias="projectedPrice", default=0)
    reasoning: list[str] = []
    factor_breakdown: FactorBreakdownDTO = Field(
        alias="factorBreakdown", default_factory=FactorBreakdownDTO
    )

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Trading DTOs
# ---------------------------------------------------------------------------

class TradePositionDTO(BaseModel):
    id: str
    symbol: str
    side: str
    source: str
    entry_price: float = Field(alias="entryPrice")
    size: float
    stop_loss: float = Field(alias="stopLoss")
    take_profit: float = Field(alias="takeProfit")
    pnl: float = 0.0
    entry_time: str = Field(alias="entryTime", default="")
    status: str = "OPEN"
    exit_price: Optional[float] = Field(alias="exitPrice", default=None)
    exit_time: Optional[str] = Field(alias="exitTime", default=None)
    close_reason: Optional[str] = Field(alias="closeReason", default=None)
    metadata: Optional[dict[str, Any]] = None

    model_config = {"populate_by_name": True}


class PortfolioDTO(BaseModel):
    balance: float
    equity: float
    leverage: int = 10
    positions: list[TradePositionDTO] = []
    closed_trades: list[TradePositionDTO] = Field(alias="closedTrades", default=[])
    history: list[dict[str, Any]] = []

    model_config = {"populate_by_name": True}


class StrategyStatsDTO(BaseModel):
    total_trades: int = Field(alias="totalTrades", default=0)
    wins: int = 0
    losses: int = 0
    win_rate: float = Field(alias="winRate", default=0)
    net_profit: float = Field(alias="netProfit", default=0)
    avg_profit: float = Field(alias="avgProfit", default=0)
    largest_win: float = Field(alias="largestWin", default=0)
    largest_loss: float = Field(alias="largestLoss", default=0)

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Footprint DTOs
# ---------------------------------------------------------------------------

class FootprintLevelDTO(BaseModel):
    price: float
    bid: float
    ask: float
    delta: float
    imbalance: bool = False


class FootprintCandleDTO(BaseModel):
    time: str
    levels: list[FootprintLevelDTO] = []
    poc_price: float = Field(alias="pocPrice", default=0)
    total_delta: float = Field(alias="totalDelta", default=0)
    step_price: float = Field(alias="stepPrice", default=0)

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Chat / AI Command DTOs
# ---------------------------------------------------------------------------

class ChatMessageDTO(BaseModel):
    id: str
    role: MessageRoleDTO
    text: str
    timestamp: Optional[str] = None


class AICommandResponseDTO(BaseModel):
    message: str
    config_updates: Optional[dict[str, Any]] = Field(alias="configUpdates", default=None)
    action: Optional[str] = None

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Request DTOs
# ---------------------------------------------------------------------------

class AMTRequestDTO(BaseModel):
    data: list[OHLCDataDTO]
    order_book: Optional[OrderBookDTO] = Field(alias="orderBook", default=None)

    model_config = {"populate_by_name": True}


class PredictionRequestDTO(BaseModel):
    data: list[OHLCDataDTO]
    weights: ModelWeightsDTO = Field(default_factory=ModelWeightsDTO)
    count: int = 10
    order_book: Optional[OrderBookDTO] = Field(alias="orderBook", default=None)

    model_config = {"populate_by_name": True}


class FootprintRequestDTO(BaseModel):
    data: list[OHLCDataDTO]


class StatsRequestDTO(BaseModel):
    closed_trades: list[TradePositionDTO] = Field(alias="closedTrades", default=[])
    source: str = "AMT"

    model_config = {"populate_by_name": True}


class CommandRequestDTO(BaseModel):
    prompt: str
    current_config: dict[str, Any] = Field(alias="currentConfig", default={})

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Converters: Domain ↔ DTO
# ---------------------------------------------------------------------------

def ohlc_to_dto(o) -> dict:
    """Convert a domain OHLC to a serialisable dict with camelCase keys."""
    return {
        "time": o.time, "open": o.open, "high": o.high,
        "low": o.low, "close": o.close, "volume": o.volume,
        "vwap": o.vwap, "takerBuyVolume": o.taker_buy_volume,
        "delta": o.delta,
    }


def dto_to_ohlc(d: OHLCDataDTO):
    """Convert a Pydantic DTO to a domain OHLC value object."""
    from app.domain.trading.models.value_objects import OHLC
    return OHLC(
        time=d.time, open=d.open, high=d.high, low=d.low,
        close=d.close, volume=d.volume, vwap=d.vwap,
        taker_buy_volume=d.taker_buy_volume, delta=d.delta,
    )


def dto_to_order_book(d: Optional[OrderBookDTO]):
    """Convert a DTO OrderBook to domain."""
    if d is None:
        return None
    from app.domain.trading.models.value_objects import OrderBook, OrderBookLevel
    return OrderBook(
        bids=tuple(OrderBookLevel(price=b.price, quantity=b.quantity) for b in d.bids),
        asks=tuple(OrderBookLevel(price=a.price, quantity=a.quantity) for a in d.asks),
    )


def dto_to_weights(d: ModelWeightsDTO):
    from app.domain.fabio_ai.models.predictions import ModelWeights
    return ModelWeights(
        trend=d.trend, momentum=d.momentum, delta=d.delta,
        order_book=d.order_book, volatility=d.volatility,
    )


def position_to_dto(p) -> dict:
    """Convert a domain Position entity to a serialisable dict."""
    return {
        "id": p.id, "symbol": p.symbol,
        "side": p.side.value if hasattr(p.side, "value") else p.side,
        "source": p.source.value if hasattr(p.source, "value") else p.source,
        "entryPrice": p.entry_price, "size": p.size,
        "stopLoss": p.stop_loss, "takeProfit": p.take_profit,
        "pnl": p.pnl, "entryTime": p.entry_time,
        "status": p.status.value if hasattr(p.status, "value") else p.status,
        "exitPrice": p.exit_price, "exitTime": p.exit_time,
        "closeReason": p.close_reason, "metadata": p.metadata,
    }


def portfolio_to_dto(p) -> dict:
    """Convert a domain Portfolio aggregate to a serialisable dict."""
    return {
        "balance": p.balance, "equity": p.equity,
        "leverage": p.leverage,
        "positions": [position_to_dto(pos) for pos in p.positions],
        "closedTrades": [position_to_dto(ct) for ct in p.closed_trades[-50:]],
        "history": p.history[-100:],
    }


def signal_to_dto(s) -> Optional[dict]:
    """Convert domain Signal to serialisable dict."""
    if s is None:
        return None
    return {
        "type": s.type.value if hasattr(s.type, "value") else s.type,
        "price": s.price, "reason": s.reason,
        "stopLoss": s.stop_loss, "takeProfit": s.take_profit,
        "timestamp": s.timestamp,
        "setup": s.setup.value if hasattr(s.setup, "value") else s.setup,
        "source": s.source.value if hasattr(s.source, "value") else s.source,
        "metadata": s.metadata,
    }


def amt_result_to_dto(r) -> dict:
    """Convert domain AMTResult to serialisable dict."""
    return {
        "marketState": r.market_state, "poc": r.poc,
        "valueAreaHigh": r.value_area_high, "valueAreaLow": r.value_area_low,
        "lvns": list(r.lvns), "hvns": list(r.hvns),
        "aggression": r.aggression,
        "signal": signal_to_dto(r.signal),
        "setup": r.setup,
        "profile": [
            {"price": p.price, "volume": p.volume,
             "buyVolume": p.buy_volume, "sellVolume": p.sell_volume}
            for p in r.profile
        ],
        "aggressivePrints": [
            {"price": ap.price, "time": ap.time, "volume": ap.volume,
             "delta": ap.delta, "side": ap.side}
            for ap in r.aggressive_prints
        ],
    }


def stats_to_dto(s) -> dict:
    return {
        "totalTrades": s.total_trades, "wins": s.wins, "losses": s.losses,
        "winRate": s.win_rate, "netProfit": s.net_profit,
        "avgProfit": s.avg_profit,
        "largestWin": s.largest_win, "largestLoss": s.largest_loss,
    }


def footprint_to_dto(fp) -> dict:
    """Convert a domain FootprintCandle to serialisable dict."""
    return {
        "time": fp.time,
        "levels": [
            {"price": l.price, "bid": l.bid, "ask": l.ask,
             "delta": l.delta, "imbalance": l.imbalance}
            for l in fp.levels
        ],
        "pocPrice": fp.poc_price,
        "totalDelta": fp.total_delta,
        "stepPrice": fp.step_price,
    }
