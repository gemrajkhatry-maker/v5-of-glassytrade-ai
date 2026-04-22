#!/usr/bin/env python3
import os, sys, time, faulthandler

faulthandler.enable()
from pathlib import Path

backend = Path("/Users/apple/Downloads/v5-of-glassytrade-ai/backend")
sys.path.insert(0, str(backend))
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

print("[0] Setup env")
os.environ["MLX_MODEL_PATH"] = "mlx-community/gemma-4-26b-a4b-it-4bit"
os.environ["MLX_ADAPTER_PATH"] = (
    "/Users/apple/Downloads/v5-of-glassytrade-ai/gemma4_26b_clean_adapter"
)

print("[1] Imports")
from config.config import Configuration
from app.infrastructure.adapters.mlx_inference_adapter import MLXInferenceAdapter
from app.domain.fabio_ai.services.generative_ai_service import GenerativeAIService
from app.infrastructure.adapters.lgbm_probability_adapter import LGBMProbabilityAdapter
from app.infrastructure.adapters.paper_broker import PaperBrokerAdapter
from app.infrastructure.storage.database import SQLiteStorageAdapter
from app.domain.models.exchange_config import ExchangeConfig
from app.application.services.trading_session import TradingSessionService

print("[2] Config")
config = Configuration.from_env()

print("[3] MLX adapter")
llm = MLXInferenceAdapter()
print(f"   LLM ready: {llm.is_ready()}")

print("[4] GenAI service")
gen_ai = GenerativeAIService(llm_adapter=llm)

print("[5] Probability engine")
prob = LGBMProbabilityAdapter(model_dir=backend / "models")
print(f"   Prob ready: {prob.is_ready()}")

print("[6] Broker & storage")
broker = PaperBrokerAdapter()
storage = SQLiteStorageAdapter()

print("[7] Exchange config")
exc = ExchangeConfig.for_exchange("NFO")

print("[8] Creating TradingSessionService...")
session = TradingSessionService(
    broker=broker,
    gen_ai_service=gen_ai,
    storage=storage,
    probability_engine=prob,
    exchange_config=exc,
    allow_short=False,
)
print(f"✓ TradingSessionService created: {type(session).__name__}")
time.sleep(3)
print("Done, exiting cleanly.")
