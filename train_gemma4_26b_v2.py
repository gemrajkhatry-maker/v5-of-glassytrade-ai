#!/usr/bin/env python3
"""
V2 Training script for Gemma 4 26B using mlx_vlm.lora.
Optimized for 64GB RAM with Rank 64 for high accuracy.
"""

import argparse
import os
import sys
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Train Gemma 4 26B V2 with mlx_vlm")
    parser.add_argument("--iters", type=int, default=1500, help="Number of training iterations")
    parser.add_argument("--rank", type=int, default=64, help="LoRA rank (high for accuracy)")
    parser.add_argument("--batch-size", type=int, default=1, help="Batch size")
    parser.add_argument("--lr", type=float, default=1e-5, help="Learning rate")
    
    args = parser.parse_args()
    
    # Target directory for the new adapter
    adapter_path = "./gemma4_26b_v2_adapter"
    
    # Build command using mlx_vlm.lora
    # Parameters corrected for mlx_vlm 0.4.4+
    cmd = [
        sys.executable, "-m", "mlx_vlm.lora",
        "--model-path", "mlx-community/gemma-4-26b-a4b-it-4bit",
        "--dataset", "fabio_amt_dataset",
        "--iters", str(args.iters),
        "--batch-size", str(args.batch_size),
        "--learning-rate", str(args.lr),
        "--output-path", adapter_path,
        "--lora-rank", str(args.rank),
        "--lora-alpha", str(args.rank * 2),
        "--max-seq-length", "1024",
        "--steps-per-report", "10",
        "--steps-per-eval", "200",
        "--steps-per-save", "100",
        "--grad-checkpoint"
    ]
    
    print("="*80)
    print("Gemma 4 26B V2 (VLM-Native) LoRA Training")
    print("="*80)
    print(f"  Loader: mlx_vlm.lora (Native Architecture Support)")
    print(f"  Rank: {args.rank} | Alpha: {args.rank * 2}")
    print(f"  Iterations: {args.iters}")
    print(f"  Output: {adapter_path}")
    print("="*80)
    
    # Execute training
    os.execvp(cmd[0], cmd)

if __name__ == "__main__":
    main()
