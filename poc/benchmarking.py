import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer
import time
import json
import random
import statistics

from generate_fabio_data import (
    generate_aaa_long, generate_aaa_short, generate_momentum_long,
    generate_momentum_short, generate_failed_auction, generate_risk_management,
    generate_poc_scenario, generate_edge_case,
    generate_lvn_trend_long, generate_lvn_trend_short,
    generate_lvn_meanrev_long, generate_lvn_meanrev_short,
    SYSTEM_INSTRUCTION,
)

# Configuration
BASE_MODEL = "./models/Nanbeige4.1-3B"
ADAPTER_PATH = "./lora_adapter_mac"
NUM_TESTS = 30
RISK_PER_TRADE = 1000
REWARD_RATIO = 3

def load_model():
    print(f"Loading model from {BASE_MODEL}...")
    device = "mps" if torch.backends.mps.is_available() else "cpu"
    tokenizer = AutoTokenizer.from_pretrained(BASE_MODEL)
    base_model = AutoModelForCausalLM.from_pretrained(
        BASE_MODEL, torch_dtype=torch.float16, device_map=device, trust_remote_code=True
    )
    model = PeftModel.from_pretrained(base_model, ADAPTER_PATH)
    model.eval()
    return model, tokenizer, device

def generate_test_case():
    """Generates a single test case with ground truth."""
    r = random.random()
    if r < 0.12:
        data = generate_aaa_long()
        setup_type, expected = "AAA Long", "Long"
    elif r < 0.24:
        data = generate_aaa_short()
        setup_type, expected = "AAA Short", "Short"
    elif r < 0.32:
        data = generate_momentum_long()
        setup_type, expected = "Momentum Long", "Long"
    elif r < 0.38:
        data = generate_momentum_short()
        setup_type, expected = "Momentum Short", "Short"
    elif r < 0.48:
        data = generate_failed_auction()
        setup_type, expected = "Failed Auction", "Short"
    elif r < 0.56:
        data = generate_lvn_trend_long()
        setup_type, expected = "LVN Trend Long", "Long"
    elif r < 0.64:
        data = generate_lvn_trend_short()
        setup_type, expected = "LVN Trend Short", "Short"
    elif r < 0.70:
        data = generate_lvn_meanrev_long()
        setup_type, expected = "LVN MeanRev Long", "Long"
    elif r < 0.76:
        data = generate_lvn_meanrev_short()
        setup_type, expected = "LVN MeanRev Short", "Short"
    elif r < 0.88:
        data = generate_risk_management()
        setup_type, expected = "Risk Mgmt", "Flat"
    else:
        data = generate_edge_case()
        setup_type, expected = "Edge Case", "Flat"

    pnl_if_correct = RISK_PER_TRADE * REWARD_RATIO if expected != "Flat" else 0

    return {
        "input": data["messages"][1]["content"],
        "type": setup_type,
        "expected_action": expected,
        "pnl_if_correct": pnl_if_correct,
    }

def run_inference(model, tokenizer, device, input_text):
    # ChatML format matching MLX inference adapter
    prompt = (
        f"<|im_start|>system\n{SYSTEM_INSTRUCTION}<|im_end|>\n"
        f"<|im_start|>user\n{input_text}<|im_end|>\n"
        "<|im_start|>assistant\nMarket State:"
    )
    inputs = tokenizer(prompt, return_tensors="pt").to(device)

    start_time = time.time()
    with torch.no_grad():
        outputs = model.generate(
            **inputs, max_new_tokens=80, use_cache=True, temperature=0.3
        )
    latency = time.time() - start_time

    response = tokenizer.decode(outputs[0], skip_special_tokens=True)
    # Extract assistant response after the prefill
    clean = "Market State:" + response.split("Market State:")[-1].strip()

    tps = len(outputs[0]) / latency
    return clean, latency, tps

def parse_decision(response_text):
    lower = response_text.lower()
    import re
    trigger_match = re.search(r'trigger:\s*(.+?)(?:\.\s|\n|$)', lower)
    if trigger_match:
        trigger = trigger_match.group(1).strip()
        short_kw = ["enter short", "short on", "short with", "short at"]
        long_kw = ["enter long", "long with", "long on", "long at", "add to longs"]
        for kw in short_kw:
            if kw in trigger: return "Short"
        for kw in long_kw:
            if kw in trigger: return "Long"
        if "stay flat" in trigger or "flat" in trigger:
            return "Flat"
    flat_kw = ["walk away", "stay flat", "bank profit", "stop trading",
               "reduce size", "risk management", "discipline"]
    for kw in flat_kw:
        if kw in lower: return "Flat"
    if "enter long" in lower: return "Long"
    if "enter short" in lower: return "Short"
    return "Unknown"

def main():
    model, tokenizer, device = load_model()

    results = {
        "total_pnl": 0, "wins": 0, "losses": 0, "trades": 0,
        "latencies": [], "failures": [], "correct_flat": 0,
    }

    print(f"\nBenchmarking ({NUM_TESTS} scenarios, ChatML format)...\n")

    for i in range(NUM_TESTS):
        test_case = generate_test_case()
        resp_text, latency, tps = run_inference(model, tokenizer, device, test_case["input"])

        results["latencies"].append(latency)
        decision = parse_decision(resp_text)

        step_pnl = 0
        if decision == test_case["expected_action"]:
            if decision != "Flat":
                step_pnl = test_case["pnl_if_correct"]
                results["wins"] += 1
                results["trades"] += 1
            else:
                results["correct_flat"] += 1
        elif test_case["expected_action"] == "Flat" and decision != "Flat":
            step_pnl = -RISK_PER_TRADE
            results["losses"] += 1
            results["trades"] += 1
            results["failures"].append({"case": test_case, "decision": decision, "reason": "Overtrading"})
        elif decision != "Flat":
            step_pnl = -RISK_PER_TRADE
            results["losses"] += 1
            results["trades"] += 1
            results["failures"].append({"case": test_case, "decision": decision, "reason": "Wrong Direction"})

        results["total_pnl"] += step_pnl

        if (i+1) % 10 == 0:
            print(f"  {i+1}/{NUM_TESTS} | P&L: ${results['total_pnl']} | {tps:.1f} t/s")

    avg_latency = statistics.mean(results["latencies"])
    win_rate = (results["wins"] / results["trades"] * 100) if results["trades"] > 0 else 0

    print("\n" + "="*40)
    print("      BENCHMARK REPORT")
    print("="*40)
    print(f"Scenarios: {NUM_TESTS}")
    print(f"Total P&L: ${results['total_pnl']}")
    print(f"Win Rate:  {win_rate:.1f}% ({results['wins']}/{results['trades']} trades)")
    print(f"Correct Flat: {results['correct_flat']}")
    print(f"Avg Latency: {avg_latency:.2f}s")
    print("-" * 40)

    if results["failures"]:
        print(f"\nFailures ({len(results['failures'])}):")
        with open("benchmark_failures.json", "w") as f:
            json.dump(results["failures"], f, indent=2)
        for fail in results["failures"][:5]:
            print(f"  - Expected {fail['case']['expected_action']}, Got {fail['decision']} ({fail['reason']})")
            print(f"    Type: {fail['case']['type']}")

if __name__ == "__main__":
    main()
