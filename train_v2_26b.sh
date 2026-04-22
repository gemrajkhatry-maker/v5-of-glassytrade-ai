#!/bin/bash

# Permanent Metal Stability Fix
# Relaxes the macOS Metal Watchdog to prevent 'Impacting Interactivity' GPU crashes
export AGX_RELAX_CDM_CTXSTORE_TIMEOUT=1

# Reserve 40% memory for OS UI to ensure system remains usable
export MLX_GPU_MEMORY_LIMIT=0.6

# Use the virtual environment python
VENV_PYTHON="./backend/venv/bin/python"

echo "Starting Gemma 4 26B Training (Clean Start)..."
echo "Using Python: $VENV_PYTHON"
echo "Adapter Path: ./gemma4_26b_clean_adapter"
echo "Logs: gemma4_clean_training.log"

# caffeinate prevents the system from sleeping during training
caffeinate -i "$VENV_PYTHON" -m mlx_lm.lora --config gemma4_26b_v2_config.yaml
