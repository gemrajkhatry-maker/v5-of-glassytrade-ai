"""Daily Loss Tracker — tracks cumulative P&L and enforces daily loss limits."""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import date


class DailyLossTracker:
    """Tracks daily P&L and halts trading at max loss limit."""

    def __init__(self, capital: float, max_loss_pct: float = 3.0):
        self._capital = capital
        self._max_loss_pct = max_loss_pct
        self._daily_pnl: float = 0.0
        self._trades_today: int = 0
        self._current_date: str = str(date.today())
        self._is_halted: bool = False

    @property
    def is_halted(self) -> bool:
        return self._is_halted

    @property
    def daily_pnl(self) -> float:
        return self._daily_pnl

    @property
    def trades_today(self) -> int:
        return self._trades_today

    @property
    def max_loss_amount(self) -> float:
        return self._capital * (self._max_loss_pct / 100)

    def record_trade(self, pnl: float) -> None:
        """Record a completed trade's P&L."""
        self._check_date_rollover()
        self._daily_pnl += pnl
        self._trades_today += 1

        # Check halt condition
        if self._daily_pnl <= -self.max_loss_amount:
            self._is_halted = True

    def reset(self) -> None:
        self._daily_pnl = 0.0
        self._trades_today = 0
        self._is_halted = False
        self._current_date = str(date.today())

    def _check_date_rollover(self) -> None:
        today = str(date.today())
        if today != self._current_date:
            self.reset()
