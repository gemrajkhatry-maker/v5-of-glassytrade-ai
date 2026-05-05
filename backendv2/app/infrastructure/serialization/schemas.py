"""Pydantic DTOs for API and runtime boundary."""

from __future__ import annotations

from enum import Enum
from typing import Any, Optional

from pydantic import BaseModel, Field

from app.domain.trading.model.enums import Side, Source, PositionStatus
from app.domain.trading.model.value_objects import AMTResult, OHLC, OrderBook, OrderBookLevel


class MessageRoleDTO(str, Enum):
    USER = "user"
    ASSISTANT = "assistant"
    SYSTEM = "system"


class ChatMessageDTO(BaseModel):
    id: str
    role: MessageRoleDTO
    text: str
    timestamp: str | None = None


class OHLCDataDTO(BaseModel):
    time: str | None = None
    open: float
    high: float
    low: float
    close: float
    volume: float
    vwap: float = 0.0
    takerBuyVolume: float = Field(alias="takerBuyVolume", default=0.0)
    delta: float = 0.0
    symbol: str | None = None
    timestamp: int | None = None


class VolumeProfileLevelDTO(BaseModel):
    price: float
    volume: float = 0.0
    buyVolume: float = Field(alias="buyVolume", default=0.0)
    sellVolume: float = Field(alias="sellVolume", default=0.0)


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
    stopLoss: float = Field(alias="stopLoss", default=0.0)
    takeProfit: float = Field(alias="takeProfit", default=0.0)
    timestamp: str = ""
    setup: str = ""
    source: str = ""
    metadata: dict[str, Any] | None = None


class AMTAnalysisDTO(BaseModel):
    marketState: str
    poc: float = 0.0
    valueAreaHigh: float = 0.0
    valueAreaLow: float = 0.0
    signal: object | None = None
    setup: str | None = None
    profile: list[VolumeProfileLevelDTO] = Field(default_factory=list)
    aggressivePrints: list[AggressivePrintDTO] = Field(
        default_factory=list, alias="aggressivePrints"
    )
    cvdSlope: float = 0.0
    cvdDivergence: str = ""
    profileShape: str = ""
    profileType: str = "Session"
    sessionVwap: float = 0.0
    vwapUpper1: float = 0.0
    vwapLower1: float = 0.0
    vwapUpper2: float = 0.0
    vwapLower2: float = 0.0
    balanceRatio: float = 0.0
    legProfile: list[VolumeProfileLevelDTO] = Field(default_factory=list)
    legLvns: list[float] = Field(default_factory=list)
    legPoc: float = 0.0
    legVah: float = 0.0
    legVal: float = 0.0
    hasDisplacement: bool = False
    marketStructure: str = "BALANCE"
    structureConfidence: int = 0
    ibHigh: float = 0.0
    ibLow: float = 0.0
    ibComplete: bool = False
    priorPoc: float = 0.0
    priorVah: float = 0.0
    priorVal: float = 0.0
    gapType: str = ""
    openingBias: str = ""
    acceptanceAbove: bool = False
    acceptanceBelow: bool = False
    rejectionAtHigh: bool = False
    rejectionAtLow: bool = False
    priceVelocity: float = 0.0
    breakDirection: str = ""
    breakType: str = ""
    breakLevel: float = 0.0
    pocSignal: str = ""
    pocVsPrice: str = ""
    lvnPlay: dict[str, Any] | None = Field(alias="lvnPlay", default=None)
    isSecondDrive: bool = False
    cushionTier: str = "Conservative"
    llmThinking: str = ""
    llmJson: str = "{}"
    sessionPnl: float = 0.0
    openingType: str = ""
    mtfAlignment: str = ""
    dailyVah: float = 0.0
    dailyVal: float = 0.0
    dailyPoc: float = 0.0
    hourlyVah: float = 0.0
    hourlyVal: float = 0.0
    hourlyPoc: float = 0.0
    isExtremeDeviation: bool = False
    liquiditySweep: str = ""
    absorptionSide: str = ""
    absorptionRangeRatio: float = 0.0
    absorptionVolRatio: float = 0.0
    deltaNormalizedOption: float = 0.0
    cvdSource: str = ""
    ofi: float = 0.0
    devPoc: float = 0.0
    devVah: float = 0.0
    devVal: float = 0.0
    dayType: str = ""
    swingDelta: float = 0.0
    bimodalActivePole: str = ""
    npocAbove: float = 0.0
    npocBelow: float = 0.0
    underlyingPrice: float = 0.0
    optionType: str = "UNKNOWN"


