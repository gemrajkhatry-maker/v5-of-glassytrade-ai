"""Domain events — immutable records of things that happened in the domain.

Each event is a frozen dataclass carrying only the data needed by handlers.
Events flow through the EventBus; services subscribe and react.

DESIGN PRINCIPLES:
1. Immutable: All events are frozen dataclasses
2. Idempotent: Events include idempotency_key to prevent duplicates
3. Complete: Events contain all data needed for reconstruction
4. Ordered: Events include timestamp for ordering
"""

# RESERVED: Event classes preserved for future event sourcing. Currently no subscribers.

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

from quant.contracts.value_objects import OHLC, OrderBook
from quant.contracts.entities import Signal, Position


def _utc_now() -> str:
    """Generate UTC timestamp in ISO format."""
    return datetime.now(timezone.utc).isoformat()


def _generate_idempotency_key(*parts: str) -> str:
    """Generate a unique idempotency key from parts."""
    return "|".join(parts)


# ---------------------------------------------------------------------------
# Base
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DomainEvent:
    """Base class for all domain events.

    All events are immutable (frozen=True) to ensure:
    - Thread safety
    - Deterministic state derivation
    - Audit trail integrity
    """

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(default_factory=_utc_now)
    idempotency_key: str = field(default_factory=lambda: str(uuid.uuid4()))

    def __str__(self) -> str:
        return f"{self.__class__.__name__}(id={self.event_id[:8]})"


# ---------------------------------------------------------------------------
# Market Data Events
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class TickReceived(DomainEvent):
    """A new market tick arrived for a symbol.

    This is the foundational event - all market data flows from here.
    """

    symbol: str = ""
    tick: OHLC = None
    order_book: OrderBook | None = None
    data: tuple[OHLC, ...] = ()  # full history window
    # Underlying futures candles for regime / volume features (when dual feed is active)
    agent_series: tuple[OHLC, ...] = ()
    tick_trace_id: str = ""
    daily_data: tuple[OHLC, ...] = ()  # Daily timeframe for structural bias
    hourly_data: tuple[OHLC, ...] = ()  # Hourly timeframe for execution bias

    def __str__(self) -> str:
        return f"TickReceived(symbol={self.symbol}, price={self.tick.close if self.tick else 'N/A'})"


# ---------------------------------------------------------------------------
# Analysis Events
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class AIAnalysisCompleted(DomainEvent):
    """Generative AI analysis finished for a symbol."""

    symbol: str = ""
    direction: str = "FLAT"  # "LONG", "SHORT", "FLAT"
    rationale: str = ""
    confidence: str = "Medium"
    analysis_id: str = ""

    @staticmethod
    def create(
        symbol: str,
        direction: str,
        rationale: str,
        confidence: str,
        analysis_id: str = "",
    ) -> "AIAnalysisCompleted":
        idempotency_key = _generate_idempotency_key(
            symbol, analysis_id or "ai_analysis", direction
        )
        return AIAnalysisCompleted(
            idempotency_key=idempotency_key,
            symbol=symbol,
            direction=direction,
            rationale=rationale,
            confidence=confidence,
            analysis_id=analysis_id,
        )


# ---------------------------------------------------------------------------
# Signal Events
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class SignalGenerated(DomainEvent):
    """A trade signal was generated (not yet risk-validated).

    This is the entry point for trade lifecycle.
    Idempotency key: symbol + signal_id
    """

    symbol: str = ""
    signal_id: str = ""
    direction: str = "FLAT"
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    position_size: float = 0.0
    confidence: str = "Medium"
    setup_type: str = ""

    @staticmethod
    def create(
        symbol: str,
        signal_id: str,
        direction: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        position_size: float,
        confidence: str,
        setup_type: str,
    ) -> "SignalGenerated":
        idempotency_key = _generate_idempotency_key(symbol, signal_id)
        return SignalGenerated(
            idempotency_key=idempotency_key,
            symbol=symbol,
            signal_id=signal_id,
            direction=direction,
            entry_price=entry_price,
            stop_loss=stop_loss,
            take_profit=take_profit,
            position_size=position_size,
            confidence=confidence,
            setup_type=setup_type,
        )


