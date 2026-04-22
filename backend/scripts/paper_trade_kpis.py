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

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.application.services.backtest_engine import BacktestEngine
from app.infrastructure.storage.database import SQLiteStorageAdapter


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

    engine = BacktestEngine(initial_capital=args.capital)
    result = engine.run(trades)
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
