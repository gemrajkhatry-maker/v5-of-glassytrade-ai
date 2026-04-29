#!/bin/bash
# Start backend in NSE mode with POC-18 local Gemma-2-2B adapter

cd /Users/apple/Downloads/v5-of-glassytrade-ai/backend

# Activate virtual environment
source venv/bin/activate

# Set NSE mode environment variables
export GLASSYTRADE_ENV=paper
export GLASSYTRADE_STRATEGY=nse_options
export KMP_DUPLICATE_LIB_OK=TRUE
export MLX_SET_NUM_THREADS=1
export MLX_DEFER_LOADING=1

# Local MLX Inference (POC-18 10k Iterations)
export LLM_CLOUD_FALLBACK_ENABLED=0
export MLX_MODEL_PATH="mlx-community/gemma-2-2b-it-4bit"
export MLX_ADAPTER_PATH="/Users/apple/Downloads/v5-of-glassytrade-ai/poc18/adapters"

echo "Starting backend in NSE mode (LOCAL LLM: POC-18)..."
echo "GLASSYTRADE_ENV=$GLASSYTRADE_ENV"
echo "GLASSYTRADE_STRATEGY=$GLASSYTRADE_STRATEGY"
echo "LLM_CLOUD_FALLBACK_ENABLED=$LLM_CLOUD_FALLBACK_ENABLED"
echo "MLX_ADAPTER_PATH=$MLX_ADAPTER_PATH"

# Start uvicorn
exec uvicorn app.main:app --host 0.0.0.0 --port 9090 --log-level info
