#!/usr/bin/env python3
"""Test ServiceGraph creation with Gemma model"""

import sys
import os
from pathlib import Path

# Add backend to path
backend_path = Path("/Users/apple/Downloads/v5-of-glassytrade-ai/backend")
sys.path.insert(0, str(backend_path))

# Set environment
os.environ["MLX_MODEL_PATH"] = "mlx-community/gemma-4-26b-a4b-it-4bit"
os.environ["MLX_ADAPTER_PATH"] = (
    "/Users/apple/Downloads/v5-of-glassytrade-ai/gemma4_26b_clean_adapter"
)
os.environ["GLASSYTRADE_STRATEGY"] = "nse_options"
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

print("Setting up environment...")

try:
    from config.config import Configuration
    from app.application.service_graph import ServiceGraph

    print("Loading configuration...")
    config = Configuration.from_env()
    print(f"Config loaded: {config}")

    print("\nCreating ServiceGraph (this will instantiate MLX model)...")
    sg = ServiceGraph(config)
    print("✓ ServiceGraph created successfully!")
    print(f"Trading session: {sg.trading_session}")
    print(f"Active symbols: {sg.active_symbols}")

except Exception as e:
    print(f"\n✗ FAILED: {type(e).__name__}: {e}")
    import traceback

    traceback.print_exc()
    sys.exit(1)
