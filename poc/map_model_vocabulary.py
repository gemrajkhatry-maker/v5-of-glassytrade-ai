"""Map the fine-tuned model's output vocabulary.

Generates 120 diverse trading scenarios, runs inference on each,
and catalogs all unique Trigger/Logic/Market State patterns.
"""

import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer
import json
import re
import random
import time
from collections import Counter

BASE_MODEL = "./models/Nanbeige4.1-3B"
ADAPTER_PATH = "./lora_adapter_mac"
INSTRUCTION = (
    "Analyze the trading scenario based on Fabio Valentini's "
    "methodology (Orderflow, Auction Market Theory)."
)

# ---------------------------------------------------------------------------
# Scenario generators — much broader than training data
# ---------------------------------------------------------------------------

def _rp(lo, hi):
    return random.randint(lo, hi)

def gen_aaa_long_scenarios(n=30):
    """AAA absorption at VAL — LONG setups."""
    templates = [
        "New York Open. Price is testing Value Area Low (VAL) at {val}. Sellers are aggressive with -{delta} Delta but price is not moving down. Big buy orders are hitting the bid.",
        "Price pushed below VAL {val} during London close but is dragging back inside. Footprint shows {vol} contracts sold at lows with no follow-through.",
        "Market is rotational. We are at the bottom of the distribution ({val}). Delta is continuously red but price is ticking higher.",
        "Price at {val}, sellers dumped {vol} contracts but passive buyers absorbed everything. Price holding firm.",
        "VAL test at {val}. Aggressive selling with -{delta} Delta. Footprint shows iceberg buyers. Price refuses to break lower.",
        "Opening range established near VAL {val}. Multiple attempts to break lower failed. Buy absorption visible in orderflow.",
    ]
    scenarios = []
    for _ in range(n):
        t = random.choice(templates)
        scenarios.append({
            "input": t.format(val=_rp(14900, 15000), delta=_rp(300, 800), vol=_rp(1000, 5000), vah=_rp(15100, 15200)),
            "expected": "LONG",
            "category": "AAA_Long",
        })
    return scenarios

def gen_momentum_long_scenarios(n=15):
    """Momentum/breakout LONG setups."""
    templates = [
        "Price broke above Value Area High {vah} with strong +{delta} Delta. Aggressive buyers are lifting the offer.",
        "Volatility spike. Price blasted through {vah}. A P-Shape profile is forming. Short covering in progress.",
        "Aggressive buyers pushing. Making Higher Highs. A wall of bids at {vah}. Delta +{delta}.",
        "Breakout above {vah} confirmed. Volume surge {vol} contracts. Buyers in full control.",
    ]
    scenarios = []
    for _ in range(n):
        t = random.choice(templates)
        scenarios.append({
            "input": t.format(vah=_rp(15100, 15200), delta=_rp(500, 2000), vol=_rp(2000, 8000)),
            "expected": "LONG",
            "category": "Momentum_Long",
        })
    return scenarios

def gen_failed_auction_short_scenarios(n=15):
    """Failed auction at VAH — SHORT setups."""
    templates = [
        "Price broke VAH {vah} but immediately stalled. Delta was +{delta} but price ticked down. Buyers are trapped at highs.",
        "Tried to squeeze the high at {vah} three times. Each time price rejected. Volume is drying up on the bid.",
        "Failed breakout above {vah}. Aggressive buyers trapped. Market rotating back inside value area.",
        "Price tagged {vah}, delta turned from +{delta} to negative. Sellers stepping in aggressively.",
    ]
    scenarios = []
    for _ in range(n):
        t = random.choice(templates)
        scenarios.append({
            "input": t.format(vah=_rp(15100, 15200), val=_rp(14900, 15000), delta=_rp(500, 1500)),
            "expected": "SHORT",
            "category": "Failed_Auction",
        })
    return scenarios

def gen_aaa_short_scenarios(n=15):
    """AAA absorption at VAH — SHORT setups (not in original training)."""
    templates = [
        "Price is testing Value Area High (VAH) at {vah}. Buyers are aggressive with +{delta} Delta but price is not moving up. Big sell orders absorbing all buying pressure.",
        "Price pushed above VAH {vah} but dragging back inside. Footprint shows {vol} contracts bought at highs with no follow-through.",
        "At the top of distribution ({vah}). Delta is continuously green but price is ticking lower. Sellers absorbing.",
        "VAH test at {vah}. Aggressive buying with +{delta} Delta. Iceberg sellers visible. Price refuses to break higher.",
    ]
    scenarios = []
    for _ in range(n):
        t = random.choice(templates)
        scenarios.append({
            "input": t.format(vah=_rp(15100, 15200), delta=_rp(300, 800), vol=_rp(1000, 5000)),
            "expected": "SHORT",
            "category": "AAA_Short",
        })
    return scenarios

