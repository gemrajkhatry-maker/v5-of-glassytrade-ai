#!/usr/bin/env python3
"""Measure the deferred first-call cost: load + realistic warmup + first real gen."""
import os
import time

import mlx.core as mx

from mlx_lm import load, stream_generate
from mlx_lm.sample_utils import make_sampler

base = "/Users/apple/Documents/v5-of-glassytrade-ai/models/vibethinker-3b"
adapter = "/Users/apple/Documents/v5-of-glassytrade-ai/models/vibethinker-amt-lora"

# ~2000-token realistic warmup prompt (entry-prompt-like narrative)
warmup_prompt = (
    "You are an expert market analyst using the AMT methodology. Analyze the auction context "
    "to identify high-probability entries. Session phase: Mid-session. Market state: BALANCED. "
    "Price is inside session VA. POC at 97.05, VAH 112.72, VAL 89.47. CVD slope +2.0. "
    "VWAP deviation 1.2 sigma. Volume profile: 200 buckets, balanced. " * 30
    + 'Respond ONLY with a JSON object: {"direction": "LONG/SHORT/FLAT", "rationale": "...", "confidence": "Low/Medium/High"}'
)

real_prompt = (
    "You are an expert market analyst using the AMT methodology. "
    "NIFTY 11 AUG 24550 CALL at 100.35, session VA [89.47, 112.72], POC 97.05, "
    "BALANCED, CVD slope 2.0, VWAP deviation 1.2 sigma. "
    'Decide. Respond ONLY with JSON: {"direction": "LONG/SHORT/FLAT", "rationale": "...", "confidence": "Low/Medium/High"}'
)

sampler = make_sampler(temp=0.35, top_p=0.95)

t0 = time.time()
model, tok = load(base, adapter_path=adapter)
print(f"load: {time.time()-t0:.1f}s, gpu mem {mx.get_active_memory()/1e9:.2f} GB")

print(f"warmup prompt tokens: {len(tok.encode(warmup_prompt))}")

# realistic warmup: compile shaders for long prompt + a few decode steps
t0 = time.time()
n = 0
for resp in stream_generate(model, tok, prompt=warmup_prompt, max_tokens=24, sampler=sampler):
    if resp.text:
        n += 1
print(f"warmup (long prompt): {time.time()-t0:.2f}s ({n} tok)")

# first REAL generation after warmup
t0 = time.time()
out = ""
for resp in stream_generate(model, tok, prompt=real_prompt, max_tokens=120, sampler=sampler):
    out += resp.text or ""
dt = time.time() - t0
n_new = len(tok.encode(out))
print(f"FIRST real gen after warmup: {dt:.2f}s for {n_new} tok ({n_new/dt:.1f} tok/s)")
print(f"output: {out[:100]!r}")

# second real generation (steady state)
t0 = time.time()
out = ""
for resp in stream_generate(model, tok, prompt=real_prompt, max_tokens=120, sampler=sampler):
    out += resp.text or ""
dt = time.time() - t0
n_new = len(tok.encode(out))
print(f"SECOND real gen (steady): {dt:.2f}s for {n_new} tok ({n_new/dt:.1f} tok/s)")
