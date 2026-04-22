#!/usr/bin/env python3
import json
import random
import re
from pathlib import Path

# Setup constants
SYSTEM_PROMPT = (
    "You are an expert AMT scalping analyst using Fabio Valentini's Auction Market Theory. "
    "You READ the auction — you do NOT predict. "
    "MANDATORY REASONING STRUCTURE (Inside <think> tags): "
    "1. SESSION CHECK: [Window] -> Bias [Bullish/Bearish/Neutral] "
    "2. RISK CHECK: [P&L/Rule Status] -> Permit [Yes/No] "
    "3. STRUCTURE CHECK: [State/Location] -> Signal [Confirmed/No] "
    "4. AGGRESSION CHECK: [CVD/Delta/Bubbles] -> Trigger [Confirmed/No] "
    "5. FINAL LOGIC: [Narrative summary] "
    "Then respond with a JSON object only. "
    "JSON format: {\"direction\": \"LONG|SHORT|FLAT\", \"confidence\": \"High|Medium|Low\", \"rationale\": \"brief reason\"}"
)

def extract_value(text, pattern, default="Unknown"):
    match = re.search(pattern, text, re.IGNORECASE)
    if match:
        return match.group(1).strip()
    return default

def generate_think_block(user_content, assistant_state, direction):
    # 1. SESSION CHECK
    session = extract_value(user_content, r"Session: ([^.]+)\.")
    bias = extract_value(user_content, r"([A-Za-z]+) bias\.", "Neutral")
    vwap_logic = "Price vs VWAP alignment confirmed." if bias != "Neutral" else "Price near VWAP, neutral bias."
    
    # 2. RISK CHECK
    pl_match = re.search(r"Session P&L: ([^.]+)\.", user_content, re.IGNORECASE)
    pl_info = pl_match.group(1) if pl_match else "No active risk constraints"
    permit = "No" if any(x in user_content.lower() for x in ["3 consecutive losses", "3 losses"]) else "Yes"
    
    # 3. STRUCTURE CHECK
    val = extract_value(user_content, r"VAL: ([0-9,]+)")
    vah = extract_value(user_content, r"VAH: ([0-9,]+)")
    poc = extract_value(user_content, r"POC: ([0-9,]+)")
    underlying = extract_value(user_content, r"underlying at ([0-9,]+)")
    profile = extract_value(user_content, r"([A-Za-z]-shaped profile|[A-Za-z]-Shape profile)")
    
    # 4. AGGRESSION CHECK
    delta = extract_value(user_content, r"delta ([-+]?[0-9,]+)")
    if delta == "Unknown":
        delta = extract_value(user_content, r"delta diverging (?:negative|positive) at ([-+]?[0-9,]+)")
        
    cvd_match = re.search(r"CVD (?:trending|divergence):?\s*([a-zA-Z]+)", user_content, re.IGNORECASE)
    cvd = cvd_match.group(1) if cvd_match else "Neutral"
    
    bubbles = "Bubbles detected" if "bubble" in user_content.lower() else "No significant bubbles"
    trigger = "Confirmed" if direction != "FLAT" else "No clear trigger"
    
    # Heuristic Logic
    think = f"""1. SESSION CHECK: {session}. Bias {bias}. {vwap_logic}
2. RISK CHECK: {pl_info} -> Permit {permit}.
3. STRUCTURE CHECK: {assistant_state}. Underlying {underlying} near key levels. Profile {profile} confirmed.
4. AGGRESSION CHECK: Delta {delta}, CVD status {cvd}. {bubbles} -> Trigger {trigger}.
5. FINAL LOGIC: Fabio principle applied: Reading state ({assistant_state}) and confirming location ({underlying}). Directional decision: {direction}."""
    
    return think.strip()

def reformat_sample(sample):
    user_msg = next((m for m in sample["messages"] if m["role"] == "user"), None)
    ast_msg = next((m for m in sample["messages"] if m["role"] == "assistant"), None)
    
    if not user_msg or not ast_msg:
        return None
    
    user_content = user_msg["content"]
    ast_content = ast_msg["content"]
    
    # Parse old assistant format
    state_match = re.search(r"STATE: ([^\n]+)", ast_content)
    trade_match = re.search(r"TRADE: ([^\n]+)", ast_content)
    
    state = state_match.group(1) if state_match else "Unknown"
    trade = trade_match.group(1) if trade_match else "FLAT"
    
    # Standardize trade direction
    direction = "FLAT"
    if "LONG" in trade.upper(): direction = "LONG"
    elif "SHORT" in trade.upper(): direction = "SHORT"
    
    # Heuristic confidence
    confidence = "High"
    if "neutral" in user_content.lower() or "first touch" in user_content.lower():
        confidence = "Medium"
    
    think_block = generate_think_block(user_content, state, direction)
    
    json_output = {
        "direction": direction,
        "confidence": confidence,
        "rationale": state
    }
    
    new_assistant_content = f"<think>\n{think_block}\n</think>\n{json.dumps(json_output)}"
    
    return {
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": user_content},
            {"role": "assistant", "content": new_assistant_content}
        ]
    }

def process_file(input_path, output_path):
    print(f"Processing {input_path} -> {output_path}...")
    samples = []
    with open(input_path, 'r') as f:
        for line in f:
            if not line.strip(): continue
            try:
                data = json.loads(line)
                new_data = reformat_sample(data)
                if new_data:
                    samples.append(new_data)
            except Exception as e:
                print(f"Error processing line: {e}")
                
    # Shuffle the data
    print(f"Shuffling {len(samples)} samples...")
    random.shuffle(samples)
    
    with open(output_path, 'w') as f:
        for sample in samples:
            f.write(json.dumps(sample) + "\n")
    print(f"Done. Saved to {output_path}")

if __name__ == "__main__":
    base_dir = Path("/Users/apple/Downloads/v5-of-glassytrade-ai/fabio_amt_dataset")
    process_file(base_dir / "train.jsonl", base_dir / "train_v2.jsonl")
    process_file(base_dir / "test.jsonl", base_dir / "test_v2.jsonl")
