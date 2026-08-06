#!/usr/bin/env bash
# Reproducible LoRA retrain for the AMT entry model.
# Usage: bash backend/scripts/train_mlx.sh [iters]
set -euo pipefail
cd "$(dirname "$0")/../.."
ITERS="${1:-300}"
yq -i ".iters = $ITERS" backend/scripts/mlx_lora_retrain.yaml 2>/dev/null || sed -i '' "s/^iters: .*/iters: $ITERS/" backend/scripts/mlx_lora_retrain.yaml
python -m mlx_lm.lora --config backend/scripts/mlx_lora_retrain.yaml
echo "Adapter saved. To use it, set MLX_ADAPTER_PATH in .env to the new adapter dir and restart."
