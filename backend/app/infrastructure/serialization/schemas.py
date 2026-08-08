"""Pydantic DTOs for API serialization — separate from domain models.

These DTOs handle camelCase aliasing for the frontend JSON contract and
provide converters to/from domain objects.  The API layer (routers) uses
these exclusively; the domain layer never imports Pydantic.
"""

from enum import Enum
from typing import Any, Dict, List, Optional

from pydantic import BaseModel, Field
from shared.entities.models import Side as SharedSide, OrderSide, OrderStatus


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
    is_warmup: bool = Field(alias="isWarmUp", default=False)

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
    aggressive_prints: list[AggressivePrintDTO] = Field(
        alias="aggressivePrints", default=[]
    )
    cvd_slope: float = Field(alias="cvdSlope", default=0.0)
    cvd_divergence: str = Field(alias="cvdDivergence", default="")
    profile_shape: str = Field(alias="profileShape", default="")
    profile_type: str = Field(alias="profileType", default="Session")
    session_vwap: float = Field(alias="sessionVwap", default=0.0)
    vwap_upper_1: float = Field(alias="vwapUpper1", default=0.0)
    vwap_lower_1: float = Field(alias="vwapLower1", default=0.0)
    vwap_upper_2: float = Field(alias="vwapUpper2", default=0.0)
    vwap_lower_2: float = Field(alias="vwapLower2", default=0.0)
    balance_ratio: float = Field(alias="balanceRatio", default=0.0)
    # Displacement leg profile
    leg_profile: list[VolumeProfileLevelDTO] = Field(alias="legProfile", default=[])
    leg_lvns: list[float] = Field(alias="legLvns", default=[])
    leg_poc: float = Field(alias="legPoc", default=0.0)
    leg_vah: float = Field(alias="legVah", default=0.0)
    leg_val: float = Field(alias="legVal", default=0.0)
    has_displacement: bool = Field(alias="hasDisplacement", default=False)
    # Market structure (5-state classifier)
    market_structure: str = Field(alias="marketStructure", default="BALANCE")
    structure_confidence: int = Field(alias="structureConfidence", default=0)
    # Initial Balance
    ib_high: float = Field(alias="ibHigh", default=0.0)
    ib_low: float = Field(alias="ibLow", default=0.0)
    ib_complete: bool = Field(alias="ibComplete", default=False)
    # Prior day levels
    prior_poc: float = Field(alias="priorPoc", default=0.0)
    prior_vah: float = Field(alias="priorVah", default=0.0)
    prior_val: float = Field(alias="priorVal", default=0.0)
    gap_type: str = Field(alias="gapType", default="")
    opening_bias: str = Field(alias="openingBias", default="")
    # Acceptance / Rejection
    acceptance_above: bool = Field(alias="acceptanceAbove", default=False)
    acceptance_below: bool = Field(alias="acceptanceBelow", default=False)
    rejection_at_high: bool = Field(alias="rejectionAtHigh", default=False)
    rejection_at_low: bool = Field(alias="rejectionAtLow", default=False)
    price_velocity: float = Field(alias="priceVelocity", default=0.0)
    # Break detection
    break_direction: str = Field(alias="breakDirection", default="")
    break_type: str = Field(alias="breakType", default="")
    break_level: float = Field(alias="breakLevel", default=0.0)
    # POC migration + LVN play
    poc_signal: str = Field(alias="pocSignal", default="")
    poc_vs_price: str = Field(alias="pocVsPrice", default="")
    lvn_play: Optional[dict[str, Any]] = Field(alias="lvnPlay", default=None)
    is_second_drive: bool = Field(alias="isSecondDrive", default=False)  # Task 3.3: Fabio Playbook drive cycle
    llm_thinking: str = Field(alias="llmThinking", default="")
    llm_json: str = Field(alias="llmJson", default="{}")
    daily_vah: float = Field(alias="dailyVah", default=0.0)
    daily_val: float = Field(alias="dailyVal", default=0.0)
    daily_poc: float = Field(alias="dailyPoc", default=0.0)
    hourly_poc: float = Field(alias="hourlyPoc", default=0.0)

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
    partial_realized_pnl: float = Field(alias="partialRealizedPnl", default=0.0)
    original_size: float = Field(alias="originalSize", default=0.0)

    model_config = {"populate_by_name": True, "extra": "forbid"}


