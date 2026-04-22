#!/usr/bin/env python3
"""Test Gemma 4 26B + adapter loading without backend"""

import sys
import os
from pathlib import Path

print("=" * 60)
print("TESTING: Gemma 4 26B + LoRA Adapter (Iteration 1950)")
print("=" * 60)

base_model = "mlx-community/gemma-4-26b-a4b-it-4bit"
adapter_path = "/Users/apple/Downloads/v5-of-glassytrade-ai/gemma4_26b_clean_adapter"

print(f"\nBase model: {base_model}")
print(f"Adapter path: {adapter_path}")
print(f"Adapter file: {adapter_path}/adapters.safetensors")
print(f"Adapter config: {adapter_path}/adapter_config.json")

# Check cache
cache_dir = Path.home() / ".cache" / "huggingface" / "hub"
model_cache = cache_dir / "models--mlx-community--gemma-4-26b-a4b-it-4bit"
print(f"\nBase model cached: {model_cache.exists()}")
if model_cache.exists():
    total_size = sum(f.stat().st_size for f in model_cache.rglob("*") if f.is_file())
    print(f"  Size: {total_size / 1e9:.1f} GB")

# Check memory
import psutil

ram = psutil.virtual_memory()
print(
    f"\nSystem RAM: {ram.total / 1e9:.1f} GB total, {ram.available / 1e9:.1f} GB available"
)

print("\nAttempting to load model...")
print("-" * 60)

try:
    from mlx_lm import load
    import time

    start = time.time()
    model, tokenizer = load(base_model, adapter_path=adapter_path)
    elapsed = time.time() - start

    print(f"✓ Model loaded successfully in {elapsed:.2f}s")
    print(f"  Model type: {type(model).__name__}")
    print(f"  Tokenizer: {tokenizer.__class__.__name__}")

    # Quick test generation
    print("\nTesting quick inference...")
    test_prompt = "You are READING the auction using Fabio Valentini's AMT methodology. Market is BALANCED. Price at VAL. What is your direction?"

    # Use mlx_lm.generate
    from mlx_lm import generate

    response = generate(
        model,
        tokenizer,
        test_prompt,
        max_tokens=20,
        temperature=0.3,
    )
    output = response
    print(f"  Output: {output[:100]}...")
    print("\n✓ SUCCESS: Gemma 4 26B with adapter is working!")

except Exception as e:
    print(f"\n✗ FAILED: {type(e).__name__}: {e}")
    import traceback

    traceback.print_exc()
    print("\nThis indicates the model cannot be loaded on this system.")
    print("Recommendation: Use cloud Gemma or switch to Qwen 2B model.")
