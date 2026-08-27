"""Live-Aligned Dataset Generator for Fabio AMT Trading Assistant.

Generates balanced, schema-faithful training & evaluation datasets containing:
- 1:1:1 balanced distribution (ENTER_LONG, ENTER_SHORT, FLAT)
- Multi-market coverage: NSE indices + MCX commodities
- Real DecisionContext JSON formatting matching the production engine
"""

from __future__ import annotations

import json
import random
import os
from pathlib import Path
from quant.contracts.enums import MarketState
from typing import Any, Dict, List

from quant.llm.bridge import SYSTEM_PROMPT


SYMBOLS = {
    "NSE": ["NIFTY", "BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"],
    "MCX": ["CRUDEOIL", "NATURALGAS", "GOLDM", "SILVERM"],
}

BASE_PRICES = {
    "NIFTY": 24200.0,
    "BANKNIFTY": 57400.0,
    "FINNIFTY": 26150.0,
    "MIDCPNIFTY": 14850.0,
    "CRUDEOIL": 8150.0,
    "NATURALGAS": 268.0,
    "GOLDM": 163000.0,
    "SILVERM": 248000.0,
}


def generate_scenario(target_action: str, symbol: str) -> Dict[str, Any]:
    """Generate a single realistic market state and ground-truth label."""
    base_px = BASE_PRICES[symbol]
    is_mcx = symbol in SYMBOLS["MCX"]

    if target_action == "ENTER_LONG":
        poc = base_px
        val = round(base_px * 0.995, 2)
        vah = round(base_px * 1.005, 2)
        px = round(val + random.uniform(0.5, 3.0), 2)
        delta = random.uniform(400, 1500)
        cvd_slope = random.uniform(2.5, 12.0)
        absorption = "BUY"
        shape = "b"
        phase = random.choice(["PRIMARY", "MID_SESSION", "POWER_HOUR" if is_mcx else "PRIMARY"])
        payload = {
            "symbol": symbol,
            "time": "10:15:00+05:30" if not is_mcx else "18:30:00+05:30",
            "session_phase": phase,
            "market_state": MarketState.BALANCED.value,
            "price": px,
            "volume": random.randint(1200, 5000),
            "bar_delta": round(delta, 1),
            "poc": poc,
            "vah": vah,
            "val": val,
            "cvd_slope": round(cvd_slope, 2),
            "absorption_side": absorption,
            "profile_shape": shape,
            "spread": 0.05 if not is_mcx else 1.0,
            "option_delta": round(random.uniform(0.45, 0.55), 2),
            "is_expiry": False,
            "stacked_imbalance": "BUY",
            "position_open": False,
            "risk_halted": False,
        }
        completion = {
            "action": "ENTER_LONG",
            "direction": "LONG",
            "setup": "TRIPLE_A",
            "confidence": "High",
            "rationale": f"Triple-A Long setup on {symbol}: Volume absorption at VAL ({val}) with positive CVD slope ({cvd_slope:.1f}) and b-shape accumulation.",
        }

    elif target_action == "ENTER_SHORT":
        poc = base_px
        val = round(base_px * 0.995, 2)
        vah = round(base_px * 1.005, 2)
        px = round(vah - random.uniform(0.5, 3.0), 2)
        delta = -random.uniform(400, 1500)
        cvd_slope = -random.uniform(2.5, 12.0)
        absorption = "SELL"
        shape = "P"
        phase = random.choice(["PRIMARY", "MID_SESSION", "POWER_HOUR" if is_mcx else "PRIMARY"])
        payload = {
            "symbol": symbol,
            "time": "11:30:00+05:30" if not is_mcx else "19:45:00+05:30",
            "session_phase": phase,
            "market_state": MarketState.BALANCED.value,
            "price": px,
            "volume": random.randint(1200, 5000),
            "bar_delta": round(delta, 1),
            "poc": poc,
            "vah": vah,
            "val": val,
            "cvd_slope": round(cvd_slope, 2),
            "absorption_side": absorption,
            "profile_shape": shape,
            "spread": 0.05 if not is_mcx else 1.0,
            "option_delta": round(random.uniform(0.45, 0.55), 2),
            "is_expiry": False,
            "stacked_imbalance": "SELL",
            "position_open": False,
            "risk_halted": False,
        }
        completion = {
            "action": "ENTER_SHORT",
            "direction": "SHORT",
            "setup": "TRIPLE_A",
            "confidence": "High",
            "rationale": f"Triple-A Short setup on {symbol}: Selling absorption at VAH ({vah}) with aggressive negative CVD slope ({cvd_slope:.1f}) and P-shape distribution.",
        }

    else:  # FLAT
        sub_type = random.choice(["OPENING_WARMUP", "CVD_CONFLICT", "MIDDAY_CHOP", "RISK_HALTED", "SPREAD_BLOWOUT"])
        poc = base_px
        val = round(base_px * 0.995, 2)
        vah = round(base_px * 1.005, 2)
        px = round(base_px + random.uniform(-5.0, 5.0), 2)

        if sub_type == "OPENING_WARMUP":
            phase = "OPENING_NOISE"
            rationale = "Opening noise / warmup phase active — no trade execution allowed."
            risk_halted = False
            spread = 0.05
            cvd_slope = random.uniform(-1.0, 1.0)
        elif sub_type == "CVD_CONFLICT":
            phase = "PRIMARY"
            px = val
            cvd_slope = -random.uniform(4.0, 9.0)  # conflicting negative CVD at support
            rationale = "Order flow conflict: price testing support but CVD slope is aggressively negative."
            risk_halted = False
            spread = 0.05
        elif sub_type == "RISK_HALTED":
            phase = "PRIMARY"
            risk_halted = True
            cvd_slope = 0.0
            rationale = "Daily risk threshold reached; trading engine halted."
            spread = 0.05
        elif sub_type == "SPREAD_BLOWOUT":
            phase = "PRIMARY"
            risk_halted = False
            spread = 15.0
            cvd_slope = 0.0
            rationale = "Bid-ask spread exceeds liquidity threshold; trade entry blocked."
        else:
            phase = "MIDDAY_CHOP"
            risk_halted = False
            spread = 0.05
            cvd_slope = random.uniform(-0.5, 0.5)
            rationale = "Midday low-volume compression inside value area; waiting for structural edge."

        payload = {
            "symbol": symbol,
            "time": "09:20:00+05:30" if phase == "OPENING_NOISE" else "12:45:00+05:30",
            "session_phase": phase,
            "market_state": MarketState.BALANCED.value,
            "price": px,
            "volume": random.randint(300, 1500),
            "bar_delta": round(random.uniform(-100, 100), 1),
            "poc": poc,
            "vah": vah,
            "val": val,
            "cvd_slope": round(cvd_slope, 2),
            "absorption_side": "NONE",
            "profile_shape": "D",
            "spread": spread,
            "option_delta": 0.5,
            "is_expiry": False,
            "stacked_imbalance": "NONE",
            "position_open": False,
            "risk_halted": risk_halted,
        }
        completion = {
            "action": "FLAT",
            "direction": "FLAT",
            "setup": "NO_EDGE",
            "confidence": "Low",
            "rationale": rationale,
        }

    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": f"Market Auction Snapshot:\n{json.dumps(payload, indent=2)}"},
            {"role": "assistant", "content": json.dumps(completion)},
        ]
    }


