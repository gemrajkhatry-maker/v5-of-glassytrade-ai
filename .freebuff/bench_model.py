#!/usr/bin/env python3
"""Benchmark decode tok/s for an arbitrary MLX model (path via MODEL env)."""
import os
import time

import mlx.core as mx

from mlx_lm import load, stream_generate
from mlx_lm.sample_utils import make_sampler

model_path = os.environ["MODEL"]
adapter = os.environ.get("ADAPTER") or None
print(f"model: {model_path}")
print(f"metal: {mx.metal.is_available()}, device: {mx.default_device()}")

t0 = time.time()
model, tok = load(model_path, adapter_path=adapter)
print(f"load: {time.time()-t0:.1f}s, gpu mem {mx.get_active_memory()/1e9:.2f} GB")

sampler = make_sampler(temp=0.35, top_p=0.95)

prompt = (
    "You are an expert market analyst using the AMT methodology. Analyze the auction: "
    "NIFTY 11 AUG 24550 CALL at 100.35, session VA [89.47, 112.72], POC 97.05, "
    "BALANCED market state, CVD slope 2.0, VWAP deviation 1.2 sigma, "
    "volume profile 200 buckets, aggression healthy, price inside NEAR_POC zone. "
    "Decide direction. Respond ONLY with a JSON object: "
    '{"direction": "LONG/SHORT/FLAT", "rationale": "...", "confidence": "Low/Medium/High"}'
)

# warmup pass (compiles shaders / warms cache for this shape)
t0 = time.time()
for _ in stream_generate(model, tok, prompt=prompt, max_tokens=2, sampler=sampler):
    pass
print(f"warmup (prefill {len(tok.encode(prompt))} tok + 2): {time.time()-t0:.2f}s")

# timed decode
t0 = time.time()
n = 0
out = ""
for resp in stream_generate(model, tok, prompt=prompt, max_tokens=100, sampler=sampler):
    if resp.text:
        n += 1
        out += resp.text
dt = time.time() - t0
print(f"decode: {n} tokens in {dt:.2f}s = {n/dt:.1f} tok/s (prefill {len(tok.encode(prompt))} tok)")
print(f"sample output head: {out[:80]!r}")
