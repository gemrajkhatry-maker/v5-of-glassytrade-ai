#!/usr/bin/env python3
"""
Validate Gemma-4-26B 75-iteration adapter against fabio_amt_dataset/valid_json.jsonl
"""

import sys
sys.path.insert(0, '/Users/apple/Downloads/v5-of-glassytrade-ai/backend/venv/lib/python3.14/site-packages')

import json
import mlx.core as mx
from mlx_lm import load, generate
from mlx_lm.tuner.utils import load_adapters
from collections import Counter
import re

print("="*80)
print("Gemma-4-26B Adapter Validation (75 iterations)")
print("="*80)

# Load model and adapter
print("\n1. Loading base model...")
model, tokenizer = load("mlx-community/gemma-4-26b-a4b-it-4bit")
print("   ✓ Base model loaded")

print("\n2. Loading 75-iteration adapter...")
load_adapters(model, "gemma4_26b_amt_adapter_final")
print("   ✓ Adapter loaded")

# Load validation data
print("\n3. Loading validation dataset...")
with open("fabio_amt_dataset/valid_json.jsonl", "r") as f:
    lines = f.readlines()
print(f"   ✓ Loaded {len(lines)} validation examples")

# Test configuration
NUM_SAMPLES = 50  # Test first 50 examples (can increase)
print(f"\n4. Testing on {NUM_SAMPLES} samples...")
print("="*80)

results = {
    "correct": 0,
    "total": 0,
    "exact_match": 0,
    "direction_match": 0,
    "errors": []
}

for i in range(min(NUM_SAMPLES, len(lines))):
    try:
        # Parse example
        example = json.loads(lines[i])
        messages = example["messages"]

        user_msg = next(m for m in messages if m["role"] == "user")["content"]
        expected = next(m for m in messages if m["role"] == "assistant")["content"]

        # Extract expected direction
        expected_match = re.search(r'"direction":\s*"(\w+)"', expected, re.IGNORECASE)
        expected_direction = expected_match.group(1).upper() if expected_match else "UNKNOWN"

        # Build prompt
        prompt = f"{user_msg}\n\nRespond with only JSON: {{\"direction\": \"LONG|SHORT|FLAT\", \"confidence\": \"High|Medium|Low\", \"rationale\": \"brief\"}}\n\n{{\"direction\": \""

        # Generate
        output = generate(model, tokenizer, prompt=prompt, max_tokens=60, verbose=False)

        # Parse output
        output_lower = output.lower()

        # Try to extract direction
        if "long" in output_lower:
            predicted_direction = "LONG"
        elif "short" in output_lower:
            predicted_direction = "SHORT"
        elif "flat" in output_lower or "stay" in output_lower:
            predicted_direction = "FLAT"
        else:
            predicted_direction = "UNKNOWN"

        # Check match
        direction_match = (predicted_direction == expected_direction)

        results["total"] += 1
        results["correct"] += direction_match
        if direction_match:
            results["direction_match"] += 1

        status = "✓" if direction_match else "✗"
        print(f"[{i+1:2d}/{NUM_SAMPLES}] {status} Expected: {expected_direction:6s} | Predicted: {predicted_direction:6s}")

        # Show failures
        if not direction_match:
            print(f"      Prompt: {user_msg[:60]}...")
            print(f"      Output: {output[:100]}...")
            results["errors"].append({
                "idx": i,
                "expected": expected_direction,
                "predicted": predicted_direction,
                "output": output[:200]
            })

    except Exception as e:
        print(f"[{i+1:2d}/{NUM_SAMPLES}] ✗ Error: {e}")
        results["errors"].append({"idx": i, "error": str(e)})

# Print summary
print("\n" + "="*80)
print("VALIDATION SUMMARY")
print("="*80)

accuracy = (results["direction_match"] / results["total"] * 100) if results["total"] > 0 else 0
print(f"\nTotal tested: {results['total']}")
print(f"Direction correct: {results['direction_match']}")
print(f"Accuracy: {accuracy:.1f}%")

print(f"\n{'='*80}")
if accuracy >= 80:
    print("✅ HIGH ACCURACY - Adapter is production-ready")
elif accuracy >= 60:
    print("⚠️  MODERATE ACCURACY - May need more training")
else:
    print("❌ LOW ACCURACY - Needs retraining on better data")

print("="*80)
