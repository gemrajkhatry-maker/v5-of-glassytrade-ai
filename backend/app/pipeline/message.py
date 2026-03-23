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
    timestamp: datetime  # market time (IST)
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
    depth_bids: tuple = ()  # tuple of (price, qty) pairs
    depth_asks: tuple = ()
    source: str = "ws"  # "ws" | "poll" | "file" | "sim"


@dataclass(frozen=True)
class CandlePayload:
    """A completed (closed) or updating OHLCV candle."""

    time: str  # ISO8601, candle open time in IST
    open: float
    high: float
    low: float
    close: float
    volume: float
    delta: float  # buy_vol - sell_vol
    vwap: float = 0.0
    closed: bool = False  # True = candle complete, False = still building


@dataclass(frozen=True)
class AMTResultPayload:
    """Volume profile + market state analysis — ENRICHED for downstream processors."""

    market_state: str  # "BALANCED" | "IMBALANCED"
    leg_state: str
    poc: float
    vah: float
    val: float
    cvd_slope: float = 0.0
    cvd_divergence: str = ""  # "BEARISH_DIV" | "BULLISH_DIV" | ""
    profile_shape: str = "D"  # "P" | "b" | "D"
    delta_score: float = 0.0
    aggression: str = "NEUTRAL"
    balance_pct: float = 50.0
    near_level: bool = False
    confirmation_score: int = 0  # 0-3 out of 3

    # NEW: Developing VA (short lookback — adapts fast after large moves)
    dev_poc: float = 0.0
    dev_vah: float = 0.0
    dev_val: float = 0.0

    # NEW: Impulse leg profile (Fabio: profile the leg that broke structure)
    leg_poc: float = 0.0
    leg_vah: float = 0.0
    leg_val: float = 0.0
    leg_lvns: tuple[float, ...] = ()

    # NEW: Session VWAP (Fabio: VWAP for trailing stops)
    session_vwap: float = 0.0
    vwap_upper_2: float = 0.0
    vwap_lower_2: float = 0.0

    # NEW: LVN/HVN levels from session profile
    lvns: tuple[float, ...] = ()
    hvns: tuple[float, ...] = ()

    # NEW: LVN Play detection (Fabio's highest-conviction setup)
    lvn_play: dict | None = None

    # NEW: Aggressive print clusters (institutional level markers)
    aggressive_prints: tuple[dict, ...] = ()

    # NEW: Bubble retests (Fabio: high volume area being re-tested)
    bubble_retests: tuple[dict, ...] = ()


@dataclass(frozen=True)
class SignalGatePayload:
    """Result of the Three-Align gate check — NOW WITH FULL AMT CONTEXT for LLM.

    This payload carries ALL the data the LLM needs to "read the auction"
    per Fabio's methodology. Before this fix, the LLM received zeros.
    """

    passed: bool
    reason: str  # why gate passed or blocked
    setup_grade: str = ""  # "A" | "B" | "C"
    confidence: float = 0.0

    # ── Full AMT Context (carried from AMTAnalysisProcessor) ──
    market_state: str = "BALANCED"
    profile_shape: str = "D"
    poc: float = 0.0
    vah: float = 0.0
    val: float = 0.0
    cvd_slope: float = 0.0
    cvd_divergence: str = ""  # "BEARISH_DIV" | "BULLISH_DIV" | ""
    delta_score: float = 0.0
    aggression: str = "NEUTRAL"

    # Developing VA
    dev_poc: float = 0.0
    dev_vah: float = 0.0
    dev_val: float = 0.0

    # Impulse leg
    leg_poc: float = 0.0
    leg_vah: float = 0.0
    leg_val: float = 0.0

    # VWAP
    session_vwap: float = 0.0
    vwap_upper_2: float = 0.0
    vwap_lower_2: float = 0.0

    # Structural levels
    lvns: tuple[float, ...] = ()
    hvns: tuple[float, ...] = ()
    is_second_drive: bool = False

    # LVN Play (highest conviction setup)
    lvn_play: dict | None = None

    # Aggressive prints
    aggressive_prints: tuple[dict, ...] = ()
    bubble_retests: tuple[dict, ...] = ()

    # Session context (added by gate processor)
    session_name: str = ""
    favor_strategy: str = ""
    opening_bias: str = ""
    ib_high: float = 0.0
    ib_low: float = 0.0
    session_phase: str = ""

    # CVD hard gate result
    cvd_hard_block: bool = False
    cvd_hard_block_reason: str = ""


@dataclass(frozen=True)
class LLMDecisionPayload:
    """LLM entry decision."""

    direction: str  # "LONG" | "SHORT" | "FLAT"
    logic: str
    trigger: str
    probability: float = 0.0
    latency_ms: float = 0.0


@dataclass(frozen=True)
class OverseerDecisionPayload:
    """LLM overseer action on an open position."""

    action: str  # "HOLD" | "TIGHTEN" | "PARTIAL" | "FULL_EXIT" | "ADD"
    reason: str
    position_id: str = ""


@dataclass(frozen=True)
class OrderPayload:
    """An order to be sent to the broker."""

    direction: str  # "BUY" | "SELL"
    symbol: str
    size: int
    order_type: str = "MARKET"
    stop_loss: float = 0.0
    take_profit: float = 0.0
    signal_id: str = ""


@dataclass(frozen=True)
class PositionEventPayload:
    """Any position lifecycle event."""

    event_type: str  # "OPENED" | "CLOSED" | "MODIFIED" | "PARTIAL_EXIT"
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
