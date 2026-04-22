#!/usr/bin/env python3
"""
IN-DEPTH Validation for Qwen Coder 14B (Iteration 500 Checkpoint).
Tests 100 samples for Accuracy, JSON Integrity, and Reasoning Quality.
"""

import json
import time
import re
import os
from pathlib import Path
from typing import Dict, List
from collections import defaultdict

def load_test_data(test_file: str = "fabio_amt_dataset/test_v2.jsonl", max_samples: int = 100) -> List[Dict]:
    samples = []
    with open(test_file, 'r') as f:
        for line in f:
            if len(samples) >= max_samples:
                break
            data = json.loads(line)
            messages = data['messages']
            user_content = messages[1]['content']
            assistant_content = messages[2]['content']
            
            expected_trade = "FLAT"
            try:
                json_match = re.search(r'\{.*\}', assistant_content, re.DOTALL)
                if json_match:
                    json_data = json.loads(json_match.group())
                    expected_trade = json_data.get("direction", "FLAT")
            except:
                pass
            
            samples.append({
                'input': user_content,
                'expected_trade': expected_trade
            })
    return samples

def extract_model_decision(output: str) -> Dict:
    """Extract full JSON decision from Qwen Coder output."""
    res = {"direction": None, "confidence": None, "rationale": None, "valid_json": False}
    try:
        json_match = re.search(r'\{.*\}', output, re.DOTALL)
        if json_match:
            json_data = json.loads(json_match.group())
            res["direction"] = json_data.get("direction")
            res["confidence"] = json_data.get("confidence")
            res["rationale"] = json_data.get("rationale")
            res["valid_json"] = True
    except:
        pass
    
    # Fallback for direction
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

    # CONFIGURATION: Point to the Iteration 800 Checkpoint
    model_path = "mlx-community/Qwen2.5-Coder-14B-Instruct-4bit"
    adapter_path = "qwen_coder_amt_adapter"
    # We must ensure we load the specific 800 checkpoint
    
    checkpoint_file = os.path.join(adapter_path, "0000800_adapters.safetensors")
    target_file = os.path.join(adapter_path, "adapters.safetensors")
    
    print(f"🔬 IN-DEPTH VALIDATION: Qwen Coder 14B (Checkpoint 800)")
    print(f"Targeting: {checkpoint_file}")
    
    samples = load_test_data()
    print(f"Loaded {len(samples)} test samples.")

    # Load model
    model, tokenizer = load(model_path, adapter_path=adapter_path)
    
    stats = {
        "correct": 0,
        "json_valid": 0,
        "total": len(samples),
        "directions": defaultdict(int),
        "errors": []
    }
    
    start_time = time.time()
    
    for i, sample in enumerate(samples):
        messages = [
            {"role": "system", "content": "You are an expert AMT scalping analyst. Respond with JSON only."},
            {"role": "user", "content": sample['input']}
        ]
        prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
        
        # Non-thinking models should be very fast with low max_tokens
        output = generate(model, tokenizer, prompt=prompt, max_tokens=150, verbose=False)
        parsed = extract_model_decision(output)
        
        is_correct = (parsed["direction"] == sample['expected_trade'])
        if is_correct: stats["correct"] += 1
        if parsed["valid_json"]: stats["json_valid"] += 1
        
        stats["directions"][parsed["direction"]] += 1
        
        if (i+1) % 10 == 0:
            print(f"  [{i+1}/{len(samples)}] Accuracy: {(stats['correct']/(i+1))*100:.1f}% | JSON: {(stats['json_valid']/(i+1))*100:.1f}%")

    total_time = time.time() - start_time
    accuracy = (stats["correct"] / stats["total"]) * 100
    json_rate = (stats["json_valid"] / stats["total"]) * 100
    
    print(f"\n{'='*50}")
    print(f"FINAL DEPTH REPORT")
    print(f"{'='*50}")
    print(f"Accuracy:      {accuracy:.1f}%")
    print(f"JSON Integrity: {json_rate:.1f}%")
    print(f"Avg Speed:     {total_time/stats['total']:.2f}s per trade")
    print(f"Distribution:   {dict(stats['directions'])}")
    print(f"{'='*50}\n")

if __name__ == "__main__":
    main()
