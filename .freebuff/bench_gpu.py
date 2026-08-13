#!/usr/bin/env python3
"""Raw MLX compute check — is the GPU actually being used?"""
import time

import mlx.core as mx

print(f"metal available: {mx.metal.is_available()}")
print(f"default device: {mx.default_device()}")

def bench_matmul(device, n=2048, iters=20):
    a = mx.random.normal((n, n), dtype=mx.float16)
    b = mx.random.normal((n, n), dtype=mx.float16)
    if device is not None:
        a = a.to_device(device)
        b = b.to_device(device)
    # warmup
    for _ in range(3):
        c = mx.matmul(a, b)
        mx.eval(c)
    t0 = time.time()
    for _ in range(iters):
        c = mx.matmul(a, b)
        mx.eval(c)
    dt = (time.time() - t0) / iters
    print(f"matmul {n}x{n} fp16 on {device or 'default'}: {dt*1000:.1f} ms/op")
    return dt

bench_matmul(None)          # default device

# Decode: with adapter vs base model
from mlx_lm import load, stream_generate
from mlx_lm.sample_utils import make_sampler

sampler = make_sampler(temp=0.0, top_p=0.95)
base = "/Users/apple/Documents/v5-of-glassytrade-ai/models/vibethinker-3b"
adapter = "/Users/apple/Documents/v5-of-glassytrade-ai/models/vibethinker-amt-lora"

for label, ap in (("WITH adapter", adapter), ("BASE only", None)):
    t0 = time.time()
    model, tok = load(base, adapter_path=ap)
    print(f"load {label}: {time.time()-t0:.1f}s, gpu mem {mx.metal.get_active_memory()/1e9:.2f} GB")
    prompt = "Ready"
    # warm 1 token
    for _ in stream_generate(model, tok, prompt=prompt, max_tokens=1, sampler=sampler):
        pass
    t0 = time.time()
    n = 0
    for resp in stream_generate(model, tok, prompt=prompt, max_tokens=40, sampler=sampler):
        if resp.text:
            n += 1
    dt = time.time() - t0
    print(f"decode {label}: {n} tokens in {dt:.2f}s = {n/dt:.1f} tok/s, gpu mem {mx.metal.get_active_memory()/1e9:.2f} GB")
