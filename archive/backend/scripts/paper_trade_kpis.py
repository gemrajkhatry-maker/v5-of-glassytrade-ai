"""Paper / live closed-trade KPIs from SQLite (expectancy, drawdown, profit factor).

Reads the same `trades` table as production persistence (`SQLiteStorageAdapter`).
This is the intended **empirical** complement to gate/unit tests — not a substitute
for walk-forward validation.

Usage:
    python -m scripts.paper_trade_kpis [--db PATH] [--start YYYY-MM-DD] [--end YYYY-MM-DD] [--json OUT]

Environment:
    GLASSYTRADE_DB — default database path if --db omitted.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from dataclasses import dataclass

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.infrastructure.storage.database import SQLiteStorageAdapter


@dataclass
class KpiResult:
    """KPI computation result for closed trades."""
    total_trades: int
    wins: int
    losses: int
    win_rate: float
    total_pnl: float
    avg_win: float
    avg_loss: float
    profit_factor: float
    max_drawdown: float
    max_drawdown_pct: float
    sharpe_ratio: float


def compute_kpis(trades: list, initial_capital: float = 10_000_000) -> KpiResult:
    """Compute KPIs from closed trades list."""
    if not trades:
        return KpiResult(0, 0, 0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0, 0.0)

    wins = [t.pnl for t in trades if t.pnl > 0]
    losses = [t.pnl for t in trades if t.pnl <= 0]
    total = len(trades)
    win_rate = (len(wins) / total * 100) if total else 0.0
    total_pnl = sum(t.pnl for t in trades)
    avg_win = sum(wins) / len(wins) if wins else 0.0
    avg_loss = abs(sum(losses) / len(losses)) if losses else 0.0
    gross_profit = sum(wins)
    gross_loss = abs(sum(losses))
    profit_factor = gross_profit / gross_loss if gross_loss > 0 else 0.0

    # Compute equity curve for drawdown
    equity = initial_capital
    peak = equity
    max_dd = 0.0
    for t in trades:
        equity += t.pnl
        peak = max(peak, equity)
        dd = peak - equity
        if dd > max_dd:
            max_dd = dd
    max_dd_pct = (max_dd / initial_capital) if initial_capital else 0.0

    # Approximate Sharpe (simplified - assumes daily returns)
    returns = [t.pnl / initial_capital for t in trades] if trades else [0]
    avg_ret = sum(returns) / len(returns) if returns else 0
    std_ret = (sum((r - avg_ret) ** 2 for r in returns) / len(returns)) ** 0.5 if len(returns) > 1 else 0
    sharpe = (avg_ret / std_ret) * (len(returns) ** 0.5) if std_ret > 0 else 0.0

    return KpiResult(
        total_trades=total,
        wins=len(wins),
        losses=len(losses),
        win_rate=win_rate,
        total_pnl=total_pnl,
        avg_win=avg_win,
        avg_loss=avg_loss,
        profit_factor=profit_factor,
        max_drawdown=max_dd,
        max_drawdown_pct=max_dd_pct,
        sharpe_ratio=sharpe,
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Closed-trade KPIs (expectancy, DD, profit factor) from SQLite",
    )
    default_db = os.environ.get("GLASSYTRADE_DB", "glassytrade.db")
    parser.add_argument("--db", default=default_db, help="SQLite database path")
    parser.add_argument("--start", default=None, help="Filter closed_at >= (YYYY-MM-DD)")
    parser.add_argument("--end", default=None, help="Filter closed_at <= (YYYY-MM-DD)")
    parser.add_argument(
        "--capital",
        type=float,
        default=10_000_000,
        help="Starting equity for drawdown curve (reporting only)",
    )
    parser.add_argument("--json", default=None, help="Write full KPI dict to this path")
    args = parser.parse_args()

    storage = SQLiteStorageAdapter(db_path=args.db)
    trades = storage.query_trades(start=args.start, end=args.end)

    if not trades:
        print("No closed trades in range — cannot compute KPIs.")
        print(f"Database: {args.db}")
        return

    result = compute_kpis(trades, args.capital)
    n = result.total_trades
    expectancy = result.total_pnl / n if n else 0.0

    print("=" * 56)
    print(" CLOSED TRADE KPIs (paper / live history)")
    print("=" * 56)
    print(f"Database:        {args.db}")
    print(f"Trades:          {n} (wins={result.wins}, losses={result.losses})")
    print(f"Win rate:        {result.win_rate:.2f}%")
    print(f"Expectancy/trade:{expectancy:,.4f}  (avg PnL per closed trade)")
    print(f"Total P&L:       {result.total_pnl:,.2f}")
    print(f"Avg win:         {result.avg_win:,.2f}")
    print(f"Avg loss:        {result.avg_loss:,.2f}")
    print(f"Profit factor:   {result.profit_factor:.2f}")
    print(f"Max drawdown:    {result.max_drawdown:,.2f} ({result.max_drawdown_pct:.1%})")
    print(f"Sharpe (approx): {result.sharpe_ratio:.2f}")
    print("=" * 56)
    print("Interpretation: expectancy > 0 after costs/slippage is the production bar.")

    if args.json:
        out = {
            "db": args.db,
            "start": args.start,
            "end": args.end,
            "total_trades": result.total_trades,
            "wins": result.wins,
            "losses": result.losses,
            "win_rate_pct": result.win_rate,
            "expectancy_per_trade": expectancy,
            "total_pnl": result.total_pnl,
            "avg_win": result.avg_win,
            "avg_loss": result.avg_loss,
            "profit_factor": result.profit_factor,
            "max_drawdown": result.max_drawdown,
            "max_drawdown_pct": result.max_drawdown_pct,
            "sharpe_ratio": result.sharpe_ratio,
        }
        with open(args.json, "w", encoding="utf-8") as f:
            json.dump(out, f, indent=2)
        print(f"\nWrote {args.json}")


if __name__ == "__main__":
    main()
