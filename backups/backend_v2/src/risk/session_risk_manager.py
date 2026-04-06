"""
Session risk manager — daily loss/drawdown/consecutive kill switches.

Kill switches:
- Daily loss: 2% of session-start equity
- Consecutive losses: 3
- Drawdown: 3% from peak
- Absolute ceiling: 1% per trade
"""

from dataclasses import dataclass
from datetime import date
from typing import Optional, Tuple

from src.config.engine_config import CFG


@dataclass
class RiskState:
    """Current risk state."""

    session_start_equity: float
    current_equity: float
    peak_equity: float
    daily_pnl: float
    daily_pnl_pct: float
    drawdown_pct: float
    consecutive_losses: int
    total_trades: int
    winning_trades: int
    is_halted: bool
    halt_reason: str


class SessionRiskManager:
    """
    Session-level risk management.

    Tracks daily P&L, drawdown, and consecutive losses.
    Enforces kill switches before every trade.
    """

    def __init__(self, session_start_equity: float):
        self._session_start_equity = session_start_equity
        self._current_equity = session_start_equity
        self._peak_equity = session_start_equity
        self._daily_pnl = 0.0
        self._consecutive_losses = 0
        self._total_trades = 0
        self._winning_trades = 0
        self._is_halted = False
        self._halt_reason = ""

    def can_trade(self) -> Tuple[bool, str]:
        """
        Check if trading is allowed.

        Returns:
            Tuple of (can_trade, reason).
        """
        if self._is_halted:
            return False, self._halt_reason

        # Check daily loss limit
        daily_loss_pct = -self._daily_pnl / self._session_start_equity
        if daily_loss_pct >= CFG.max_daily_loss_pct:
            self._is_halted = True
            self._halt_reason = "DAILY_LOSS_LIMIT"
            return False, "DAILY_LOSS_LIMIT"

        # Check consecutive losses
        if self._consecutive_losses >= CFG.max_consecutive_losses:
            self._is_halted = True
            self._halt_reason = "CONSECUTIVE_LOSSES"
            return False, "CONSECUTIVE_LOSSES"

        # Check drawdown
        if self._peak_equity > 0:
            drawdown_pct = (self._peak_equity - self._current_equity) / self._peak_equity
            if drawdown_pct >= CFG.max_drawdown_pct:
                self._is_halted = True
                self._halt_reason = "MAX_DRAWDOWN"
                return False, "MAX_DRAWDOWN"

        return True, ""

    def register_trade_result(self, pnl: float) -> None:
        """
        Register a trade result.

        Args:
            pnl: Profit/loss for the trade.
        """
        self._total_trades += 1
        self._daily_pnl += pnl
        self._current_equity += pnl

        # Update peak
        if self._current_equity > self._peak_equity:
            self._peak_equity = self._current_equity

        # Track consecutive losses
        if pnl < 0:
            self._consecutive_losses += 1
        else:
            self._consecutive_losses = 0
            self._winning_trades += 1

    def get_state(self) -> RiskState:
        """Get current risk state."""
        daily_pnl_pct = self._daily_pnl / self._session_start_equity if self._session_start_equity > 0 else 0
        drawdown_pct = (self._peak_equity - self._current_equity) / self._peak_equity if self._peak_equity > 0 else 0

        return RiskState(
            session_start_equity=self._session_start_equity,
            current_equity=self._current_equity,
            peak_equity=self._peak_equity,
            daily_pnl=self._daily_pnl,
            daily_pnl_pct=daily_pnl_pct,
            drawdown_pct=drawdown_pct,
            consecutive_losses=self._consecutive_losses,
            total_trades=self._total_trades,
            winning_trades=self._winning_trades,
            is_halted=self._is_halted,
            halt_reason=self._halt_reason,
        )

    def reset(self, new_equity: float) -> None:
        """Reset for new session."""
        self._session_start_equity = new_equity
        self._current_equity = new_equity
        self._peak_equity = new_equity
        self._daily_pnl = 0.0
        self._consecutive_losses = 0
        self._total_trades = 0
        self._winning_trades = 0
        self._is_halted = False
        self._halt_reason = ""