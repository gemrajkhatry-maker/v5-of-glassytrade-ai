"""Portfolio aggregate root — encapsulates all portfolio invariants.

The Portfolio is the central aggregate managing positions, balance, equity,
trade history, and enforcing risk constraints.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal
from typing import Any

from app.domain.trading.model.entities import Position, Signal
from app.domain.trading.model.enums import Side, Source, PositionStatus
from app.domain.trading.model.value_objects import OHLC, StrategyStats

logger = logging.getLogger(__name__)

# Constants
INITIAL_CAPITAL: Decimal = Decimal("1000000")  # 10 lakhs INR
LEVERAGE: int = 1
RISK_PER_TRADE: Decimal = Decimal("0.01")
MAX_HISTORY: int = 1000
HISTORY_MIN_INTERVAL_SEC: float = 60.0
MAX_PARTICIPATION_PCT: Decimal = Decimal("0.02")
COMMISSION_PER_LOT: Decimal = Decimal("50.0")
SLIPPAGE_PCT: Decimal = Decimal("0.0015")

RISK_BY_CONFIDENCE: dict[str, Decimal] = {
    "High": Decimal("0.005"),
    "Medium": Decimal("0.0035"),
    "Low": Decimal("0.0025"),
}


@dataclass
class PortfolioConfig:
    initial_capital: Decimal = field(default_factory=lambda: INITIAL_CAPITAL)
    leverage: int = LEVERAGE
    risk_per_trade: Decimal = field(default_factory=lambda: RISK_PER_TRADE)
    slippage_pct: Decimal = field(default_factory=lambda: SLIPPAGE_PCT)
    commission_per_lot: Decimal = field(default_factory=lambda: COMMISSION_PER_LOT)
    max_participation_pct: Decimal = field(default_factory=lambda: MAX_PARTICIPATION_PCT)


@dataclass
class Portfolio:
    """Aggregate root for portfolio management.

    All mutations go through public methods that enforce domain invariants.
    """

    balance: Decimal = field(default_factory=lambda: INITIAL_CAPITAL)
    equity: Decimal = field(default_factory=lambda: INITIAL_CAPITAL)
    leverage: int = LEVERAGE
    positions: list[Position] = field(default_factory=list)
    closed_trades: list[Position] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    config: PortfolioConfig | None = field(default_factory=PortfolioConfig)

    @staticmethod
    def create_default() -> "Portfolio":
        return Portfolio(
            balance=INITIAL_CAPITAL,
            equity=INITIAL_CAPITAL,
            leverage=LEVERAGE,
            config=PortfolioConfig(),
        )

    # ----- queries -----

    def has_open_positions(self) -> bool:
        return any(p.status == PositionStatus.OPEN for p in self.positions)

    def open_position_ids(self) -> set[str]:
        return {p.id for p in self.positions if p.status == PositionStatus.OPEN}

    def has_open_position_for_source(self, source: Source) -> bool:
        return any(p.source == source and p.is_open for p in self.positions)

    def has_straddle_conflict(self, symbol: str, strike: float | int) -> bool:
        """Check if opening a position would create a straddle."""
        for pos in self.positions:
            if not pos.is_open:
                continue
            pos_strike = (pos.metadata or {}).get("strike", 0)
            if pos.symbol == symbol and pos_strike == strike:
                return True
        return False

    def get_open_positions_summary(self) -> list[dict]:
        result = []
        for pos in self.positions:
            if pos.is_open:
                result.append({
                    "symbol": pos.symbol,
                    "strike": (pos.metadata or {}).get("strike", 0),
                    "side": str(pos.side.value),
                    "size": float(pos.size),
                })
        return result

    def get_stats(self, source: Source) -> StrategyStats:
        trades = [t for t in self.closed_trades if t.source == source]
        wins = [t for t in trades if t.pnl > 0]
        losses = [t for t in trades if t.pnl <= 0]
        net_profit = sum(t.pnl for t in trades)
        num_trades = len(trades)
        return StrategyStats(
            total_trades=num_trades,
            wins=len(wins),
            losses=len(losses),
            win_rate=(len(wins) / num_trades * 100) if num_trades else 0.0,
            net_profit=float(net_profit),
            avg_profit=float(net_profit / num_trades) if num_trades else 0.0,
            largest_win=float(max((t.pnl for t in wins), default=Decimal("0"))),
            largest_loss=float(min((t.pnl for t in losses), default=Decimal("0"))),
        )

    # ----- commands -----

    def process_tick(self, tick: OHLC) -> list[Position]:
        """Update all open positions with a new tick. Returns newly closed positions."""
        current_price = tick.close
        current_time = tick.time
        unrealized_pnl = Decimal("0")
        active: list[Position] = []
        newly_closed: list[Position] = []

        for pos in self.positions:
            should_close = False
            reason = ""
            sl_close, sl_reason = pos.should_close(
                tick.low if pos.side == Side.LONG else tick.high
            )
            tp_close, tp_reason = pos.should_close(
                tick.high if pos.side == Side.LONG else tick.low
            )
            if sl_close:
                should_close, reason = sl_close, sl_reason
            elif tp_close:
                should_close, reason = tp_close, tp_reason

            if should_close:
                fill_price = self._apply_slippage(current_price, pos.side, is_entry=False)
                pos.close(fill_price, current_time, reason)
                commission = self._compute_commission(pos.size, pos.metadata)
                pos.pnl -= commission
                newly_closed.append(pos)
                self.balance += pos.pnl
            else:
                pos.update_pnl(current_price)
                active.append(pos)
                unrealized_pnl += pos.pnl

        self.positions = active
        self.closed_trades.extend(newly_closed)
        if len(self.closed_trades) > 200:
            self.closed_trades = self.closed_trades[-200:]
        self.equity = self.balance + unrealized_pnl
        self._append_history(current_time, unrealized_pnl)
        return newly_closed

    def open_position(
        self, signal: Signal, symbol: str, scale_fraction: float | Decimal = 1.0
    ) -> Position | None:
        """Open a new position from signal, enforcing risk constraints."""
        scale_fraction = self._to_decimal(scale_fraction)

        if self.has_open_position_for_source(signal.source):
            return None

        strike = (signal.metadata or {}).get("strike", 0)
        if strike and self.has_straddle_conflict(symbol, strike):
            logger.warning("Straddle prevention: blocking %s at strike %s", symbol, strike)
            return None

        confidence = (signal.metadata or {}).get("confidence", "Medium")
        risk_pct = RISK_BY_CONFIDENCE.get(confidence, RISK_PER_TRADE)
        risk_pct = max(Decimal("0.0025"), min(Decimal("0.005"), risk_pct))
        risk_amount = self.equity * risk_pct
        risk_per_unit = Decimal(str(abs(signal.price - signal.stop_loss)))
        if risk_per_unit == 0:
            return None

        full_size = risk_amount / risk_per_unit
        max_notional = self.equity * Decimal(self.leverage)
        signal_price = Decimal(str(signal.price))
        if full_size * signal_price > max_notional:
            full_size = max_notional / signal_price

        size = full_size * max(Decimal("0"), min(Decimal("1"), scale_fraction))
        if size <= 0:
            return None

        lot_size = Decimal(str((signal.metadata or {}).get("option_lot_size", 0)))
        if lot_size > 0:
            num_lots = max(1.0, round(float(size) / float(lot_size)))
            size = Decimal(int(num_lots)) * lot_size

        side = Side.LONG if signal.is_buy else Side.SHORT
        slipped_price = self._apply_slippage(signal.price, side, is_entry=True)

        position = Position.from_signal(signal, symbol, size)
        position.entry_price = slipped_price
        if position.metadata is None:
            position.metadata = {}
        position.metadata["full_size"] = float(full_size)
        position.metadata["deployed_fraction"] = float(scale_fraction)

        self.positions.append(position)
        return position

    def close_position(
        self, position_id: str, price: float | Decimal, reason: str = "LLM_EXIT"
    ) -> Position | None:
        """Close a specific position by ID."""
        price = self._to_decimal(price)
        for i, pos in enumerate(self.positions):
            if pos.id == position_id and pos.is_open:
                fill_price = self._apply_slippage(price, pos.side, is_entry=False)
                pos.close(fill_price, datetime.now(timezone.utc).isoformat(), reason)
                commission = self._compute_commission(pos.size, pos.metadata)
                pos.pnl -= commission
                self.balance += pos.pnl
                self.closed_trades.append(pos)
                if len(self.closed_trades) > 200:
                    self.closed_trades = self.closed_trades[-200:]
                self.positions.pop(i)
                self.equity = self.balance + sum(p.pnl for p in self.positions)
                return pos
        return None

    def partial_close_position(
        self, position_id: str, partial_pct: float | Decimal, price: float | Decimal, reason: str
    ) -> Decimal:
        """Close partial_pct of a position. Returns realized PnL."""
        partial_pct = self._to_decimal(partial_pct)
        price = self._to_decimal(price)
        for pos in self.positions:
            if pos.id == position_id and pos.is_open:
                diff = (price - pos.entry_price if pos.side == Side.LONG
                        else pos.entry_price - price)
                partial_size = pos.size * partial_pct
                partial_pnl = diff * partial_size
                pos.size -= partial_size
                self.balance += partial_pnl
                self.equity = self.balance + sum(p.pnl for p in self.positions if p.is_open)
                if pos.metadata is None:
                    pos.metadata = {}
                prev = Decimal(str(pos.metadata.get("partial_realized_pnl", 0.0)))
                pos.metadata["partial_realized_pnl"] = float(prev + partial_pnl)
                pos.stop_loss = pos.entry_price
                if pos.size <= 0:
                    pos.size = Decimal("0")
                    pos.status = PositionStatus.CLOSED
                    pos.close_reason = f"{reason} — full size closed"
                    pos.exit_price = price
                return partial_pnl
        return Decimal("0")

    def add_to_position(
        self, position_id: str, add_fraction: float | Decimal, current_price: float | Decimal
    ) -> bool:
        """Scale into an existing position (Fabio 40/30/30 rule)."""
        add_fraction = self._to_decimal(add_fraction)
        current_price = self._to_decimal(current_price)
        for pos in self.positions:
            if pos.id == position_id and pos.is_open:
                full_size = Decimal(str((pos.metadata or {}).get("full_size", 0)))
                deployed = Decimal(str((pos.metadata or {}).get("deployed_fraction", 1.0)))
                if full_size <= 0 or deployed >= 1:
                    return False
                add_size = full_size * add_fraction
                new_total = pos.size + add_size
                pos.entry_price = (pos.entry_price * pos.size + current_price * add_size) / new_total
                pos.size = new_total
                new_deployed = min(Decimal("1"), deployed + add_fraction)
                if pos.metadata is None:
                    pos.metadata = {}
                pos.metadata["deployed_fraction"] = float(new_deployed)
                return True
        return False

    def recover_position(self, pos_data: dict[str, Any]) -> Position | None:
        """Reconstruct an open position from persistent storage data."""
        position_id = pos_data.get("id", "")
        if not position_id or any(p.id == position_id for p in self.positions):
            return None

        _dec = lambda v: Decimal(str(v)) if v is not None and v != 0 else Decimal("0")
        side_val = str(pos_data.get("side", "LONG")).upper()
        side = Side.LONG if side_val == "LONG" else Side.SHORT
        source_val = str(pos_data.get("source", "AMT")).upper()
        try:
            source = Source(source_val)
        except ValueError:
            source = Source.AMT

        pos = Position(
            id=position_id,
            symbol=str(pos_data.get("symbol", "")),
            side=side,
            source=source,
            entry_price=_dec(pos_data.get("entry_price")),
            size=_dec(pos_data.get("size")),
            stop_loss=_dec(pos_data.get("stop_loss")),
            take_profit=_dec(pos_data.get("take_profit")),
            pnl=Decimal("0"),
            entry_time=str(pos_data.get("opened_at", "")),
            status=PositionStatus.OPEN,
            metadata=pos_data.get("extra", pos_data.get("metadata", None)),
        )
        self.positions.append(pos)
        return pos

    # ----- internal -----

    def _to_decimal(self, value: float | Decimal) -> Decimal:
        return value if isinstance(value, Decimal) else Decimal(str(value))

    def _compute_commission(self, size: Decimal, metadata: dict | None) -> Decimal:
        lot_size = Decimal(str((metadata or {}).get("option_lot_size", 0)))
        if lot_size > 0:
            num_lots = max(1, int(size / lot_size))
        else:
            num_lots = 1
        return Decimal(num_lots) * COMMISSION_PER_LOT

    @staticmethod
    def _apply_slippage(
        price: float | Decimal, side: Side, is_entry: bool, slippage_pct: Decimal = SLIPPAGE_PCT
    ) -> Decimal:
        price = Decimal(str(price)) if not isinstance(price, Decimal) else price
        if is_entry:
            return (price * (Decimal("1") + slippage_pct) if side == Side.LONG
                    else price * (Decimal("1") - slippage_pct))
        else:
            return (price * (Decimal("1") - slippage_pct) if side == Side.LONG
                    else price * (Decimal("1") + slippage_pct))

    def _append_history(self, time_str: str, pnl: Decimal) -> None:
        should_add = True
        if self.history:
            try:
                last_ts = self._parse_ts(self.history[-1].get("time", ""))
                curr_ts = self._parse_ts(time_str)
                should_add = (curr_ts - last_ts) > HISTORY_MIN_INTERVAL_SEC
            except (ValueError, TypeError):
                should_add = True
        if should_add or not self.history:
            self.history.append({"time": time_str, "pnl": float(pnl)})
            if len(self.history) > MAX_HISTORY:
                self.history.pop(0)

    @staticmethod
    def _parse_ts(s: str) -> float:
        stripped = s.strip()
        if (stripped.replace(".", "", 1).lstrip("-").isdigit()
                and "T" not in stripped and len(stripped) >= 9):
            return float(stripped)
        return datetime.fromisoformat(stripped.replace("Z", "+00:00")).timestamp()
