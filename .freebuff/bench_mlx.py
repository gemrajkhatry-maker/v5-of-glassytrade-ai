#!/usr/bin/env python3
"""Quick MLX generation benchmark — isolate prefill vs decode cost."""
import os
import sys
import time

import mlx.core as mx

model_path = os.environ.get("MODEL", "/Users/apple/Documents/v5-of-glassytrade-ai/models/vibethinker-3b")
adapter = os.environ.get("ADAPTER", "/Users/apple/Documents/v5-of-glassytrade-ai/models/vibethinker-amt-lora")
threads = os.environ.get("MLX_SET_NUM_THREADS", "")

print(f"metal available: {mx.metal.is_available()}")
print(f"default device: {mx.default_device()}")
if threads:
    print(f"MLX_SET_NUM_THREADS env: {threads}")
print(f"active memory before load: {mx.get_active_memory()/1e9:.2f} GB")

from mlx_lm import load, generate, stream_generate
from mlx_lm.sample_utils import make_sampler

sampler = make_sampler(temp=0.0, top_p=0.95)

t0 = time.time()
model, processor = load(model_path, adapter_path=adapter)
t_load = time.time() - t0
print(f"load+adapter fuse: {t_load:.1f}s")
print(f"active memory after load: {mx.get_active_memory()/1e9:.2f} GB")

def bench(prompt: str, max_tokens: int, label: str):
    # Prefill timing: generate with max_tokens=1 is essentially prefill + 1 token
    t0 = time.time()
    _ = stream_generate(model, processor, prompt=prompt, max_tokens=1, sampler=sampler)
    t_prefill = time.time() - t0
    n_prefill = len(processor.encode(prompt))
    print(f"[{label}] prefill: {t_prefill:.2f}s for {n_prefill} tokens ({n_prefill/t_prefill:.0f} tok/s)")

    t0 = time.time()
    out = ""
    n_steps = 0
    for resp in stream_generate(model, processor, prompt=prompt, max_tokens=max_tokens, sampler=sampler):
        out += resp.text or ""
        n_steps += 1
        if n_steps % 10 == 0 and hasattr(mx, "metal"):
            print(f"      ...step {n_steps} at {time.time()-t0:.1f}s, gpu mem {mx.metal.get_active_memory()/1e9:.2f} GB")
    t_total = time.time() - t0
    n_new = len(processor.encode(out))
    t_decode = t_total - t_prefill
    print(f"[{label}] generate {max_tokens} tok: {t_total:.2f}s total, decode {n_new} tok in {t_decode:.2f}s ({n_new/t_decode:.1f} tok/s), gpu mem {mx.metal.get_active_memory()/1e9:.2f} GB")

short = "Ready"
long_prompt = (
    "You are an expert market analyst using the AMT methodology. Analyze the auction: "
    + "NIFTY 11 AUG 24550 CALL at 100.35, session VA [89.47, 112.72], POC 97.05, "
    + "BALANCED market state, CVD slope 2.0, VWAP deviation 1.2 sigma, "
    + "volume profile 200 buckets, aggression healthy, price inside NEAR_POC zone. "
    + "Decide direction. Respond ONLY with a JSON object: "
    + '{"direction": "LONG/SHORT/FLAT", "rationale": "...", "confidence": "Low/Medium/High"}'
)

bench(short, 40, "short")
bench(long_prompt, 120, "long-entry-like")