@dataclass(frozen=True)
class SignalValidated(DomainEvent):
    """Signal passed risk checks and is ready for execution."""

    signal_id: str = ""
    symbol: str = ""
    validation_result: str = ""  # "APPROVED", "REJECTED"
    rejection_reason: str = ""

    @staticmethod
    def create(
        signal_id: str, symbol: str, approved: bool, rejection_reason: str = ""
    ) -> "SignalValidated":
        idempotency_key = _generate_idempotency_key(signal_id, "validated")
        return SignalValidated(
            idempotency_key=idempotency_key,
            signal_id=signal_id,
            symbol=symbol,
            validation_result="APPROVED" if approved else "REJECTED",
            rejection_reason=rejection_reason,
        )


# ---------------------------------------------------------------------------
# Order Events
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class OrderPlaced(DomainEvent):
    """Order submitted to broker.

    Idempotency key: trade_id + order_id ensures no duplicates.
    """

    trade_id: str = ""
    order_id: str = ""
    symbol: str = ""
    side: str = ""  # "BUY" or "SELL"
    order_type: str = "MARKET"  # "MARKET", "LIMIT"
    price: float = 0.0
    quantity: float = 0.0

    @staticmethod
    def create(
        trade_id: str,
        order_id: str,
        symbol: str,
        side: str,
        order_type: str,
        price: float,
        quantity: float,
    ) -> "OrderPlaced":
        idempotency_key = _generate_idempotency_key(trade_id, order_id)
        return OrderPlaced(
            idempotency_key=idempotency_key,
            trade_id=trade_id,
            order_id=order_id,
            symbol=symbol,
            side=side,
            order_type=order_type,
            price=price,
            quantity=quantity,
        )


@dataclass(frozen=True)
class OrderCancelled(DomainEvent):
    """Order cancelled."""

    trade_id: str = ""
    order_id: str = ""
    reason: str = ""

    @staticmethod
    def create(trade_id: str, order_id: str, reason: str) -> "OrderCancelled":
        idempotency_key = _generate_idempotency_key(trade_id, order_id, "cancelled")
        return OrderCancelled(
            idempotency_key=idempotency_key,
            trade_id=trade_id,
            order_id=order_id,
            reason=reason,
        )


# ---------------------------------------------------------------------------
# FILL EVENTS (Source of Truth)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class FillReceived(DomainEvent):
    """Fill confirmation from broker - SOURCE OF TRUTH for position.

    CRITICAL: This is the authoritative event for position state.
    All position calculations must derive from FillReceived events.

    Idempotency key: trade_id + fill_id ensures no duplicates.
    """

    trade_id: str = ""
    fill_id: str = ""
    order_id: str = ""
    symbol: str = ""
    side: str = ""  # "BUY" or "SELL"
    fill_type: str = "ENTRY"  # "ENTRY", "PARTIAL", "EXIT", "SCALE_IN", "SCALE_OUT"
    price: float = 0.0
    quantity: float = 0.0
    commission: float = 0.0
    slippage: float = 0.0

    @staticmethod
    def create(
        trade_id: str,
        fill_id: str,
        order_id: str,
        symbol: str,
        side: str,
        fill_type: str,
        price: float,
        quantity: float,
        commission: float = 0.0,
        slippage: float = 0.0,
    ) -> "FillReceived":
        idempotency_key = _generate_idempotency_key(trade_id, fill_id)
        return FillReceived(
            idempotency_key=idempotency_key,
            trade_id=trade_id,
            fill_id=fill_id,
            order_id=order_id,
            symbol=symbol,
            side=side,
            fill_type=fill_type,
            price=price,
            quantity=quantity,
            commission=commission,
            slippage=slippage,
        )


# ---------------------------------------------------------------------------
# Position Events (Derived)
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class PositionChanged(DomainEvent):
    """Position state changed (derived from fills).

    This is a DERIVED event - position is computed from FillReceived events.
    It exists for event handlers that need to react to position changes.
    """

    trade_id: str = ""
    symbol: str = ""
    quantity: float = 0.0
    avg_entry_price: float = 0.0
    unrealized_pnl: float = 0.0
    is_open: bool = True

    @staticmethod
    def create(
        trade_id: str,
        symbol: str,
        quantity: float,
        avg_entry_price: float,
        unrealized_pnl: float,
        is_open: bool,
    ) -> "PositionChanged":
        idempotency_key = _generate_idempotency_key(
            trade_id, "position_changed", str(quantity)
        )
        return PositionChanged(
            idempotency_key=idempotency_key,
            trade_id=trade_id,
            symbol=symbol,
            quantity=quantity,
            avg_entry_price=avg_entry_price,
            unrealized_pnl=unrealized_pnl,
            is_open=is_open,
        )


