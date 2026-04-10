#!/usr/bin/env python3
"""Convert fabio_amt_dataset from STATE/TRADE format to JSON format for Gemma 4 training."""

import json
from pathlib import Path

def convert_dataset(input_file: str, output_file: str):
    """Convert STATE/TRADE format to JSON format."""
    
    # Mapping from STATE to confidence
    state_to_confidence = {
        "BREAKOUT": "High",
        "TREND": "High",
        "IMBALANCE": "High",
        "REJECTION": "Medium",
        "FAILED BREAKOUT": "Medium",
        "EXHAUSTION": "Medium",
        "ROTATION": "Low",
        "BALANCE": "Low",
        "RANGING": "Low",
    }
    
    converted = 0
    with open(input_file, 'r') as fin, open(output_file, 'w') as fout:
        for line in fin:
            data = json.loads(line)
            messages = data['messages']
            
            # Extract user input
            user_content = messages[0]['content']
            
            # Parse STATE and TRADE from assistant response
            assistant_content = messages[1]['content']
            state = None
            trade = None
            
            for line_text in assistant_content.split('\n'):
                if line_text.startswith('STATE:'):
                    state = line_text.replace('STATE:', '').strip()
                elif line_text.startswith('TRADE:'):
                    trade = line_text.replace('TRADE:', '').strip()
            
            if not state or not trade:
                continue
            
            # Create rationale based on state and trade
            rationale_map = {
                ("BREAKOUT", "LONG"): "Price breaking above resistance with momentum - initiating LONG position",
                ("BREAKOUT", "SHORT"): "Price breaking below support with momentum - initiating SHORT position",
                ("TREND", "LONG"): "Strong uptrend continuation signal - entering LONG",
                ("TREND", "SHORT"): "Strong downtrend continuation signal - entering SHORT",
                ("REJECTION", "LONG"): "Price rejected at support level - entering LONG for reversal",
                ("REJECTION", "SHORT"): "Price rejected at resistance level - entering SHORT for reversal",
                ("FAILED BREAKOUT", "LONG"): "Failed breakdown - buyers stepping in, entering LONG",
                ("FAILED BREAKOUT", "SHORT"): "Failed breakout - sellers stepping in, entering SHORT",
                ("EXHAUSTION", "LONG"): "Selling exhaustion detected - entering LONG for reversal",
                ("EXHAUSTION", "SHORT"): "Buying exhaustion detected - entering SHORT for reversal",
                ("ROTATION", "FLAT"): "Market in rotation/ranging - staying FLAT, no clear edge",
                ("BALANCE", "FLAT"): "Market in balance - staying FLAT, awaiting breakout",
                ("RANGING", "FLAT"): "Market ranging without direction - staying FLAT",
            }
            
            rationale = rationale_map.get((state, trade), f"Market state: {state}, Trade decision: {trade}")
            confidence = state_to_confidence.get(state, "Medium")
            
            # Create JSON response
            json_response = json.dumps({
                "direction": trade,
                "confidence": confidence,
                "rationale": rationale
            }, indent=2)
            
            # Create new training sample
            new_sample = {
                "messages": [
                    {"role": "user", "content": user_content},
                    {"role": "assistant", "content": json_response}
                ]
            }
            
            fout.write(json.dumps(new_sample) + '\n')
            converted += 1
    
    print(f"✓ Converted {converted} samples to JSON format")
    print(f"  Output: {output_file}")

if __name__ == "__main__":
    base_path = Path("/Users/apple/Downloads/v5-of-glassytrade-ai/fabio_amt_dataset")
    
    # Convert all splits
    for split in ["train", "valid", "test"]:
        input_file = base_path / f"{split}.jsonl"
        output_file = base_path / f"{split}_json.jsonl"
        
        if input_file.exists():
            print(f"\nConverting {split}.jsonl...")
            convert_dataset(str(input_file), str(output_file))
        else:
            print(f"\n⚠️  {input_file} not found")
