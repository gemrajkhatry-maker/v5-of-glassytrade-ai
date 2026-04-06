 """Quick integration test for LFM2-24B in the live trading adapter."""
import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), 'backend'))
os.environ['KMP_DUPLICATE_LIB_OK'] = 'TRUE'

from app.config import settings

print('=== Config Check ===')
print(f'MLX_MODEL_PATH:     {settings.MLX_MODEL_PATH}')
print(f'MLX_ADAPTER_PATH:   {settings.MLX_ADAPTER_PATH}')
print(f'Model exists:       {os.path.exists(settings.MLX_MODEL_PATH)}')
print(f'Adapter exists:     {os.path.exists(settings.MLX_ADAPTER_PATH)}')
print(f'LLM_MAX_NEW_TOKENS: {settings.LLM_MAX_NEW_TOKENS}')
print()

print('=== Loading LFM2 via MLXInferenceAdapter ===')
import logging
logging.basicConfig(level=logging.INFO)

from app.infrastructure.adapters.mlx_inference_adapter import MLXInferenceAdapter

# Reset singleton for fresh test
MLXInferenceAdapter._instance = None
adapter = MLXInferenceAdapter()

print('Waiting for model to load (up to 180s)...')
ready = adapter.wait_until_ready(timeout=180)
print(f'Model ready: {ready}')

if not ready:
    print(f'Load error: {adapter._load_error}')
    sys.exit(1)

# Test 1: AAA Long Setup
print('\n' + '='*60)
print('Test 1: AAA Long Setup at VAL (expect: Enter Long)')
print('='*60)
result1 = adapter.predict(
    instruction=settings.LLM_INSTRUCTION,
    input_text=(
        'NSE Primary Window (09:30-11:30). NIFTY at 24500. VAL: 24480, POC: 24540, VAH: 24600. '
        'Sellers sweeping bids at 24480 but getting absorbed every time. Delta -812, volume 3200. '
        'Volume bubbles detected: 2.5σ aggressive buy at 24480 (3200 lots). '
        'CVD trending up. Buyers in control. Price below VWAP (24550). '
        'OI walls: 24700 CE (180K OI), 24300 PE (240K OI). PCR: 1.38 (elevated). '
        'SECOND DRIVE at this level.'
    ),
)
print(f'\nOutput:\n{result1}')

# Test 2: Phase 1 Opening Noise
print('\n' + '='*60)
print('Test 2: Phase 1 Opening Noise (expect: Stay Flat)')
print('='*60)
result2 = adapter.predict(
    instruction=settings.LLM_INSTRUCTION,
    input_text=(
        'Session: Phase 1: Opening Noise (09:15-09:30 IST). '
        'Market just opened. First 15 minutes. Price volatile at 24620. '
        'No significant volume bubbles. First touch at this level.'
    ),
)
print(f'\nOutput:\n{result2}')

# Test 3: 3-Loss Stop
print('\n' + '='*60)
print('Test 3: 3-Loss Stop (expect: Stay Flat)')
print('='*60)
result3 = adapter.predict(
    instruction=settings.LLM_INSTRUCTION,
    input_text=(
        'Session P&L: -₹4,000 (3 consecutive losses). Signal firing at VAL. '
        'D-shaped profile. No significant volume bubbles. First touch at this level.'
    ),
)
print(f'\nOutput:\n{result3}')

print('\n' + '='*60)
print('Integration test complete!')
print('='*60)
