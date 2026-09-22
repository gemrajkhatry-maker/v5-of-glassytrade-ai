"""Portfolio aggregate root — encapsulates all portfolio invariants.

The Portfolio is the central aggregate managing positions, balance, equity,
trade history, and enforcing risk constraints.
"""

from __future__ import annotations

from typing import Any

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from decimal import Decimal

from quant.contracts.enums import Side, Source, PositionStatus
from quant.contracts.entities import Position, Signal
from quant.contracts.value_objects import StrategyStats

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration (could be injected; kept as module-level for simplicity)
# ---------------------------------------------------------------------------

INITIAL_CAPITAL: Decimal = Decimal("1000000")  # 10 lakhs INR (1M)
LEVERAGE: int = 1
RISK_PER_TRADE: Decimal = Decimal("0.01")
MAX_HISTORY: int = 1000
HISTORY_MIN_INTERVAL_SEC: float = 60.0
MAX_PARTICIPATION_PCT: Decimal = Decimal("0.02")  # Never be > 2% of avg daily volume

# Commission & Slippage Model (NFO Options)
# Round-trip costs: STT (₹17.5/lot), Exchange txn (₹3.2/lot),
# GST (18% on brokerage+txn), Stamp duty, SEBI charges.
# Total per-lot round-trip ≈ ₹40-60 for NFO options.
COMMISSION_PER_LOT: Decimal = Decimal("50.0")  # ₹50 round-trip per lot (conservative)
DEFAULT_LOT_SIZE: int = 1  # Overridden per-instrument at runtime
SLIPPAGE_PCT: Decimal = Decimal(
    "0.0015"
)  # Default 0.15% (15 bps); overridden via PortfolioConfig at runtime

# Tiered risk by confidence level (Fabio Valentini position sizing)
RISK_BY_CONFIDENCE: dict[str, Decimal] = {
    "High": Decimal("0.005"),  # A setup: 0.5%
    "Medium": Decimal("0.0035"),  # B setup: 0.35%
    "Low": Decimal("0.0025"),  # C setup: 0.25%
}


@dataclass
class PortfolioConfig:
    """Configuration for Portfolio behavior."""

    initial_capital: Decimal = field(default_factory=lambda: INITIAL_CAPITAL)
    leverage: int = LEVERAGE
    risk_per_trade: Decimal = field(default_factory=lambda: RISK_PER_TRADE)
    slippage_pct: Decimal = field(default_factory=lambda: SLIPPAGE_PCT)
    commission_per_lot: Decimal = field(default_factory=lambda: COMMISSION_PER_LOT)
    max_participation_pct: Decimal = field(
        default_factory=lambda: MAX_PARTICIPATION_PCT
    )


