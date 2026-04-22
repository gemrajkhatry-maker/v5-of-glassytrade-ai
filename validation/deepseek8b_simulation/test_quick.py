#!/usr/bin/env python3
"""
Quick test to see full DeepSeek 8B output
"""

import sys
import os
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent.parent.parent / "backend"
sys.path.insert(0, str(backend_path))

# Configure environment
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["LLM_CLOUD_FALLBACK_ENABLED"] = "false"
os.environ["MLX_MODEL_PATH"] = "lmstudio-community/DeepSeek-R1-0528-Qwen3-8B-MLX-8bit"
os.environ["MLX_ADAPTER_PATH"] = str(Path(__file__).parent.parent.parent / "poc_deepseek8b" / "deepseek8b_amt_adapter")

from app.infrastructure.adapters.mlx_inference_adapter import MLXInferenceAdapter

print("Loading model...")
llm = MLXInferenceAdapter()

if not llm.wait_until_ready(timeout=120):
    print("❌ Model failed to load")
    sys.exit(1)

print("✅ Model loaded\n")

SYSTEM_PROMPT = """You are an expert AMT scalping analyst using Fabio Valentini's Auction Market Theory. Respond with JSON only.
Format: {"direction": "LONG|SHORT|FLAT", "confidence": "High|Medium|Low", "rationale": "brief reason"}"""

test_input = """Market state: TRENDING_UP
Location: above VAH
Distance_to_POC: 15 ticks
Delta: 6500
CVD: rising
Volume_spike: yes
Orderbook_imbalance: buyers
Absorption: no
Question: What is the trade decision?"""

print("Testing prediction...")
result = llm.predict(
    instruction=SYSTEM_PROMPT,
    input_text=test_input,
    max_tokens=256
)

print(f"\nFull output ({len(result)} chars):")
print("="*80)
print(result)
print("="*80)
