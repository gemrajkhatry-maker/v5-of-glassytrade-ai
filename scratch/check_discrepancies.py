import json
from scratch.evaluate_dataset_accuracy import parse_position_text
from quant.decision.timesfm_agents import TimesFMPositionAgent, TimesFMForecast
import numpy as np
from quant.bars import Bar
from quant.decision.context import DecisionContext

agent = TimesFMPositionAgent(target_horizon=32)
with open("amt_dataset/position_mgmt/valid.jsonl") as f:
    for i, line in enumerate(f):
        item = json.loads(line)
        exp = json.loads(item["messages"][-1]["content"])
        if exp.get("action") == "EXIT":
            parsed = parse_position_text(item["messages"][1]["content"])
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
            rr_val = parsed.get("rr_achieved", 0.0)
            
            p50 = np.linspace(curr, curr + (1.0 if cvd_slope > 0 else -1.0) * 5.0, 32)
            forecast = TimesFMForecast(32, p50, p50 - 2, p50 + 2, 4.0, p50[-1], 0.001, ["LONG"]*32, curr, 10.0)
            bar = Bar("2026-09-08T15:00:00", curr, curr, curr, curr, 1000, 100)
            ctx = DecisionContext(symbol="X", bar=bar, position_open=True, position_side=side,
                                  position_entry_price=entry, position_sl=sl, position_tp=tp,
                                  position_unrealized_pnl=pnl, position_bars_held=bars_held,
                                  cvd_slope=cvd_slope, absorption_side=absorption, stacked_imbalance_direction=stacked_imb)
            res = agent.evaluate(ctx, forecast)
            if res["action"] != "EXIT":
                exp_reason = exp.get("reason")
                act = res["action"]
                reas = res["reason"]
                rat = exp.get("rationale")
                print(f"Sample {i}: expected EXIT ({exp_reason}), got {act} ({reas})")
                print(f"  side={side}, curr={curr}, entry={entry}, sl={sl}, pnl={pnl}, rr={rr_val}, cvd={cvd_slope}, abs={absorption}, imb={stacked_imb}, bars={bars_held}")
                print(f"  dataset rationale: {rat}")
