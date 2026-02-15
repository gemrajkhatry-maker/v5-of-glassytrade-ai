"""Portfolio aggregate root — encapsulates all portfolio invariants.

The Portfolio is the central aggregate managing positions, balance, equity,
trade history, and enforcing risk constraints.
"""

from __future__ import annotations

import copy
from dataclasses import dataclass, field
from datetime import datetime

from app.domain.trading.models.enums import Side, Source, PositionStatus
from app.domain.trading.models.entities import Position, Signal
from app.domain.trading.models.value_objects import OHLC, StrategyStats


# ---------------------------------------------------------------------------
# Configuration (could be injected; kept as module-level for simplicity)
# ---------------------------------------------------------------------------

INITIAL_CAPITAL: float = 10_000_000
LEVERAGE: int = 10
RISK_PER_TRADE: float = 0.01
MAX_HISTORY: int = 1000
HISTORY_MIN_INTERVAL_SEC: float = 60.0
BREAKEVEN_DELTA_THRESHOLD: float = 0.5


@dataclass
class Portfolio:
    """Aggregate root for portfolio management.

    All mutations go through public methods that enforce domain invariants.
    """
    balance: float = INITIAL_CAPITAL
    equity: float = INITIAL_CAPITAL
    leverage: int = LEVERAGE
    positions: list[Position] = field(default_factory=list)
    closed_trades: list[Position] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)

    # ----- factories -----

    @staticmethod
    def create_default() -> "Portfolio":
        return Portfolio(
            balance=INITIAL_CAPITAL,
            equity=INITIAL_CAPITAL,
            leverage=LEVERAGE,
        )

    # ----- queries -----

    def has_open_position_for_source(self, source: Source) -> bool:
        return any(p.source == source and p.is_open for p in self.positions)

    def get_stats(self, source: Source) -> StrategyStats:
        """Calculate strategy statistics filtered by *source*."""
        trades = [t for t in self.closed_trades if t.source == source]
        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]
        net_profit = sum(t.pnl for t in trades)

        return StrategyStats(
            total_trades=len(trades),
            wins=len(wins),
            losses=len(losses),
            win_rate=(len(wins) / len(trades) * 100) if trades else 0.0,
            net_profit=net_profit,
            avg_profit=net_profit / len(trades) if trades else 0.0,
            largest_win=max((t.pnl for t in wins), default=0.0),
            largest_loss=min((t.pnl for t in losses), default=0.0),
        )

    # ----- commands -----

    def process_tick(self, tick: OHLC) -> list[Position]:
        """Update all open positions with a new tick.

        Returns a list of positions that were closed during this tick.
        """
        current_price = tick.close
        current_time = tick.time
        unrealized_pnl = 0.0

        active: list[Position] = []
        newly_closed: list[Position] = []

        for pos in self.positions:
            # Break-even on strong CVD pressure
            norm_delta = tick.delta / tick.volume if tick.volume > 0 else 0.0
            if (pos.side == Side.LONG
                    and norm_delta > BREAKEVEN_DELTA_THRESHOLD
                    and pos.stop_loss < pos.entry_price):
                pos.move_stop_to_breakeven()
            elif (pos.side == Side.SHORT
                    and norm_delta < -BREAKEVEN_DELTA_THRESHOLD
                    and pos.stop_loss > pos.entry_price):
                pos.move_stop_to_breakeven()

            should_close, reason = pos.should_close(current_price)
            if should_close:
                pos.close(current_price, current_time, reason)
                newly_closed.append(pos)
                self.balance += pos.pnl
            else:
                pos.update_pnl(current_price)
                active.append(pos)
                unrealized_pnl += pos.pnl

        self.positions = active
        self.closed_trades.extend(newly_closed)
        self.equity = self.balance + unrealized_pnl

        # Equity history (throttled to one per minute)
        self._append_history(current_time, unrealized_pnl)

        return newly_closed

    def open_position(self, signal: Signal, symbol: str) -> Position | None:
        """Open a new position from *signal*, enforcing risk constraints.

        Returns the created Position, or None if constraints prevent opening.
        """
        # Invariant: no duplicate source positions
        if self.has_open_position_for_source(signal.source):
            return None

        # Position sizing based on risk
        risk_amount = self.equity * RISK_PER_TRADE
        risk_per_unit = abs(signal.price - signal.stop_loss)
        if risk_per_unit == 0:
            return None

        size = risk_amount / risk_per_unit
        max_notional = self.equity * self.leverage
        if size * signal.price > max_notional:
            size = max_notional / signal.price

        position = Position.from_signal(signal, symbol, size)
        self.positions.append(position)
        return position

    def close_position(self, position_id: str, price: float, reason: str = "LLM_EXIT") -> Position | None:
        """Close a specific position by ID at the given price.
        
        Used by the LLM trading engine for manual exits.
        Returns the closed Position, or None if not found.
        """
        for i, pos in enumerate(self.positions):
            if pos.id == position_id and pos.is_open:
                pos.close(price, datetime.utcnow().isoformat() + "Z", reason)
                self.balance += pos.pnl
                self.closed_trades.append(pos)
                self.positions.pop(i)
                self.equity = self.balance + sum(p.pnl for p in self.positions)
                return pos
        return None

    # ----- internal -----

    def _append_history(self, time_str: str, pnl: float) -> None:
        should_add = True
        if self.history:
            last_time = self.history[-1].get("time", "")
            try:
                curr_ts = datetime.fromisoformat(
                    time_str.replace("Z", "+00:00")
                ).timestamp()
                last_ts = datetime.fromisoformat(
                    last_time.replace("Z", "+00:00")
                ).timestamp()
                should_add = (curr_ts - last_ts) > HISTORY_MIN_INTERVAL_SEC
            except Exception:
                should_add = True

        if should_add or not self.history:
            self.history.append({"time": time_str, "pnl": pnl})
            if len(self.history) > MAX_HISTORY:
                self.history.pop(0)
