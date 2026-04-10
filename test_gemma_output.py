#!/usr/bin/env python3
"""Quick test to see what the trained model actually outputs."""

from mlx_lm import load, generate
import os

# Load model with adapter
model_path = "mlx-community/gemma-4-26b-a4b-it-4bit"
adapter_path = "./gemma4_26b_amt_adapter"

print("Loading model...")
# For HuggingFace models, don't use absolute path
model, tokenizer = load(model_path, adapter_path=adapter_path)
print("Model loaded!\n")

# Test prompts - need to use chat format for Gemma 4 IT
test_conversations = [
    [
        {"role": "user", "content": "Market state: INITIATIVE\nLocation: above VAH\nCVD: rising\nPrice action: strong bullish candles\nPOC: shifting up\nQuestion: What is the trade decision?"}
    ],
    [
        {"role": "user", "content": "Market state: RESPONSIVE\nLocation: below VAL\nCVD: falling\nPrice action: strong bearish candles\nPOC: shifting down\nQuestion: What is the trade decision?"}
    ],
]

for i, messages in enumerate(test_conversations):
    print(f"\n{'='*80}")
    print(f"Test {i+1}:")
    print(f"{'='*80}")
    print(f"Input: {messages[0]['content']}\n")
    print(f"Output:")
    print("-" * 80)
    
    # Apply chat template
    prompt = tokenizer.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    
    output = generate(
        model,
        tokenizer,
        prompt=prompt,
        max_tokens=50,
        verbose=False
    )
    
    print(output)
    print("-" * 80)
