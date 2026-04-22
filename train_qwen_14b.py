#!/usr/bin/env python3
"""
Training script for Qwen 2.5 14B Instruct using mlx_lm.lora.
Pure text model - much more stable for trading thesis than VLM models.
Optimized for 64GB RAM with Rank 64.
"""

import argparse
import os
import sys

def main():
    parser = argparse.ArgumentParser(description="Train Qwen 2.5 14B with mlx_lm")
    parser.add_argument("--iters", type=int, default=1500, help="Number of training iterations")
    parser.add_argument("--rank", type=int, default=64, help="LoRA rank")
    
    args = parser.parse_args()
    
    # Model ID
    model_id = "mlx-community/Qwen2.5-14B-Instruct-4bit"
    adapter_path = "./qwen_14b_amt_adapter"
    
    # Build command
    cmd = [
        sys.executable, "-m", "mlx_lm.lora",
        "--model", model_id,
        "--data", "fabio_amt_dataset",
        "--train",
        "--iters", str(args.iters),
        "--batch-size", "1",
        "--learning-rate", "1e-5",
        "--adapter-path", adapter_path,
        "--lora-layers", "16",
        "--rank", str(args.rank),
        "--alpha", str(args.rank * 2),
        "--mask-prompt",
        "--max-seq-length", "1024",
        "--steps-per-report", "10",
        "--steps-per-eval", "200",
        "--save-every", "100",
        "--grad-checkpoint"
    ]
    
    print("="*80)
    print("Qwen 2.5 14B LoRA Training (Trading Thesis)")
    print("="*80)
    print(f"  Model: {model_id}")
    print(f"  Rank: {args.rank} | Alpha: {args.rank * 2}")
    print(f"  Iterations: {args.iters}")
    print(f"  Output: {adapter_path}")
    print("="*80)
    
    # Execute training
    os.execvp(cmd[0], cmd)

if __name__ == "__main__":
    main()
