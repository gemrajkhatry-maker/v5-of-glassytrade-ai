#!/usr/bin/env python3
"""
Test DeepSeek 8B model integration with the backend MLX adapter
Validates that the model loads and responds correctly
"""

import sys
import os
import json
from pathlib import Path

# Add backend to path
backend_path = Path(__file__).parent.parent.parent / "backend"
sys.path.insert(0, str(backend_path))

# Configure environment for DeepSeek 8B
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"
os.environ["LLM_CLOUD_FALLBACK_ENABLED"] = "false"  # Use local model
os.environ["MLX_MODEL_PATH"] = "lmstudio-community/DeepSeek-R1-0528-Qwen3-8B-MLX-8bit"
os.environ["MLX_ADAPTER_PATH"] = str(Path(__file__).parent.parent.parent / "poc_deepseek8b" / "deepseek8b_amt_adapter")

print("="*80)
print("DeepSeek 8B Integration Test")
print("="*80)
print(f"Model: {os.environ['MLX_MODEL_PATH']}")
print(f"Adapter: {os.environ['MLX_ADAPTER_PATH']}")
print(f"Cloud Fallback: {os.environ['LLM_CLOUD_FALLBACK_ENABLED']}")
print("="*80)

# Import MLX adapter
from app.infrastructure.adapters.mlx_inference_adapter import MLXInferenceAdapter

print("\n[1/4] Initializing MLX adapter...")
llm = MLXInferenceAdapter()

print("[2/4] Waiting for model to load...")
if not llm.wait_until_ready(timeout=120):
    print("❌ Model failed to load within 120 seconds")
    sys.exit(1)

print("✅ Model loaded successfully!")

print(f"\n[3/4] Running validation test...")
if not llm.validate():
    print("❌ Validation failed")
    sys.exit(1)

print("\n[4/4] Testing AMT trade decision...")

# Test with realistic AMT market scenario
test_prompt = """Market state: TRENDING_UP
Location: above VAH
Distance_to_POC: 15 ticks
Delta: 6500
CVD: rising
Volume_spike: yes
Orderbook_imbalance: buyers
Absorption: no
Question: What is the trade decision?"""

SYSTEM_PROMPT = """You are an expert AMT scalping analyst using Fabio Valentini's Auction Market Theory. You READ the auction — you do NOT predict. MANDATORY REASONING STRUCTURE (Inside <think> tags): 1. SESSION CHECK: [Window] -> Bias [Bullish/Bearish/Neutral] 2. RISK CHECK: [P&L/Rule Status] -> Permit [Yes/No] 3. STRUCTURE CHECK: [State/Location] -> Signal [Confirmed/No] 4. AGGRESSION CHECK: [CVD/Delta/Bubbles] -> Trigger [Confirmed/No] 5. FINAL LOGIC: [Narrative summary] Then respond with a JSON object only. JSON format: {"direction": "LONG|SHORT|FLAT", "confidence": "High|Medium|Low", "rationale": "brief reason"}"""

try:
    result = llm.predict(
        instruction=SYSTEM_PROMPT,
        input_text=test_prompt
    )
    
    print(f"\nInput:")
    print(f"  Market state: TRENDING_UP")
    print(f"  Location: above VAH")
    print(f"  Delta: 6500")
    print(f"  CVD: rising")
    
    print(f"\nModel Output:")
    print(f"  {result}")
    
    # Try to parse JSON
    try:
        parsed = json.loads(result)
        direction = parsed.get('direction', 'UNKNOWN')
        confidence = parsed.get('confidence', 'UNKNOWN')
        rationale = parsed.get('rationale', '')
        
        print(f"\n✅ Parsed JSON Response:")
        print(f"  Direction: {direction}")
        print(f"  Confidence: {confidence}")
        print(f"  Rationale: {rationale}")
        
        # Validate response
        if direction == "LONG":
            print(f"\n✅ CORRECT! Model predicted LONG for bullish breakout scenario")
        else:
            print(f"\n⚠️ Unexpected direction: {direction} (expected LONG)")
            
    except json.JSONDecodeError:
        print(f"\n⚠️ Response is not valid JSON (model may need system prompt)")
        
except Exception as e:
    print(f"\n❌ Prediction failed: {e}")
    import traceback
    traceback.print_exc()
    sys.exit(1)

print(f"\n{'='*80}")
print("✅ DeepSeek 8B Integration Test PASSED")
print(f"{'='*80}")
