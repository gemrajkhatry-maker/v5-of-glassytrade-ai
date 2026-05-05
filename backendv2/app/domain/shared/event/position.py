"""Position events — position lifecycle."""

from __future__ import annotations

from dataclasses import dataclass, field

from app.domain.shared.event.base import DomainEvent, _generate_idempotency_key


@dataclass(frozen=True)
class PositionChanged(DomainEvent):
    """Position state changed (derived from fills).

    This is a DERIVED event — position is computed from FillReceived events.
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
    """A new position was opened (derived from first ENTRY fill).

    Published by trade lifecycle handler after processing FillReceived(fill_type="ENTRY").
    Consumed by risk manager, state snapshot builder, alert manager.
    """

    trade_id: str = ""
    symbol: str = ""
    side: str = ""
    entry_price: float = 0.0
    quantity: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0

    @staticmethod
    def create(
        trade_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        quantity: float,
        stop_loss: float = 0.0,
        take_profit: float = 0.0,
    ) -> "PositionOpened":
        idempotency_key = _generate_idempotency_key(trade_id, "opened")
        return PositionOpened(
            idempotency_key=idempotency_key,
            trade_id=trade_id,
            symbol=symbol,
            side=side,
            entry_price=entry_price,
            quantity=quantity,
            stop_loss=stop_loss,
            take_profit=take_profit,
        )


@dataclass(frozen=True)
class PositionClosed(DomainEvent):
    """A position was closed (derived from fills summing to zero).

    Published by trade lifecycle handler after processing FillReceived(fill_type="EXIT").
    Consumed by risk manager, state snapshot builder, alert manager, P&L tracker.

    close_reason: "STOP_LOSS", "TAKE_PROFIT", "PARTIAL_TP", "TIME_STOP", "MANUAL"
    """

    trade_id: str = ""
    symbol: str = ""
    close_reason: str = ""
    realized_pnl: float = 0.0
    total_commission: float = 0.0
    total_slippage: float = 0.0
    hold_time_seconds: float = 0.0
    exit_price: float = 0.0

    @staticmethod
    def create(
        trade_id: str,
        symbol: str,
        close_reason: str,
        realized_pnl: float,
        total_commission: float = 0.0,
        total_slippage: float = 0.0,
        hold_time_seconds: float = 0.0,
        exit_price: float = 0.0,
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
            exit_price=exit_price,
        )
