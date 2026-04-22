#!/usr/bin/env python3
import os, threading, time

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

from mlx_lm import load, generate

MLX_GPU_LOCK = threading.Lock()
model_path = "mlx-community/gemma-4-26b-a4b-it-4bit"
adapter_path = "/Users/apple/Downloads/v5-of-glassytrade-ai/gemma4_26b_clean_adapter"

print("Acquiring lock...")
with MLX_GPU_LOCK:
    print("Loading model...")
    model, tokenizer = load(model_path, adapter_path=adapter_path)
    processor = tokenizer
print("Model loaded successfully!")
print("Sleeping 10 sec...")
time.sleep(10)
print("Exiting cleanly.")
