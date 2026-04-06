"""CLI for running backtests on historical trade data.

Usage:
    python -m scripts.run_backtest [--db PATH] [--start DATE] [--end DATE]
"""

import argparse
import json
import sys
import os

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.infrastructure.storage.database import SQLiteStorageAdapter
from app.application.services.backtest_engine import BacktestEngine, BacktestResult


def main():
    parser = argparse.ArgumentParser(description="Run backtest on historical trades")
    parser.add_argument("--db", default="glassytrade.db", help="SQLite database path")
    parser.add_argument("--start", default=None, help="Start date (YYYY-MM-DD)")
    parser.add_argument("--end", default=None, help="End date (YYYY-MM-DD)")
    parser.add_argument("--capital", type=float, default=10_000_000, help="Initial capital")
    parser.add_argument("--output", default=None, help="Output JSON file path")
    args = parser.parse_args()

    storage = SQLiteStorageAdapter(db_path=args.db)
    trades = storage.query_trades(start=args.start, end=args.end)

    if not trades:
        print("No trades found in the specified range.")
        return

    engine = BacktestEngine(initial_capital=args.capital)
    result = engine.run(trades)

    print("=" * 50)
    print("         BACKTEST REPORT")
    print("=" * 50)
    print(f"Total Trades:    {result.total_trades}")
    print(f"Win Rate:        {result.win_rate:.1f}% ({result.wins}/{result.total_trades})")
    print(f"Total P&L:       ${result.total_pnl:,.2f}")
    print(f"Avg Win:         ${result.avg_win:,.2f}")
    print(f"Avg Loss:        ${result.avg_loss:,.2f}")
    print(f"Profit Factor:   {result.profit_factor:.2f}")
    print(f"Max Drawdown:    ${result.max_drawdown:,.2f} ({result.max_drawdown_pct:.1%})")
    print(f"Sharpe Ratio:    {result.sharpe_ratio:.2f}")
    print("=" * 50)

    if args.output:
        report = {
            "total_trades": result.total_trades,
            "wins": result.wins,
            "losses": result.losses,
            "win_rate": result.win_rate,
            "total_pnl": result.total_pnl,
            "max_drawdown": result.max_drawdown,
            "max_drawdown_pct": result.max_drawdown_pct,
            "sharpe_ratio": result.sharpe_ratio,
            "profit_factor": result.profit_factor,
        }
        with open(args.output, "w") as f:
            json.dump(report, f, indent=2)
        print(f"\nReport saved to {args.output}")


if __name__ == "__main__":
    main()
