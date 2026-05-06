"""Risk Manager — domain service validating signals before execution.

Ported from backend/app/domain/trading/services/risk_manager.py.
Daily drawdown, consecutive losses, position limits, kill switch, drift detection.
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass, field
from datetime import date, datetime, timezone, timedelta
from decimal import Decimal

from app.domain.trading.model.entities import Signal, Position
from app.domain.trading.model.aggregates import Portfolio
from app.domain.trading.model.enums import PositionStatus

logger = logging.getLogger(__name__)

IST = timezone(timedelta(hours=5, minutes=30))


@dataclass
class DailyRiskState:
    """Tracks intra-day risk metrics. Resets on new trading day."""
    trade_date: date = field(default_factory=lambda: datetime.now(IST).date())
    starting_equity: float = 0.0
    peak_equity: float = 0.0
    current_equity: float = 0.0
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


class KillSwitch:
    """Emergency kill switch — halts all trading immediately."""
    def __init__(self):
        self.is_halted = False
        self.reason = ""
        self.triggered_at: datetime | None = None

    def trigger(self, reason: str) -> None:
        self.is_halted = True
        self.reason = reason
        self.triggered_at = datetime.now(IST)
        logger.critical("KILL SWITCH TRIGGERED: %s", reason)

    def reset(self) -> None:
        self.is_halted = False
        self.reason = ""
        self.triggered_at = None


class RiskManager:
    """Validates trade signals against portfolio risk constraints.

    Circuit-breaker thresholds (per Fabio AMT spec FR-10):
    - MAX_DAILY_DRAWDOWN_PCT: 2% from peak equity (FR-10-04)
    - MAX_CONSECUTIVE_LOSSES: 3 consecutive losses = pause (FR-10-03)
    - MAX_CONCURRENT_POSITIONS: 5
    - MAX_PORTFOLIO_NOTIONAL_PCT: 60% of equity total
    - MAX_PER_SYMBOL_NOTIONAL_PCT: 20% of equity per symbol
    """

    MAX_DAILY_DRAWDOWN_PCT = 0.02
    MAX_CONSECUTIVE_LOSSES = 3
    MAX_CONCURRENT_POSITIONS = 5
    MAX_PORTFOLIO_NOTIONAL_PCT = Decimal("0.60")
    MAX_PER_SYMBOL_NOTIONAL_PCT = Decimal("0.20")

    def __init__(self, kill_switch: KillSwitch | None = None):
        self._daily = DailyRiskState()
        self._kill_switch = kill_switch
        self._recent_outcomes: list[bool] = []
        self._baseline_win_rate = 0.45
        self._drift_alert = False
        self._drift_message = ""

    @property
    def is_halted(self) -> bool:
        return (self._kill_switch is not None and self._kill_switch.is_halted) or self._daily.halted

    @property
    def halt_reason(self) -> str:
        if self._kill_switch is not None and self._kill_switch.is_halted:
            return f"Emergency kill switch: {self._kill_switch.reason}"
        return self._daily.halt_reason

    def check_signal(self, signal: Signal, portfolio: Portfolio) -> tuple[bool, str]:
        """Validate a trade signal against all risk constraints.

        Returns: (approved, rejection_reason)
        """
        # Kill switch check
        if self.is_halted:
            return False, self.halt_reason

        # Daily reset check
        today = datetime.now(IST).date()
        if today != self._daily.trade_date:
            self._daily.reset(float(portfolio.equity))

        # Daily drawdown check
        if self._daily.peak_equity > 0:
            drawdown_pct = (self._daily.peak_equity - self._daily.current_equity) / self._daily.peak_equity
            if drawdown_pct >= self.MAX_DAILY_DRAWDOWN_PCT:
                self._daily.halted = True
                self._daily.halt_reason = f"Daily drawdown {drawdown_pct:.1%} exceeds {self.MAX_DAILY_DRAWDOWN_PCT:.1%}"
                return False, self._daily.halt_reason

        # Consecutive losses check
        if self._daily.consecutive_losses >= self.MAX_CONSECUTIVE_LOSSES:
            return False, f"Consecutive losses ({self._daily.consecutive_losses}) >= limit ({self.MAX_CONSECUTIVE_LOSSES})"

        # Max concurrent positions check
        open_count = sum(1 for p in portfolio.positions if p.status == PositionStatus.OPEN)
        if open_count >= self.MAX_CONCURRENT_POSITIONS:
            return False, f"Max concurrent positions ({open_count}) >= limit ({self.MAX_CONCURRENT_POSITIONS})"

        # Portfolio notional check
        total_notional = sum(
            abs(float(p.entry_price) * float(p.size))
            for p in portfolio.positions
            if p.status == PositionStatus.OPEN
        )
        equity = float(portfolio.equity)
        if equity > 0 and Decimal(str(total_notional)) / Decimal(str(equity)) > self.MAX_PORTFOLIO_NOTIONAL_PCT:
            return False, f"Portfolio notional {total_notional/equity:.1%} exceeds {self.MAX_PORTFOLIO_NOTIONAL_PCT:.1%}"

        # Per-symbol notional check
        symbol_notional = sum(
            abs(float(p.entry_price) * float(p.size))
            for p in portfolio.positions
            if p.status == PositionStatus.OPEN and p.symbol == signal.metadata.get("symbol", "")
        )
        if equity > 0 and Decimal(str(symbol_notional)) / Decimal(str(equity)) > self.MAX_PER_SYMBOL_NOTIONAL_PCT:
            return False, f"Symbol notional {symbol_notional/equity:.1%} exceeds {self.MAX_PER_SYMBOL_NOTIONAL_PCT:.1%}"

        return True, ""

    def record_trade_result(self, pnl: float) -> None:
        """Record a closed trade result."""
        today = datetime.now(IST).date()
        if today != self._daily.trade_date:
            self._daily.reset(self._daily.current_equity + pnl)

        self._daily.total_trades += 1
        self._daily.realized_pnl += pnl
        self._daily.current_equity += pnl

        if pnl > 0:
            self._daily.consecutive_losses = 0
            if self._daily.current_equity > self._daily.peak_equity:
                self._daily.peak_equity = self._daily.current_equity
        else:
            self._daily.consecutive_losses += 1
            if self._daily.consecutive_losses >= self.MAX_CONSECUTIVE_LOSSES:
                self._daily.halt_reason = f"{self.MAX_CONSECUTIVE_LOSSES} consecutive losses"

        self._recent_outcomes.append(pnl > 0)
        if len(self._recent_outcomes) > 50:
            self._recent_outcomes = self._recent_outcomes[-50:]

    def check_drift(self) -> tuple[bool, str]:
        """Detect win rate drift from historical baseline."""
        if len(self._recent_outcomes) < 20:
            return False, ""

        recent_wr = sum(1 for o in self._recent_outcomes[-20:] if o) / 20
        if abs(recent_wr - self._baseline_win_rate) > 0.15:
            self._drift_alert = True
            self._drift_message = f"Win rate drift: {recent_wr:.0%} vs baseline {self._baseline_win_rate:.0%}"
            return True, self._drift_message

        return False, ""

    @property
    def consecutive_losses(self) -> int:
        return self._daily.consecutive_losses

    @property
    def daily_pnl(self) -> float:
        return self._daily.realized_pnl

    @property
    def is_drift_alert(self) -> bool:
        return self._drift_alert
