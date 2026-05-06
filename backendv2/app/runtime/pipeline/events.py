"""Pipeline event types — all events flowing between pipeline stages."""

from __future__ import annotations

from dataclasses import asdict, dataclass, field, is_dataclass
from enum import Enum
from typing import Any, Optional, Union

# Re-export AMTResult from domain model for pipeline use
from app.domain.trading.model.value_objects import AMTResult


class CandleTimeframe(Enum):
    M1 = "1m"
    M5 = "5m"
    M15 = "15m"
    H1 = "1h"
    D1 = "1d"


@dataclass(frozen=True)
class Tick:
    """Raw tick from exchange feed."""
    symbol: str
    price: float
    volume: float
    timestamp: float  # Unix nanoseconds
    bid: float = 0.0
    ask: float = 0.0
    bid_volume: float = 0.0
    ask_volume: float = 0.0
    exchange: str = ""
    is_trade: bool = True
    is_depth: bool = False
    depth_bids: tuple[tuple[float, float], ...] = ()
    depth_asks: tuple[tuple[float, float], ...] = ()


@dataclass(frozen=True)
class SequencedTick:
    """Tick with monotonic sequence number assigned by TickSequencer."""
    tick: Tick
    sequence: int


@dataclass(frozen=True)
class NormalizedTick:
    """Tick normalized to canonical internal representation."""
    symbol: str
    price: float
    volume: float
    timestamp: float  # Unix nanoseconds
    bid: float
    ask: float
    bid_volume: float
    ask_volume: float
    sequence: int
    tick_size: float = 0.0
    lot_size: int = 1
    multiplier: float = 1.0


@dataclass(frozen=True)
class Candle:
    """OHLC candle."""
    symbol: str
    timeframe: CandleTimeframe
    open: float
    high: float
    low: float
    close: float
    volume: float
    timestamp: float  # Unix nanoseconds of candle close
    tick_count: int = 0
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    vwap: float = 0.0
    complete: bool = True


@dataclass(frozen=True)
class OrderFlowMetrics:
    """Tick-level order flow metrics."""
    symbol: str
    timestamp: float
    cumulative_delta: float
    bid_volume: float
    ask_volume: float
    ofi: float  # Order Flow Imbalance
    big_trades: int  # Count of big trades in window
    volume_bubble: bool
    absorption_detected: bool
    absorption_side: str  # "BUY", "SELL", "NONE"
    absorption_strength: float
    stacked_imbalance: bool = False
    window_size: int = 100


@dataclass(frozen=True)
class MicrostructureMetrics:
    """Level 2 / depth-derived metrics."""
    symbol: str
    timestamp: float
    spread: float
    spread_pct: float
    book_imbalance: float  # (bid_vol - ask_vol) / (bid_vol + ask_vol)
    depth_pressure: float
    iceberg_detected: bool
    stop_run_detected: bool
    depth_available: bool = False


@dataclass(frozen=True)
class MarketStructureResult:
    """Complete market structure analysis result."""
    symbol: str
    timestamp: float
    poc: float
    vah: float
    val: float
    lvn_levels: tuple[float, ...] = field(default_factory=tuple)
    hvn_levels: tuple[float, ...] = field(default_factory=tuple)
    market_state: str = "BALANCED"  # BALANCED, IMBALANCED
    market_zone: str = "NEAR_POC"
    confidence: float = 0.5
    is_extreme: bool = False
    composite_poc: float = 0.0
    composite_vah: float = 0.0
    composite_val: float = 0.0
    opening_type: str = ""
    npoc_levels: tuple[float, ...] = field(default_factory=tuple)
    ob_imbalance: float = 0.0
    ms_classifier_state: str = ""
    break_detected: bool = False
    break_direction: str = ""
    break_type: str = ""
    displacement_detected: bool = False
    displacement_direction: str = ""
    acceptance_above: bool = False
    acceptance_below: bool = False
    rejection_at_high: bool = False
    rejection_at_low: bool = False
    liquidity_sweep: str = ""  # SWEEP_HIGH, SWEEP_LOW, ""
    profile_shape: str = "D"  # P, b, D, B
    poc_migration: str = "NONE"
    drive_number: int = 0
    drive_exhausted: bool = False
    gap_size: str = "NONE"
    opening_bias: str = "NEUTRAL"
    session_phase: str = "MORNING"
    day_type: str = ""
    mtf_alignment: str = ""  # ALIGNED_BULLISH, ALIGNED_BEARISH, DIVERGENT, ""


