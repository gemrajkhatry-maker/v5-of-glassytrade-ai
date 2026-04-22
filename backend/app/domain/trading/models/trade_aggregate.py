"""Trade Aggregate Root — Domain-Driven Design for Trading.

This module defines the core domain model where:
- Trade is the AGGREGATE ROOT
- EntrySignal, Fill are immutable value objects
- Position is DERIVED from fills (not stored)
- TradeEvents provide audit trail

Design Principles:
1. Single Source of Truth: All state derived from immutable events
2. No Mutable State: Position computed on-demand from fills
3. Idempotency: Every event has a unique idempotency key
4. Determinism: Same events → Same state (replay-able)
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass, field
from decimal import Decimal
from enum import Enum
from typing import Optional

from app.domain.trading.models.enums import (
    Side,
    SetupType,
)


# =============================================================================
# ENUMS
# =============================================================================


class TradeStatus(str, Enum):
    """Trade lifecycle status."""

    PENDING = "PENDING"  # Signal generated, order not yet placed
    OPEN = "OPEN"  # Position open
    CLOSED = "CLOSED"  # Position closed (all fills complete)


class CloseReason(str, Enum):
    """Reason for trade closure."""

    STOP_LOSS = "STOP_LOSS"
    TAKE_PROFIT = "TAKE_PROFIT"
    PARTIAL_TP = "PARTIAL_TP"  # Partial take profit (runner)
    TIME_STOP = "TIME_STOP"  # Max hold time exceeded
    MANUAL = "MANUAL"  # Manual close
    SIGNAL_REJECTED = "SIGNAL_REJECTED"  # Entry signal invalidated
    BROKER_REJECTED = "BROKER_REJECTED"


class Confidence(str, Enum):
    """Signal confidence level."""

    HIGH = "HIGH"
    MEDIUM = "MEDIUM"
    LOW = "LOW"


class Direction(str, Enum):
    """Trade direction."""

    LONG = "LONG"
    SHORT = "SHORT"
    FLAT = "FLAT"


class FillType(str, Enum):
    """Type of fill."""

    ENTRY = "ENTRY"  # Initial entry fill
    PARTIAL = "PARTIAL"  # Partial exit (e.g., 50% at TP)
    EXIT = "EXIT"  # Full exit
    SCALE_IN = "SCALE_IN"  # Adding to position
    SCALE_OUT = "SCALE_OUT"  # Reducing position


# =============================================================================
# VALUE OBJECTS (Immutable)
# =============================================================================


@dataclass(frozen=True)
class TradeThesis:
    """Trading thesis - why we're taking this trade."""

    market_state: str  # BALANCED / IMBALANCED
    location_type: str  # POC / VAH / VAL / LVN / etc
    location_level: float
    aggression_trigger: str  # DELTA_EXPANSION / CVD_EXPANSION / etc
    session_context: str
    invalidation_level: float


@dataclass(frozen=True)
class EntrySignal:
    """Immutable entry signal - the decision to enter a trade.

    This is created by the strategy and passed to the Trade aggregate.
    """

    signal_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = ""
    direction: Direction = Direction.FLAT
    entry_price: Decimal = Decimal("0")
    stop_loss: Decimal = Decimal("0")
    take_profit: Decimal = Decimal("0")
    position_size: Decimal = Decimal("0")
    setup_type: SetupType = SetupType.TREND_MODEL
    confidence: Confidence = Confidence.MEDIUM
    thesis: Optional[TradeThesis] = None

    @property
    def is_long(self) -> bool:
        return self.direction == Direction.LONG

    @property
    def is_short(self) -> bool:
        return self.direction == Direction.SHORT

    @property
    def risk_per_share(self) -> Decimal:
        """Risk per share (entry - SL)."""
        return abs(self.entry_price - self.stop_loss)

    @property
    def reward_per_share(self) -> Decimal:
        """Reward per share (TP - entry)."""
        return abs(self.take_profit - self.entry_price)

    @property
    def risk_reward_ratio(self) -> float:
        """Risk/reward ratio."""
        risk = float(self.risk_per_share)
        if risk == 0:
            return 0.0
        return float(self.reward_per_share) / risk


