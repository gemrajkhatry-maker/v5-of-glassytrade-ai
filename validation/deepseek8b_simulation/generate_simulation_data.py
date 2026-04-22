#!/usr/bin/env python3
"""
Generate realistic AMT market simulation data for DeepSeek 8B validation
Creates market scenarios based on real NIFTY/BANKNIFTY trading conditions
"""

import json
import random
from datetime import datetime, timedelta

# System prompt for JSON output
SYSTEM_PROMPT = """You are an expert AMT scalping analyst using Fabio Valentini's Auction Market Theory. You READ the auction — you do NOT predict. MANDATORY REASONING STRUCTURE (Inside <think> tags): 1. SESSION CHECK: [Window] -> Bias [Bullish/Bearish/Neutral] 2. RISK CHECK: [P&L/Rule Status] -> Permit [Yes/No] 3. STRUCTURE CHECK: [State/Location] -> Signal [Confirmed/No] 4. AGGRESSION CHECK: [CVD/Delta/Bubbles] -> Trigger [Confirmed/No] 5. FINAL LOGIC: [Narrative summary] Then respond with a JSON object only. JSON format: {"direction": "LONG|SHORT|FLAT", "confidence": "High|Medium|Low", "rationale": "brief reason"}"""

# Realistic market scenarios
SCENARIOS = {
    "bullish_breakout": {
        "description": "Strong bullish breakout above VAH with volume",
        "market_states": ["INITIATIVE", "TRENDING_UP", "BREAKOUT"],
        "locations": ["above VAH", "at VAH"],
        "delta_range": (3000, 8000),
        "cvd_options": ["rising", "neutral"],
        "volume_spike": True,
        "orderbook_imbalance": "buyers",
        "absorption": False,
        "expected_direction": "LONG",
        "expected_confidence": "High"
    },
    "bearish_rejection": {
        "description": "Bearish rejection at VAH with negative delta",
        "market_states": ["REJECTION", "FAILED_BREAKOUT", "TEST"],
        "locations": ["VAH", "near VAH"],
        "delta_range": (-8000, -2000),
        "cvd_options": ["falling", "neutral"],
        "volume_spike": True,
        "orderbook_imbalance": "sellers",
        "absorption": True,
        "expected_direction": "SHORT",
        "expected_confidence": "High"
    },
    "balanced_rotation": {
        "description": "Balanced market rotating around POC",
        "market_states": ["BALANCED", "BALANCE", "ROTATION"],
        "locations": ["POC", "near POC"],
        "delta_range": (-1000, 1000),
        "cvd_options": ["neutral"],
        "volume_spike": False,
        "orderbook_imbalance": "balanced",
        "absorption": False,
        "expected_direction": "FLAT",
        "expected_confidence": "Medium"
    },
    "bullish_retest_val": {
        "description": "Bullish retest and bounce from VAL support",
        "market_states": ["TEST", "RETEST", "ACCEPTANCE"],
        "locations": ["VAL", "near VAL", "above VAL"],
        "delta_range": (1500, 5000),
        "cvd_options": ["rising", "neutral"],
        "volume_spike": False,
        "orderbook_imbalance": "buyers",
        "absorption": False,
        "expected_direction": "LONG",
        "expected_confidence": "Medium"
    },
    "bearish_breakdown_val": {
        "description": "Bearish breakdown below VAL with momentum",
        "market_states": ["INITIATIVE", "BREAKDOWN", "TRENDING_DOWN"],
        "locations": ["below VAL", "at VAL"],
        "delta_range": (-7000, -3000),
        "cvd_options": ["falling", "neutral"],
        "volume_spike": True,
        "orderbook_imbalance": "sellers",
        "absorption": False,
        "expected_direction": "SHORT",
        "expected_confidence": "High"
    },
    "false_breakout_trap": {
        "description": "False breakout above VAH, trap and reverse",
        "market_states": ["FAILED_BREAKOUT", "TRAP", "REVERSAL"],
        "locations": ["above VAH", "near VAH"],
        "delta_range": (-3000, -500),
        "cvd_options": ["falling", "neutral"],
        "volume_spike": True,
        "orderbook_imbalance": "sellers",
        "absorption": True,
        "expected_direction": "SHORT",
        "expected_confidence": "Medium"
    },
    "poc_battle": {
        "description": "Market fighting at POC, indecision",
        "market_states": ["BALANCED", "CONSOLIDATION", "NEUTRAL"],
        "locations": ["POC"],
        "delta_range": (-500, 500),
        "cvd_options": ["neutral"],
        "volume_spike": False,
        "orderbook_imbalance": "balanced",
        "absorption": False,
        "expected_direction": "FLAT",
        "expected_confidence": "Low"
    },
    "strong_trend_continuation": {
        "description": "Strong trending day, continuation signal",
        "market_states": ["TRENDING_UP", "TRENDING_DOWN", "INITIATIVE"],
        "locations": ["above VAH", "below VAL"],
        "delta_range": (5000, 10000),
        "cvd_options": ["rising", "falling"],
        "volume_spike": True,
        "orderbook_imbalance": "buyers",
        "absorption": False,
        "expected_direction": "LONG",  # Will be adjusted based on location
        "expected_confidence": "High"
    }
}

