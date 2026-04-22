#!/usr/bin/env python3
"""
Training script for DeepSeek-R1 (Qwen Distill) 7B/8B using mlx_lm.lora.
Optimized for logical reasoning and <think> tag structure.
"""

import argparse
import os
import sys

def main():
    parser = argparse.ArgumentParser(description="Train DeepSeek-R1 Qwen Distill with mlx_lm")
    parser.add_argument("--iters", type=int, default=1500, help="Number of training iterations")
    parser.add_argument("--rank", type=int, default=64, help="LoRA rank")
    
    args = parser.parse_args()
    
    # Model ID from your link (DeepSeek-R1-Distill-Qwen-7B is standard, 
    # but we'll use the most stable distill version)
    model_id = "mlx-community/DeepSeek-R1-Distill-Qwen-7B-4bit"
    adapter_path = "./deepseek_r1_amt_adapter"
    
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
    print("DeepSeek-R1 AMT Reasoning Training")
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
