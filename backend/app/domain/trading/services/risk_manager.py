"""Risk Manager — domain service validating signals before execution.

Ensures position sizing, leverage limits, and risk-per-trade constraints
are met before forwarding to the broker.  Includes circuit breakers for
daily loss limits, consecutive losses, and max concurrent positions.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal

# IST (UTC+5:30) — NSE/NFO trading timezone

from app.domain.trading.models.entities import Signal
from app.domain.trading.models.aggregates import Portfolio
from app.domain.trading.services.kill_switch import KillSwitch
from app.domain.constants import MAX_DAILY_LOSS_PCT, MAX_CONSECUTIVE_LOSSES
from app.shared.timezones import IST

logger = logging.getLogger(__name__)


@dataclass
class DailyRiskState:
    """Tracks intra-day risk metrics.  Resets on new trading day."""

    trade_date: date = field(default_factory=lambda: datetime.now(IST).date())
    starting_equity: float = 0.0
    peak_equity: float = 0.0  # High-water mark for the day
    current_equity: float = 0.0  # Updated after every trade result
    realized_pnl: float = 0.0
    consecutive_losses: int = 0
    total_trades: int = 0
    halted: bool = False
    halt_reason: str = ""

    def reset(self, equity: float) -> None:
        self.trade_date = datetime.now(IST).date()
        self.starting_equity = equity
        self.peak_equity = equity
        self.current_equity = equity
        self.realized_pnl = 0.0
        self.consecutive_losses = 0
        self.total_trades = 0
        self.halted = False
        self.halt_reason = ""


class RiskManager:
    """Validates trade signals against portfolio risk constraints."""

    # Circuit-breaker thresholds (per Fabio AMT spec FR-10)
    MAX_DAILY_DRAWDOWN_PCT: float = MAX_DAILY_LOSS_PCT  # 2% from day's peak equity (FR-10-04)
    MAX_CONSECUTIVE_LOSSES: int = MAX_CONSECUTIVE_LOSSES  # 3 consecutive losses = pause (FR-10-03)
    MAX_CONCURRENT_POSITIONS: int = 5
    MAX_PORTFOLIO_NOTIONAL_PCT: Decimal = Decimal("0.60")  # 60% of equity total
    MAX_PER_SYMBOL_NOTIONAL_PCT: Decimal = Decimal("0.20")  # 20% of equity per symbol

    def __init__(self, kill_switch: KillSwitch | None = None) -> None:
        self._daily = DailyRiskState()
        self._kill_switch = kill_switch

        # Drift detection — rolling win rate vs historical baseline
        self._recent_outcomes: list[bool] = []  # True=win, False=loss (last 50 trades)
        self._baseline_win_rate: float = 0.45  # Expected baseline from backtest
        self._drift_alert: bool = False
        self._drift_message: str = ""

    @property
    def is_halted(self) -> bool:
        return (self._kill_switch is not None and self._kill_switch.is_halted) or self._daily.halted

    @property
    def halt_reason(self) -> str:
        if self._kill_switch is not None and self._kill_switch.is_halted:
            return "Emergency kill switch active"
        return self._daily.halt_reason

    @property
    def daily_state(self) -> DailyRiskState:
        return self._daily

    # ------------------------------------------------------------------
    # Emergency kill switch (delegates to shared KillSwitch)
    # ------------------------------------------------------------------

    @staticmethod
    def halt_trading() -> None:
        """Deprecated: use KillSwitch.halt() directly."""
        logger.warning("RiskManager.halt_trading() is deprecated — use KillSwitch.halt()")

    @staticmethod
    def resume_trading() -> None:
        """Deprecated: use KillSwitch.resume() directly."""
        logger.warning("RiskManager.resume_trading() is deprecated — use KillSwitch.resume()")

    # ------------------------------------------------------------------
    # Core validation
    # ------------------------------------------------------------------

    def validate(self, signal: Signal, portfolio: Portfolio) -> bool:
        """Return True if *signal* passes all risk checks."""
        # Emergency kill switch — always checked first
        if self._kill_switch is not None and self._kill_switch.is_halted:
            logger.warning("Trade rejected: emergency kill switch active")
            return False

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

        # Pre-compute open positions once — used for multiple checks below
        open_positions = [p for p in portfolio.positions if p.is_open]

        # Max concurrent positions
        if len(open_positions) >= self.MAX_CONCURRENT_POSITIONS:
            logger.warning(
                "Trade rejected: max concurrent positions (%d)",
                self.MAX_CONCURRENT_POSITIONS,
            )
            return False

        # Portfolio notional cap (60% of equity)
        total_notional = sum(p.size * p.entry_price for p in open_positions)
        max_notional = portfolio.equity * self.MAX_PORTFOLIO_NOTIONAL_PCT
        if total_notional >= max_notional:
            logger.warning(
                "Trade rejected: portfolio notional cap (%.0f >= %.0f)",
                total_notional,
                max_notional,
            )
            return False

        # Per-symbol notional cap (20% of equity) — prevents one symbol eating the whole book
        # Uses signal.symbol if available, else falls back to position symbol
        sig_symbol = getattr(signal, "symbol", None)
        if sig_symbol and portfolio.equity > 0:
            symbol_notional = sum(
                p.size * p.entry_price
                for p in open_positions
                if getattr(p, "symbol", None) == sig_symbol
            )
            max_sym_notional = portfolio.equity * self.MAX_PER_SYMBOL_NOTIONAL_PCT
            if symbol_notional >= max_sym_notional:
                logger.warning(
                    "Trade rejected: per-symbol notional cap for %s (%.0f >= %.0f)",
                    sig_symbol,
                    symbol_notional,
                    max_sym_notional,
                )
                return False

        return True

    # ------------------------------------------------------------------
    # Post-trade feedback (call after a position closes)
    # ------------------------------------------------------------------

    def record_trade_result(self, pnl: float, portfolio: Portfolio) -> None:
        """Update daily risk state after a trade closes."""
        # Normalize Decimal values from Portfolio to float (this method
        # expects float throughout, but callers may pass Decimal).
        pnl = float(pnl)
        equity = float(portfolio.equity)

        self._maybe_reset_day(portfolio)
        self._daily.realized_pnl += pnl
        self._daily.total_trades += 1

        # Initialize peak equity on first call (lazy init for fresh sessions).
        # If the first trade is a loss, reconstruct pre-loss equity so the
        # drawdown denominator correctly reflects where we started the day.
        if self._daily.peak_equity <= 0:
            pre_trade_equity = equity + abs(pnl) if pnl < 0 else equity
            self._daily.peak_equity = pre_trade_equity
            self._daily.starting_equity = pre_trade_equity

        # Update current equity and high-water mark
        self._daily.current_equity = equity
        if equity > self._daily.peak_equity:
            self._daily.peak_equity = equity

        # Consecutive losses — breakeven (pnl == 0) is neutral, not a loss
        if pnl < 0:
            self._daily.consecutive_losses += 1
        else:
            self._daily.consecutive_losses = 0

        # Check circuit breakers
        if self._daily.consecutive_losses >= self.MAX_CONSECUTIVE_LOSSES:
            self._halt(
                f"Circuit breaker: {self._daily.consecutive_losses} consecutive losses"
            )

        # Percentage-based drawdown from day's peak equity
        if self._daily.peak_equity > 0:
            drawdown_pct = (
                self._daily.peak_equity - equity
            ) / self._daily.peak_equity
            if drawdown_pct >= self.MAX_DAILY_DRAWDOWN_PCT:
                self._halt(
                    f"Circuit breaker: daily drawdown {drawdown_pct:.1%} from peak exceeds {self.MAX_DAILY_DRAWDOWN_PCT:.0%} limit"
                )

        # Drift detection — rolling win rate vs baseline
        self._recent_outcomes.append(pnl > 0)
        if len(self._recent_outcomes) > 50:
            self._recent_outcomes = self._recent_outcomes[-50:]

        if len(self._recent_outcomes) >= 20:
            # math imported at top of module — no per-call import overhead
            n = len(self._recent_outcomes)
            rolling_wr = sum(self._recent_outcomes) / n
            sigma = math.sqrt(
                self._baseline_win_rate * (1 - self._baseline_win_rate) / n
            )
            threshold = self._baseline_win_rate - 2 * sigma
            if rolling_wr < threshold:
                self._drift_alert = True
                self._drift_message = (
                    f"Performance drift: rolling WR {rolling_wr:.0%} "
                    f"(last {n} trades) below threshold {threshold:.0%}"
                )
                logger.warning(self._drift_message)
            else:
                self._drift_alert = False
                self._drift_message = ""

    # ------------------------------------------------------------------
    # Internal helpers
    # ------------------------------------------------------------------

    def _maybe_reset_day(self, portfolio: Portfolio) -> None:
        """Reset daily state if the trading day has changed."""
        today = datetime.now(IST).date()
        if self._daily.trade_date != today:
            self._daily.reset(portfolio.equity)

    def _halt(self, reason: str) -> None:
        self._daily.halted = True
        self._daily.halt_reason = reason
        logger.warning("Trading HALTED: %s", reason)