def generate_dataset(n_samples: int = 300) -> List[Dict[str, Any]]:
    """Generate a balanced dataset across all symbols and actions."""
    dataset = []
    actions = ["ENTER_LONG", "ENTER_SHORT", "FLAT"]
    all_symbols = SYMBOLS["NSE"] + SYMBOLS["MCX"]

    for i in range(n_samples):
        act = actions[i % 3]
        sym = random.choice(all_symbols)
        dataset.append(generate_scenario(act, sym))

    random.seed(42)
    random.shuffle(dataset)
    return dataset


def save_datasets(output_dir: str = "amt_dataset/live_aligned", train_n: int = 600, test_n: int = 150):
    os.makedirs(output_dir, exist_ok=True)
    train_data = generate_dataset(train_n)
    test_data = generate_dataset(test_n)

    train_path = os.path.join(output_dir, "train.jsonl")
    test_path = os.path.join(output_dir, "test.jsonl")

    with open(train_path, "w") as f:
        for item in train_data:
            f.write(json.dumps(item) + "\n")

    with open(test_path, "w") as f:
        for item in test_data:
            f.write(json.dumps(item) + "\n")

    print(f"Datasets generated successfully:\n  Train: {train_path} ({len(train_data)} records)\n  Test:  {test_path} ({len(test_data)} records)")


if __name__ == "__main__":
    save_datasets()
