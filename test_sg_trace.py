#!/usr/bin/env python3
"""Test ServiceGraph creation with Gemma model — detailed trace"""

import sys, os, time, faulthandler

faulthandler.enable()
from pathlib import Path

backend_path = Path("/Users/apple/Downloads/v5-of-glassytrade-ai/backend")
sys.path.insert(0, str(backend_path))

os.environ["MLX_MODEL_PATH"] = "mlx-community/gemma-4-26b-a4b-it-4bit"
os.environ["MLX_ADAPTER_PATH"] = (
    "/Users/apple/Downloads/v5-of-glassytrade-ai/gemma4_26b_clean_adapter"
)
os.environ["GLASSYTRADE_STRATEGY"] = "nse_options"
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

print("[TRACE] Env set", flush=True)

try:
    print("[TRACE] Importing modules...", flush=True)
    from config.config import Configuration
    from app.application.service_graph import ServiceGraph

    print("[TRACE] Loading config...", flush=True)
    config = Configuration.from_env()
    print(f"[TRACE] Config loaded, llm.model_path={config.llm.model_path}", flush=True)

    print("[TRACE] Creating ServiceGraph...", flush=True)
    start = time.time()
    sg = ServiceGraph(config)
    elapsed = time.time() - start
    print(f"[TRACE] ServiceGraph created in {elapsed:.2f}s", flush=True)
    print(f"Trading session: {sg.trading_session}")
    print(f"Active symbols: {sg.active_symbols}")

except Exception as e:
    print(f"[TRACE] EXCEPTION: {type(e).__name__}: {e}", flush=True)
    import traceback

    traceback.print_exc()
    sys.exit(1)
