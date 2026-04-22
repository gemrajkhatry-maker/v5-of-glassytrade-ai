#!/usr/bin/env python3
import mlx.core as mx
import sys

# 1. FORCE CPU IMMEDIATELY
# This must happen before any model loading or mlx-lm imports if possible
mx.set_default_device(mx.cpu)
print(f"[LAUNCHER] MLX Default Device forced to: {mx.default_device()}")

import mlx_lm.lora

if __name__ == "__main__":
    # Ensure a config is provided
    if "--config" not in sys.argv and "-c" not in sys.argv:
        print("[ERROR] No configuration file provided. Use --config <file>.yaml")
        sys.exit(1)
        
    print("[LAUNCHER] Rerouting to mlx_lm.lora.main() on CPU...")
    try:
        mlx_lm.lora.main()
    except Exception as e:
        print(f"[ERROR] Training failed: {e}")
        sys.exit(1)
