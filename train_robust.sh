#!/bin/bash
# Robust training script with automatic restart on METAL GPU errors

CONFIG_FILE="gemma4_26b_json_training_config.yaml"
LOG_FILE="gemma4_training_robust.log"
MAX_RETRIES=10
RETRY_DELAY=30

echo "========================================="
echo "Gemma 4 Robust Training Script"
echo "========================================="
echo "Config: $CONFIG_FILE"
echo "Log: $LOG_FILE"
echo "Max Retries: $MAX_RETRIES"
echo ""

for attempt in $(seq 1 $MAX_RETRIES); do
    echo "[$(date)] Attempt $attempt / $MAX_RETRIES"
    echo "[$(date)] Starting training..." | tee -a "$LOG_FILE"
    
    # Run training
    backend/venv/bin/python -m mlx_lm lora --config "$CONFIG_FILE" >> "$LOG_FILE" 2>&1
    EXIT_CODE=$?
    
    # Check if training completed successfully
    if [ $EXIT_CODE -eq 0 ]; then
        echo "[$(date)] ✓ Training completed successfully!" | tee -a "$LOG_FILE"
        break
    fi
    
    # Check if it's a METAL error
    if tail -20 "$LOG_FILE" | grep -q "METAL.*Command buffer execution failed"; then
        echo "[$(date)] ✗ METAL GPU error detected" | tee -a "$LOG_FILE"
        
        # Find the latest checkpoint
        LATEST_CHECKPOINT=$(ls -t gemma4_26b_amt_adapter_json/000*_adapters.safetensors 2>/dev/null | head -1)
        
        if [ -n "$LATEST_CHECKPOINT" ]; then
            echo "[$(date)] Latest checkpoint: $LATEST_CHECKPOINT" | tee -a "$LOG_FILE"
            
            # Update config to resume from latest checkpoint
            sed -i '' "s|resume_adapter_file:.*|resume_adapter_file: \"./$LATEST_CHECKPOINT\"|" "$CONFIG_FILE"
            echo "[$(date)] Updated config to resume from: $LATEST_CHECKPOINT" | tee -a "$LOG_FILE"
        else
            echo "[$(date)] ✗ No checkpoint found!" | tee -a "$LOG_FILE"
            exit 1
        fi
    else
        echo "[$(date)] ✗ Training failed with exit code $EXIT_CODE (non-METAL error)" | tee -a "$LOG_FILE"
        tail -30 "$LOG_FILE"
        exit 1
    fi
    
    # Wait before retry
    if [ $attempt -lt $MAX_RETRIES ]; then
        echo "[$(date)] Waiting ${RETRY_DELAY}s before retry..." | tee -a "$LOG_FILE"
        sleep $RETRY_DELAY
        
        # Clear GPU memory
        echo "[$(date)] Attempting to clear GPU memory..." | tee -a "$LOG_FILE"
        purge >/dev/null 2>&1
    fi
done

if [ $attempt -eq $MAX_RETRIES ]; then
    echo "[$(date)] ✗ Max retries ($MAX_RETRIES) reached. Training failed." | tee -a "$LOG_FILE"
    exit 1
fi

echo ""
echo "========================================="
echo "Training Summary"
echo "========================================="
echo "[$(date)] Final status:" | tee -a "$LOG_FILE"
grep -E "Iter [0-9]+:" "$LOG_FILE" | tail -10
echo ""
echo "Log file: $LOG_FILE"
ls -lh "$LOG_FILE"
