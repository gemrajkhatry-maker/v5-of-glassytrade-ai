"""Post-Trade Analytics — computes trading performance metrics.

Metrics:
- Win rate, loss rate
- Average win, average loss
- Expectancy = (Win% × Avg Win) - (Loss% × Avg Loss)
- Profit factor = Gross Profit / Gross Loss
- Max drawdown
- Consecutive wins/losses
- Average trade duration
- R-multiple distribution
"""

from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(frozen=True)
class TradeStats:
    total_trades: int
    wins: int
    losses: int
    win_rate: float  # 0-1
    avg_win: float
    avg_loss: float
    expectancy: float  # Per trade
    profit_factor: float
    gross_profit: float
    gross_loss: float
    max_drawdown: float
    max_consecutive_wins: int
    max_consecutive_losses: int
    avg_duration_minutes: float
    avg_r_multiple: float  # Risk multiple
    sharpe_ratio: float  # Annualized


class PostTradeAnalytics:
    """Computes trading performance metrics from trade history."""

    def __init__(self):
        self._trades: list[dict] = []

    def add_trade(self, trade_data: dict) -> None:
        """Add a completed trade.

        Expected keys:
            realized_pnl, duration_minutes, entry_price, stop_loss,
            exit_price, exit_reason
        """
        self._trades.append(trade_data)

    def compute_stats(self) -> TradeStats:
        """Compute all performance metrics."""
        if not self._trades:
            return TradeStats(
                total_trades=0, wins=0, losses=0, win_rate=0,
                avg_win=0, avg_loss=0, expectancy=0, profit_factor=0,
                gross_profit=0, gross_loss=0, max_drawdown=0,
                max_consecutive_wins=0, max_consecutive_losses=0,
                avg_duration_minutes=0, avg_r_multiple=0, sharpe_ratio=0,
            )

        pnls = [t.get("realized_pnl", 0) for t in self._trades]
        wins = [p for p in pnls if p > 0]
        losses = [p for p in pnls if p <= 0]

        total = len(pnls)
        win_count = len(wins)
        loss_count = len(losses)
        win_rate = win_count / total if total > 0 else 0

        avg_win = sum(wins) / win_count if win_count > 0 else 0
        avg_loss = sum(losses) / loss_count if loss_count > 0 else 0

        gross_profit = sum(wins)
        gross_loss = abs(sum(losses))
        profit_factor = gross_profit / gross_loss if gross_loss > 0 else float("inf")

        # Expectancy
        loss_rate = loss_count / total if total > 0 else 0
        expectancy = (win_rate * avg_win) - (loss_rate * abs(avg_loss))

        # Max drawdown (running)
        running_pnl = 0
        peak = 0
        max_dd = 0
        for pnl in pnls:
            running_pnl += pnl
            peak = max(peak, running_pnl)
            drawdown = peak - running_pnl
            max_dd = max(max_dd, drawdown)

        # Consecutive wins/losses
        max_cw = 0
        max_cl = 0
        cw = 0
        cl = 0
        for pnl in pnls:
            if pnl > 0:
                cw += 1
                cl = 0
            else:
                cl += 1
                cw = 0
            max_cw = max(max_cw, cw)
            max_cl = max(max_cl, cl)

        # Average duration
        durations = [t.get("duration_minutes", 0) for t in self._trades]
        avg_duration = sum(durations) / len(durations) if durations else 0

        # R-multiple (P&L / risk)
        r_multiples = []
        for t in self._trades:
            risk = abs(t.get("entry_price", 0) - t.get("stop_loss", 0))
            if risk > 0:
                r_mult = t.get("realized_pnl", 0) / (risk * t.get("quantity", 1))
                r_multiples.append(r_mult)
        avg_r = sum(r_multiples) / len(r_multiples) if r_multiples else 0

        # Sharpe ratio (simplified: mean/std of returns)
        if len(pnls) >= 2:
            mean_pnl = sum(pnls) / len(pnls)
            variance = sum((p - mean_pnl) ** 2 for p in pnls) / (len(pnls) - 1)
            std = variance ** 0.5
            sharpe = (mean_pnl / std) if std > 0 else 0
        else:
            sharpe = 0

        return TradeStats(
            total_trades=total,
            wins=win_count,
            losses=loss_count,
            win_rate=win_rate,
            avg_win=avg_win,
            avg_loss=avg_loss,
            expectancy=expectancy,
            profit_factor=profit_factor,
            gross_profit=gross_profit,
            gross_loss=gross_loss,
            max_drawdown=max_dd,
            max_consecutive_wins=max_cw,
            max_consecutive_losses=max_cl,
            avg_duration_minutes=avg_duration,
            avg_r_multiple=avg_r,
            sharpe_ratio=sharpe,
        )

    def reset(self) -> None:
        self._trades.clear()

    @property
    def trade_count(self) -> int:
        return len(self._trades)
