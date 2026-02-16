"""Backtesting Engine — replays historical ticks through the trading pipeline.

Computes performance metrics: Sharpe ratio, max drawdown, win rate, profit factor.
"""

from __future__ import annotations

import math
import logging
from dataclasses import dataclass, field
from typing import Any

logger = logging.getLogger(__name__)


@dataclass
class BacktestResult:
    """Summary of a backtest run."""
    total_trades: int = 0
    wins: int = 0
    losses: int = 0
    win_rate: float = 0.0
    total_pnl: float = 0.0
    max_drawdown: float = 0.0
    max_drawdown_pct: float = 0.0
    sharpe_ratio: float = 0.0
    profit_factor: float = 0.0
    avg_win: float = 0.0
    avg_loss: float = 0.0
    trade_log: list[dict[str, Any]] = field(default_factory=list)


class BacktestEngine:
    """Replays historical trades and computes performance metrics."""

    def __init__(self, initial_capital: float = 10_000_000) -> None:
        self._initial_capital = initial_capital

    def run(self, trades: list[dict[str, Any]]) -> BacktestResult:
        """Run backtest on a list of historical trades.

        Each trade dict should have at least: pnl, entry_price, exit_price, side.
        """
        if not trades:
            return BacktestResult()

        pnls = [t.get("pnl", 0) for t in trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        total_pnl = sum(pnls)
        win_rate = len(wins) / len(pnls) * 100 if pnls else 0

        # Max drawdown
        equity_curve = []
        running = self._initial_capital
        peak = running
        max_dd = 0.0
        max_dd_pct = 0.0
        for p in pnls:
            running += p
            equity_curve.append(running)
            if running > peak:
                peak = running
            dd = peak - running
            dd_pct = dd / peak if peak > 0 else 0
            if dd > max_dd:
                max_dd = dd
                max_dd_pct = dd_pct

        # Sharpe ratio (annualized, assuming ~252 trading days)
        if len(pnls) > 1:
            mean_ret = sum(pnls) / len(pnls)
            var = sum((p - mean_ret) ** 2 for p in pnls) / (len(pnls) - 1)
            std = math.sqrt(var) if var > 0 else 1e-9
            sharpe = (mean_ret / std) * math.sqrt(252) if std > 1e-9 else 0.0
        else:
            sharpe = 0.0

        # Profit factor
        gross_profit = sum(wins) if wins else 0
        gross_loss = abs(sum(losses)) if losses else 1e-9
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float('inf')

        return BacktestResult(
            total_trades=len(pnls),
            wins=len(wins),
            losses=len(losses),
            win_rate=win_rate,
            total_pnl=total_pnl,
            max_drawdown=max_dd,
            max_drawdown_pct=max_dd_pct,
            sharpe_ratio=sharpe,
            profit_factor=profit_factor,
            avg_win=sum(wins) / len(wins) if wins else 0,
            avg_loss=sum(losses) / len(losses) if losses else 0,
            trade_log=trades,
        )