def generate_scenario(scenario_type, index):
    """Generate a single market scenario"""
    scenario = SCENARIOS[scenario_type]
    
    # Generate realistic values
    delta = random.randint(*scenario["delta_range"])
    distance_to_poc = random.randint(-15, 20)
    
    # Adjust expected direction based on location for trending
    expected_dir = scenario["expected_direction"]
    if scenario_type == "strong_trend_continuation":
        location = random.choice(scenario["locations"])
        if "below" in location:
            expected_dir = "SHORT"
            delta = abs(delta) * -1  # Make negative
        else:
            expected_dir = "LONG"
            delta = abs(delta)
    else:
        location = random.choice(scenario["locations"])
    
    # Build user prompt (matching training format)
    user_content = f"""Market state: {random.choice(scenario['market_states'])}
Location: {location}
Distance_to_POC: {abs(distance_to_poc)} ticks
Delta: {delta}
CVD: {random.choice(scenario['cvd_options'])}
Volume_spike: {'yes' if scenario['volume_spike'] else 'no'}
Orderbook_imbalance: {scenario['orderbook_imbalance']}
Absorption: {'detected' if scenario['absorption'] else 'no'}
Question: What is the trade decision?"""
    
    # Build expected output
    expected_output = {
        "direction": expected_dir,
        "confidence": scenario["expected_confidence"],
        "rationale": scenario["description"]
    }
    
    # Create training-format example
    example = {
        "messages": [
            {
                "role": "system",
                "content": SYSTEM_PROMPT
            },
            {
                "role": "user",
                "content": user_content
            },
            {
                "role": "assistant",
                "content": f"<think>\n1. SESSION CHECK: Simulated. Bias determined from market state.\n2. RISK CHECK: No active risk constraints -> Permit Yes.\n3. STRUCTURE CHECK: {scenario['market_states'][0]}. Market structure confirmed.\n4. AGGRESSION CHECK: Delta {delta}, CVD {scenario['cvd_options'][0]}. Volume spike {'detected' if scenario['volume_spike'] else 'none'}.\n5. FINAL LOGIC: Fabio principle applied: Reading auction behavior and confirming location. Directional decision: {expected_dir}.\n</think>\n{json.dumps(expected_output)}"
            }
        ],
        "metadata": {
            "scenario_type": scenario_type,
            "scenario_description": scenario["description"],
            "expected_direction": expected_dir,
            "expected_confidence": scenario["expected_confidence"],
            "generated_at": datetime.now().isoformat(),
            "example_index": index
        }
    }
    
    return example

def generate_simulation_dataset(num_samples=200):
    """Generate complete simulation dataset"""
    dataset = []
    
    # Distribute samples across scenarios
    scenario_types = list(SCENARIOS.keys())
    samples_per_scenario = num_samples // len(scenario_types)
    
    print(f"Generating {num_samples} simulation samples...")
    print(f"Scenarios: {len(scenario_types)}")
    print(f"Samples per scenario: {samples_per_scenario}")
    
    idx = 0
    for scenario_type in scenario_types:
        print(f"\n  Generating {scenario_type}...")
        for i in range(samples_per_scenario):
            example = generate_scenario(scenario_type, idx)
            dataset.append(example)
            idx += 1
    
    # Shuffle dataset
    random.shuffle(dataset)
    
    return dataset

if __name__ == "__main__":
    print("="*80)
    print("AMT Market Simulation Data Generator")
    print("="*80)
    
    # Generate dataset
    dataset = generate_simulation_dataset(num_samples=200)
    
    # Save to file
    output_file = "validation/deepseek8b_simulation/simulation_data.jsonl"
    with open(output_file, 'w') as f:
        for example in dataset:
            f.write(json.dumps(example) + '\n')
    
    print(f"\n{'='*80}")
    print(f"✅ Generated {len(dataset)} simulation scenarios")
    print(f"✅ Saved to: {output_file}")
    print(f"{'='*80}")
    
    # Print distribution
    from collections import Counter
    directions = []
    for ex in dataset:
        directions.append(ex['metadata']['expected_direction'])
    
    print(f"\nDirection Distribution:")
    for dir_type, count in sorted(Counter(directions).items()):
        print(f"  {dir_type}: {count} ({count/len(dataset)*100:.1f}%)")
