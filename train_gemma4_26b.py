#!/usr/bin/env python3
"""
Training script for Gemma 4 26B with LoRA on AMT trading data.
Optimized for Apple M1 Max 64GB RAM.

Usage:
    python train_gemma4_26b.py
    python train_gemma4_26b.py --iters 3000 --rank 64
"""

import argparse
import os
import sys
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Train Gemma 4 26B with LoRA")
    parser.add_argument("--iters", type=int, default=2000, help="Number of training iterations")
    parser.add_argument("--rank", type=int, default=32, help="LoRA rank")
    parser.add_argument("--batch-size", type=int, default=1, help="Batch size")
    parser.add_argument("--lr", type=float, default=1e-5, help="Learning rate")
    parser.add_argument("--layers", type=int, default=16, help="Number of LoRA layers")
    parser.add_argument("--config", action="store_true", help="Use YAML config instead")
    
    args = parser.parse_args()
    
    # Build command
    cmd = [
        sys.executable, "-m", "mlx_lm.lora",
        "--model", "mlx-community/gemma-4-26b-a4b-it-4bit",
        "--data", "fabio_amt_dataset",
        "--train",
        "--iters", str(args.iters),
        "--batch-size", str(args.batch_size),
        "--num-layers", str(args.layers),
        "--learning-rate", str(args.lr),
        "--adapter-path", "./gemma4_26b_amt_adapter",
        "--mask-prompt",
        "--max-seq-length", "1024",
        "--steps-per-report", "10",
        "--steps-per-eval", "200",
        "--save-every", "200",
        "--grad-checkpoint",
        "--seed", "42"
    ]
    
    print("="*80)
    print("Gemma 4 26B LoRA Training")
    print("="*80)
    print(f"\nConfiguration:")
    print(f"  Model: mlx-community/gemma-4-26b-a4b-it-4bit")
    print(f"  Dataset: fabio_amt_dataset")
    print(f"  Iterations: {args.iters}")
    print(f"  Batch Size: {args.batch_size}")
    print(f"  LoRA Layers: {args.layers}")
    print(f"  LoRA Rank: {args.rank}")
    print(f"  Learning Rate: {args.lr}")
    print(f"  Max Sequence Length: 1024")
    print(f"  Adapter Output: ./gemma4_26b_amt_adapter")
    print(f"\nEstimated Training Time: {args.iters // 120:.0f}-{args.iters // 60:.0f} minutes")
    print(f"Estimated Memory Usage: ~38-45 GB")
    print("\n" + "="*80)
    print("\nStarting training...\n")
    
    # Execute training
    os.execvp(cmd[0], cmd)

if __name__ == "__main__":
    main()
