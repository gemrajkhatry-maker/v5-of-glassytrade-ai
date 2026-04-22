#!/usr/bin/env python3
import os, sys, time
from pathlib import Path

# Setup
backend = Path("/Users/apple/Downloads/v5-of-glassytrade-ai/backend")
sys.path.insert(0, str(backend))
os.environ["MLX_MODEL_PATH"] = "mlx-community/gemma-4-26b-a4b-it-4bit"
os.environ["MLX_ADAPTER_PATH"] = (
    "/Users/apple/Downloads/v5-of-glassytrade-ai/gemma4_26b_clean_adapter"
)
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

print("[1] Loading config...")
from config.config import Configuration

config = Configuration.from_env()

print("[2] Creating MLX adapter directly...")
from app.infrastructure.adapters.mlx_inference_adapter import MLXInferenceAdapter

llm = MLXInferenceAdapter()
print(f"Adapter ready: {llm.is_ready()}")

print("[3] Creating GenerativeAIService...")
from app.domain.fabio_ai.services.generative_ai_service import GenerativeAIService

gen_ai = GenerativeAIService(llm_adapter=llm)
print("GenerativeAIService created")

print("[4] Importing LLMEntryHandler...")
from app.application.handlers.llm_entry_handler import LLMEntryHandler

print("LLMEntryHandler imported")

print("[5] Creating LLMEntryHandler...")
handler = LLMEntryHandler(gen_ai, storage=None, exchange="NFO", allow_short=False)
print("LLMEntryHandler created")

print("\n✓ All steps completed without crash!")
time.sleep(2)
