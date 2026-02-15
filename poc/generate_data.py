import json
import random

# Number of examples to generate
NUM_EXAMPLES = 100

def generate_trend_scenario():
    direction = random.choice(["Long", "Short"])
    
    if direction == "Long":
        input_text = f"New York Open. Price broke previous session VAH at {random.randint(15000, 16000)}. Price is holding above. A Low Volume Node (LVN) exists at {random.randint(15000, 16000)}."
        output_text = f"Market State: **Imbalance** (Trend). Logic: Buyers are aggressive. Do not fade. Setup: Wait for pullback to **Location** (LVN). **Execution Trigger**: Enter Long only if big buy bubbles appear at support. Target: Extension or next volume node."
    else:
        input_text = f"London Session. Price broke previous session VAL at {random.randint(15000, 16000)}. Price is holding below. Testing a Low Volume Node (LVN) from below."
        output_text = f"Market State: **Imbalance** (Trend). Logic: Sellers are aggressive. Do not fade. Setup: Wait for pullback to **Location** (LVN). **Execution Trigger**: Enter Short only if big sell bubbles appear at resistance. Target: Extension or next volume node."

    return {
        "instruction": "Analyze the current market state based on Profile and Orderflow.",
        "input": input_text,
        "output": output_text
    }

def generate_mean_reversion_scenario():
    direction = random.choice(["Long", "Short"])
    
    if direction == "Short": # Fade the breakout
        input_text = f"Price broke VAH at {random.randint(15000, 16000)} but failed to hold. Price is now back inside the previous day's Value Area. Delta is negative divergent."
        output_text = f"Market State: **Balance** (Failed Auction). Logic: Breakout failed; price seeks fair value. **Location**: Value Area High. **Execution Trigger**: Short on re-entry with negative Delta. **Target**: Session Point of Control (POC)."
    else: # Fade the breakdown
        input_text = f"Price broke VAL at {random.randint(15000, 16000)} but rejected lower prices. Price is now back inside Value. CVD is trending up."
        output_text = f"Market State: **Balance** (Failed Auction). Logic: Breakdown failed; price seeks fair value. **Location**: Value Area Low. **Execution Trigger**: Long on re-entry with positive Delta. **Target**: Session Point of Control (POC)."

    return {
        "instruction": "Analyze the current market state based on Profile and Orderflow.",
        "input": input_text,
        "output": output_text
    }

def generate_chop_scenario():
    input_text = f"Mid-session. Price is strictly inside yesterday's Value Area between {random.randint(15000, 15500)} and {random.randint(15500, 16000)}. Volume is low. No clear CVD divergence."
    output_text = "Market State: **Balance** (Chop). Logic: Market is bracketing with no conviction. **Location**: Poor (Inside Value). **Execution Trigger**: None. **Target**: N/A. Action: Stay Flat."
    
    return {
        "instruction": "Analyze the current market state based on Profile and Orderflow.",
        "input": input_text,
        "output": output_text
    }

def main():
    data = []
    print(f"Generating {NUM_EXAMPLES} synthetic examples...")
    
    for _ in range(NUM_EXAMPLES):
        r = random.random()
        if r < 0.4:
            example = generate_trend_scenario()
        elif r < 0.8:
            example = generate_mean_reversion_scenario()
        else:
            example = generate_chop_scenario()
        data.append(example)

    output_file = "training_data.jsonl"
    with open(output_file, "w") as f:
        for entry in data:
            json.dump(entry, f)
            f.write("\n")
    
    print(f"Successfully generated {len(data)} examples to {output_file}")

if __name__ == "__main__":
    main()
