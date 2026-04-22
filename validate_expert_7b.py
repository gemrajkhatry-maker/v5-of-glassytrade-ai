#!/usr/bin/env python3
"""
IN-DEPTH Validation for Qwen Coder 7B (V3 EXPERT - Iteration 800).
Tests if the merged dataset fixed the "too safe" bias.
"""

import json
import time
import re
import os
from pathlib import Path
from typing import Dict, List
from collections import defaultdict

def load_test_data(test_file: str = "expert_amt_dataset/valid.jsonl", max_samples: int = 100) -> List[Dict]:
    """Using the validation split of the NEW expert dataset."""
    samples = []
    with open(test_file, 'r') as f:
        for line in f:
            if len(samples) >= max_samples:
                break
            data = json.loads(line)
            messages = data['messages']
            user_content = messages[0]['content']
            assistant_content = messages[1]['content']
            
            expected_trade = "FLAT"
            try:
                json_data = json.loads(assistant_content)
                expected_trade = json_data.get("direction", "FLAT")
            except:
                pass
            
            samples.append({
                'input': user_content,
                'expected_trade': expected_trade
            })
    return samples

def extract_model_decision(output: str) -> Dict:
    res = {"direction": None, "valid_json": False}
    try:
        json_match = re.search(r'\{.*\}', output, re.DOTALL)
        if json_match:
            json_data = json.loads(json_match.group())
            res["direction"] = json_data.get("direction")
            res["valid_json"] = True
    except:
        pass
    
    if not res["direction"]:
        out_lower = output.lower()
        if 'long' in out_lower: res["direction"] = 'LONG'
        elif 'short' in out_lower: res["direction"] = 'SHORT'
        else: res["direction"] = 'FLAT'
        
    return res

def main():
    try:
        from mlx_lm import load, generate
    except ImportError:
        print("Please install mlx_lm")
        return

    model_path = "mlx-community/Qwen2.5-Coder-7B-Instruct-4bit"
    adapter_path = "qwen_coder_v3_expert"
    checkpoint_file = os.path.join(adapter_path, "0000800_adapters.safetensors")
    
    print(f"🔬 EXPERT VALIDATION: Qwen Coder 7B (Checkpoint 800)")
    print(f"Model: {model_path}")
    
    samples = load_test_data()
    print(f"Loaded {len(samples)} Expert test samples.")

    # Load model
    model, tokenizer = load(model_path, adapter_path=adapter_path)
    
    stats = {"correct": 0, "total": len(samples), "directions": defaultdict(int)}
    
    for i, sample in enumerate(samples):
        messages = [
            {"role": "system", "content": "You are an expert AMT analyst. Respond with JSON only."},
            {"role": "user", "content": sample['input']}
        ]
        prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        output = generate(model, tokenizer, prompt=prompt, max_tokens=150, verbose=False)
        parsed = extract_model_decision(output)
        
        is_correct = (parsed["direction"] == sample['expected_trade'])
        if is_correct: stats["correct"] += 1
        stats["directions"][parsed["direction"]] += 1
        
        if (i+1) % 10 == 0:
            print(f"  [{i+1}/{len(samples)}] Accuracy: {(stats['correct']/(i+1))*100:.1f}% | Dist: {dict(stats['directions'])}")

    accuracy = (stats["correct"] / stats["total"]) * 100
    print(f"\n{'='*50}")
    print(f"FINAL EXPERT REPORT (7B)")
    print(f"{'='*50}")
    print(f"Accuracy:    {accuracy:.1f}%")
    print(f"Distribution: {dict(stats['directions'])}")
    print(f"{'='*50}\n")

if __name__ == "__main__":
    main()