@dataclass(frozen=True)
class FeatureVector:
    """Computed features for signal generation."""
    symbol: str
    timestamp: float
    vwap: float
    vwap_upper_1sigma: float
    vwap_lower_1sigma: float
    vwap_upper_2sigma: float
    vwap_lower_2sigma: float
    atr_14: float
    rsi_14: float = 50.0
    rolling_volume_avg_20: float = 0.0


@dataclass(frozen=True)
class Signal:
    """Trade signal from Triple-A or strategy."""
    symbol: str
    timestamp: float
    type: str  # LONG, SHORT, NO_TRADE
    entry: float
    sl: float
    tp: float
    rr: float
    confidence: float
    reason: str
    source: str = "pipeline"  # pipeline, strategy_llm, strategy_rl, strategy_rule


class GateResultType(Enum):
    APPROVED = "APPROVED"
    REJECTED = "REJECTED"
    PENDING = "PENDING"


@dataclass(frozen=True)
class GateResult:
    """Gate evaluation result."""
    symbol: str
    timestamp: float
    signal: Signal
    result: GateResultType
    rejection_reason: str = ""
    aggression_score: float = 0.0
    aggression_confidence: str = "LOW"
    persistence_met: bool = False
    session_phase_ok: bool = True
    playbook_ok: bool = True
    llm_overseer_ok: bool = True
    gate_results: tuple[tuple[str, object], ...] = ()


@dataclass(frozen=True)
class RiskResult:
    """Risk evaluation result."""
    symbol: str
    timestamp: float
    approved: bool
    rejection_reason: str = ""
    drawdown_ok: bool = True
    consecutive_losses_ok: bool = True
    position_limit_ok: bool = True
    notional_ok: bool = True
    kill_switch_active: bool = False
    circuit_breaker_triggered: bool = False
    remaining_buying_power: float = 0.0


@dataclass(frozen=True)
class PositionEvent:
    """Position lifecycle event."""
    symbol: str
    timestamp: float
    event_type: str  # OPENED, UPDATED, CLOSED, REJECTED
    position_id: str = ""
    entry_price: float = 0.0
    size: float = 0.0
    side: str = ""  # LONG, SHORT
    stop_loss: float = 0.0
    take_profit: float = 0.0
    pnl: float = 0.0
    exit_reason: str = ""
    partial_taken: bool = False
    runner_active: bool = False


@dataclass(frozen=True)
class OrderRequest:
    """Order to submit to broker."""
    symbol: str
    side: str  # BUY, SELL
    quantity: float
    order_type: str = "LIMIT"  # LIMIT, MARKET, SL, SLM
    price: float = 0.0
    trigger_price: float = 0.0
    validity: str = "DAY"
    position_id: str = ""
    correlation_id: str = ""


@dataclass(frozen=True)
class OrderStatusEvent:
    """Order lifecycle status from broker."""
    order_id: str
    symbol: str
    status: str  # PENDING, FILLED, PARTIAL, CANCELLED, REJECTED
    filled_quantity: float = 0.0
    filled_price: float = 0.0
    remaining_quantity: float = 0.0
    reject_reason: str = ""
    timestamp: float = 0.0


@dataclass(frozen=True)
class FillEvent:
    """Fill notification from broker."""
    order_id: str
    symbol: str
    side: str
    quantity: float
    price: float
    timestamp: float
    commission: float = 0.0
    exchange: str = ""


@dataclass(frozen=True)
class ExitDecision:
    """Decision to exit a position."""
    exit_type: str  # FULL, PARTIAL
    size_pct: float  # 0.0 to 1.0
    price: float
    reason: str
    new_stop: Optional[float] = None


PipelineEvent = Union[
    Tick,
    SequencedTick,
    NormalizedTick,
    Candle,
    OrderFlowMetrics,
    MicrostructureMetrics,
    MarketStructureResult,
    FeatureVector,
    Signal,
    GateResult,
    RiskResult,
    PositionEvent,
    OrderRequest,
    OrderStatusEvent,
    FillEvent,
    ExitDecision,
]


def as_pipeline_payload(event: PipelineEvent) -> dict[str, Any]:
    if not is_dataclass(event):
        raise TypeError("Pipeline event must be dataclass-backed.")
    payload = asdict(event)
    payload["type"] = type(event).__name__
    return payload