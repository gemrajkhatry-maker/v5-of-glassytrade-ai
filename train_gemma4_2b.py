#!/usr/bin/env python3
"""
Fine-tune Gemma 4 2B model on consolidated AMT trading dataset.

Dataset: amt_dataset/mlx_format/ (from consolidate_amt_dataset.py)
  - 78,681 unique scenarios (deduped from expert + fabio sources)
  - 66,879 train / 5,901 valid / 5,901 test
  - Tier 1 (43,943): Compact JSON-only system prompt
  - Tier 2 (34,738): CoT with <think> for brief rationales
  - Direction balance: ~25k LONG / ~26k SHORT / ~27k FLAT
  - 13 scenario types: rejection, absorption, divergence, squeeze, aaa_setup,
    exhaustion, breakout, trend, risk_mgmt, mean_reversion, no_trade, etc.

Trains with JSON format output (direction, rationale, confidence).
max_seq_length=1024 fits the CoT + JSON output comfortably.
mask_prompt=True ensures we only train on assistant responses.
"""

import json
import yaml
from pathlib import Path
from collections import Counter
from mlx_lm.tuner import train

# Configuration
MODEL_ID = "mlx-community/gemma-4-e2b-8bit"
ADAPTER_PATH = "gemma4_2b_amt_adapters"
DATA_PATH = "amt_dataset/mlx_format"

CONFIG = {
    "model": MODEL_ID,
    "data": DATA_PATH,
    "save_every": 100,
    "steps_per_eval": 100,
    "iters": 1000,
    "val": True,
    "grad_checkpoint": False,
    "learning_rate": 1e-4,
    "lora_layers": 16,
    "lora_parameters": {
        "rank": 32,
        "alpha": 64,
        "dropout": 0.1,
        "scale": 1.0,
    },
    "batch_size": 2,
    "max_seq_length": 1024,
    "mask_prompt": True,
    "adapter_path": ADAPTER_PATH,
}


def verify_dataset():
    """Verify the MLX-format dataset is well-formed."""
    stats = {"train": 0, "valid": 0, "test": 0}
    dir_dist = Counter()
    tier_dist = Counter()

    for split in ["train", "valid", "test"]:
        path = Path(DATA_PATH) / f"{split}.jsonl"
        if not path.exists():
            print(f"ERROR: {path} not found. Run consolidate_amt_dataset.py first.")
            return False

        with open(path) as f:
            for i, line in enumerate(f):
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    print(f"WARN: malformed line {i} in {split}.jsonl")
                    continue

                msgs = entry.get("messages", [])
                if len(msgs) != 3:
                    print(f"WARN: entry {i} in {split} has {len(msgs)} messages, expected 3")
                    continue

                roles = [m.get("role") for m in msgs]
                if roles != ["system", "user", "assistant"]:
                    print(f"WARN: entry {i} in {split} has roles {roles}")
                    continue

                # Parse direction from assistant output for stats
                asst = msgs[2].get("content", "")
                # Find JSON
                import re
                m = re.search(r'"direction"\s*:\s*"(\w+)"', asst)
                if m:
                    dir_dist[m.group(1)] += 1

                # Check tier from system prompt
                sys_msg = msgs[0].get("content", "")
                if "Think step by step" in sys_msg or "<think>" in sys_msg:
                    tier_dist["cot"] += 1
                else:
                    tier_dist["compact"] += 1

                stats[split] += 1

    print(f"Dataset verified:")
    print(f"  Train: {stats['train']}, Valid: {stats['valid']}, Test: {stats['test']}")
    print(f"  Total: {sum(stats.values())}")
    print(f"  Direction dist: {dict(dir_dist)}")
    print(f"  Tier dist: {dict(tier_dist)}")

    # Sanity checks
    if stats["train"] < 1000:
        print("ERROR: training set too small")
        return False

    return True


def main():
    print("=" * 80)
    print("Gemma 4 2B AMT Fine-tuning — Consolidated Dataset")
    print("=" * 80)
    print(f"Model:     {MODEL_ID}")
    print(f"Adapter:   {ADAPTER_PATH}")
    print(f"Data:      {DATA_PATH}")
    print(f"Iters:     {CONFIG['iters']}")
    print(f"LoRA:      rank={CONFIG['lora_parameters']['rank']}, layers={CONFIG['lora_layers']}")
    print(f"LR:        {CONFIG['learning_rate']}")
    print(f"Max seq:   {CONFIG['max_seq_length']}")
    print(f"Mask prompt: {CONFIG['mask_prompt']}")
    print("=" * 80)

    if not verify_dataset():
        return

    # Save config
    config_path = Path("training/gemma4_2b_amt_config.yaml")
    config_path.parent.mkdir(exist_ok=True)
    with open(config_path, "w") as f:
        yaml.dump(CONFIG, f, default_flow_style=False)
    print(f"\nConfig saved to {config_path}")

    # Save training note
    note = {
        "dataset": "amt_dataset/mlx_format",
        "dataset_source": "consolidated from expert_amt_dataset_clean + fabio_amt_dataset_clean",
        "total_scenarios": "78,681 unique (deduped from 83,619 raw)",
        "system_prompts": {
            "tier1_compact": "43,943 entries — expert narratives, compact JSON output",
            "tier2_cot": "34,738 entries — structured scenarios, CoT + JSON output",
        },
        "direction_balance": "LONG ~25k / SHORT ~26k / FLAT ~27k",
        "config": CONFIG,
    }
    with open(config_path.with_suffix(".json"), "w") as f:
        json.dump(note, f, indent=2)

    print(f"\n{'=' * 80}")
    print("Starting training...")
    print(f"{'=' * 80}\n")

    try:
        train(**CONFIG)
        print(f"\n✓ Training complete!")
        print(f"✓ Adapters saved to: {ADAPTER_PATH}")
    except Exception as e:
        print(f"\n✗ Training failed: {e}")
        import traceback
        traceback.print_exc()


if __name__ == "__main__":
    main()