class ModelWeightsDTO(BaseModel):
    trend: float = 0.4
    momentum: float = 0.25
    delta: float = 0.15
    orderBook: float = 0.15
    volatility: float = 0.05


class FactorBreakdownDTO(BaseModel):
    factors: dict[str, float] = Field(default_factory=dict)
    reasons: list[str] = Field(default_factory=list)


class AIAnalysisDTO(BaseModel):
    sentiment: str = "NEUTRAL"
    confidence: float = 0.0
    longTermTrend: str = Field(default="SIDEWAYS")
    volatilityScore: float = Field(default=0.0)
    projectedPrice: float = Field(default=0.0)
    reasoning: list[str] = Field(default_factory=list)
    factorBreakdown: dict[str, float] = Field(default_factory=dict)
    weights: ModelWeightsDTO = Field(default_factory=ModelWeightsDTO)


class TradePositionDTO(BaseModel):
    id: str
    symbol: str
    side: str
    source: str
    entryPrice: float
    size: float
    stopLoss: float
    takeProfit: float
    pnl: float = 0.0
    entryTime: str = ""
    status: str = "OPEN"
    exitPrice: float | None = None
    exitTime: str | None = None
    closeReason: str | None = None
    metadata: dict[str, Any] | None = None
    partialRealizedPnl: float = 0.0
    originalSize: float = 0.0
    lotSize: float | None = None


class PortfolioDTO(BaseModel):
    balance: float
    equity: float
    leverage: float | int
    positions: list[TradePositionDTO] = Field(default_factory=list)
    closedTrades: list[TradePositionDTO] = Field(default_factory=list)
    history: list[dict[str, Any]] = Field(default_factory=list)


class PositionEventDTO(BaseModel):
    eventId: str
    positionId: str
    symbol: str
    eventType: str
    eventTime: str
    createdAt: str
    side: str | None = None
    entryPrice: float | None = None
    exitPrice: float | None = None
    stopLoss: float | None = None
    takeProfit: float | None = None
    source: str | None = None
    pnl: float | None = None
    exitReason: str | None = None
    partialPct: float | None = None
    sizeClosed: float | None = None
    sizeRemaining: float | None = None
    realizedPnl: float | None = None
    timeInTradeS: float | None = None


class StrategyStatsDTO(BaseModel):
    totalTrades: int = 0
    wins: int = 0
    losses: int = 0
    winRate: float = 0.0
    netProfit: float = 0.0
    avgProfit: float = 0.0
    largestWin: float = 0.0
    largestLoss: float = 0.0


class OrderBookLevelDTO(BaseModel):
    price: float
    quantity: float


class OrderBookDTO(BaseModel):
    bids: list[OrderBookLevelDTO] = Field(default_factory=list)
    asks: list[OrderBookLevelDTO] = Field(default_factory=list)


class FootprintLevelDTO(BaseModel):
    price: float
    bid: float
    ask: float
    delta: float
    imbalance: bool = False


class FootprintCandleDTO(BaseModel):
    time: str
    levels: list[FootprintLevelDTO] = Field(default_factory=list)
    pocPrice: float = Field(alias="pocPrice", default=0.0)
    totalDelta: float = Field(alias="totalDelta", default=0.0)
    stepPrice: float = Field(alias="stepPrice", default=0.0)


