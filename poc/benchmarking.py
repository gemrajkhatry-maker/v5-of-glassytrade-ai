import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer
import time
import json
import random
import statistics

# Re-use generation logic from generate_fabio_data.py for consistency but strictly for testing
from generate_fabio_data import (
    generate_aaa_long, generate_aaa_short, generate_momentum_long,
    generate_momentum_short, generate_failed_auction, generate_risk_management,
    generate_poc_scenario, generate_edge_case,
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
    if r < 0.15:
        data = generate_aaa_long()
        setup_type = "AAA Long"
        expected_action = "Long"
    elif r < 0.30:
        data = generate_aaa_short()
        setup_type = "AAA Short"
        expected_action = "Short"
    elif r < 0.45:
        data = generate_momentum_long()
        setup_type = "Momentum Long"
        expected_action = "Long"
    elif r < 0.55:
        data = generate_momentum_short()
        setup_type = "Momentum Short"
        expected_action = "Short"
    elif r < 0.70:
        data = generate_failed_auction()
        setup_type = "Failed Auction"
        expected_action = "Short"
    elif r < 0.85:
        data = generate_risk_management()
        setup_type = "Risk Mgmt"
        expected_action = "Flat"
    else:
        data = generate_edge_case()
        setup_type = "Edge Case"
        expected_action = "Flat"

    if expected_action == "Flat":
        pnl_if_correct = 0
    else:
        pnl_if_correct = RISK_PER_TRADE * REWARD_RATIO

    return {
        "input": data["input"],
        "type": setup_type,
        "expected_action": expected_action,
        "pnl_if_correct": pnl_if_correct
    }

def run_inference(model, tokenizer, device, input_text):
    instruction = "Analyze the trading scenario based on Fabio Valentini's methodology (Orderflow, Auction Market Theory)."
    alpaca_prompt = f"""Below is an instruction that describes a task, paired with an input that provides further context. Write a response that appropriately completes the request.

### Instruction:
{instruction}

### Input:
{input_text}

### Response:
"""
    inputs = tokenizer(alpaca_prompt, return_tensors="pt").to(device)
    
    start_time = time.time()
    with torch.no_grad():
        outputs = model.generate(
            **inputs, max_new_tokens=128, use_cache=True, temperature=0.1
        )
    end_time = time.time()
    
    latency = end_time - start_time
    response = tokenizer.decode(outputs[0], skip_special_tokens=True)
    clean_response = response.split("### Response:")[-1].strip()
    
    # Calculate tokens per second
    num_tokens = len(outputs[0])
    tps = num_tokens / latency
    
    return clean_response, latency, tps

def parse_decision(response_text):
    """Use same keywords as production parser."""
    lower = response_text.lower()
    # Check trigger line first
    import re
    trigger_match = re.search(r'trigger:\s*(.+?)(?:\.\s|$)', lower, re.IGNORECASE)
    if trigger_match:
        trigger = trigger_match.group(1).strip()
        long_kw = ["enter long", "long with size", "long on pullback", "long on any dip",
                    "long on re-entry", "long into", "add to longs", "re-enter long",
                    "long with target", "long with full"]
        short_kw = ["enter short", "short on confirmation", "short with target",
                     "short or", "short with"]
        for kw in short_kw:
            if kw in trigger: return "Short"
        for kw in long_kw:
            if kw in trigger: return "Long"
    # Flat keywords
    flat_kw = ["walk away", "stay flat", "bank profit", "stop trading",
               "reduce size", "take profit", "exit long", "risk management", "discipline"]
    for kw in flat_kw:
        if kw in lower: return "Flat"
    # Broad scan
    if "enter long" in lower or "**long**" in lower: return "Long"
    if "enter short" in lower or "**short**" in lower: return "Short"
    return "Unknown"

def main():
    model, tokenizer, device = load_model()
    
    results = {
        "total_pnl": 0,
        "wins": 0,
        "losses": 0,
        "trades": 0,
        "latencies": [],
        "failures": []
    }
    
    print(f"\nStarting Benchmarking Run ({NUM_TESTS} scenarios)...\n")
    
    for i in range(NUM_TESTS):
        test_case = generate_test_case()
        resp_text, latency, tps = run_inference(model, tokenizer, device, test_case["input"])
        
        results["latencies"].append(latency)
        decision = parse_decision(resp_text)
        
        # P&L Logic
        step_pnl = 0
        if decision == test_case["expected_action"]:
            if decision != "Flat":
                step_pnl = test_case["pnl_if_correct"]
                results["wins"] += 1
                results["trades"] += 1
            else:
                 # Correctly stayed flat
                 pass
        elif test_case["expected_action"] == "Flat" and decision != "Flat":
            # Traded when should have stayed flat
            step_pnl = -RISK_PER_TRADE
            results["losses"] += 1
            results["trades"] += 1
            results["failures"].append({"case": test_case, "decision": decision, "reason": "Overtrading"})
        elif decision != "Flat":
             # Wrong direction
            step_pnl = -RISK_PER_TRADE
            results["losses"] += 1
            results["trades"] += 1
            results["failures"].append({"case": test_case, "decision": decision, "reason": "Wrong Direction"})
            
        results["total_pnl"] += step_pnl
        
        if (i+1) % 10 == 0:
            print(f"Processed {i+1}/{NUM_TESTS} | Current P&L: ${results['total_pnl']} | Avg Speed: {tps:.1f} t/s")

    # Analysis
    avg_latency = statistics.mean(results["latencies"])
    win_rate = (results["wins"] / results["trades"] * 100) if results["trades"] > 0 else 0
    
    print("\n" + "="*40)
    print("      BENCHMARK REPORT      ")
    print("="*40)
    print(f"Scenarios: {NUM_TESTS}")
    print(f"Total P&L: ${results['total_pnl']}")
    print(f"Win Rate:  {win_rate:.1f}% ({results['wins']}/{results['trades']})")
    print(f"Avg Latency: {avg_latency:.2f}s per request")
    print("-" * 40)
    
    if results["failures"]:
        print(f"\nFailures ({len(results['failures'])}):")
        with open("benchmark_failures.json", "w") as f:
            json.dump(results["failures"], f, indent=2)
        print("Detailed failure log saved to 'benchmark_failures.json'")
        for f in results["failures"][:3]: # Show first 3
            print(f"- Expected {f['case']['expected_action']}, Got {f['decision']} ({f['reason']})")
            print(f"  Input: {f['case']['input'][:50]}...")

if __name__ == "__main__":
    main()
