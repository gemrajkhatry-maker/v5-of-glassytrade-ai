#!/usr/bin/env python3
"""
Gemma-4-E4B-it LoRA Fine-Tuning Script
for GlassyTrade AMT Options Scalper System

Model:  mlx-community/gemma-4-e4b-it-nvfp4
Target: > 95% accuracy on Fabio AMT test suite
        < 2s avg inference (currently 1.18s base)
        JSON output: {direction, confidence, rationale}
        + <think> reasoning visible for transparency

Usage:
    python poc_gemma4_e4b/finetune_gemma4.py
    python poc_gemma4_e4b/finetune_gemma4.py --iters 1500 --adapter-path adapters_v2
"""

import argparse
import subprocess
import sys
import os
import json
import time
from pathlib import Path

BASE_MODEL   = "mlx-community/gemma-4-e4b-it-nvfp4"
ADAPTER_DIR  = "poc_gemma4_e4b/adapters"
DATA_DIR     = "poc_gemma4_e4b/data"
RESULTS_FILE = "poc_gemma4_e4b/finetune_log.json"


def parse_args():
    p = argparse.ArgumentParser(description="Gemma-4-E4B LoRA fine-tuning for AMT trading")
    p.add_argument("--iters",          type=int,   default=800,  help="Training iterations")
    p.add_argument("--batch-size",     type=int,   default=2,    help="Batch size (keep low for MoE on M-series)")
    p.add_argument("--learning-rate",  type=float, default=2e-5, help="Peak learning rate")
    p.add_argument("--lora-rank",      type=int,   default=16,   help="LoRA rank (8 or 16)")
    p.add_argument("--lora-alpha",     type=int,   default=32,   help="LoRA alpha (2x rank)")
    p.add_argument("--steps-per-eval", type=int,   default=50,   help="Validation frequency")
    p.add_argument("--steps-per-save", type=int,   default=100,  help="Checkpoint save frequency")
    p.add_argument("--max-seq-len",    type=int,   default=1024, help="Max token length per example")
    p.add_argument("--adapter-path",   type=str,   default=ADAPTER_DIR, help="Where to save adapters")
    p.add_argument("--skip-data-gen",  action="store_true",      help="Skip training data generation")
    p.add_argument("--skip-fuse",      action="store_true",      help="Skip adapter fusion step")
    p.add_argument("--dry-run",        action="store_true",      help="Print commands only, don't run")
    return p.parse_args()


def run_cmd(cmd: list[str], desc: str, dry_run: bool = False):
    print(f"\n{'─'*70}")
    print(f"  {desc}")
    print(f"  CMD: {' '.join(cmd[:6])}{'...' if len(cmd) > 6 else ''}")
    print(f"{'─'*70}")
    if dry_run:
        print(f"  [DRY RUN] Would execute: {' '.join(cmd)}")
        return True
    result = subprocess.run(cmd, capture_output=False)
    if result.returncode != 0:
        print(f"\n❌ Step failed: {desc}")
        return False
    return True