class PortfolioDTO(BaseModel):
    balance: float
    equity: float
    leverage: int = 1
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


class PositionEventDTO(BaseModel):
    id: int
    event_id: str = Field(alias="eventId", default="")
    position_id: str = Field(alias="positionId")
    symbol: str
    event_type: str = Field(alias="eventType")
    event_time: str = Field(alias="eventTime", default="")
    created_at: str = Field(alias="createdAt", default="")
    side: Optional[str] = None
    entry_price: Optional[float] = Field(alias="entryPrice", default=None)
    exit_price: Optional[float] = Field(alias="exitPrice", default=None)
    stop_loss: Optional[float] = Field(alias="stopLoss", default=None)
    take_profit: Optional[float] = Field(alias="takeProfit", default=None)
    source: Optional[str] = None
    pnl: Optional[float] = None
    exit_reason: Optional[str] = Field(alias="exitReason", default=None)
    partial_pct: Optional[float] = Field(alias="partialPct", default=None)
    size_closed: Optional[float] = Field(alias="sizeClosed", default=None)
    size_remaining: Optional[float] = Field(alias="sizeRemaining", default=None)
    realized_pnl: Optional[float] = Field(alias="realizedPnl", default=None)
    time_in_trade_s: Optional[float] = Field(alias="timeInTradeS", default=None)

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
    is_warmup: bool = Field(alias="isWarmUp", default=False)

    model_config = {"populate_by_name": True}


# ---------------------------------------------------------------------------
# Chat DTOs
# ---------------------------------------------------------------------------


class ChatMessageDTO(BaseModel):
    id: str
    role: MessageRoleDTO
    text: str
    timestamp: Optional[str] = None


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


# ---------------------------------------------------------------------------
# Converters: Domain ↔ DTO
# ---------------------------------------------------------------------------


def enum_to_value(val):
    """Convert enum to its value, pass through non-enums."""
    return val.value if hasattr(val, "value") else val


def ohlc_to_dto(o) -> dict:
    """Convert a domain OHLC to a serialisable dict with camelCase keys."""
    return {
        "time": o.time,
        "open": float(o.open),
        "high": float(o.high),
        "low": float(o.low),
        "close": float(o.close),
        "volume": float(o.volume),
        "vwap": float(o.vwap),
        "takerBuyVolume": float(o.taker_buy_volume),
        "delta": float(o.delta),
        "isWarmUp": bool(getattr(o, "is_warmup", False)),
    }


def dto_to_ohlc(d: OHLCDataDTO):
    """Convert a Pydantic DTO to a domain OHLC value object."""
    from quant.contracts.value_objects import OHLC

    return OHLC(
        time=d.time,
        open=d.open,
        high=d.high,
        low=d.low,
        close=d.close,
        volume=d.volume,
        vwap=d.vwap,
        taker_buy_volume=d.taker_buy_volume,
        delta=d.delta,
    )


def dto_to_order_book(d: Optional[OrderBookDTO]):
    """Convert a DTO OrderBook to domain."""
    if d is None:
        return None
    from quant.contracts.value_objects import OrderBook, OrderBookLevel

    return OrderBook(
        bids=tuple(OrderBookLevel(price=b.price, quantity=b.quantity) for b in d.bids),
        asks=tuple(OrderBookLevel(price=a.price, quantity=a.quantity) for a in d.asks),
    )


def dto_to_weights(d: ModelWeightsDTO):
    from quant.inference.models import ModelWeights

    return ModelWeights(
        trend=d.trend,
        momentum=d.momentum,
        delta=d.delta,
        order_book=d.order_book,
        volatility=d.volatility,
    )