def gen_risk_mgmt_scenarios(n=15):
    """Risk management — FLAT/walk away."""
    templates = [
        "We are up ${profit} for the session. Price is entering a chop zone/contraction.",
        "I took two stop losses. Down ${loss}. Market is not giving a clear setup.",
        "Floating ${profit} profit on a Long. Price is reaching a technical resistance.",
        "Third losing trade today. Down ${loss} total. No clear setups visible.",
        "Market is choppy, low volume. No clear direction. We've been flat for 30 minutes.",
    ]
    scenarios = []
    for _ in range(n):
        t = random.choice(templates)
        scenarios.append({
            "input": t.format(profit=_rp(5000, 25000), loss=_rp(1000, 5000)),
            "expected": "FLAT",
            "category": "Risk_Mgmt",
        })
    return scenarios

def gen_poc_scenarios(n=10):
    """Near POC — could go either way or FLAT."""
    templates = [
        "Market is inside the Value Area (Balance). Current price is {poc}. VAH at {vah}. VAL at {val}. POC at {poc}. Delta is neutral. Price is at the Point of Control.",
        "Price sitting at POC {poc}. No directional pressure. Volume declining. Waiting for catalyst.",
        "At POC {poc}, delta flipped from negative to +{delta}. Buyers stepping in. VAH at {vah}.",
        "Price at POC {poc} with aggressive sellers. Delta -{delta}. Breaking down toward VAL {val}.",
    ]
    scenarios = []
    for _ in range(n):
        poc = _rp(15000, 15100)
        t = random.choice(templates)
        scenarios.append({
            "input": t.format(poc=poc, vah=_rp(15100, 15200), val=_rp(14900, 15000), delta=_rp(200, 600)),
            "expected": "MIXED",
            "category": "POC",
        })
    return scenarios

def gen_edge_case_scenarios(n=10):
    """Edge cases: outside VA, crypto prices, ambiguous."""
    templates = [
        "Market is trending outside the Value Area (Imbalanced). Current price is {price}. VAH at {vah}. VAL at {val}. POC at {poc}. Buyers are aggressive with +{delta} Delta. Price is testing Value Area High (VAH). Watching for breakout or failed auction. Orderflow: Aggression Score: {agg}.",
        "Market is inside the Value Area (Balance). Current price is {price}. VAH at {vah}. VAL at {val}. POC at {poc}. Sellers are aggressive with -{delta} Delta. Price is testing Value Area Low (VAL). Watching for absorption or breakdown. Orderflow: Aggression Score: {agg}.",
        "BTC trading at {btc_price}. Value Area High at {btc_vah}. Value Area Low at {btc_val}. Delta +{delta}. Strong buyer aggression.",
        "Current price is {price}. VAH at {vah}. VAL at {val}. POC at {poc}. Delta is neutral. No clear setup. Orderflow: Aggression Score: 0.50.",
        "Market is inside the Value Area (Balance). Current price is {price}. VAH at {vah}. VAL at {val}. POC at {poc}. Delta is neutral. Price is at the Point of Control (POC). Orderflow: Aggression Score: {agg}.",
    ]
    scenarios = []
    for _ in range(n):
        t = random.choice(templates)
        val = _rp(14900, 15000)
        vah = _rp(15100, 15200)
        poc = _rp(15000, 15100)
        scenarios.append({
            "input": t.format(
                price=_rp(val - 50, vah + 50), vah=vah, val=val, poc=poc,
                delta=_rp(100, 2000), agg=f"{random.uniform(0.5, 5.0):.2f}",
                btc_price=_rp(60000, 70000), btc_vah=_rp(65000, 68000), btc_val=_rp(61000, 64000),
            ),
            "expected": "MIXED",
            "category": "Edge_Case",
        })
    return scenarios

# ---------------------------------------------------------------------------
# Inference
# ---------------------------------------------------------------------------

def load_model():
    print("Loading model...")
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL, trust_remote_code=True)
    base_model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL, torch_dtype=torch.float16, device_map=device, trust_remote_code=True,
    )
    model = PeftModel.from_pretrained(base_model, ADAPTER_PATH)
    model.eval()
    return model, tokenizer, device

def run_inference(model, tokenizer, device, input_text):
    prompt = f"""Below is an instruction that describes a task, paired with an input that provides further context. Write a response that appropriately completes the request.

### Instruction:
{INSTRUCTION}

### Input:
{input_text}

### Response:
"""
    inputs = tokenizer(prompt, return_tensors="pt").to(device)
    start = time.time()
    with torch.no_grad():
        out = model.generate(**inputs, max_new_tokens=256, use_cache=True, temperature=0.1)
    latency = time.time() - start
    response = tokenizer.decode(out[0], skip_special_tokens=True)
    return response.split("### Response:")[-1].strip(), latency

# ---------------------------------------------------------------------------
# Pattern extraction
# ---------------------------------------------------------------------------