class AICommandResponseDTO(BaseModel):
    message: str
    configUpdates: dict[str, Any] | None = Field(default_factory=dict)
    action: str | None = None
    llmThinking: str = ""
    warnings: list[str] = Field(default_factory=list)


class AICommandHistoryItemDTO(BaseModel):
    command: str
    response: str
    createdAt: str
    source: str = "user"


class RuntimeControlRequest(BaseModel):
    session_id: str
    symbols: list[str]
    mode: str | None = None


class AMTRequestDTO(BaseModel):
    data: list[OHLCDataDTO]
    orderBook: OrderBookDTO | None = Field(default=None, alias="orderBook")


class PredictionRequestDTO(BaseModel):
    data: list[OHLCDataDTO]
    weights: ModelWeightsDTO = Field(default_factory=ModelWeightsDTO)
    count: int = 10
    orderBook: OrderBookDTO | None = Field(default=None, alias="orderBook")


class FootprintRequestDTO(BaseModel):
    data: list[OHLCDataDTO]


class StatsRequestDTO(BaseModel):
    closedTrades: list[TradePositionDTO] = Field(default_factory=list, alias="closedTrades")
    source: str = "AMT"


class CommandRequestDTO(BaseModel):
    prompt: str
    currentConfig: dict[str, Any] = Field(default_factory=dict, alias="currentConfig")


class TradeLifecycleEventDTO(BaseModel):
    eventType: str
    symbol: str
    payload: dict[str, Any] = Field(default_factory=dict)
    createdAt: str = ""


class ScannerResponseDTO(BaseModel):
    symbol: str
    score: float
    signal: str
    reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class HealthResponseDTO(BaseModel):
    status: str = "ok"
    timestamp: str = ""
    details: dict[str, Any] = Field(default_factory=dict)


class RuntimeStateDTO(BaseModel):
    session_id: str
    running: bool = False
    mode: str = "live"
    symbols: list[str] = Field(default_factory=list)
    checkpoint: dict[str, Any] | None = None


class HealthReadyResponseDTO(HealthResponseDTO):
    ready: bool = True


def _side_value(side: Side) -> str:
    return side.value if hasattr(side, "value") else str(side)


def _source_value(source: Source) -> str:
    return source.value if hasattr(source, "value") else str(source)


def enum_to_value(val):
    return val.value if hasattr(val, "value") else val


def ohlc_to_dto(item: OHLC) -> dict[str, Any]:
    return OHLCDataDTO(
        open=item.open,
        high=item.high,
        low=item.low,
        close=item.close,
        volume=float(item.volume),
        time=item.time,
    ).dict(by_alias=True)


def dto_to_ohlc(dto: OHLCDataDTO) -> OHLC:
    return OHLC(
        time=dto.time,
        open=dto.open,
        high=dto.high,
        low=dto.low,
        close=dto.close,
        volume=dto.volume,
        vwap=dto.vwap,
        taker_buy_volume=dto.takerBuyVolume,
        delta=dto.delta,
    )


def dto_to_order_book(dto: OrderBookDTO) -> OrderBook:
    return OrderBook(
        bids=tuple(OrderBookLevel(price=b.price, quantity=b.quantity) for b in dto.bids),
        asks=tuple(OrderBookLevel(price=a.price, quantity=a.quantity) for a in dto.asks),
    )


def dto_to_weights(d: ModelWeightsDTO) -> dict[str, float]:
    return {
        "trend": d.trend,
        "momentum": d.momentum,
        "delta": d.delta,
        "order_book": d.orderBook,
        "volatility": d.volatility,
    }


