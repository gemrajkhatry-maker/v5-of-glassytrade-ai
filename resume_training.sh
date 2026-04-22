#!/bin/bash
# Resume/fresh Gemma-4-26B LoRA Training with crash-proof settings (Modern mlx_lm syntax)

set -e

cd "$(dirname "$0")"

echo "═══════════════════════════════════════════════════════════════════════════"
echo "  Gemma-4-26B-A4B LoRA Training (Crash-Proof)"
echo "═══════════════════════════════════════════════════════════════════════════"
echo ""
echo "Configuration:"
echo "  Model: mlx-community/gemma-4-26b-a4b-it-4bit"
echo "  Dataset: fabio_amt_dataset"
echo "  Iterations: 1000"
echo "  Batch Size: 1"
echo "  LoRA Rank: 32 (Alpha: 64)"
echo "  Layers: 16"
echo "  Max Seq Length: 1024"
echo "  Steps Per Eval: 0 (DISABLED - prevents crashes)"
echo "  Save Every: 100"
echo "  Adapter Path: ./gemma4_26b_amt_adapter_final"
echo ""
echo "Training Time Estimate: ~45-60 minutes (M1 Max)"
echo "Expected Memory Usage: 20-30 GB"
echo ""
echo "⚠️  IMPORTANT: Keep Mac plugged in and idle for duration of training"
echo "═══════════════════════════════════════════════════════════════════════════"
echo ""

# Check dataset exists
if [ ! -f "fabio_amt_dataset/train.jsonl" ]; then
    echo "❌ Error: Training data not found in fabio_amt_dataset/"
    exit 1
fi

# Check for existing checkpoints
CHECKPOINT_DIR="gemma4_26b_amt_adapter_final"
RESUME_ARGS=""

if [ -d "$CHECKPOINT_DIR" ]; then
    LATEST_CHECKPOINT=$(find "$CHECKPOINT_DIR" -name "*.safetensors" | sort -V | tail -1)
    if [ -n "$LATEST_CHECKPOINT" ]; then
        echo "✅ Found checkpoint: $LATEST_CHECKPOINT"
        RESUME_ARGS="--resume-adapter-file $LATEST_CHECKPOINT"
    else
        echo "ℹ️  No checkpoint found, starting fresh"
    fi
else
    echo "ℹ️  Starting fresh training (no existing adapter)"
    mkdir -p "$CHECKPOINT_DIR"
fi

# Run training using yaml config
echo ""
echo "🚀 Starting training..."
echo ""

if [ -n "$RESUME_ARGS" ]; then
    echo "Command: mlx_lm.lora --config gemma4_26b_final.yaml $RESUME_ARGS"
    backend/venv/bin/mlx_lm.lora \
        --config gemma4_26b_final.yaml \
        $RESUME_ARGS 2>&1 | tee "gemma4_training_$(date +%s).log"
else
    echo "Command: mlx_lm.lora --config gemma4_26b_final.yaml"
    backend/venv/bin/mlx_lm.lora \
        --config gemma4_26b_final.yaml 2>&1 | tee "gemma4_training_$(date +%s).log"
fi

echo ""
echo "═══════════════════════════════════════════════════════════════════════════"
echo "  Training Complete!"
echo "═══════════════════════════════════════════════════════════════════════════"
