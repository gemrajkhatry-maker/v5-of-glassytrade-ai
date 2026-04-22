#!/usr/bin/env python3
"""
Direct mlx_lm test without backend wrapper
"""

from mlx_lm import load, generate

print("Loading model...")
model_path = "lmstudio-community/DeepSeek-R1-0528-Qwen3-8B-MLX-8bit"
adapter_path = "/Users/apple/Downloads/v5-of-glassytrade-ai/poc_deepseek8b/deepseek8b_amt_adapter"

model, tokenizer = load(model_path, adapter_path=adapter_path)
print("✅ Model loaded\n")

# Test simple prompt
messages = [
    {"role": "system", "content": "You are a helpful assistant. Respond with JSON: {\"status\": \"ok\"}"},
    {"role": "user", "content": "Test message"}
]

prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
prompt += "{"  # Prefill

print("Generating...")
output = generate(model, tokenizer, prompt=prompt, max_tokens=100, verbose=True)

print(f"\nOutput (with prefill):")
print("="*80)
print("{" + output)
print("="*80)
