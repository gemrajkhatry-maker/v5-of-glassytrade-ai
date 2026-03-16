"""Pipeline message schemas — the contracts between processors.

All messages are frozen dataclasses. Two processors are coupled ONLY by the
message type they exchange. No processor imports another processor.
"""
from __future__ import annotations
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import TypeVar, Generic

T = TypeVar("T")

# ---------------------------------------------------------------------------
# Envelope
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class Message(Generic[T]):
    payload: T
    symbol: str
    timestamp: datetime          # market time (IST)
    message_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    produced_at: datetime = field(default_factory=lambda: datetime.now(timezone.utc))
    source_processor: str = ""
    pipeline_id: str = "default"

# ---------------------------------------------------------------------------
# Payload types (one per pipeline stage)
# ---------------------------------------------------------------------------

@dataclass(frozen=True)
class RawTickPayload:
    """Raw market tick from any data source (WS, REST, file, sim)."""
    ltp: float
    volume: int = 0
    ltq: int = 0
    oi: int = 0
    total_buy_qty: int = 0
    total_sell_qty: int = 0
    depth_bids: tuple = ()     # tuple of (price, qty) pairs
    depth_asks: tuple = ()
    source: str = "ws"         # "ws" | "poll" | "file" | "sim"

@dataclass(frozen=True)
class CandlePayload:
    """A completed (closed) or updating OHLCV candle."""
    time: str                  # ISO8601, candle open time in IST
    open: float
    high: float
    low: float
    close: float
    volume: float
    delta: float               # buy_vol - sell_vol
    vwap: float = 0.0
    closed: bool = False       # True = candle complete, False = still building

@dataclass(frozen=True)
class AMTResultPayload:
    """Volume profile + market state analysis."""
    market_state: str          # "BALANCED" | "IMBALANCED"
    leg_state: str
    poc: float
    vah: float
    val: float
    cvd_slope: float = 0.0
    cvd_divergence: bool = False
    profile_shape: str = "D"   # "P" | "b" | "D"
    delta_score: float = 0.0
    aggression: str = "NEUTRAL"
    balance_pct: float = 50.0
    near_level: bool = False
    confirmation_score: int = 0  # 0-3 out of 3

@dataclass(frozen=True)
class SignalGatePayload:
    """Result of the Three-Align gate check."""
    passed: bool
    reason: str                # why gate passed or blocked
    setup_grade: str = ""      # "A" | "B" | "C"
    confidence: float = 0.0

@dataclass(frozen=True)
class LLMDecisionPayload:
    """LLM entry decision."""
    direction: str             # "LONG" | "SHORT" | "FLAT"
    logic: str
    trigger: str
    probability: float = 0.0
    latency_ms: float = 0.0

@dataclass(frozen=True)
class OverseerDecisionPayload:
    """LLM overseer action on an open position."""
    action: str                # "HOLD" | "TIGHTEN" | "PARTIAL" | "FULL_EXIT" | "ADD"
    reason: str
    position_id: str = ""

@dataclass(frozen=True)
class OrderPayload:
    """An order to be sent to the broker."""
    direction: str             # "BUY" | "SELL"
    symbol: str
    size: int
    order_type: str = "MARKET"
    stop_loss: float = 0.0
    take_profit: float = 0.0
    signal_id: str = ""

@dataclass(frozen=True)
class PositionEventPayload:
    """Any position lifecycle event."""
    event_type: str            # "OPENED" | "CLOSED" | "MODIFIED" | "PARTIAL_EXIT"
    position_id: str
    pnl: float = 0.0
    reason: str = ""

# ---------------------------------------------------------------------------
# Typed aliases for convenience
# ---------------------------------------------------------------------------
RawTickMessage = Message[RawTickPayload]
CandleMessage = Message[CandlePayload]
AMTResultMessage = Message[AMTResultPayload]
SignalGateMessage = Message[SignalGatePayload]
LLMDecisionMessage = Message[LLMDecisionPayload]
OverseerDecisionMessage = Message[OverseerDecisionPayload]
OrderMessage = Message[OrderPayload]
PositionEventMessage = Message[PositionEventPayload]
