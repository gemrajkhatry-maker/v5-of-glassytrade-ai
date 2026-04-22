#!/usr/bin/env python3
import os, time
from mlx_lm import load

os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

print("Loading Gemma 26B with adapter...")
model, tokenizer = load(
    "mlx-community/gemma-4-26b-a4b-it-4bit",
    adapter_path="/Users/apple/Downloads/v5-of-glassytrade-ai/gemma4_26b_clean_adapter",
)
print("Model loaded successfully!")

print("Sleeping 15 seconds to observe background threads...")
time.sleep(15)
print("Done, exiting cleanly.")
