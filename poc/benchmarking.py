import torch
from peft import PeftModel
from transformers import AutoModelForCausalLM, AutoTokenizer
import time
import json
import random
import statistics

# Re-use generation logic from generate_fabio_data.py for consistency but strictly for testing
from generate_fabio_data import generate_aaa_setup, generate_momentum_setup, generate_failed_auction_setup, generate_risk_management_scenario

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
    if r < 0.3:
        data = generate_aaa_setup()
        setup_type = "AAA Setup"
        expected_action = "Long" # Simplified for this specific logic
    elif r < 0.6:
        data = generate_momentum_setup()
        setup_type = "Momentum"
        expected_action = "Long"
    elif r < 0.8:
        data = generate_failed_auction_setup()
        setup_type = "Failed Auction"
        expected_action = "Short"
    else:
        data = generate_risk_management_scenario()
        setup_type = "Risk Mgmt"
        expected_action = "Flat" # Or Close

    # Assign Outcome based on "Ground Truth" logic assumption
    # In a real backtest, this would be the actual market move. 
    # Here, we assume the specific setups defined *should* work if identified correctly.
    if setup_type == "Risk Mgmt":
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
    instruction = "Analyze the trading scenario based on Fabio Valentini's methodology. Provide a Trigger: Enter Long, Enter Short, or Stay Flat."
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
    if "Enter Long" in response_text or "**Long**" in response_text:
        return "Long"
    elif "Enter Short" in response_text or "**Short**" in response_text:
        return "Short"
    elif "Stay Flat" in response_text or "Walk away" in response_text or "Close" in response_text:
        return "Flat"
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