def position_to_dto(p) -> dict:
    """Convert a domain Position entity to a serialisable dict."""
    metadata = p.metadata or {}

    return {
        "id": p.id,
        "symbol": p.symbol,
        "side": enum_to_value(p.side),
        "source": enum_to_value(p.source),
        "entryPrice": float(p.entry_price),
        "size": float(p.size),
        "stopLoss": float(p.stop_loss),
        "takeProfit": float(p.take_profit),
        "pnl": round(float(p.pnl), 2),
        "entryTime": p.entry_time,
        "status": enum_to_value(p.status),
        "exitPrice": float(p.exit_price) if p.exit_price is not None else None,
        "exitTime": p.exit_time,
        "closeReason": p.close_reason,
        "metadata": metadata,
        "partialRealizedPnl": round(
            float(metadata.get("partial_realized_pnl", 0.0)), 2
        ),
        "originalSize": float(metadata.get("full_size", p.size)),
    }


def position_event_to_dto(event: dict[str, Any]) -> dict:
    """Convert a persisted lifecycle event row to a serialisable dict."""
    return PositionEventDTO(
        id=event.get("id", 0),
        eventId=event.get("event_id", "") or "",
        positionId=event.get("position_id", ""),
        symbol=event.get("symbol", ""),
        eventType=event.get("event_type", ""),
        eventTime=event.get("event_time", "") or "",
        createdAt=event.get("created_at", "") or "",
        side=event.get("side"),
        entryPrice=event.get("entry_price"),
        exitPrice=event.get("exit_price"),
        stopLoss=event.get("stop_loss"),
        takeProfit=event.get("take_profit"),
        source=event.get("source"),
        pnl=event.get("pnl"),
        exitReason=event.get("exit_reason"),
        partialPct=event.get("partial_pct"),
        sizeClosed=event.get("size_closed"),
        sizeRemaining=event.get("size_remaining"),
        realizedPnl=event.get("realized_pnl"),
        timeInTradeS=event.get("time_in_trade_s"),
    ).model_dump(by_alias=True)


def portfolio_to_dto(p) -> dict:
    """Convert a domain Portfolio aggregate to a serialisable dict."""
    return {
        "balance": float(p.balance),
        "equity": float(p.equity),
        "leverage": p.leverage,
        "positions": [position_to_dto(pos) for pos in p.positions],
        "closedTrades": [position_to_dto(ct) for ct in p.closed_trades[-50:]],
    }


def signal_to_dto(s) -> Optional[dict]:
    """Convert domain Signal to serialisable dict."""
    if s is None:
        return None
    return {
        "type": enum_to_value(s.type),
        "price": s.price,
        "reason": s.reason,
        "stopLoss": s.stop_loss,
        "takeProfit": s.take_profit,
        "timestamp": s.timestamp,
        "setup": enum_to_value(s.setup),
        "source": enum_to_value(s.source),
        "metadata": s.metadata,
    }


def stats_to_dto(s) -> dict:
    return {
        "totalTrades": s.total_trades,
        "wins": s.wins,
        "losses": s.losses,
        "winRate": s.win_rate,
        "netProfit": s.net_profit,
        "avgProfit": s.avg_profit,
        "largestWin": s.largest_win,
        "largestLoss": s.largest_loss,
    }


def footprint_to_dto(fp) -> dict:
    """Convert a domain FootprintCandle to serialisable dict."""
    return {
        "time": fp.time,
        "levels": [
            {
                "price": l.price,
                "bid": l.bid,
                "ask": l.ask,
                "delta": l.delta,
                "imbalance": l.imbalance,
                "stacked": getattr(l, "stacked", False),
            }
            for l in fp.levels
        ],
        "pocPrice": fp.poc_price,
        "totalDelta": fp.total_delta,
        "stepPrice": fp.step_price,
        "isWarmUp": bool(getattr(fp, "is_warmup", False)),
    }
