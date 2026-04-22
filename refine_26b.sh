#!/bin/bash
# refine_26b.sh: Absolute Stability Mode (CPU)
# Forces CPU training to eliminate Metal GPU crashes completely.

CONFIG="gemma4_26b_safe_config.yaml"
ADAPTER_DIR="gemma4_26b_amt_adapter_absolute"
PYTHON_BIN="backend/venv/bin/python"
LOG_FILE="refine_gemma26b_absolute.log"

# Force CPU Mode
export MLX_DEVICE=cpu

echo "===================================================="
echo "Gemma 4 26B Refinement: ABSOLUTE STABILITY (CPU)"
echo "===================================================="
echo "Config: $CONFIG"
echo "Log:    $LOG_FILE"
echo "Device: CPU (Forced)"
echo "===================================================="

mkdir -p "$ADAPTER_DIR"

# Simple Loop for potential network/file interruptions (Metal crashes are unlikely now)
while true; do
    LATEST_CHECKPOINT=$(ls -v "$ADAPTER_DIR"/000*_adapters.safetensors 2>/dev/null | tail -1)
    
    if [ -n "$LATEST_CHECKPOINT" ]; then
        echo "[$(date)] Resuming from: $LATEST_CHECKPOINT"
        cp "$CONFIG" "${CONFIG}.tmp"
        if grep -q "resume_adapter_file:" "${CONFIG}.tmp"; then
            sed -i '' "s|resume_adapter_file:.*|resume_adapter_file: \"$LATEST_CHECKPOINT\"|" "${CONFIG}.tmp"
        else
            echo "resume_adapter_file: \"$LATEST_CHECKPOINT\"" >> "${CONFIG}.tmp"
        fi
        CURRENT_CONFIG="${CONFIG}.tmp"
    else
        echo "[$(date)] Starting fresh CPU run"
        CURRENT_CONFIG="$CONFIG"
    fi

    echo "[$(date)] Launching CPU training session..."
    $PYTHON_BIN -m mlx_lm.lora --config "$CURRENT_CONFIG" 2>&1 | tee -a "$LOG_FILE"
    EXIT_CODE=${PIPESTATUS[0]}

    if [ $EXIT_CODE -eq 0 ]; then
        echo "[$(date)] ✅ Training completed successfully!"
        rm -f "${CONFIG}.tmp"
        break
    else
        echo "[$(date)] ⚠️ Training interrupted (Code: $EXIT_CODE). Retrying in 10s..."
        sleep 10
    fi
done
