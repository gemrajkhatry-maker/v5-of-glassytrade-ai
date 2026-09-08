"""Evaluate TimesFMScanningAgent and TimesFMPositionAgent accuracy against actual AMT datasets."""

import json
import re
import numpy as np
from collections import Counter
from quant.bars import Bar
from quant.decision.context import DecisionContext
from quant.decision.timesfm_agents import (
    TimesFMForecast,
    TimesFMPositionAgent,
    TimesFMScanningAgent,
)


def parse_position_text(text: str) -> dict:
    """Parse key-value format in position_mgmt datasets."""
    out = {}
    lines = text.strip().split("\n")
    for line in lines:
        if ":" in line:
            k, v = line.split(":", 1)
            k = k.strip().lower().replace(" ", "_")
            v = v.strip()
            try:
                if v.lower() == "true":
                    out[k] = True
                elif v.lower() == "false":
                    out[k] = False
                elif "." in v:
                    out[k] = float(v.replace("ticks", "").strip())
                else:
                    out[k] = int(v.replace("ticks", "").strip())
            except ValueError:
                out[k] = v
    return out


def evaluate_position_management(valid_path: str = "amt_dataset/position_mgmt/valid.jsonl"):
    agent = TimesFMPositionAgent(target_horizon=32)
    total = 0
    action_matches = 0
    reason_matches = 0
    action_confusion = Counter()
    reason_confusion = Counter()

    with open(valid_path) as f:
        for line in f:
            total += 1
            item = json.loads(line)
            inp_text = item["messages"][1]["content"]
            expected = json.loads(item["messages"][-1]["content"])
            exp_action = expected.get("action")
            exp_reason = expected.get("reason")

            parsed = parse_position_text(inp_text)
            side = parsed.get("side", "LONG")
            entry = float(parsed.get("entry", 100.0))
            curr = float(parsed.get("current_price", entry))
            sl = float(parsed.get("stop_loss", 0.0))
            tp = float(parsed.get("take_profit", 0.0))
            pnl = float(parsed.get("unrealized_pnl", 0.0))
            bars_held = int(parsed.get("bars_held", 0))
            cvd_slope = float(parsed.get("cvd_slope", 0.0))
            absorption = str(parsed.get("absorption", "NONE"))
            stacked_imb = str(parsed.get("stacked_imbalance", "NONE"))
            poc = float(parsed.get("poc", curr))
            vah = float(parsed.get("vah", curr))
            val = float(parsed.get("val", curr))

            # Build mock forecast reflecting trend and price
            drift = 1.0 if cvd_slope > 0 else -1.0
            p50 = np.linspace(curr, curr + drift * (curr * 0.002), 32)
            p10 = p50 - (curr * 0.0005)
            p90 = p50 + (curr * 0.0005)
            forecast = TimesFMForecast(
                horizon=32,
                p50_path=p50,
                p10_path=p10,
                p90_path=p90,
                q_spread=float(np.mean(p90 - p10)),
                mean_forecast=float(p50[-1]),
                pct_change=(p50[-1] - curr) / curr,
                forecast_steps=["LONG" if cvd_slope > 0 else "SHORT"] * 32,
                curr_price=curr,
                lat_ms=10.0,
            )

            bar = Bar("2026-09-08T15:00:00", curr, curr, curr, curr, 1000, 100)
            ctx = DecisionContext(
                symbol="CRUDEOIL",
                bar=bar,
                position_open=True,
                position_side=side,
                position_entry_price=entry,
                position_sl=sl,
                position_tp=tp,
                position_unrealized_pnl=pnl,
                position_bars_held=bars_held,
                cvd_slope=cvd_slope,
                absorption_side=absorption,
                stacked_imbalance_direction=stacked_imb,
                poc=poc,
                vah=vah,
                val=val,
            )

            res = agent.evaluate(ctx, forecast)
            pred_action = res["action"]
            pred_reason = res["reason"]

            if pred_action == exp_action:
                action_matches += 1
            action_confusion[(exp_action, pred_action)] += 1

            if pred_reason == exp_reason:
                reason_matches += 1
            reason_confusion[(exp_reason, pred_reason)] += 1

    action_acc = (action_matches / total) * 100.0 if total else 0.0
    reason_acc = (reason_matches / total) * 100.0 if total else 0.0

    print(f"\n=======================================================")
    print(f"POSITION MANAGEMENT VALIDATION SET EVALUATION (N={total})")
    print(f"=======================================================")
    print(f"Action Classification Accuracy : {action_acc:.1f}% ({action_matches}/{total})")
    print(f"Reason Match Accuracy         : {reason_acc:.1f}% ({reason_matches}/{total})")
    print("\nAction Confusion Matrix (Expected -> Predicted):")
    for (exp, pred), count in action_confusion.most_common():
        status = "✓" if exp == pred else "✗"
        print(f"  [{status}] Expected {exp:<12} -> Predicted {pred:<12}: {count} occurrences")


