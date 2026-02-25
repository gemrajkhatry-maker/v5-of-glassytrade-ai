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

INITIAL_CAPITAL: float = 1_000_000  # 10 lakhs INR
LEVERAGE: int = 10
RISK_PER_TRADE: float = 0.01
MAX_HISTORY: int = 1000
HISTORY_MIN_INTERVAL_SEC: float = 60.0
MAX_PARTICIPATION_PCT: float = 0.02  # Never be > 2% of avg daily volume

# Tiered risk by confidence level (Fabio Valentini position sizing)
RISK_BY_CONFIDENCE: dict[str, float] = {
    "High": 0.005,    # A setup: 0.5%
    "Medium": 0.0035, # B setup: 0.35%
    "Low": 0.0025,    # C setup: 0.25%
}


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
            # LLM positions: SL/TP managed exclusively by TradeManager
            # (which handles trailing stops, partials, time-based exits).
            # Portfolio SL/TP only fires for non-LLM sources as a safety net.
            if pos.source == Source.LLM:
                pos.update_pnl(current_price)
                active.append(pos)
                unrealized_pnl += pos.pnl
                continue
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
        # Trim to prevent unbounded growth throughout the day
        if len(self.closed_trades) > 200:
            self.closed_trades = self.closed_trades[-200:]
        self.equity = self.balance + unrealized_pnl

        # Equity history (throttled to one per minute)
        self._append_history(current_time, unrealized_pnl)

        return newly_closed

    def open_position(
        self, signal: Signal, symbol: str, scale_fraction: float = 1.0,
    ) -> Position | None:
        """Open a new position from *signal*, enforcing risk constraints.

        Position sizing uses tiered risk based on signal confidence:
        - High confidence (A setup): 0.5% risk per trade
        - Medium confidence (B setup): 0.35% risk per trade
        - Low confidence (C setup): 0.2% risk per trade

        ``scale_fraction`` controls how much of the full size to deploy
        (Fabio 40/30/30 scale-in: first entry uses 0.4, add-ons use 0.3).
        The full size is computed from risk, but only ``scale_fraction`` is deployed.

        Returns the created Position, or None if constraints prevent opening.
        """
        # Invariant: no duplicate source positions
        if self.has_open_position_for_source(signal.source):
            return None

        # Tiered position sizing based on confidence, clamped to 0.25%-0.5%
        confidence = (signal.metadata or {}).get("confidence", "Medium")
        risk_pct = RISK_BY_CONFIDENCE.get(confidence, RISK_PER_TRADE)
        risk_pct = max(0.0025, min(0.005, risk_pct))  # hard clamp
        risk_amount = self.equity * risk_pct

        risk_per_unit = abs(signal.price - signal.stop_loss)
        if risk_per_unit == 0:
            return None

        full_size = risk_amount / risk_per_unit
        max_notional = self.equity * self.leverage
        if full_size * signal.price > max_notional:
            full_size = max_notional / signal.price

        # Apply scale-in fraction (Fabio Rule 4: 40/30/30)
        size = full_size * max(0.0, min(1.0, scale_fraction))
        if size <= 0:
            return None

        # Snap to whole lot multiples for options
        lot_size = (signal.metadata or {}).get("option_lot_size", 0)
        if lot_size > 0:
            num_lots = max(1, int(size / lot_size))
            size = float(num_lots * lot_size)
            full_size = max(full_size, size)  # ensure full_size >= deployed

        position = Position.from_signal(signal, symbol, size)
        # Store full_size in metadata so scale-in adds know the target
        if position.metadata is None:
            position.metadata = {}
        position.metadata["full_size"] = full_size
        position.metadata["deployed_fraction"] = scale_fraction

        self.positions.append(position)
        return position

    def add_to_position(self, position_id: str, add_fraction: float, current_price: float) -> bool:
        """Scale into an existing position (Fabio 40/30/30 rule).

        Adds ``add_fraction`` of the original full_size at ``current_price``.
        Uses weighted-average to adjust entry_price.
        Returns True if successful.
        """
        for pos in self.positions:
            if pos.id == position_id and pos.is_open:
                full_size = (pos.metadata or {}).get("full_size", 0)
                deployed = (pos.metadata or {}).get("deployed_fraction", 1.0)
                if full_size <= 0 or deployed >= 1.0:
                    return False  # already fully deployed

                add_size = full_size * add_fraction
                new_total = pos.size + add_size

                # Weighted average entry
                pos.entry_price = (
                    (pos.entry_price * pos.size + current_price * add_size) / new_total
                )
                pos.size = new_total

                # Update metadata
                new_deployed = min(1.0, deployed + add_fraction)
                pos.metadata["deployed_fraction"] = new_deployed

                return True
        return False

    def partial_close_position(
        self, position_id: str, partial_pct: float, price: float, reason: str
    ) -> float:
        """Close partial_pct of a position. Returns realized PnL from the partial.

        The position remains open with reduced size. Stop loss on the Position
        entity is moved to break-even by the TradeManager.
        """
        for pos in self.positions:
            if pos.id == position_id and pos.is_open:
                # Calculate PnL on the partial size
                diff = (
                    price - pos.entry_price
                    if pos.side == Side.LONG
                    else pos.entry_price - price
                )
                partial_size = pos.size * partial_pct
                partial_pnl = diff * partial_size

                # Reduce position size
                pos.size -= partial_size

                # Credit partial PnL to balance
                self.balance += partial_pnl
                self.equity = self.balance + sum(
                    p.pnl for p in self.positions if p.is_open
                )

                # Move stop to break-even on the Position entity
                pos.stop_loss = pos.entry_price

                return partial_pnl
        return 0.0

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
                # Trim to prevent unbounded growth throughout the day
                if len(self.closed_trades) > 200:
                    self.closed_trades = self.closed_trades[-200:]
                self.positions.pop(i)
                self.equity = self.balance + sum(p.pnl for p in self.positions)
                return pos
        return None

    # ----- internal -----

    @staticmethod
    def _parse_ts(s: str) -> float:
        """Parse a timestamp string to epoch seconds (handles ISO and epoch formats)."""
        stripped = s.strip()
        if stripped.replace(".", "", 1).lstrip("-").isdigit() and "T" not in stripped and len(stripped) >= 9:
            return float(stripped)
        return datetime.fromisoformat(stripped.replace("Z", "+00:00")).timestamp()

    def _append_history(self, time_str: str, pnl: float) -> None:
        should_add = True
        if self.history:
            last_time = self.history[-1].get("time", "")
            try:
                curr_ts = self._parse_ts(time_str)
                last_ts = self._parse_ts(last_time)
                should_add = (curr_ts - last_ts) > HISTORY_MIN_INTERVAL_SEC
            except Exception:
                should_add = True

        if should_add or not self.history:
            self.history.append({"time": time_str, "pnl": pnl})
            if len(self.history) > MAX_HISTORY:
                self.history.pop(0)
