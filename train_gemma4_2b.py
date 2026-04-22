#!/usr/bin/env python3
"""
Fine-tune Gemma 4 2B model on AMT trading dataset.
Trains with JSON format output (direction, rationale, confidence).
"""

import json
import yaml
from pathlib import Path
from mlx_lm.tuner import train

# Configuration
MODEL_ID = "mlx-community/gemma-4-e2b-8bit"
ADAPTER_PATH = "gemma4_2b_amt_adapters"
DATA_PATH = "fabio_amt_dataset"

# Training hyperparameters
CONFIG = {
    "model": MODEL_ID,
    "data": DATA_PATH,
    "save_every": 100,
    "steps_per_eval": 100,
    "iters": 1000,  # Training iterations
    "val": True,
    "grad_checkpoint": False,
    "learning_rate": 1e-4,
    "lora_layers": 16,  # Number of layers to apply LoRA
    "lora_parameters": {
        "rank": 32,  # LoRA rank (higher = more capacity)
        "alpha": 64,  # LoRA alpha (2x rank is standard)
        "dropout": 0.1,
        "scale": 1.0
    },
    "batch_size": 2,
    "max_seq_length": 1024,
    "mask_prompt": True,  # Only train on assistant responses
    "adapter_path": ADAPTER_PATH
}

def create_training_data():
    """Convert fabio_amt_dataset to JSON training format."""
    print("Converting training data to JSON format...")
    
    train_data = []
    valid_data = []
    
    # Read train.jsonl
    with open(f"{DATA_PATH}/train_json.jsonl", 'r') as f:
        for line in f:
            data = json.loads(line)
            train_data.append(data)
    
    # Read valid.jsonl
    with open(f"{DATA_PATH}/valid_json.jsonl", 'r') as f:
        for line in f:
            data = json.loads(line)
            valid_data.append(data)
    
    print(f"✓ Training samples: {len(train_data)}")
    print(f"✓ Validation samples: {len(valid_data)}")
    
    return len(train_data), len(valid_data)

def main():
    print("="*80)
    print("Gemma 4 2B AMT Fine-tuning")
    print("="*80)
    print(f"Model: {MODEL_ID}")
    print(f"Adapter: {ADAPTER_PATH}")
    print(f"Data: {DATA_PATH}")
    print(f"Iterations: {CONFIG['iters']}")
    print(f"LoRA Rank: {CONFIG['lora_parameters']['rank']}")
    print(f"Learning Rate: {CONFIG['learning_rate']}")
    print("="*80)
    
    # Create training data
    train_count, valid_count = create_training_data()
    
    # Save config
    config_path = Path("gemma4_2b_training_config.yaml")
    with open(config_path, 'w') as f:
        yaml.dump(CONFIG, f, default_flow_style=False)
    print(f"\n✓ Config saved to {config_path}")
    
    # Start training
    print(f"\n{'='*80}")
    print("Starting training...")
    print(f"{'='*80}\n")
    
    try:
        # mlx_lm.tuner.train is a function, not a module
        train(**CONFIG)
        print(f"\n✓ Training complete!")
        print(f"✓ Adapters saved to: {ADAPTER_PATH}")
        
    except Exception as e:
        print(f"\n✗ Training failed: {e}")
        import traceback
        traceback.print_exc()

if __name__ == "__main__":
    main()
