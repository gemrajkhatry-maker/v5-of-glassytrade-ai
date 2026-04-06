"""Collect profitable trades from SQLite and generate Alpaca-format training examples.

Usage:
    python -m scripts.collect_training_data [--db PATH] [--output PATH] [--min-pnl FLOAT]
"""

import argparse
import json
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))


def main():
    parser = argparse.ArgumentParser(description="Collect training data from profitable trades")
    parser.add_argument("--db", default="glassytrade.db")
    parser.add_argument("--output", default="new_training_data.jsonl")
    parser.add_argument("--min-pnl", type=float, default=0, help="Minimum P&L to include")
    args = parser.parse_args()

    from app.infrastructure.storage.database import SQLiteStorageAdapter

    storage = SQLiteStorageAdapter(db_path=args.db)
    trades = storage.query_trades()

    instruction = (
        "Analyze the trading scenario based on Fabio Valentini's "
        "methodology (Orderflow, Auction Market Theory)."
    )

    count = 0
    with open(args.output, "w") as f:
        for trade in trades:
            pnl = trade.get("pnl", 0)
            if pnl < args.min_pnl:
                continue

            # Get corresponding LLM decision
            decisions = storage.query_llm_decisions(
                start=trade.get("opened_at"), end=trade.get("closed_at")
            )
            if not decisions:
                continue

            decision = decisions[0]
            input_prompt = decision.get("input_prompt", "")
            raw_output = decision.get("raw_output") or decision.get("rationale", "")

            if not input_prompt or not raw_output:
                continue

            example = {
                "instruction": instruction,
                "input": input_prompt,
                "output": raw_output,
            }
            f.write(json.dumps(example) + "\n")
            count += 1

    print(f"Collected {count} training examples → {args.output}")


if __name__ == "__main__":
    main()