@dataclass
class Portfolio:
    """Aggregate root for portfolio management.

    All mutations go through public methods that enforce domain invariants.
    All monetary values use Decimal for precision in financial calculations.
    """

    balance: Decimal = field(default_factory=lambda: INITIAL_CAPITAL)
    equity: Decimal = field(default_factory=lambda: INITIAL_CAPITAL)
    leverage: int = LEVERAGE
    positions: list[Position] = field(default_factory=list)
    closed_trades: list[Position] = field(default_factory=list)
    history: list[dict] = field(default_factory=list)
    config: PortfolioConfig | None = field(default_factory=lambda: None)

    # ----- factories -----

    @staticmethod
    def create_default(capital: Decimal | float | int | None = None) -> "Portfolio":
        cap = (
            capital
            if capital is not None
            else INITIAL_CAPITAL
        )
        cap = cap if isinstance(cap, Decimal) else Decimal(str(cap))
        return Portfolio(
            balance=cap,
            equity=cap,
            leverage=LEVERAGE,
            config=PortfolioConfig(
                initial_capital=cap,
            ),
        )

    @staticmethod
    def _position_strike(metadata: dict | None) -> float | int:
        """Resolve the strike from position/signal metadata.

        The entry path stores the strike under ``option_strike`` (see
        EntryCoordinator).  ``strike`` is supported as a legacy alias so
        tests and other callers that use it keep working.
        """
        md = metadata or {}
        return md.get("strike") or md.get("option_strike") or 0

    @staticmethod
    def _position_option_type(metadata: dict | None) -> str:
        """Resolve the option type (CE/PE) from metadata, defaulting to empty."""
        md = metadata or {}
        raw = md.get("option_type") or md.get("type") or ""
        upper = str(raw).strip().upper()
        if upper in ("CE", "CALL"):
            return "CE"
        if upper in ("PE", "PUT"):
            return "PE"
        return ""

    def has_straddle_conflict(
        self, symbol: str, strike: float | int, new_meta: dict | None = None
    ) -> bool:
        """Check if opening a position would create a straddle.

        Straddles are forbidden in AMT - you cannot have both CE and PE
        at the same strike price simultaneously.

        Args:
            symbol: The underlying symbol (e.g., "CRUDEOIL")
            strike: The strike price to check
            new_meta: Metadata of the proposed new position (its option type
                determines whether the conflict is a true straddle).

        Returns:
            True if a straddle would be created, False otherwise
        """
        new_type = self._position_option_type(new_meta)
        for pos in self.positions:
            if not pos.is_open:
                continue
            pos_metadata = pos.metadata or {}
            pos_strike = self._position_strike(pos_metadata)
            # Check same symbol and SAME strike (exact match).
            # Only a true straddle (opposite option types at the same strike)
            # is blocked; same-direction positions at the same strike are
            # still rejected by the duplicate-source invariant.  If either
            # side has no option type, block conservatively.
            if pos.symbol == symbol and pos_strike == strike:
                pos_type = self._position_option_type(pos_metadata)
                if not pos_type or not new_type or pos_type != new_type:
                    return True
        return False

    def get_open_positions_summary(self) -> list[dict]:
        """Get summary of open positions for LLM context.
        
        Returns list of {symbol, strike, side, size} for each open position.
        """
        result = []
        for pos in self.positions:
            if pos.is_open:
                result.append({
                    "symbol": pos.symbol,
                    "strike": self._position_strike(pos.metadata),
                    "side": str(pos.side.value) if hasattr(pos.side, "value") else str(pos.side),
                    "size": float(pos.size),
                })
        return result

    # ----- queries -----

    def has_open_positions(self) -> bool:
        """Single source of truth: does this portfolio have any OPEN positions?"""
        return any(p.status == PositionStatus.OPEN for p in self.positions)

    def open_position_ids(self) -> set[str]:
        """Return set of IDs for all OPEN positions."""
        return {p.id for p in self.positions if p.status == PositionStatus.OPEN}

    def has_open_position_for_source(self, source: Source) -> bool:
        return any(p.source == source and p.is_open for p in self.positions)

    def get_stats(self, source: Source) -> StrategyStats:
        """Calculate strategy statistics filtered by *source*."""
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

    def _compute_commission(
        self, size: float | Decimal, metadata: dict | None = None
    ) -> Decimal:
        """Compute round-trip commission for a position.

        Uses lot-based commission when option_lot_size is explicitly known
        (NFO options), otherwise charges a single flat commission per trade.
        """
        size = self._scale_fraction_to_decimal(size)
        lot_size = Decimal(str((metadata or {}).get("option_lot_size", 0)))
        if lot_size > 0:
            num_lots = max(1, int(size / lot_size))
        else:
            # No lot info (equities, crypto, or tests) — flat fee per trade
            num_lots = 1
        return Decimal(num_lots) * COMMISSION_PER_LOT

    def _scale_fraction_to_decimal(self, value: float | Decimal) -> Decimal:
        """Convert scale_fraction parameter to Decimal."""
        if isinstance(value, Decimal):
            return value
        return Decimal(str(value))

    @staticmethod
    def _apply_slippage(
        price: float | Decimal,
        side: Side,
        is_entry: bool,
        slippage_pct: Decimal = SLIPPAGE_PCT,
    ) -> Decimal:
        """Apply slippage to a fill price.

        Entry: buy higher / sell lower (adverse).
        Exit: buy lower / sell higher (adverse).
        """
        price = Decimal(str(price)) if not isinstance(price, Decimal) else price

        if is_entry:
            return (
                price * (Decimal("1") + slippage_pct)
                if side == Side.LONG
                else price * (Decimal("1") - slippage_pct)
            )
        else:
            # Exit long = sell (adverse is lower), Exit short = buy (adverse is higher)
            return (
                price * (Decimal("1") - slippage_pct)
                if side == Side.LONG
                else price * (Decimal("1") + slippage_pct)
            )

    def open_position(
        self,
        signal: Signal,
        symbol: str,
        scale_fraction: float | Decimal = 1.0,
    ) -> Position | None:
        """Open a new position from *signal*, enforcing risk constraints.

        Position sizing uses tiered risk based on signal confidence:
        - High confidence (A setup): 0.5% risk per trade
        - Medium confidence (B setup): 0.35% risk per trade
        - Low confidence (C setup): 0.2% risk per trade

        ``scale_fraction`` controls how much of the full size to deploy
        (Fabio 40/30/30 scale-in: first entry uses 0.4, add-ons use 0.3).
        The full size is computed from risk, but only ``scale_fraction`` is deployed.

        Slippage is applied to the entry price to simulate real-world fills.

        Returns the created Position, or None if constraints prevent opening.
        """
        # Convert scale_fraction to Decimal if needed
        scale_fraction = self._scale_fraction_to_decimal(scale_fraction)

        # Invariant: no duplicate source positions
        if self.has_open_position_for_source(signal.source):
            return None

        # Straddle prevention: don't allow both CE and PE at same strike
        strike = self._position_strike(signal.metadata)
        if strike and self.has_straddle_conflict(symbol, strike, signal.metadata or {}):
            logger.warning(
                "Straddle prevention: blocking %s at strike %s - position already exists",
                symbol, strike
            )
            return None

        # Tiered position sizing based on confidence, clamped to 0.25%-0.5%
        # COMPOUNDING: Use session-aware risk if available (Fabio cushion system)
        session_risk_pct = (signal.metadata or {}).get("session_risk_pct", None)
        if session_risk_pct and session_risk_pct > 0:
            # Use dynamic session risk (compounding based on session P&L)
            risk_pct = Decimal(str(session_risk_pct))
        else:
            confidence = (signal.metadata or {}).get("confidence", "Medium")
            risk_pct = RISK_BY_CONFIDENCE.get(confidence, RISK_PER_TRADE)
        risk_pct = max(Decimal("0.0025"), min(Decimal("0.005"), risk_pct))  # hard clamp
        risk_amount = self.equity * risk_pct

        risk_per_unit = Decimal(str(abs(signal.price - signal.stop_loss)))
        if risk_per_unit == 0:
            return None

        full_size = risk_amount / risk_per_unit
        max_notional = self.equity * Decimal(self.leverage)
        signal_price = Decimal(str(signal.price))  # Ensure Decimal type
        if full_size * signal_price > max_notional:
            full_size = max_notional / signal_price

        # Apply scale-in fraction (Fabio Rule 4: 40/30/30)
        size = full_size * max(Decimal("0"), min(Decimal("1"), scale_fraction))
        if size <= 0:
            return None

        # Snap to whole lot multiples for options
        lot_size = Decimal(str((signal.metadata or {}).get("option_lot_size", 0)))
        if lot_size > 0:
            # Round size to nearest lot multiple (not truncate)
            num_lots = max(1.0, round(float(size) / float(lot_size)))
            size = Decimal(int(num_lots)) * lot_size
            full_size = max(full_size, size)  # ensure full_size >= deployed
        
        # MCX-specific: Ensure minimum 1 lot for commodity options
        if lot_size > 0 and size < lot_size * Decimal("0.5"):
            size = lot_size

        # Apply slippage to entry price for realistic fill simulation
        side = Side.LONG if signal.is_buy else Side.SHORT
        slipped_price = self._apply_slippage(signal.price, side, is_entry=True)

        position = Position.from_signal(signal, symbol, size)
        position.entry_price = slipped_price  # Override with slipped fill price
        # Store full_size in metadata so scale-in adds know the target
        if position.metadata is None:
            position.metadata = {}
        position.metadata["full_size"] = float(full_size)
        position.metadata["deployed_fraction"] = float(scale_fraction)

        self.positions.append(position)
        return position

    def add_to_position(
        self,
        position_id: str,
        add_fraction: float | Decimal,
        current_price: float | Decimal,
    ) -> bool:
        """Scale into an existing position (Fabio 40/30/30 rule).

        Adds ``add_fraction`` of the original full_size at ``current_price``.
        Uses weighted-average to adjust entry_price.
        Returns True if successful.
        """
        # Convert to Decimal if needed
        add_fraction = self._scale_fraction_to_decimal(add_fraction)
        current_price = self._scale_fraction_to_decimal(current_price)

        for pos in self.positions:
            if pos.id == position_id and pos.is_open:
                full_size = Decimal(str((pos.metadata or {}).get("full_size", 0)))
                deployed = Decimal(
                    str((pos.metadata or {}).get("deployed_fraction", 1.0))
                )
                if full_size <= 0 or deployed >= 1:
                    return False  # already fully deployed

                add_size = full_size * add_fraction
                new_total = pos.size + add_size

                # Weighted average entry
                pos.entry_price = (
                    pos.entry_price * pos.size + current_price * add_size
                ) / new_total
                pos.size = new_total

                # Update metadata
                new_deployed = min(Decimal("1"), deployed + add_fraction)
                if pos.metadata is None:
                    pos.metadata = {}
                pos.metadata["deployed_fraction"] = float(new_deployed)

                return True
        return False

    def recover_position(self, pos_data: dict[str, Any]) -> "Position | None":
        """Reconstruct an open position from persistent storage data.

        Called during engine startup to restore positions that were open
        when the process crashed or was restarted.  Rebuilds a Position
        entity from the raw dict saved by ``save_position`` and appends
        it to the positions list so it can resume being managed.
        """
        from quant.contracts.entities import Position
        from decimal import Decimal

        position_id = pos_data.get("id", "")
        if not position_id:
            return None

        # Skip if already present
        if any(p.id == position_id for p in self.positions):
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

    def partial_close_position(
        self,
        position_id: str,
        partial_pct: float | Decimal,
        price: float | Decimal,
        reason: str,
    ) -> Decimal:
        """Close partial_pct of a position. Returns realized PnL from the partial.

        The position remains open with reduced size. Stop loss on the Position
        entity is moved to break-even by the TradeManager.
        """
        # Convert to Decimal if needed
        partial_pct = self._scale_fraction_to_decimal(partial_pct)
        price = self._scale_fraction_to_decimal(price)

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

                # Track cumulative partial PnL for accurate final close accounting
                if pos.metadata is None:
                    pos.metadata = {}
                prev_partial = Decimal(
                    str(pos.metadata.get("partial_realized_pnl", 0.0))
                )
                pos.metadata["partial_realized_pnl"] = float(prev_partial + partial_pnl)

                # Move stop to break-even on the Position entity
                pos.stop_loss = pos.entry_price

                # If all partials sum to full size, treat as a full close
                if pos.size <= 0:
                    pos.size = Decimal("0")
                    pos.status = PositionStatus.CLOSED
                    pos.close_reason = f"{reason} — full size closed"
                    pos.exit_price = price

                return partial_pnl
        return Decimal("0")

    def close_position(
        self, position_id: str, price: float | Decimal, reason: str = "LLM_EXIT"
    ) -> Position | None:
        """Close a specific position by ID at the given price.

        Used by the LLM trading engine for manual exits.
        Applies slippage and commission to simulate real-world fills.
        Returns the closed Position, or None if not found.
        """
        # Convert to Decimal if needed
        price = self._scale_fraction_to_decimal(price)

        for i, pos in enumerate(self.positions):
            if pos.id == position_id and pos.is_open:
                logger.debug(
                    "Portfolio.close_position: CLOSING %s reason=%s price=%.2f",
                    position_id,
                    reason,
                    float(price) if hasattr(price, "__float__") else price,
                )
                # Apply slippage to exit fill
                fill_price = self._apply_slippage(price, pos.side, is_entry=False)
                pos.close(
                    fill_price,
                    datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
                    reason,
                )
                # Deduct commission from P&L
                commission = self._compute_commission(pos.size, pos.metadata)
                pos.pnl -= commission
                # Store realized partial PnL in closed trade record for accurate reporting
                partial_realized = Decimal(
                    str((pos.metadata or {}).get("partial_realized_pnl", 0.0))
                )
                pos.pnl += partial_realized  # combine partial + runner for display
                self.balance += (
                    pos.pnl - partial_realized
                )  # only credit runner portion (partial already credited)
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
        if (
            stripped.replace(".", "", 1).lstrip("-").isdigit()
            and "T" not in stripped
            and len(stripped) >= 9
        ):
            return float(stripped)
        return datetime.fromisoformat(stripped.replace("Z", "+00:00")).timestamp()

    def _append_history(self, time_str: str, pnl: Decimal) -> None:
        should_add = True
        if self.history:
            last_time = self.history[-1].get("time", "")
            try:
                curr_ts = self._parse_ts(time_str)
                last_ts = self._parse_ts(last_time)
                should_add = (curr_ts - last_ts) > HISTORY_MIN_INTERVAL_SEC
            except (ValueError, TypeError):
                should_add = True

        if should_add or not self.history:
            self.history.append({"time": time_str, "pnl": float(pnl)})
            if len(self.history) > MAX_HISTORY:
                self.history.pop(0)
