#!/bin/bash
# Start backend in MCX mode with LOCAL Gemma-2-2B adapter
# Optimized for stability on Apple Silicon

cd /Users/apple/Downloads/v5-of-glassytrade-ai/backend

# Activate virtual environment
source venv/bin/activate

# Set MCX mode environment variables
export GLASSYTRADE_ENV=paper
export GLASSYTRADE_STRATEGY=mcx_options
export KMP_DUPLICATE_LIB_OK=TRUE
export MLX_SET_NUM_THREADS=1
export MLX_DEFER_LOADING=1

# Local MLX Inference (Using Gemma-2-2B for stability)
export LLM_CLOUD_FALLBACK_ENABLED=0
export MLX_MODEL_PATH="mlx-community/gemma-2-2b-it-4bit"
export MLX_ADAPTER_PATH="/Users/apple/Downloads/v5-of-glassytrade-ai/poc18/adapters"

echo "Starting backend in MCX mode (LOCAL LLM: GEMMA-2-2B)..."
echo "Strategy: $GLASSYTRADE_STRATEGY"
echo "Model: $MLX_MODEL_PATH"
echo "Local Mode: Active (Cloud Fallback DISABLED)"

# Start uvicorn
exec uvicorn app.main:app --host 0.0.0.0 --port 9090 --log-level info