@dataclass(frozen=True)
class PositionOpened(DomainEvent):
    """A new position was opened (derived from first ENTRY fill)."""

    trade_id: str = ""
    symbol: str = ""
    side: str = ""
    entry_price: float = 0.0
    quantity: float = 0.0

    @staticmethod
    def create(
        trade_id: str, symbol: str, side: str, entry_price: float, quantity: float
    ) -> "PositionOpened":
        idempotency_key = _generate_idempotency_key(trade_id, "opened")
        return PositionOpened(
            idempotency_key=idempotency_key,
            trade_id=trade_id,
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            quantity=quantity,
        )


@dataclass(frozen=True)
class PositionClosed(DomainEvent):
    """A position was closed (derived from fills summing to zero).

    close_reason: "STOP_LOSS", "TAKE_PROFIT", "PARTIAL_TP", "TIME_STOP", "MANUAL"
    """

    trade_id: str = ""
    symbol: str = ""
    close_reason: str = ""
    realized_pnl: float = 0.0
    total_commission: float = 0.0
    total_slippage: float = 0.0
    hold_time_seconds: float = 0.0

    @staticmethod
    def create(
        trade_id: str,
        symbol: str,
        close_reason: str,
        realized_pnl: float,
        total_commission: float = 0.0,
        total_slippage: float = 0.0,
        hold_time_seconds: float = 0.0,
    ) -> "PositionClosed":
        idempotency_key = _generate_idempotency_key(trade_id, "closed", close_reason)
        return PositionClosed(
            idempotency_key=idempotency_key,
            trade_id=trade_id,
            symbol=symbol,
            close_reason=close_reason,
            realized_pnl=realized_pnl,
            total_commission=total_commission,
            total_slippage=total_slippage,
            hold_time_seconds=hold_time_seconds,
        )


# ---------------------------------------------------------------------------
# Risk Events
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class RiskCheckFailed(DomainEvent):
    """Risk check failed - signal rejected."""

    signal_id: str = ""
    symbol: str = ""
    check_name: str = ""  # "DAILY_LOSS", "POSITION_LIMIT", "CONCENTRATION"
    reason: str = ""

    @staticmethod
    def create(
        signal_id: str, symbol: str, check_name: str, reason: str
    ) -> "RiskCheckFailed":
        idempotency_key = _generate_idempotency_key(
            signal_id, "risk_failed", check_name
        )
        return RiskCheckFailed(
            idempotency_key=idempotency_key,
            signal_id=signal_id,
            symbol=symbol,
            check_name=check_name,
            reason=reason,
        )


@dataclass(frozen=True)
class DailyLossLimitReached(DomainEvent):
    """Daily loss limit reached - trading halted for the day."""

    symbol: str = ""
    current_loss: float = 0.0
    limit: float = 0.0

    @staticmethod
    def create(
        symbol: str, current_loss: float, limit: float
    ) -> "DailyLossLimitReached":
        idempotency_key = _generate_idempotency_key(
            symbol, "daily_loss_limit", str(int(current_loss))
        )
        return DailyLossLimitReached(
            idempotency_key=idempotency_key,
            symbol=symbol,
            current_loss=current_loss,
            limit=limit,
        )


# ---------------------------------------------------------------------------
# Diagnostics Events
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class DataAnomalyEvent(DomainEvent):
    """A data anomaly was detected by the state bus validation middleware."""

    symbol: str = ""
    anomaly_type: str = ""  # "SESSION_MISMATCH", "INVARIANT_VIOLATION", "STALE_DATA"
    detail: str = ""
    timestamp: str = ""  # Override parent timestamp with anomaly detection time


# ---------------------------------------------------------------------------
# Event Type Registry
# ---------------------------------------------------------------------------

EVENT_TYPES = {
    "TickReceived": TickReceived,
    "AIAnalysisCompleted": AIAnalysisCompleted,
    "SignalGenerated": SignalGenerated,
    "SignalValidated": SignalValidated,
    "OrderPlaced": OrderPlaced,
    "OrderCancelled": OrderCancelled,
    "FillReceived": FillReceived,
    "PositionChanged": PositionChanged,
    "PositionOpened": PositionOpened,
    "PositionClosed": PositionClosed,
    "RiskCheckFailed": RiskCheckFailed,
    "DailyLossLimitReached": DailyLossLimitReached,
    "DataAnomalyEvent": DataAnomalyEvent,
}
