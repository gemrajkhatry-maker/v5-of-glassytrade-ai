#!/usr/bin/env python3
"""Minimal MLX model loading test with faulthandler for segfault diagnostics."""
import faulthandler
faulthandler.enable()

import json
import os
import sys
import time
from pathlib import Path

# Resolve paths
REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_PATH = REPO_ROOT / "gemma4_26b_fused_production"

print(f"Repo root: {REPO_ROOT}")
print(f"Model path: {MODEL_PATH}")
print()

# ---- Step 0: Check MLX core works ----
print("=" * 60)
print("STEP 0: MLX core import + device check")
print("=" * 60)
try:
    import mlx.core as mx
    device = mx.default_device()
    print(f"  mlx.core imported OK")
    print(f"  default_device(): {device}")
    # Quick tensor op to verify Metal backend
    a = mx.array([1.0, 2.0, 3.0])
    b = mx.array([4.0, 5.0, 6.0])
    c = a + b
    print(f"  tensor add: {c}")
    print("  MLX core: OK")
except Exception as e:
    print(f"  MLX core FAILED: {e}")
    sys.exit(1)

print()

# ---- Step 1: Check config.json ----
print("=" * 60)
print("STEP 1: config.json validation")
print("=" * 60)
config_file = MODEL_PATH / "config.json"
if not config_file.exists():
    print(f"  FAIL: {config_file} does not exist")
    sys.exit(1)

with open(config_file) as f:
    config = json.load(f)

architectures = config.get("architectures", [])
print(f"  architectures: {architectures}")
print(f"  model_type: {config.get('model_type')}")
print(f"  dtype: {config.get('dtype')}")
quant = config.get("quantization", {})
print(f"  quantization: bits={quant.get('bits')}, group_size={quant.get('group_size')}, mode={quant.get('mode')}")
print("  config.json: OK")

print()

# ---- Step 2: Import mlx_vlm ----
print("=" * 60)
print("STEP 2: Import mlx_vlm")
print("=" * 60)
try:
    import mlx_vlm
    print(f"  mlx_vlm version: {getattr(mlx_vlm, '__version__', 'unknown')}")
    print("  import: OK")
except Exception as e:
    print(f"  FAILED: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print()

# ---- Step 3: Load model with mlx_vlm ----
print("=" * 60)
print("STEP 3: Load model (this may take 30-120s for 14GB quantized)")
print("=" * 60)
t0 = time.time()
try:
    from mlx_vlm import load
    model_path_str = str(MODEL_PATH.resolve())
    print(f"  Loading from: {model_path_str}")
    print(f"  Starting load...")
    sys.stdout.flush()

    model, processor = load(model_path_str)

    elapsed = time.time() - t0
    print(f"  Model loaded in {elapsed:.1f}s")
    print(f"  model type: {type(model)}")
    print(f"  processor type: {type(processor)}")
    print("  LOAD: SUCCESS")
except Exception as e:
    elapsed = time.time() - t0
    print(f"  FAILED after {elapsed:.1f}s: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print()

# ---- Step 4: Quick generate test ----
print("=" * 60)
print("STEP 4: Quick generate test (10 tokens)")
print("=" * 60)
try:
    from mlx_vlm import generate
    messages = [{"role": "user", "content": "Say hello."}]
    prompt = processor.apply_chat_template(messages, tokenize=False, add_generation_prompt=True)
    sys.stdout.flush()
    t1 = time.time()
    result = generate(model, processor, prompt=prompt, max_tokens=10, verbose=False)
    elapsed = time.time() - t1
    print(f"  Generated in {elapsed:.1f}s: {result[:100]}")
    print("  GENERATE: SUCCESS")
except Exception as e:
    print(f"  FAILED: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print()
print("=" * 60)
print("ALL TESTS PASSED")
print("=" * 60)
