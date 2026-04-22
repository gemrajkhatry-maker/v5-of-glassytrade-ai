#!/usr/bin/env python3
"""
Direct training script for Gemma-4-26B with MLX lora library.
Manually controls training to avoid Metal crashes.
"""

import sys
sys.path.insert(0, '/Users/apple/Downloads/v5-of-glassytrade-ai/backend/venv/lib/python3.14/site-packages')

import mlx.core as mx
from mlx_lm import load, generate
from mlx_lm.tuner import linear_to_lora_layers, train
from mlx_lm.tuner.datasets import load_dataset
import time
import os

def main():
    model_path = "mlx-community/gemma-4-26b-a4b-it-4bit"
    data_path = "fabio_amt_dataset"
    adapter_path = "./gemma4_26b_amt_adapter_final"

    print("=" * 80)
    print("Gemma-4-26B LoRA Training (Manual Control)")
    print("=" * 80)
    print(f"Model: {model_path}")
    print(f"Data: {data_path}")
    print(f"Adapter: {adapter_path}")
    print()

    # Load model
    print("Loading model...")
    start = time.time()
    model, tokenizer = load(model_path)
    print(f"Model loaded in {time.time()-start:.1f}s")
    print(f"Model size: {sum(p.size for p in tree_flatten(model.parameters())) / 1e9:.1f}B params")

    # Apply LoRA
    print("Applying LoRA...")
    linear_to_lora_layers(model, 16, {
        "rank": 32,
        "alpha": 64,
        "dropout": 0.05,
        "scale": 2.0
    })

    # Load dataset
    print("Loading dataset...")
    train_set, valid_set, test_set = load_dataset(data_path, tokenizer)
    print(f"Train set size: {len(train_set)}")
    print(f"Valid set size: {len(valid_set)}")

    # Train manually in batches
    print()
    print("Starting training...")
    print("=" * 80)

    optimizer = mx.optimizers.AdamW(learning_rate=1e-5)

    # Manual training loop
    for iteration in range(1, 1001):
        try:
            # Train step
            batch = next(iter(train_set))
            loss = train_step(model, batch, optimizer)

            if iteration % 10 == 0:
                print(f"Iter {iteration}: Loss = {loss:.4f}")

            # Save checkpoint every 100 iterations
            if iteration % 100 == 0:
                save_path = os.path.join(adapter_path, f"{iteration:06d}_adapters.safetensors")
                print(f"Saving checkpoint to {save_path}...")
                # saver logic here

        except Exception as e:
            print(f"Error at iteration {iteration}: {e}")
            break

def train_step(model, batch, optimizer):
    """Single training step."""
    def loss_fn(model, batch):
        # Compute loss
        logits, targets = model(batch["input_ids"], targets=batch["labels"])
        return nn.losses.cross_entropy(logits, targets)

    loss_and_grad = mx.value_and_grad(loss_fn)
    loss, grads = loss_and_grad(model, batch)
    optimizer.update(model.parameters(), grads)
    mx.eval(model.parameters(), optimizer.state)
    return loss

def tree_flatten(pytree):
    """Flatten nested structure."""
    from mlx.utils import tree_flatten as tf
    return tf(pytree)

if __name__ == "__main__":
    import mlx.nn as nn
    main()
