import json
import os
import sys
import random
from mlx_lm import load, generate

# Configuration
MODEL_PATH = "mlx-community/gemma-4-26b-a4b-it-4bit"
ADAPTER_PATH = "./gemma4_26b_clean_adapter"

# Define all sources identified in the workspace
SOURCES = [
    {"name": "Fabio AMT (Primary - Test)", "path": "fabio_amt_dataset/test_json.jsonl", "format": "messages", "count": 15},
    {"name": "Fabio AMT (Primary - Valid)", "path": "fabio_amt_dataset/valid_json.jsonl", "format": "messages", "count": 10},
    {"name": "POC Breakout/FirstDrive", "path": "poc_gemma4_e4b/data/valid.jsonl", "format": "messages", "count": 10},
    {"name": "POC3 Options (BankNifty)", "path": "poc3/test_scenarios.jsonl", "format": "user_expected", "count": 10},
    {"name": "POC3 Real Trading", "path": "poc3/training_data_real.jsonl", "format": "user_expected", "count": 10},
    {"name": "POC LFM2 (NSE Equity)", "path": "poc_lfm2/data/test.jsonl", "format": "messages", "count": 5},
    {"name": "Legacy POC1 Training", "path": "poc/training_data.jsonl", "format": "messages", "count": 5},
]

SYSTEM_PROMPT = """You are an expert AMT scalping analyst using Fabio Valentini's Auction Market Theory. You READ the auction — you do NOT predict. MANDATORY REASONING STRUCTURE (Inside <think> tags): 1. SESSION CHECK: [Window] -> Bias [Bullish/Bearish/Neutral] 2. RISK CHECK: [P&L/Rule Status] -> Permit [Yes/No] 3. STRUCTURE CHECK: [State/Location] -> Signal [Confirmed/No] 4. AGGRESSION CHECK: [CVD/Delta/Bubbles] -> Trigger [Confirmed/No] 5. FINAL LOGIC: [Narrative summary] Then respond with a JSON object only. JSON format: {"direction": "LONG|SHORT|FLAT", "confidence": "High|Medium|Low", "rationale": "brief reason"}"""

def get_messages(item, fmt):
    if fmt == "messages":
        msgs = item["messages"]
        # Injects the "production" system prompt to check if the model can adapt old data to new reasoning
        if msgs[0]["role"] == "system":
            msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + msgs[1:]
        else:
            msgs = [{"role": "system", "content": SYSTEM_PROMPT}] + msgs
        return msgs
    elif fmt == "user_expected":
        user_content = item.get("user") or item.get("input") or ""
        return [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content}
        ]
    return []

def run_validation():
    print(f"Initializing Comprehensive Validation Model: {MODEL_PATH}", flush=True)
    model, tokenizer = load(MODEL_PATH, adapter_path=ADAPTER_PATH)
    print("Model and Adapter Loaded successfully.\n", flush=True)

    report = []

    for source in SOURCES:
        print(f"\nVALIDATING SOURCE: {source['name']}")
        print(f"Path: {source['path']}\n", flush=True)

        if not os.path.exists(source["path"]):
            print(f"WARNING: Source not found: {source['path']}", flush=True)
            continue

        with open(source["path"], "r") as f:
            all_lines = f.readlines()
            # Sample data
            batch = random.sample(all_lines, min(len(all_lines), source["count"]))
            
            source_results = {"source": source["name"], "total": 0, "reasoning_pass": 0, "json_pass": 0}

            for idx, line in enumerate(batch):
                try:
                    item = json.loads(line)
                    messages = get_messages(item, source["format"])
                    
                    # Only take the messages up to the user query for generation
                    # Usually messages is [sys, user, assist] or [sys, user]
                    # We want [sys, user]
                    gen_messages = [m for m in messages if m["role"] != "assistant"]
                    
                    prompt = tokenizer.apply_chat_template(gen_messages, tokenize=False, add_generation_prompt=True)
                    
                    print(f"[{source['name']}] Test Case {idx+1}...", end=" ", flush=True)
                    output = generate(model, tokenizer, prompt=prompt, max_tokens=600)
                    
                    has_reasoning = "<think>" in output and "</think>" in output
                    has_json = "{" in output and "}" in output and '"direction"' in output

                    if has_reasoning: source_results["reasoning_pass"] += 1
                    if has_json: source_results["json_pass"] += 1
                    source_results["total"] += 1
                    
                    print(f"Reasoning: {'PASS' if has_reasoning else 'FAIL'}, JSON: {'PASS' if has_json else 'FAIL'}", flush=True)
                    
                except Exception as e:
                    print(f"Error processing case {idx+1}: {e}", flush=True)

            report.append(source_results)

    # Output Final Report to a file
    with open("validation_master_report.json", "w") as rf:
        json.dump(report, rf, indent=2)
    
    print("\nVALIADTION COMPLETE. Master report saved to validation_master_report.json", flush=True)

if __name__ == "__main__":
    run_validation()
