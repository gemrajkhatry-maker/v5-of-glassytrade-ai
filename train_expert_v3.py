#!/usr/bin/env python3
"""
V3 Expert Training script for Qwen 2.5 Coder 14B.
Uses the Expert AMT Dataset (merged poc3 + poc_lfm2).
Optimized for 64GB RAM with Rank 64.
"""

import argparse
import os
import sys
from pathlib import Path

def main():
    parser = argparse.ArgumentParser(description="Train Qwen 2.5 Coder 14B V3 Expert")
    parser.add_argument("--iters", type=int, default=1500, help="Number of training iterations")
    
    args = parser.parse_args()
    
    # Model ID
    model_id = "mlx-community/Qwen2.5-Coder-14B-Instruct-4bit"
    adapter_path = "./qwen_coder_v3_expert"
    
    # Configuration
    config = {
        "model": model_id,
        "data": "expert_amt_dataset",
        "train": True,
        "iters": args.iters,
        "batch_size": 1,
        "learning_rate": 1e-5,
        "adapter_path": adapter_path,
        "num_layers": 16,
        "rank": 64,
        "alpha": 128,
        "max_seq_length": 1024,
        "grad_checkpoint": True,
        "mask_prompt": True,
        "save_every": 100,
        "steps_per_report": 10,
        "steps_per_eval": 200,
    }
    
    # Save config to YAML
    import yaml
    config_path = Path("qwen_coder_v3_config.yaml")
    with open(config_path, "w") as f:
        yaml.dump(config, f)
    
    print("="*80)
    print("Qwen 2.5 Coder 14B V3 EXPERT Training")
    print("="*80)
    print(f"  Dataset: expert_amt_dataset (29k High-Conviction Samples)")
    print(f"  Rank: 64 | Alpha: 128")
    print(f"  Output: {adapter_path}")
    print("="*80)
    
    # Execute training
    cmd = [sys.executable, "-m", "mlx_lm.lora", "--config", str(config_path)]
    os.execvp(cmd[0], cmd)

if __name__ == "__main__":
    main()
