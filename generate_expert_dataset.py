#!/usr/bin/env python3
"""
Expert Dataset Converter for GlassyTrade V3.
Merges high-quality data from poc3 and poc_lfm2 into a unified JSON training set.
"""

import json
import re
import os
from pathlib import Path

def parse_3_line_output(content: str):
    """Parses 'Market State: ... Logic: ... Trigger: ...' into JSON components."""
    lines = content.strip().split('\n')
    state = "Unknown"
    logic = ""
    trigger = "FLAT"
    
    for line in lines:
        if "Market State:" in line:
            state = line.split("Market State:")[1].strip()
        elif "Logic:" in line:
            logic = line.split("Logic:")[1].strip()
        elif "Trigger:" in line:
            raw_trigger = line.split("Trigger:")[1].strip().upper()
            if "LONG" in raw_trigger: trigger = "LONG"
            elif "SHORT" in raw_trigger: trigger = "SHORT"
            else: trigger = "FLAT"
            
    # Map to JSON schema
    # Logic + State = Rationale
    rationale = f"{state}: {logic}"
    # Simple confidence mapping
    confidence = "High" if trigger != "FLAT" else "Low"
    
    return {
        "direction": trigger,
        "confidence": confidence,
        "rationale": rationale
    }

def process_file(input_path: str, output_list: list):
    count = 0
    if not os.path.exists(input_path):
        print(f"Warning: {input_path} not found.")
        return
        
    with open(input_path, 'r') as f:
        for line in f:
            try:
                data = json.loads(line)
                messages = data['messages']
                
                # System prompt is usually index 0
                # User prompt is index 1
                # Assistant response is index 2
                user_msg = messages[1]['content']
                assistant_raw = messages[2]['content']
                
                parsed_json = parse_3_line_output(assistant_raw)
                
                # Create the training pair
                new_example = {
                    "messages": [
                        {
                            "role": "user", 
                            "content": user_msg
                        },
                        {
                            "role": "assistant", 
                            "content": json.dumps(parsed_json, indent=2)
                        }
                    ]
                }
                output_list.append(new_example)
                count += 1
            except Exception as e:
                continue
    print(f"Processed {count} samples from {input_path}")

def main():
    expert_data = []
    
    # 1. Load LFM2 (Enhanced Scenarios)
    process_file("poc_lfm2/training_data_lfm2.jsonl", expert_data)
    
    # 2. Load POC3 (NSE Options Scenarios)
    process_file("poc3/training_data_options.jsonl", expert_data)
    
    # 3. Create expert directory
    output_dir = Path("expert_amt_dataset")
    output_dir.mkdir(exist_ok=True)
    
    # 4. Save merged dataset
    output_file = output_dir / "train.jsonl"
    with open(output_file, 'w') as f:
        for item in expert_data:
            f.write(json.dumps(item) + '\n')
            
    # 5. Create validation set (5% of data)
    import random
    random.shuffle(expert_data)
    split = int(len(expert_data) * 0.95)
    
    with open(output_dir / "train.jsonl", 'w') as f:
        for item in expert_data[:split]:
            f.write(json.dumps(item) + '\n')
            
    with open(output_dir / "valid.jsonl", 'w') as f:
        for item in expert_data[split:]:
            f.write(json.dumps(item) + '\n')
            
    print(f"\n✅ EXPERT DATASET CREATED: {len(expert_data)} total samples.")
    print(f"   Train: {split} | Valid: {len(expert_data) - split}")

if __name__ == "__main__":
    main()