def extract_patterns(text):
    lower = text.lower()
    trigger = ""
    logic = ""
    market_state = ""

    m = re.search(r'trigger:\s*(.+?)(?:\.|$)', lower)
    if m:
        trigger = m.group(1).strip()

    m = re.search(r'logic:\s*(.+?)(?:\.|trigger)', lower)
    if m:
        logic = m.group(1).strip()

    m = re.search(r'market state:\s*(.+?)(?:\.|logic)', lower)
    if m:
        market_state = m.group(1).strip()

    return {"trigger": trigger, "logic": logic, "market_state": market_state}

# ---------------------------------------------------------------------------
# Main
# ---------------------------------------------------------------------------

def main():
    random.seed(42)
    all_scenarios = (
        gen_aaa_long_scenarios(30) +
        gen_momentum_long_scenarios(15) +
        gen_failed_auction_short_scenarios(15) +
        gen_aaa_short_scenarios(15) +
        gen_risk_mgmt_scenarios(15) +
        gen_poc_scenarios(10) +
        gen_edge_case_scenarios(10)
    )
    # Shuffle to avoid ordering bias
    random.shuffle(all_scenarios)

    print(f"Total scenarios: {len(all_scenarios)}")
    model, tokenizer, device = load_model()

    results = []
    trigger_counter = Counter()
    logic_counter = Counter()
    market_state_counter = Counter()
    direction_by_category = {}

    for i, sc in enumerate(all_scenarios):
        output, latency = run_inference(model, tokenizer, device, sc["input"])
        patterns = extract_patterns(output)

        # Simple direction parse (current parser logic)
        lower = output.lower()
        if any(k in lower for k in ["enter long", "**long**", "trigger: **long", "add to longs", "trigger: long"]):
            parsed_dir = "LONG"
        elif any(k in lower for k in ["enter short", "**short**", "trigger: **short", "trigger: short"]):
            parsed_dir = "SHORT"
        else:
            parsed_dir = "FLAT"

        result = {
            "index": i,
            "category": sc["category"],
            "expected": sc["expected"],
            "parsed_direction": parsed_dir,
            "trigger_pattern": patterns["trigger"],
            "logic_pattern": patterns["logic"],
            "market_state_pattern": patterns["market_state"],
            "raw_output": output,
            "latency_s": round(latency, 2),
        }
        results.append(result)

        if patterns["trigger"]:
            trigger_counter[patterns["trigger"]] += 1
        if patterns["logic"]:
            logic_counter[patterns["logic"]] += 1
        if patterns["market_state"]:
            market_state_counter[patterns["market_state"]] += 1

        cat = sc["category"]
        if cat not in direction_by_category:
            direction_by_category[cat] = Counter()
        direction_by_category[cat][parsed_dir] += 1

        if (i + 1) % 20 == 0:
            print(f"  [{i+1}/{len(all_scenarios)}] latency={latency:.1f}s dir={parsed_dir} cat={cat}")

    # Build report
    report = {
        "total_scenarios": len(all_scenarios),
        "unique_triggers": dict(trigger_counter.most_common()),
        "unique_logic_patterns": dict(logic_counter.most_common()),
        "unique_market_states": dict(market_state_counter.most_common()),
        "direction_by_category": {k: dict(v) for k, v in direction_by_category.items()},
        "parse_accuracy": {},
        "all_results": results,
    }

    # Accuracy per category
    for cat in direction_by_category:
        cat_results = [r for r in results if r["category"] == cat]
        if cat_results[0]["expected"] in ("LONG", "SHORT", "FLAT"):
            correct = sum(1 for r in cat_results if r["parsed_direction"] == r["expected"])
            report["parse_accuracy"][cat] = f"{correct}/{len(cat_results)} ({100*correct/len(cat_results):.0f}%)"

    with open("model_vocabulary_report.json", "w") as f:
        json.dump(report, f, indent=2)

    # Print summary
    print("\n" + "=" * 60)
    print("MODEL VOCABULARY REPORT")
    print("=" * 60)
    print(f"\nUnique Trigger patterns ({len(trigger_counter)}):")
    for pat, cnt in trigger_counter.most_common():
        print(f"  [{cnt:3d}x] {pat}")
    print(f"\nUnique Logic patterns ({len(logic_counter)}):")
    for pat, cnt in logic_counter.most_common():
        print(f"  [{cnt:3d}x] {pat}")
    print(f"\nUnique Market State patterns ({len(market_state_counter)}):")
    for pat, cnt in market_state_counter.most_common():
        print(f"  [{cnt:3d}x] {pat}")
    print(f"\nDirection by Category (current parser):")
    for cat, counts in direction_by_category.items():
        print(f"  {cat}: {dict(counts)}")
    print(f"\nParse Accuracy:")
    for cat, acc in report["parse_accuracy"].items():
        print(f"  {cat}: {acc}")
    print(f"\nSaved full report to model_vocabulary_report.json")

if __name__ == "__main__":
    main()
