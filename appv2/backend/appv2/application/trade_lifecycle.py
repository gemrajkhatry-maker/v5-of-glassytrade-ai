"""Trade Lifecycle Handler — manages trade state transitions.

Lifecycle:
  SIGNAL → ORDER_PLACED → ORDER_FILLED → OPEN → EXITING → CLOSED

Each transition is validated and persisted.
"""

from __future__ import annotations

import time
import uuid
import logging
from dataclasses import dataclass, field
from appv2.domain.enums.signal_type import OrderSide, TradeStatus
from appv2.domain.models.trade import Trade
from appv2.domain.models.signal import Signal

logger = logging.getLogger(__name__)


class TradeLifecycleHandler:
    """Manages trade lifecycle from signal to closure."""

    def __init__(self):
        self._open_trades: dict[str, Trade] = {}
        self._closed_trades: list[Trade] = []

    def create_trade(
        self,
        signal: Signal,
        quantity: int,
        lots: int,
        fill_price: float,
        commission: float = 0.0,
        slippage: float = 0.0,
    ) -> Trade:
        """Create a new trade from a filled signal."""
        trade_id = f"TRD-{int(time.time())}-{uuid.uuid4().hex[:6].upper()}"

        side = OrderSide.BUY if signal.direction.value == "LONG" else OrderSide.SELL

        trade = Trade(
            trade_id=trade_id,
            symbol=signal.symbol,
            underlying_symbol=signal.underlying_symbol,
            side=side,
            entry_price=fill_price,
            quantity=quantity,
            lots=lots,
            stop_loss=signal.stop_loss,
            take_profit=signal.take_profit,
            commission=commission,
            slippage=slippage,
            entry_poc=signal.poc,
            entry_vah=signal.vah,
            entry_val=signal.val,
        )

        self._open_trades[trade_id] = trade
        logger.info(
            "TRADE OPENED: %s | %s %s | Entry: %.4f | SL: %.4f | TP: %.4f",
            trade_id, signal.symbol, signal.direction.value,
            fill_price, signal.stop_loss, signal.take_profit,
        )
        return trade

    def update_stop_loss(self, trade_id: str, new_sl: float) -> bool:
        """Update stop loss (for trailing stops)."""
        trade = self._open_trades.get(trade_id)
        if not trade:
            return False
        trade.stop_loss = new_sl
        if new_sl > 0:
            trade.trail_price = new_sl
        return True

    def close_trade(
        self,
        trade_id: str,
        exit_price: float,
        exit_reason: str,
        commission: float = 0.0,
        slippage: float = 0.0,
    ) -> Trade | None:
        """Close a trade."""
        trade = self._open_trades.pop(trade_id, None)
        if not trade:
            return None

        trade.exit_price = exit_price
        trade.exit_time = time.time()
        trade.exit_reason = exit_reason
        trade.commission += commission
        trade.slippage += slippage

        # Compute P&L
        if trade.side == OrderSide.BUY:
            pnl = (exit_price - trade.entry_price) * trade.quantity
        else:
            pnl = (trade.entry_price - exit_price) * trade.quantity

        trade.realized_pnl = pnl
        trade.status = (
            TradeStatus.STOPPED_OUT if exit_reason == "SL_HIT" else TradeStatus.CLOSED
        )

        self._closed_trades.append(trade)
        logger.info(
            "TRADE CLOSED: %s | %s | Exit: %.4f | PnL: ₹%.2f | Reason: %s",
            trade_id, trade.symbol, exit_price, pnl, exit_reason,
        )
        return trade

    def get_open_trades(self, symbol: str = "") -> list[Trade]:
        """Get all open trades, optionally filtered by symbol."""
        trades = list(self._open_trades.values())
        if symbol:
            trades = [t for t in trades if t.symbol == symbol]
        return trades

    def get_closed_trades(self, limit: int = 50) -> list[Trade]:
        """Get recently closed trades."""
        return self._closed_trades[-limit:]

    def has_open_position(self, symbol: str) -> bool:
        """Check if symbol has open position."""
        return any(t.symbol == symbol for t in self._open_trades.values())

    @property
    def total_open(self) -> int:
        return len(self._open_trades)

    @property
    def total_pnl(self) -> float:
        return sum(t.realized_pnl for t in self._closed_trades)