def position_event_to_dto(event: dict[str, Any]) -> dict[str, Any]:
    return PositionEventDTO(
        eventId=event.get("event_id", "") or event.get("eventId", ""),
        positionId=event.get("position_id", "") or event.get("positionId", ""),
        symbol=event.get("symbol", ""),
        eventType=event.get("event_type", "") or event.get("eventType", ""),
        eventTime=event.get("event_time", "") or event.get("eventTime", ""),
        createdAt=event.get("created_at", "") or event.get("createdAt", ""),
        side=event.get("side"),
        entryPrice=event.get("entry_price"),
        exitPrice=event.get("exit_price"),
        stopLoss=event.get("stop_loss"),
        takeProfit=event.get("take_profit"),
        source=event.get("source"),
        pnl=event.get("pnl"),
        exitReason=event.get("exit_reason") or event.get("exitReason"),
        partialPct=event.get("partial_pct"),
        sizeClosed=event.get("size_closed"),
        sizeRemaining=event.get("size_remaining"),
        realizedPnl=event.get("realized_pnl"),
        timeInTradeS=event.get("time_in_trade_s"),
    ).dict(by_alias=True)


def signal_to_dto(s: Any) -> Optional[dict[str, Any]]:
    if s is None:
        return None
    return {
        "type": enum_to_value(getattr(s, "type", "")),
        "price": float(getattr(s, "price", 0.0)),
        "reason": getattr(s, "reason", ""),
        "stopLoss": float(getattr(s, "stop_loss", 0.0)),
        "takeProfit": float(getattr(s, "take_profit", 0.0)),
        "timestamp": getattr(s, "timestamp", ""),
        "setup": enum_to_value(getattr(s, "setup", "")),
        "source": enum_to_value(getattr(s, "source", "")),
        "metadata": getattr(s, "metadata", None),
    }


def order_book_to_dto(ob: OrderBook) -> OrderBookDTO:
    bid_items = [
        OrderBookLevelDTO(price=bid.price, quantity=bid.quantity) for bid in getattr(ob, "bids", [])
    ]
    ask_items = [
        OrderBookLevelDTO(price=ask.price, quantity=ask.quantity) for ask in getattr(ob, "asks", [])
    ]
    return OrderBookDTO(bids=bid_items, asks=ask_items)


def position_to_dto(position) -> dict[str, Any]:
    if isinstance(position, TradePositionDTO):
        return position.dict(by_alias=True)
    return TradePositionDTO(
        id=str(getattr(position, "id", "")),
        symbol=getattr(position, "symbol", ""),
        side=_side_value(getattr(position, "side", Side.LONG)),
        source=_source_value(getattr(position, "source", Source.AMT)),
        entryPrice=float(getattr(position, "entry_price", 0.0)),
        size=float(getattr(position, "size", 0.0)),
        stopLoss=float(getattr(position, "stop_loss", 0.0)),
        takeProfit=float(getattr(position, "take_profit", 0.0)),
        pnl=float(getattr(position, "pnl", 0.0)),
        entryTime=str(getattr(position, "entry_time", "")),
        status=getattr(position, "status", PositionStatus.OPEN).name
        if hasattr(getattr(position, "status", None), "name")
        else str(getattr(position, "status", "OPEN")),
        exitPrice=getattr(position, "exit_price", None),
        exitTime=str(getattr(position, "exit_time", "")) if getattr(position, "exit_time", None) else None,
        closeReason=str(getattr(position, "close_reason", "")) if getattr(position, "close_reason", None) else None,
        metadata=getattr(position, "metadata", None),
        partialRealizedPnl=float(getattr(position, "partial_realized_pnl", 0.0)),
        originalSize=float(getattr(position, "original_size", getattr(position, "size", 0.0))),
        lotSize=getattr(position, "lot_size", None),
    ).dict(by_alias=True)


def portfolio_to_dto(portfolio) -> dict[str, Any]:
    if hasattr(portfolio, "positions"):
        pos_list = [position_to_dto(p) for p in portfolio.positions]
    else:
        pos_list = []
    if hasattr(portfolio, "history"):
        hist = list(portfolio.history)
    else:
        hist = []
    return PortfolioDTO(
        balance=float(getattr(portfolio, "balance", 0.0)),
        equity=float(getattr(portfolio, "equity", 0.0)),
        leverage=float(getattr(portfolio, "leverage", 1.0)),
        positions=pos_list,
        closedTrades=[position_to_dto(p) for p in getattr(portfolio, "closed_trades", [])],
        history=hist,
    ).dict()


