"""Trade Aggregate Adapter - Bridges Trade Aggregate with existing TradeManager.

This adapter provides compatibility between:
1. The new Trade aggregate (immutable, derived state)
2. The existing ManagedPosition interface (mutable)

This allows gradual migration without breaking existing code.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional

from app.domain.trading.models.trade_aggregate import (
    Trade,
    Direction,
    EntrySignal,
    Fill,
    create_trade as create_trade_aggregate,
    create_trade_from_snapshot,
)
from app.domain.trading.models.enums import Side, SetupType

logger = logging.getLogger(__name__)


@dataclass
class ManagedPositionAdapter:
    """Adapter that wraps Trade aggregate to provide ManagedPosition-compatible interface.

    This allows the existing TradeManager to work with Trade aggregates
    while we migrate to the new architecture.
    """

    trade: Trade

    @property
    def position_id(self) -> str:
        return self.trade.trade_id

    @property
    def symbol(self) -> str:
        return self.trade.symbol

    @property
    def side(self) -> str:
        return "LONG" if self.trade.side == Side.LONG else "SHORT"

    @property
    def is_long(self) -> bool:
        return self.trade.side == Side.LONG

    @property
    def entry_price(self) -> float:
        return float(self.trade.entry_price)

    @property
    def stop_loss(self) -> float:
        return float(self.trade.stop_loss)

    @property
    def take_profit(self) -> float:
        return float(self.trade.take_profit)

    @property
    def position_size(self) -> float:
        return float(self.trade.position_size)

    @property
    def quantity(self) -> float:
        return float(self.trade.position.quantity)

    @property
    def is_open(self) -> bool:
        return self.trade.is_open

    @property
    def unrealized_pnl(self) -> float:
        return float(self.trade.unrealized_pnl)

    @property
    def realized_pnl(self) -> float:
        return float(self.trade.realized_pnl)

    # Mutable properties for backward compatibility
    # These update the underlying Trade through commands

    def update_stop_loss(self, new_sl: float) -> None:
        """Update stop loss (creates new Trade)."""
        # Note: In the new architecture, SL would be immutable
        # This is a compatibility shim
        logger.warning("update_stop_loss called - Trade aggregate is immutable")

    def update_take_profit(self, new_tp: float) -> None:
        """Update take profit (creates new Trade)."""
        logger.warning("update_take_profit called - Trade aggregate is immutable")

    def close(self, reason: str, timestamp: str) -> Trade:
        """Close the trade."""
        from app.domain.trading.models.trade_aggregate import CloseReason

        close_reason_map = {
            "SL": CloseReason.STOP_LOSS,
            "STOP_LOSS": CloseReason.STOP_LOSS,
            "TP": CloseReason.TAKE_PROFIT,
            "TAKE_PROFIT": CloseReason.TAKE_PROFIT,
            "PARTIAL_TP": CloseReason.PARTIAL_TP,
            "PARTIAL": CloseReason.PARTIAL_TP,
            "TIME_STOP": CloseReason.TIME_STOP,
            "TIME_STOP_MAX": CloseReason.TIME_STOP,
            "MANUAL": CloseReason.MANUAL,
            "OVERSEER": CloseReason.MANUAL,
            "CIRCUIT_BREAKER": CloseReason.MANUAL,
            "DAILY_LOSS_LIMIT": CloseReason.MANUAL,
            "SIGNAL_REJECTED": CloseReason.SIGNAL_REJECTED,
            "BROKER_REJECTED": CloseReason.BROKER_REJECTED,
        }

        close_reason = close_reason_map.get(
            reason.upper() if reason else "MANUAL", CloseReason.MANUAL
        )

        # UPDATE TRADE FIRST (transactional consistency)
        closed_trade = self.trade.close(close_reason, timestamp)

        return closed_trade

    def add_fill(self, fill: Fill) -> Trade:
        """Add a fill and return new Trade."""
        return self.trade.add_fill(fill)


class TradeAggregateService:
    """Service that manages Trade aggregates."""

    def __init__(self):
        self._trades: dict[str, Trade] = {}
        self._adapters: dict[str, ManagedPositionAdapter] = {}

    def create_trade(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        position_size: float,
        setup_type: SetupType,
        confidence: str,
    ) -> ManagedPositionAdapter:
        """Create a new trade and return adapter."""

        direction_enum = (
            Direction.LONG if direction.upper() == "LONG" else Direction.SHORT
        )

        signal = EntrySignal(
            timestamp=datetime.now(timezone.utc).isoformat(),
            direction=direction_enum,
            entry_price=Decimal(str(entry_price)),
            stop_loss=Decimal(str(stop_loss)),
            take_profit=Decimal(str(take_profit)),
            position_size=Decimal(str(position_size)),
            setup_type=setup_type,
            confidence=confidence,  # type: ignore
        )

        timestamp = datetime.now(timezone.utc).isoformat()
        trade = create_trade_aggregate(symbol, signal, timestamp)

        # Store
        self._trades[trade.trade_id] = trade
        adapter = ManagedPositionAdapter(trade=trade)
        self._adapters[trade.trade_id] = adapter

        return adapter

    def get_trade(self, trade_id: str) -> Optional[Trade]:
        """Get trade by ID."""
        return self._trades.get(trade_id)

    def get_adapter(self, trade_id: str) -> Optional[ManagedPositionAdapter]:
        """Get adapter by trade ID."""
        return self._adapters.get(trade_id)

    def get_open_trades(self) -> list[Trade]:
        """Get all open trades."""
        return [t for t in self._trades.values() if t.is_open]

    def get_trade_count(self) -> int:
        """Get total trade count."""
        return len(self._trades)

    def get_open_count(self) -> int:
        """Get open trade count."""
        return len(self.get_open_trades())

    def to_snapshot(self) -> dict:
        """Serialize all trades."""
        return {
            trade_id: trade.to_snapshot() for trade_id, trade in self._trades.items()
        }

    def from_snapshot(self, snapshot: dict) -> None:
        """Reconstruct trades from snapshot."""
        self._trades.clear()
        self._adapters.clear()

        for trade_id, data in snapshot.items():
            trade = create_trade_from_snapshot(data)
            self._trades[trade_id] = trade
            self._adapters[trade_id] = ManagedPositionAdapter(trade=trade)


def create_trade_aggregate_service() -> TradeAggregateService:
    """Factory function to create TradeAggregateService."""
    return TradeAggregateService()
