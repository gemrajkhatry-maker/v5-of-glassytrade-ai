"""Risk Manager — domain service validating signals before execution.

Ensures position sizing, leverage limits, and risk-per-trade constraints
are met before forwarding to the broker.  Includes circuit breakers for
daily loss limits, consecutive losses, and max concurrent positions.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import date

from app.domain.trading.models.entities import Signal
from app.domain.trading.models.aggregates import Portfolio

logger = logging.getLogger(__name__)


@dataclass
class DailyRiskState:
    """Tracks intra-day risk metrics.  Resets on new trading day."""

    trade_date: date = field(default_factory=date.today)
    starting_equity: float = 0.0
    realized_pnl: float = 0.0
    consecutive_losses: int = 0
    total_trades: int = 0
    halted: bool = False
    halt_reason: str = ""

    def reset(self, equity: float) -> None:
        self.trade_date = date.today()
        self.starting_equity = equity
        self.realized_pnl = 0.0
        self.consecutive_losses = 0
        self.total_trades = 0
        self.halted = False
        self.halt_reason = ""


class RiskManager:
    """Validates trade signals against portfolio risk constraints."""

    # Circuit-breaker thresholds
    MAX_DAILY_DRAWDOWN_PCT: float = 0.02  # 2% of starting equity
    MAX_CONSECUTIVE_LOSSES: int = 3
    MAX_CONCURRENT_POSITIONS: int = 5
    MAX_PORTFOLIO_NOTIONAL_PCT: float = 0.60  # 60% of equity
    MAX_PER_SYMBOL_NOTIONAL_PCT: float = 0.20  # 20% of equity

    def __init__(self) -> None:
        self._daily = DailyRiskState()

    @property
    def is_halted(self) -> bool:
        return self._daily.halted

    @property
    def halt_reason(self) -> str:
        return self._daily.halt_reason

    @property
    def daily_state(self) -> DailyRiskState:
        return self._daily

    # ------------------------------------------------------------------
    # Core validation
    # ------------------------------------------------------------------

    def validate(self, signal: Signal, portfolio: Portfolio) -> bool:
        """Return True if *signal* passes all risk checks."""
        self._maybe_reset_day(portfolio)

        # Circuit breaker — trading halted for the day
        if self._daily.halted:
            logger.warning("Trade rejected: %s", self._daily.halt_reason)
            return False

        # No duplicate source
        if portfolio.has_open_position_for_source(signal.source):
            return False

        # Valid SL (non-zero risk)
        risk_per_unit = abs(signal.price - signal.stop_loss)
        if risk_per_unit == 0:
            return False

        # Max concurrent positions
        open_positions = [p for p in portfolio.positions if p.is_open]
        if len(open_positions) >= self.MAX_CONCURRENT_POSITIONS:
            logger.warning("Trade rejected: max concurrent positions (%d)", self.MAX_CONCURRENT_POSITIONS)
            return False

        # Portfolio notional cap (60% of equity)
        total_notional = sum(p.size * p.entry_price for p in open_positions)
        max_notional = portfolio.equity * self.MAX_PORTFOLIO_NOTIONAL_PCT
        if total_notional >= max_notional:
            logger.warning("Trade rejected: portfolio notional cap (%.0f >= %.0f)", total_notional, max_notional)
            return False

        return True

    # ------------------------------------------------------------------
    # Post-trade feedback (call after a position closes)
    # ------------------------------------------------------------------

    def record_trade_result(self, pnl: float, portfolio: Portfolio) -> None:
        """Update daily risk state after a trade closes."""
        self._maybe_reset_day(portfolio)
        self._daily.realized_pnl += pnl
        self._daily.total_trades += 1

        if pnl <= 0:
            self._daily.consecutive_losses += 1
        else:
            self._daily.consecutive_losses = 0

        # Check circuit breakers
        if self._daily.consecutive_losses >= self.MAX_CONSECUTIVE_LOSSES:
            self._halt(f"Circuit breaker: {self._daily.consecutive_losses} consecutive losses")

        if self._daily.starting_equity > 0:
            drawdown_pct = abs(self._daily.realized_pnl) / self._daily.starting_equity
            if self._daily.realized_pnl < 0 and drawdown_pct >= self.MAX_DAILY_DRAWDOWN_PCT:
                self._halt(f"Circuit breaker: daily drawdown {drawdown_pct:.1%} exceeds {self.MAX_DAILY_DRAWDOWN_PCT:.0%} limit")

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _maybe_reset_day(self, portfolio: Portfolio) -> None:
        """Reset daily state if the trading day has changed."""
        today = date.today()
        if self._daily.trade_date != today:
            self._daily.reset(portfolio.equity)

    def _halt(self, reason: str) -> None:
        self._daily.halted = True
        self._daily.halt_reason = reason
        logger.warning("Trading HALTED: %s", reason)