def amt_result_to_dto(result: AMTResult, *, llm_thinking: str = "", llm_json: str = "{}") -> dict[str, Any]:
    source = dict(result) if isinstance(result, dict) else dict(getattr(result, "__dict__", {}))
    payload: dict[str, Any] = {}
    payload["marketState"] = source.get("market_state", "BALANCED")
    payload["poc"] = float(source.get("poc", 0.0))
    payload["valueAreaHigh"] = float(source.get("value_area_high", 0.0))
    payload["valueAreaLow"] = float(source.get("value_area_low", 0.0))
    payload["signal"] = signal_to_dto(source.get("signal"))
    payload["setup"] = source.get("setup")
    payload["profile"] = [
        {
            "price": p.price,
            "volume": p.volume,
            "buyVolume": p.buy_volume,
            "sellVolume": p.sell_volume,
        }
        for p in source.get("profile", ())
    ]
    payload["aggressivePrints"] = [
        {
            "price": p.price,
            "time": p.time,
            "volume": p.volume,
            "delta": p.delta,
            "side": p.side,
        }
        for p in source.get("aggressive_prints", ())
    ]
    payload["cvdSlope"] = float(source.get("cvd_slope", 0.0))
    payload["cvdDivergence"] = source.get("cvd_divergence", "")
    payload["profileShape"] = source.get("profile_shape", "")
    payload["profileType"] = source.get("profile_type", "Session")
    payload["sessionVwap"] = float(source.get("session_vwap", 0.0))
    payload["vwapUpper1"] = float(source.get("vwap_upper_1", 0.0))
    payload["vwapLower1"] = float(source.get("vwap_lower_1", 0.0))
    payload["vwapUpper2"] = float(source.get("vwap_upper_2", 0.0))
    payload["vwapLower2"] = float(source.get("vwap_lower_2", 0.0))
    payload["balanceRatio"] = float(source.get("balance_ratio", 0.0))
    payload["legProfile"] = [
        {
            "price": p.price,
            "volume": p.volume,
            "buyVolume": p.buy_volume,
            "sellVolume": p.sell_volume,
        }
        for p in source.get("leg_profile", ())
    ]
    payload["legLvns"] = list(source.get("leg_lvns", ()))
    payload["legPoc"] = float(source.get("leg_poc", 0.0))
    payload["legVah"] = float(source.get("leg_vah", 0.0))
    payload["legVal"] = float(source.get("leg_val", 0.0))
    payload["hasDisplacement"] = bool(source.get("has_displacement", False))
    payload["marketStructure"] = source.get("market_structure", "BALANCE")
    payload["structureConfidence"] = int(source.get("structure_confidence", 0))
    payload["ibHigh"] = float(source.get("ib_high", 0.0))
    payload["ibLow"] = float(source.get("ib_low", 0.0))
    payload["ibComplete"] = bool(source.get("ib_complete", False))
    payload["priorPoc"] = float(source.get("prior_poc", 0.0))
    payload["priorVah"] = float(source.get("prior_vah", 0.0))
    payload["priorVal"] = float(source.get("prior_val", 0.0))
    payload["gapType"] = source.get("gap_type", "")
    payload["openingBias"] = source.get("opening_bias", "")
    payload["acceptanceAbove"] = bool(source.get("acceptance_above", False))
    payload["acceptanceBelow"] = bool(source.get("acceptance_below", False))
    payload["rejectionAtHigh"] = bool(source.get("rejection_at_high", False))
    payload["rejectionAtLow"] = bool(source.get("rejection_at_low", False))
    payload["priceVelocity"] = float(source.get("price_velocity", 0.0))
    payload["breakDirection"] = source.get("break_direction", "")
    payload["breakType"] = source.get("break_type", "")
    payload["breakLevel"] = float(source.get("break_level", 0.0))
    payload["pocSignal"] = source.get("poc_signal", "")
    payload["pocVsPrice"] = source.get("poc_vs_price", "")
    payload["lvnPlay"] = source.get("lvn_play")
    payload["isSecondDrive"] = bool(source.get("drive_entry_valid", False))
    payload["cushionTier"] = source.get("cushion_tier", "Conservative")
    payload["sessionPnl"] = float(source.get("session_pnl", 0.0))
    payload["openingType"] = source.get("opening_type", "")
    payload["mtfAlignment"] = source.get("mtf_alignment", "")
    payload["dailyVah"] = float(source.get("daily_vah", 0.0))
    payload["dailyVal"] = float(source.get("daily_val", 0.0))
    payload["dailyPoc"] = float(source.get("daily_poc", 0.0))
    payload["hourlyVah"] = float(source.get("hourly_vah", 0.0))
    payload["hourlyVal"] = float(source.get("hourly_val", 0.0))
    payload["hourlyPoc"] = float(source.get("hourly_poc", 0.0))
    payload["isExtremeDeviation"] = bool(source.get("is_extreme_deviation", False))
    payload["liquiditySweep"] = source.get("liquidity_sweep", "")
    payload["absorptionSide"] = source.get("absorption_side", "")
    payload["absorptionRangeRatio"] = float(source.get("absorption_range_ratio", 0.0))
    payload["absorptionVolRatio"] = float(source.get("absorption_vol_ratio", 0.0))
    payload["deltaNormalizedOption"] = float(source.get("delta_normalized_option", 0.0))
    payload["cvdSource"] = source.get("cvd_source", "")
    payload["npocAbove"] = float(source.get("npoc_above", 0.0))
    payload["npocBelow"] = float(source.get("npoc_below", 0.0))
    payload["underlyingPrice"] = float(source.get("underlying_price", 0.0))
    payload["optionType"] = source.get("option_type", "UNKNOWN")

    payload["devPoc"] = float(source.get("dev_poc", 0.0))
    payload["devVah"] = float(source.get("dev_vah", 0.0))
    payload["devVal"] = float(source.get("dev_val", 0.0))
    payload["dayType"] = source.get("day_type", "UNKNOWN")
    payload["bimodalActivePole"] = source.get("bimodal_active_pole", "")
    payload["ofi"] = float(source.get("ofi", 0.0))
    payload["swingDelta"] = float(source.get("swing_delta", 0.0))
    if llm_thinking:
        payload["llmThinking"] = llm_thinking
    if llm_json:
        payload["llmJson"] = llm_json
    return AMTAnalysisDTO(**payload).dict(by_alias=True)


def stats_to_dto(s) -> dict[str, Any]:
    return StrategyStatsDTO(
        totalTrades=getattr(s, "total_trades", 0),
        wins=getattr(s, "wins", 0),
        losses=getattr(s, "losses", 0),
        winRate=float(getattr(s, "win_rate", 0.0)),
        netProfit=float(getattr(s, "net_profit", 0.0)),
        avgProfit=float(getattr(s, "avg_profit", 0.0)),
        largestWin=float(getattr(s, "largest_win", 0.0)),
        largestLoss=float(getattr(s, "largest_loss", 0.0)),
    ).dict()


def footprint_to_dto(fp) -> dict[str, Any]:
    return FootprintCandleDTO(
        time=getattr(fp, "time", ""),
        levels=[
            FootprintLevelDTO(
                price=level.price,
                bid=level.bid,
                ask=level.ask,
                delta=level.delta,
                imbalance=getattr(level, "imbalance", False),
            )
            for level in getattr(fp, "levels", [])
        ],
        pocPrice=getattr(fp, "poc_price", 0.0),
        totalDelta=getattr(fp, "total_delta", 0.0),
        stepPrice=getattr(fp, "step_price", 0.0),
    ).dict(by_alias=True)

