#!/bin/bash
# Monitor Gemma 4 training progress

LOG_FILE="gemma4_json_training_resume.log"

if [ ! -f "$LOG_FILE" ]; then
    echo "Log file not found: $LOG_FILE"
    exit 1
fi

echo "=== Gemma 4 Training Progress Monitor ==="
echo ""

# Check if process is running
if pgrep -f "mlx_lm lora" > /dev/null; then
    echo "✓ Training is RUNNING"
else
    echo "✗ Training is NOT running"
fi

echo ""
echo "=== Latest Progress (last 30 lines) ==="
tail -30 "$LOG_FILE" | grep -E "(Iter|Val loss|Train loss|Loading|Starting)"

echo ""
echo "=== Training Statistics ==="
TOTAL_LINES=$(wc -l < "$LOG_FILE")
echo "Total log lines: $TOTAL_LINES"

# Count iterations completed
ITER_COUNT=$(grep -c "Iter [0-9]*:" "$LOG_FILE" 2>/dev/null || echo "0")
echo "Iterations logged: $ITER_COUNT"

# Get last iteration
LAST_ITER=$(grep -oP "Iter \K[0-9]+" "$LOG_FILE" | tail -1)
if [ -n "$LAST_ITER" ]; then
    echo "Last iteration: $LAST_ITER / 2000"
    PERCENTAGE=$((LAST_ITER * 100 / 2000))
    echo "Progress: ${PERCENTAGE}%"
fi

echo ""
echo "=== File Size ==="
ls -lh "$LOG_FILE" | awk '{print "Log file size: "$5}'
ls -lh gemma4_26b_amt_adapter_json/ | grep safetensors | tail -1 | awk '{print "Latest adapter: "$5}'

echo ""
echo "=== Memory Usage ==="
vm_stat | perl -ne '/page size of (\d+)/ and $ps=$1; /Pages\s+([\w\s]+)\s+(\d+)/ and printf("%-30s %8.2f MB\n", $1, $2*$ps/1048576);' | grep -E "(active|wired|free)"
