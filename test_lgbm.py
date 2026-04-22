#!/usr/bin/env python3
import os, sys
from pathlib import Path

backend = Path("/Users/apple/Downloads/v5-of-glassytrade-ai/backend")
sys.path.insert(0, str(backend))
os.environ["KMP_DUPLICATE_LIB_OK"] = "TRUE"

print("[1] Importing LGBMProbabilityAdapter...")
from app.infrastructure.adapters.lgbm_probability_adapter import LGBMProbabilityAdapter

print("[2] Instantiating LGBMProbabilityAdapter...")
prob = LGBMProbabilityAdapter(model_dir=backend / "models")
print(f"Probability engine ready: {prob.is_ready()}")

print("\n✓ LGBM loaded fine")
time.sleep(2)
