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
    cvd_slope: float = Field(alias="cvdSlope", default=0.0)
    cvd_divergence: str = Field(alias="cvdDivergence", default="")
    profile_shape: str = Field(alias="profileShape", default="")
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
        "partialRealizedPnl": (p.metadata or {}).get("partial_realized_pnl", 0.0),
        "originalSize": (p.metadata or {}).get("full_size", p.size),
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
        "cvdSlope": getattr(r, "cvd_slope", 0.0),
        "cvdDivergence": getattr(r, "cvd_divergence", ""),
        "profileShape": getattr(r, "profile_shape", ""),
        "sessionVwap": getattr(r, "session_vwap", 0.0),
        "vwapUpper1": getattr(r, "vwap_upper_1", 0.0),
        "vwapLower1": getattr(r, "vwap_lower_1", 0.0),
        "vwapUpper2": getattr(r, "vwap_upper_2", 0.0),
        "vwapLower2": getattr(r, "vwap_lower_2", 0.0),
        "balanceRatio": getattr(r, "balance_ratio", 0.0),
        "legProfile": [
            {"price": p.price, "volume": p.volume,
             "buyVolume": p.buy_volume, "sellVolume": p.sell_volume}
            for p in getattr(r, "leg_profile", ())
        ],
        "legLvns": list(getattr(r, "leg_lvns", ())),
        "legPoc": getattr(r, "leg_poc", 0.0),
        "legVah": getattr(r, "leg_vah", 0.0),
        "legVal": getattr(r, "leg_val", 0.0),
        "hasDisplacement": getattr(r, "has_displacement", False),
        "ofi": getattr(r, "ofi", 0.0),
        # Market structure
        "marketStructure": getattr(r, "market_structure", "BALANCE"),
        "structureConfidence": getattr(r, "structure_confidence", 0),
        # Initial Balance
        "ibHigh": getattr(r, "ib_high", 0.0),
        "ibLow": getattr(r, "ib_low", 0.0),
        "ibComplete": getattr(r, "ib_complete", False),
        # Prior day levels
        "priorPoc": getattr(r, "prior_poc", 0.0),
        "priorVah": getattr(r, "prior_vah", 0.0),
        "priorVal": getattr(r, "prior_val", 0.0),
        "gapType": getattr(r, "gap_type", ""),
        "openingBias": getattr(r, "opening_bias", ""),
        # Acceptance / Rejection
        "acceptanceAbove": getattr(r, "acceptance_above", False),
        "acceptanceBelow": getattr(r, "acceptance_below", False),
        "rejectionAtHigh": getattr(r, "rejection_at_high", False),
        "rejectionAtLow": getattr(r, "rejection_at_low", False),
        "priceVelocity": getattr(r, "price_velocity", 0.0),
        # Break detection
        "breakDirection": getattr(r, "break_direction", ""),
        "breakType": getattr(r, "break_type", ""),
        "breakLevel": getattr(r, "break_level", 0.0),
        # POC migration + LVN play
        "pocSignal": getattr(r, "poc_signal", ""),
        "pocVsPrice": getattr(r, "poc_vs_price", ""),
        "lvnPlay": getattr(r, "lvn_play", None),
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
             "delta": l.delta, "imbalance": l.imbalance,
             "stacked": getattr(l, "stacked", False)}
            for l in fp.levels
        ],
        "pocPrice": fp.poc_price,
        "totalDelta": fp.total_delta,
        "stepPrice": fp.step_price,
    }