@dataclass(frozen=True)
class Fill:
    """Immutable fill - a completed order.

    This is the SOURCE OF TRUTH for position state.
    Fills are never modified after creation.
    """

    fill_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trade_id: str = ""
    order_id: str = ""
    symbol: str = ""  # Added for tracking
    side: Side = Side.LONG
    price: Decimal = Decimal("0")
    quantity: Decimal = Decimal("0")
    commission: Decimal = Decimal("0")
    slippage: Decimal = Decimal("0")
    timestamp: str = ""
    fill_type: FillType = FillType.ENTRY

    @property
    def total_cost(self) -> Decimal:
        """Total cost including commission and slippage."""
        base = self.price * self.quantity
        if self.side == Side.LONG:
            return base + self.commission + self.slippage
        else:
            return base - self.commission - self.slippage

    @property
    def pnl(self) -> Decimal:
        """PnL contribution of this fill.

        For exits: requires entry fill to calculate proper PnL.
        This property is deprecated - use Position.from_fills() for proper calculation.
        """
        return Decimal("0")  # Deprecated - see realized_pnl


@dataclass(frozen=True)
class Position:
    """Derived position - computed from fills.

    CRITICAL: This is NOT stored. It is ALWAYS derived from fills.
    This ensures: position = sum(fills.quantity) is always true.
    """

    trade_id: str = ""
    side: Side = Side.LONG
    quantity: Decimal = Decimal("0")
    avg_entry_price: Decimal = Decimal("0")
    current_price: Decimal = Decimal("0")

    @staticmethod
    def from_fills(
        fills: tuple[Fill, ...], current_price: Decimal = Decimal("0")
    ) -> Position:
        """Derive position from fills.

        This is the ONLY way to create a Position.
        """
        if not fills:
            return Position()

        trade_id = fills[0].trade_id

        # Calculate net quantity and weighted average entry price
        total_quantity = Decimal("0")
        total_cost = Decimal("0")

        for fill in fills:
            if fill.fill_type in (FillType.ENTRY, FillType.SCALE_IN):
                # Adding to position
                total_quantity += fill.quantity
                total_cost += fill.price * fill.quantity
            elif fill.fill_type in (
                FillType.EXIT,
                FillType.PARTIAL,
                FillType.SCALE_OUT,
            ):
                # Reducing position
                total_quantity -= fill.quantity

        # Determine side from first fill
        side = fills[0].side

        # Calculate average entry price
        if total_quantity > 0 and total_cost > 0:
            avg_price = total_cost / total_quantity
        else:
            avg_price = Decimal("0")

        return Position(
            trade_id=trade_id,
            side=side,
            quantity=total_quantity,
            avg_entry_price=avg_price,
            current_price=current_price,
        )

    @property
    def is_open(self) -> bool:
        """Position is open if quantity > 0."""
        return self.quantity > 0

    @property
    def market_value(self) -> Decimal:
        """Current market value."""
        return self.quantity * self.current_price

    @property
    def cost_basis(self) -> Decimal:
        """Entry cost basis."""
        return self.quantity * self.avg_entry_price

    @property
    def unrealized_pnl(self) -> Decimal:
        """Unrealized PnL (mark-to-market)."""
        if not self.is_open or self.current_price == 0:
            return Decimal("0")

        if self.side == Side.LONG:
            return (self.current_price - self.avg_entry_price) * self.quantity
        else:
            return (self.avg_entry_price - self.current_price) * self.quantity

    @property
    def unrealized_pnl_pct(self) -> float:
        """Unrealized PnL as percentage."""
        if self.cost_basis == 0:
            return 0.0
        return float(self.unrealized_pnl / self.cost_basis)


@dataclass(frozen=True)
class TradeEvent:
    """Immutable audit trail event."""

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    trade_id: str = ""
    event_type: str = ""
    timestamp: str = ""
    data: dict = field(default_factory=dict)


# =============================================================================
# TRADE AGGREGATE ROOT
# =============================================================================