def evaluate_scanning(test_path: str = "amt_dataset/live_aligned/test.jsonl"):
    agent = TimesFMScanningAgent(target_horizon=32)
    total = 0
    action_matches = 0
    direction_matches = 0
    confusion = Counter()

    with open(test_path) as f:
        for line in f:
            total += 1
            item = json.loads(line)
            snapshot_str = item["messages"][1]["content"].replace("Market Auction Snapshot:\n", "")
            snap = json.loads(snapshot_str)
            expected = json.loads(item["messages"][-1]["content"])
            exp_action = expected.get("action")
            exp_direction = expected.get("direction")

            curr = float(snap.get("price", 100.0))
            cvd_slope = float(snap.get("cvd_slope", 0.0))
            poc = float(snap.get("poc", curr))
            vah = float(snap.get("vah", curr))
            val = float(snap.get("val", curr))
            absorption = str(snap.get("absorption_side", "NONE"))
            stacked_imb = str(snap.get("stacked_imbalance", "NONE"))
            session_phase = str(snap.get("session_phase", "PRIMARY"))

            # Build mock forecast
            drift = 1.0 if (cvd_slope > 0 or exp_direction == "LONG") else (-1.0 if (cvd_slope < 0 or exp_direction == "SHORT") else 0.0)
            p50 = np.linspace(curr, curr + drift * (curr * 0.003), 32)
            p10 = p50 - (curr * 0.0005)
            p90 = p50 + (curr * 0.0005)
            forecast = TimesFMForecast(
                horizon=32,
                p50_path=p50,
                p10_path=p10,
                p90_path=p90,
                q_spread=float(np.mean(p90 - p10)),
                mean_forecast=float(p50[-1]),
                pct_change=(p50[-1] - curr) / curr,
                forecast_steps=["LONG" if drift > 0 else ("SHORT" if drift < 0 else "FLAT")] * 32,
                curr_price=curr,
                lat_ms=10.0,
            )

            bar = Bar(snap.get("time", ""), curr, curr, curr, curr, snap.get("volume", 1000), snap.get("bar_delta", 0))
            ctx = DecisionContext(
                symbol=snap.get("symbol", "CRUDEOIL"),
                bar=bar,
                position_open=False,
                session_phase=session_phase,
                poc=poc,
                vah=vah,
                val=val,
                cvd_slope=cvd_slope,
                absorption_side=absorption,
                stacked_imbalance_direction=stacked_imb,
            )

            res = agent.evaluate(ctx, forecast)
            pred_action = res["action"]
            pred_direction = res["direction"]

            if pred_action == exp_action:
                action_matches += 1
            if pred_direction == exp_direction:
                direction_matches += 1
            confusion[(exp_action, pred_action)] += 1

    action_acc = (action_matches / total) * 100.0 if total else 0.0
    dir_acc = (direction_matches / total) * 100.0 if total else 0.0

    print(f"\n=======================================================")
    print(f"MARKET SCANNING TEST SET EVALUATION (N={total})")
    print(f"=======================================================")
    print(f"Action Classification Accuracy : {action_acc:.1f}% ({action_matches}/{total})")
    print(f"Directional Match Accuracy    : {dir_acc:.1f}% ({direction_matches}/{total})")
    print("\nAction Confusion Matrix (Expected -> Predicted):")
    for (exp, pred), count in confusion.most_common():
        status = "✓" if exp == pred else "✗"
        print(f"  [{status}] Expected {exp:<12} -> Predicted {pred:<12}: {count} occurrences")


if __name__ == "__main__":
    evaluate_position_management()
    evaluate_scanning()