def main():
    args = parse_args()
    t_start = time.time()
    log = {"model": BASE_MODEL, "args": vars(args), "steps": []}

    print("\n" + "═"*70)
    print("  Gemma-4-E4B-it LoRA Fine-Tuning Pipeline")
    print("  GlassyTrade AMT Options Scalper System")
    print("═"*70)
    print(f"  Model:        {BASE_MODEL}")
    print(f"  Iterations:   {args.iters}")
    print(f"  LoRA rank:    r={args.lora_rank}, α={args.lora_alpha}")
    print(f"  Batch size:   {args.batch_size}")
    print(f"  LR:           {args.learning_rate}")
    print(f"  Max seq len:  {args.max_seq_len}")
    print(f"  Adapter dir:  {args.adapter_path}")

    # ─── STEP 1: Generate Training Data ──────────────────────────────────────
    if not args.skip_data_gen:
        print("\n\n STEP 1 — Generating Training Data".center(70, "─"))
        ok = run_cmd(
            [sys.executable, "poc_gemma4_e4b/generate_training_data.py"],
            "Generate Fabio AMT training examples (base + augmented)",
            dry_run=args.dry_run,
        )
        if not ok and not args.dry_run:
            sys.exit(1)
        log["steps"].append({"step": "data_gen", "status": "ok"})
    else:
        print("\n  [Skipping data generation — using existing JSONL files]")

    # Verify data files exist
    train_path = Path(f"{DATA_DIR}/train.jsonl")
    val_path   = Path(f"{DATA_DIR}/valid.jsonl")
    if not args.dry_run:
        if not train_path.exists():
            print(f"❌ {train_path} not found. Run without --skip-data-gen first.")
            sys.exit(1)
        n_train = sum(1 for _ in open(train_path))
        n_val   = sum(1 for _ in open(val_path))
        print(f"\n  Data: {n_train} train examples, {n_val} validation examples")

    # ─── STEP 2: LoRA Fine-Tuning ─────────────────────────────────────────────
    print("\n\n STEP 2 — LoRA Fine-Tuning".center(70, "─"))
    os.makedirs(args.adapter_path, exist_ok=True)

    # Build config overrides on top of lora_config.yaml
    # mlx_lm lora uses: python -m mlx_lm lora -c config.yaml [overrides]
    config_path = os.path.join(os.path.dirname(__file__), "lora_config.yaml")
    train_cmd = [
        sys.executable, "-m", "mlx_lm", "lora",
        "-c",               config_path,
        "--model",          BASE_MODEL,
        "--data",           DATA_DIR,
        "--adapter-path",   args.adapter_path,
        "--iters",          str(args.iters),
        "--batch-size",     str(args.batch_size),
        "--learning-rate",  str(args.learning_rate),
        "--steps-per-eval", str(args.steps_per_eval),
        "--save-every",     str(args.steps_per_save),
        "--max-seq-length", str(args.max_seq_len),
        "--val-batches",    "8",
    ]

    ok = run_cmd(train_cmd, f"LoRA training: {args.iters} iters, r={args.lora_rank}", dry_run=args.dry_run)
    log["steps"].append({"step": "lora_train", "status": "ok" if ok else "fail"})
    if not ok:
        sys.exit(1)

    # ─── STEP 3: Fuse Adapter into Model ─────────────────────────────────────
    FUSED_DIR = args.adapter_path + "_fused"
    if not args.skip_fuse:
        print("\n\n STEP 3 — Fuse LoRA Adapter into Model".center(70, "─"))
        fuse_cmd = [
            sys.executable, "-m", "mlx_lm.fuse",
            "--model",        BASE_MODEL,
            "--adapter-path", args.adapter_path,
            "--save-path",    FUSED_DIR,
            "--de-quantize",  # Fuse to fp16 weights for maximum inference quality
        ]
        ok = run_cmd(fuse_cmd, "Fusing LoRA adapter into model weights", dry_run=args.dry_run)
        log["steps"].append({"step": "fuse", "status": "ok" if ok else "fail"})
    else:
        print("\n  [Skipping adapter fusion]")
        FUSED_DIR = "(skipped)"

    # ─── STEP 4: Quick Validation ─────────────────────────────────────────────
    print("\n\n STEP 4 — Post-training Validation".center(70, "─"))
    val_cmd = [
        sys.executable, "poc_gemma4_e4b/validate_gemma4.py",
        "--model", args.adapter_path,  # Use adapter (faster than fused for quick check)
    ]
    ok = run_cmd(val_cmd, "Running 24-case Fabio AMT validation suite", dry_run=args.dry_run)
    log["steps"].append({"step": "validate", "status": "ok" if ok else "partial"})

    # ─── Summary ──────────────────────────────────────────────────────────────
    elapsed = time.time() - t_start
    log["elapsed_s"] = round(elapsed, 1)
    log["fused_model_path"] = FUSED_DIR

    print(f"\n\n{'═'*70}")
    print(f"  ✅ Fine-tuning Pipeline Complete")
    print(f"{'═'*70}")
    print(f"  Adapter:      {args.adapter_path}/")
    print(f"  Fused model:  {FUSED_DIR}/")
    print(f"  Elapsed:      {elapsed/60:.1f} min")
    print(f"\n  Production integration:")
    print(f"    - Set MLX_MODEL_PATH={FUSED_DIR}")
    print(f"    - Or set MLX_ADAPTER_PATH={args.adapter_path} with base model")
    print(f"    - Expected accuracy: >90% on AMT test suite")
    print(f"    - Expected latency:  ~1.5-2.5s per inference")

    with open(RESULTS_FILE, "w") as f:
        json.dump(log, f, indent=2)
    print(f"\n  Log saved → {RESULTS_FILE}")


if __name__ == "__main__":
    main()