@dataclass
class Trade:
    """Trade Aggregate Root.

    The Trade is the central aggregate that owns:
    - Entry signal (immutable)
    - Fills (append-only, immutable)
    - Derived position (computed on-demand)

    Invariants:
    1. position = Position.from_fills(fills) - ALWAYS true
    2. status = OPEN iff position.is_open
    3. realized_pnl = sum(fill.pnl for fill in fills where fill_type is EXIT/PARTIAL)
    """

    trade_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    symbol: str = ""
    status: TradeStatus = TradeStatus.PENDING
    entry_signal: Optional[EntrySignal] = None
    fills: tuple[Fill, ...] = field(default_factory=tuple)
    events: tuple[TradeEvent, ...] = field(default_factory=tuple)
    entry_time: str = ""
    close_time: Optional[str] = None
    close_reason: Optional[CloseReason] = None

    # =========================================================================
    # PROPERTIES (Derived, NOT stored)
    # =========================================================================

    def get_position(self, current_market_price: Decimal = Decimal("0")) -> Position:
        """Derive position from fills with current market price.

        Args:
            current_market_price: Current market price for mark-to-market PnL.
                                   If not provided, uses last fill price or entry price.

        Returns:
            Position with derived quantity and unrealized PnL.
        """
        # Use provided market price if available
        current_price = current_market_price

        # Fallback: use last fill price if no market price provided
        if current_price == Decimal("0") and self.fills:
            current_price = self.fills[-1].price

        # For closed trades, use last fill price
        if self.status == TradeStatus.CLOSED and self.fills:
            current_price = self.fills[-1].price

        return Position.from_fills(self.fills, current_price)

    @property
    def position(self) -> Position:
        """Derive position from fills (legacy - requires market price to be accurate).

        WARNING: This property does NOT have current market price.
        Use get_position(current_market_price) for accurate unrealized PnL.

        CRITICAL: This is computed on-demand, not stored.
        """
        # Default to entry price - this is WRONG for open trades!
        # Callers should use get_position(market_price) instead
        current_price = Decimal("0")

        if self.fills:
            # Use last fill price as approximation
            current_price = self.fills[-1].price

        return Position.from_fills(self.fills, current_price)

    @property
    def is_open(self) -> bool:
        """Trade is open if status is OPEN."""
        return self.status == TradeStatus.OPEN

    @property
    def is_pending(self) -> bool:
        """Trade is pending if signal generated but not filled."""
        return self.status == TradeStatus.PENDING

    @property
    def is_closed(self) -> bool:
        """Trade is closed."""
        return self.status == TradeStatus.CLOSED

    @property
    def side(self) -> Side:
        """Trade side from entry signal."""
        if self.entry_signal:
            return Side.LONG if self.entry_signal.is_long else Side.SHORT
        return Side.LONG

    @property
    def entry_price(self) -> Decimal:
        """Entry price from signal or first fill."""
        if self.entry_signal:
            return self.entry_signal.entry_price
        if self.fills:
            return self.fills[0].price
        return Decimal("0")

    @property
    def stop_loss(self) -> Decimal:
        """Stop loss from entry signal."""
        if self.entry_signal:
            return self.entry_signal.stop_loss
        return Decimal("0")

    @property
    def take_profit(self) -> Decimal:
        """Take profit from entry signal."""
        if self.entry_signal:
            return self.entry_signal.take_profit
        return Decimal("0")

    @property
    def position_size(self) -> Decimal:
        """Position size from entry signal."""
        if self.entry_signal:
            return self.entry_signal.position_size
        return self.position.quantity

    @property
    def unrealized_pnl(self) -> Decimal:
        """Unrealized PnL (mark-to-market for open trades)."""
        if self.is_closed:
            return Decimal("0")
        return self.position.unrealized_pnl

    @property
    def realized_pnl(self) -> Decimal:
        """Realized PnL from closed fills.

        Calculates proper PnL by matching exit fills to entry fills:
        PnL = (exit_price - entry_price) * quantity - commission
        """
        if not self.fills:
            return Decimal("0")

        total_pnl = Decimal("0")

        # Track entry fills to match with exits
        entry_fills = []
        remaining_exits = []

        for fill in self.fills:
            if fill.fill_type in (FillType.ENTRY, FillType.SCALE_IN):
                entry_fills.append(fill)
            elif fill.fill_type in (
                FillType.EXIT,
                FillType.PARTIAL,
                FillType.SCALE_OUT,
            ):
                remaining_exits.append(fill)

        # Match each exit to its corresponding entry (FIFO)
        # For simplicity, use weighted average entry price
        total_entry_cost = Decimal("0")
        total_entry_qty = Decimal("0")
        for entry in entry_fills:
            total_entry_cost += entry.price * entry.quantity
            total_entry_qty += entry.quantity

        avg_entry_price = (
            total_entry_cost / total_entry_qty if total_entry_qty > 0 else Decimal("0")
        )

        # Calculate PnL for each exit
        for exit_fill in remaining_exits:
            if exit_fill.fill_type == FillType.EXIT:
                # Full exit: calculate PnL based on avg entry price
                exit_qty = exit_fill.quantity

                # Match quantity to entries (FIFO)
                qty_to_match = exit_qty
                matched_cost = Decimal("0")

                for entry in entry_fills:
                    if qty_to_match <= 0:
                        break
                    available = entry.quantity
                    used = min(qty_to_match, available)
                    matched_cost += entry.price * used
                    qty_to_match -= used

                # PnL = (exit_price - avg_entry) * qty - commission
                if matched_cost > 0 and qty_to_match == 0:
                    avg_exit_price = exit_fill.price  # Use actual exit price
                    pnl = (avg_exit_price - (matched_cost / exit_qty)) * exit_qty
                    total_pnl += pnl - exit_fill.commission - exit_fill.slippage

            elif exit_fill.fill_type == FillType.PARTIAL:
                # Partial exit: proportional PnL
                if avg_entry_price > 0:
                    pnl = (exit_fill.price - avg_entry_price) * exit_fill.quantity
                    total_pnl += pnl - exit_fill.commission - exit_fill.slippage

        return total_pnl

    @property
    def total_commission(self) -> Decimal:
        """Total commission paid."""
        return sum(f.commission for f in self.fills)

    @property
    def total_slippage(self) -> Decimal:
        """Total slippage paid."""
        return sum(f.slippage for f in self.fills)

    @property
    def risk_per_share(self) -> Decimal:
        """Risk per share from entry signal."""
        if self.entry_signal:
            return self.entry_signal.risk_per_share
        return Decimal("0")

    @property
    def risk_reward_ratio(self) -> float:
        """Risk/reward ratio from entry signal."""
        if self.entry_signal:
            return self.entry_signal.risk_reward_ratio
        return 0.0

    # =========================================================================
    # COMMANDS (State Transitions)
    # =========================================================================

    def open(self, entry_signal: EntrySignal, timestamp: str) -> Trade:
        """Open trade with entry signal."""
        if self.status != TradeStatus.PENDING:
            raise ValueError(f"Cannot open trade in status {self.status}")

        new_event = TradeEvent(
            trade_id=self.trade_id,
            event_type="TRADE_OPENED",
            timestamp=timestamp,
            data={"signal_id": entry_signal.signal_id},
        )

        return Trade(
            trade_id=self.trade_id,
            symbol=self.symbol,
            status=TradeStatus.OPEN,
            entry_signal=entry_signal,
            fills=self.fills,
            events=self.events + (new_event,),
            entry_time=timestamp,
            close_time=None,
            close_reason=None,
        )

    def add_fill(self, fill: Fill) -> Trade:
        """Add a fill to the trade."""
        # Validate fill matches trade
        if fill.trade_id != self.trade_id:
            raise ValueError(
                f"Fill trade_id {fill.trade_id} != Trade trade_id {self.trade_id}"
            )

        new_event = TradeEvent(
            trade_id=self.trade_id,
            event_type="FILL_RECEIVED",
            timestamp=fill.timestamp,
            data={
                "fill_id": fill.fill_id,
                "fill_type": fill.fill_type.value,
                "price": str(fill.price),
                "quantity": str(fill.quantity),
            },
        )

        # Check if this fill closes the position
        new_fills = self.fills + (fill,)
        new_position = Position.from_fills(new_fills)

        new_status = self.status
        new_close_time = self.close_time
        new_close_reason = self.close_reason

        # If position is now closed and was previously open, set close reason based on fill type
        if not new_position.is_open and self.status == TradeStatus.OPEN:
            new_status = TradeStatus.CLOSED
            new_close_time = fill.timestamp
            if fill.fill_type == FillType.EXIT:
                new_close_reason = CloseReason.TAKE_PROFIT
            elif fill.fill_type == FillType.PARTIAL:
                new_close_reason = CloseReason.PARTIAL_TP

        return Trade(
            trade_id=self.trade_id,
            symbol=self.symbol,
            status=new_status,
            entry_signal=self.entry_signal,
            fills=new_fills,
            events=self.events + (new_event,),
            entry_time=self.entry_time,
            close_time=new_close_time,
            close_reason=new_close_reason,
        )

    def close(self, reason: CloseReason, timestamp: str) -> Trade:
        """Close the trade."""
        if self.status != TradeStatus.OPEN:
            raise ValueError(f"Cannot close trade in status {self.status}")

        new_event = TradeEvent(
            trade_id=self.trade_id,
            event_type="TRADE_CLOSED",
            timestamp=timestamp,
            data={"close_reason": reason.value},
        )

        return Trade(
            trade_id=self.trade_id,
            symbol=self.symbol,
            status=TradeStatus.CLOSED,
            entry_signal=self.entry_signal,
            fills=self.fills,
            events=self.events + (new_event,),
            entry_time=self.entry_time,
            close_time=timestamp,
            close_reason=reason,
        )

    def cancel(self, reason: str, timestamp: str) -> Trade:
        """Cancel a pending trade."""
        if self.status != TradeStatus.PENDING:
            raise ValueError(f"Cannot cancel trade in status {self.status}")

        new_event = TradeEvent(
            trade_id=self.trade_id,
            event_type="TRADE_CANCELLED",
            timestamp=timestamp,
            data={"cancel_reason": reason},
        )

        return Trade(
            trade_id=self.trade_id,
            symbol=self.symbol,
            status=TradeStatus.CLOSED,  # Cancelled trades are closed
            entry_signal=self.entry_signal,
            fills=self.fills,
            events=self.events + (new_event,),
            entry_time=self.entry_time,
            close_time=timestamp,
            close_reason=CloseReason.SIGNAL_REJECTED,
        )

    # =========================================================================
    # QUERY METHODS
    # =========================================================================

    def get_event_history(self) -> list[TradeEvent]:
        """Get chronological event history."""
        return list(self.events)

    def to_snapshot(self) -> dict:
        """Create a serializable snapshot."""
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "status": self.status.value,
            "entry_signal": {
                "signal_id": self.entry_signal.signal_id,
                "direction": self.entry_signal.direction.value,
                "entry_price": str(self.entry_signal.entry_price),
                "stop_loss": str(self.entry_signal.stop_loss),
                "take_profit": str(self.entry_signal.take_profit),
                "position_size": str(self.entry_signal.position_size),
                "confidence": self.entry_signal.confidence.value
                if hasattr(self.entry_signal.confidence, "value")
                else str(self.entry_signal.confidence),
            }
            if self.entry_signal
            else None,
            "fills": [
                {
                    "fill_id": f.fill_id,
                    "price": str(f.price),
                    "quantity": str(f.quantity),
                    "commission": str(f.commission),
                    "fill_type": f.fill_type.value,
                    "timestamp": f.timestamp,
                }
                for f in self.fills
            ],
            "position": {
                "quantity": str(self.position.quantity),
                "avg_entry_price": str(self.position.avg_entry_price),
                "unrealized_pnl": str(self.position.unrealized_pnl),
            },
            "entry_time": self.entry_time,
            "close_time": self.close_time,
            "close_reason": self.close_reason.value if self.close_reason else None,
            "realized_pnl": str(self.realized_pnl),
            "total_commission": str(self.total_commission),
            "total_slippage": str(self.total_slippage),
        }


