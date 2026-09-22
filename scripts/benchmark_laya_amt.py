#!/usr/bin/env python3
"""Benchmark and Prototype for Laya-MLX Typed Decisions on AMT Trading Dataset.

Evaluates:
- End-to-end inference latency (ms) per market snapshot
- Direct typed decision heads: action, direction, setup, confidence, and trade viability (noul)
- Peak MLX unified memory allocation on Apple Silicon
- Comparison against ground truth in amt_dataset/live_aligned/train.jsonl
"""

import json
import os
import sys
import time
from typing import Any, Dict, List

import laya_mlx as laya
import mlx.core as mx

DATASET_PATH = "/Users/apple/Documents/v5-of-glassytrade-ai/amt_dataset/live_aligned/train.jsonl"
MODEL_ID = "aac6fef/laya-mlx"


def load_dataset_samples(max_samples: int = 25) -> List[Dict[str, Any]]:
    """Loads first N samples from train.jsonl."""
    samples = []
    if not os.path.exists(DATASET_PATH):
        print(f"Dataset not found at {DATASET_PATH}")
        return samples

    with open(DATASET_PATH, "r") as f:
        for line in f:
            if not line.strip():
                continue
            item = json.loads(line)
            # Each item has messages: [system, user, assistant]
            user_msg = next((m["content"] for m in item.get("messages", []) if m["role"] == "user"), "")
            asst_msg = next((m["content"] for m in item.get("messages", []) if m["role"] == "assistant"), "")
            
            try:
                ground_truth = json.loads(asst_msg)
            except Exception:
                ground_truth = {"raw": asst_msg}
                
            samples.append({
                "context": user_msg,
                "ground_truth": ground_truth,
            })
            if len(samples) >= max_samples:
                break
    return samples


def main():
    print("=" * 70)
    print("🚀 Laya-MLX Auction Market Theory (AMT) Benchmark on Apple Silicon")
    print("=" * 70)
    print(f"Loading checkpoint: {MODEL_ID} ...")
    
    t0 = time.perf_counter()
    agent = laya.load(MODEL_ID)
    load_time = time.perf_counter() - t0
    print(f"✅ Model loaded in {load_time:.2f}s")
    
    samples = load_dataset_samples(max_samples=20)
    print(f"Loaded {len(samples)} test cases from {DATASET_PATH}\n")

    # AMT Schema for Typed Decisions
    schema = {
        "action": {
            "type": "choice",
            "instructions": "According to Fabio Valentini Auction Market Theory, what is the valid order action?",
            "criteria": ["ENTER_LONG", "ENTER_SHORT", "FLAT"],
        },
        "setup": {
            "type": "choice",
            "instructions": "Which AMT structural setup pattern is present?",
            "criteria": ["TRIPLE_A", "VA_FADE", "BREAKOUT", "NO_EDGE"],
        },
        "trade_permitted": {
            "type": "noul",
            "instructions": "Does the auction state satisfy all risk and session phase rules to permit trade execution?",
        },
    }

    # Warmup pass
    print("Warming up MLX graph...")
    warmup_state = samples[0]["context"]
    _ = agent.predict(warmup_state, schema)
    mx.eval()
    print("✅ Graph compiled and warmed up.\n")

    latencies = []
    matches = 0
    results_table = []

    print(f"{'#':<3} | {'Symbol':<10} | {'Expected Action':<15} | {'Laya Action':<15} | {'P(Action)':<10} | {'Setup':<12} | {'Permitted':<9} | {'Latency':<8}")
    print("-" * 95)

    for i, s in enumerate(samples, 1):
        ctx = s["context"]
        gt = s["ground_truth"]
        expected_action = gt.get("action", "UNKNOWN")
        expected_setup = gt.get("setup", "UNKNOWN")

        # Parse symbol from context text if possible
        sym = "UNKNOWN"
        for line in ctx.splitlines():
            if '"symbol":' in line:
                sym = line.split('"symbol":')[1].strip().strip('",')
                break

        t_start = time.perf_counter()
        pred = agent.predict(ctx, schema)
        mx.eval()
        t_end = time.perf_counter()
        lat_ms = (t_end - t_start) * 1000.0
        latencies.append(lat_ms)

        ans = pred.get("answers", {})
        laya_action_obj = ans.get("action", {})
        laya_action = laya_action_obj.get("choice", "N/A") if isinstance(laya_action_obj, dict) else str(laya_action_obj)
        
        # Get probability if available
        action_probs = laya_action_obj.get("probabilities", {}) if isinstance(laya_action_obj, dict) else {}
        top_prob = action_probs.get(laya_action, 0.0) if action_probs else 0.0

        laya_setup_obj = ans.get("setup", {})
        laya_setup = laya_setup_obj.get("choice", "N/A") if isinstance(laya_setup_obj, dict) else str(laya_setup_obj)

        permitted_obj = ans.get("trade_permitted", {})
        permitted = permitted_obj.get("p_true", 0.0) if isinstance(permitted_obj, dict) else 0.0
        perm_str = f"{permitted:.1%}" if isinstance(permitted, float) else str(permitted)

        match = (laya_action == expected_action)
        if match:
            matches += 1

        prob_str = f"{top_prob:.1%}" if top_prob > 0 else "N/A"
        print(f"{i:<3} | {sym:<10} | {expected_action:<15} | {laya_action:<15} | {prob_str:<10} | {laya_setup:<12} | {perm_str:<9} | {lat_ms:>6.2f}ms")

    latencies.sort()
    p50 = latencies[len(latencies) // 2]
    p90 = latencies[int(len(latencies) * 0.9)]
    avg_lat = sum(latencies) / len(latencies)
    peak_mem_mb = mx.metal.get_peak_memory() / (1024 * 1024)

    print("\n" + "=" * 70)
    print("📊 BENCHMARK SUMMARY")
    print("=" * 70)
    print(f"Sample Count       : {len(samples)}")
    print(f"Average Latency    : {avg_lat:.2f} ms")
    print(f"Median Latency P50 : {p50:.2f} ms")
    print(f"90th Percentile P90: {p90:.2f} ms")
    print(f"Fastest Pass       : {min(latencies):.2f} ms")
    print(f"Slowest Pass       : {max(latencies):.2f} ms")
    print(f"Peak Metal Memory  : {peak_mem_mb:.1f} MB (Unified RAM)")
    print(f"Raw Base Alignment : {matches}/{len(samples)} ({matches/len(samples)*100:.1f}%) [Zero-shot before domain LoRA]")
    print("=" * 70)


if __name__ == "__main__":
    main()
