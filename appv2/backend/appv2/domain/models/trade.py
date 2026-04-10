"""Trade model — represents an open or closed position."""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from appv2.domain.enums.signal_type import TradeStatus, OrderSide


@dataclass
class Trade:
    """Live trade / position.

    Mutable (not frozen) — SL, TP, trail_price update during lifecycle.
    """

    trade_id: str
    symbol: str
    underlying_symbol: str
    side: OrderSide  # BUY (CE) or SELL (PE)

    entry_price: float
    quantity: int  # In lots
    lots: int

    stop_loss: float
    take_profit: float
    trail_price: float = 0.0  # Updated by trailing logic

    status: TradeStatus = TradeStatus.OPEN

    entry_time: float = field(default_factory=time.time)
    exit_price: float = 0.0
    exit_time: float = 0.0
    exit_reason: str = ""  # SL_HIT, TP_HIT, TRAIL, TIME_STOP, MANUAL, SCRATCH

    # Scale-in tracking
    scale_count: int = 1  # 1 = full, 2 = first scale, 3 = second scale
    scale_in_prices: list[float] = field(default_factory=list)

    # P&L
    realized_pnl: float = 0.0
    commission: float = 0.0
    slippage: float = 0.0

    # AMT context at entry
    entry_poc: float = 0.0
    entry_vah: float = 0.0
    entry_val: float = 0.0
    entry_drive_number: int = 0

    @property
    def current_pnl(self) -> float:
        """Unrealized P&L (requires current_price — computed externally)."""
        return 0.0  # Computed by portfolio tracker with live price

    @property
    def total_cost(self) -> float:
        return self.commission + self.slippage

    @property
    def net_pnl(self) -> float:
        return self.realized_pnl - self.total_cost

    @property
    def duration_seconds(self) -> float:
        end = self.exit_time if self.exit_time > 0 else time.time()
        return end - self.entry_time

    @property
    def duration_minutes(self) -> float:
        return self.duration_seconds / 60.0

    def to_dict(self) -> dict:
        return {
            "trade_id": self.trade_id,
            "symbol": self.symbol,
            "underlying_symbol": self.underlying_symbol,
            "side": self.side.value,
            "entry_price": self.entry_price,
            "quantity": self.quantity,
            "lots": self.lots,
            "stop_loss": self.stop_loss,
            "take_profit": self.take_profit,
            "trail_price": self.trail_price,
            "status": self.status.value,
            "entry_time": self.entry_time,
            "exit_price": self.exit_price,
            "exit_time": self.exit_time,
            "exit_reason": self.exit_reason,
            "scale_count": self.scale_count,
            "realized_pnl": self.realized_pnl,
            "net_pnl": self.net_pnl,
            "duration_minutes": round(self.duration_minutes, 1),
        }