# =============================================================================
# FACTORY METHODS
# =============================================================================


def create_trade(
    symbol: str,
    entry_signal: EntrySignal,
    timestamp: str,
) -> Trade:
    """Factory method to create a new trade."""
    return Trade(
        trade_id=str(uuid.uuid4()),
        symbol=symbol,
        status=TradeStatus.PENDING,
        entry_signal=entry_signal,
        fills=(),
        events=(),
        entry_time=timestamp,
    )


def create_trade_from_snapshot(snapshot: dict) -> Trade:
    """Reconstruct trade from snapshot (for replay)."""
    entry_signal = None
    if snapshot.get("entry_signal"):
        es = snapshot["entry_signal"]
        thesis_data = es.get("thesis", {})
        thesis = (
            TradeThesis(
                market_state=thesis_data.get("market_state", ""),
                location_type=thesis_data.get("location_type", ""),
                location_level=thesis_data.get("location_level", 0),
                aggression_trigger=thesis_data.get("aggression_trigger", ""),
                session_context=thesis_data.get("session_context", ""),
                invalidation_level=thesis_data.get("invalidation_level", 0),
            )
            if thesis_data
            else None
        )

        entry_signal = EntrySignal(
            signal_id=es["signal_id"],
            direction=Direction(es["direction"]),
            entry_price=Decimal(es["entry_price"]),
            stop_loss=Decimal(es["stop_loss"]),
            take_profit=Decimal(es["take_profit"]),
            position_size=Decimal(es["position_size"]),
            confidence=Confidence(es["confidence"]),
            thesis=thesis,
        )

    fills = tuple(
        Fill(
            fill_id=f["fill_id"],
            trade_id=snapshot["trade_id"],
            price=Decimal(f["price"]),
            quantity=Decimal(f["quantity"]),
            commission=Decimal(f.get("commission", "0")),
            fill_type=FillType(f["fill_type"]),
            timestamp=f["timestamp"],
        )
        for f in snapshot.get("fills", [])
    )

    return Trade(
        trade_id=snapshot["trade_id"],
        symbol=snapshot["symbol"],
        status=TradeStatus(snapshot["status"]),
        entry_signal=entry_signal,
        fills=fills,
        entry_time=snapshot.get("entry_time", ""),
        close_time=snapshot.get("close_time"),
        close_reason=CloseReason(snapshot["close_reason"])
        if snapshot.get("close_reason")
        else None,
    )
