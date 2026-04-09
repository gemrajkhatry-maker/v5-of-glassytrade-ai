# Gemma 4 26B LoRA Fine-Tuning Guide

## Model Information
- **Model**: `mlx-community/gemma-4-26b-a4b-it-4bit`
- **Parameters**: 26 Billion
- **Quantization**: 4-bit (QLoRA ready)
- **Location**: Already cached locally ✓
- **Hardware**: Apple Silicon M1 Max (64GB RAM)

---

## Hardware Requirements

### For Training (QLoRA with 4-bit base model):
- **Minimum RAM**: 32GB
- **Recommended RAM**: 64GB ✅ (You have this!)
- **Disk Space**: ~20GB for model + adapters
- **GPU**: Apple Silicon Metal GPU ✅

### Memory Estimation:
```
Base Model (4-bit):     ~13 GB
Training Overhead:      ~15 GB
Activations/Gradients:  ~10 GB
Total Estimated:        ~38 GB (fits in 64GB)
```

---

## Training Configuration

### Conservative Settings (Safe for 64GB):
```yaml
model: mlx-community/gemma-4-26b-a4b-it-4bit
data: fabio_amt_dataset
train: true
iters: 2000
batch_size: 1
max_seq_length: 1024
learning_rate: 1e-5
lora_layers: 16
lora_parameters:
  rank: 32
  alpha: 64
  dropout: 0.05
  scale: 2.0
mask_prompt: true
grad_checkpoint: true
save_every: 200
steps_per_report: 10
steps_per_eval: 200
val_batches: 25
test_batches: 100
seed: 42
```

### Aggressive Settings (If memory allows):
```yaml
batch_size: 2
lora_layers: 32
rank: 64
alpha: 128
```

---

## Training Commands

### Option 1: Command Line (Direct)
```bash
cd /Users/apple/Downloads/v5-of-glassytrade-ai

# Start training
backend/venv/bin/python -m mlx_lm.lora \
    --model mlx-community/gemma-4-26b-a4b-it-4bit \
    --data fabio_amt_dataset \
    --train \
    --iters 2000 \
    --batch-size 1 \
    --lora-layers 16 \
    --learning-rate 1e-5 \
    --adapter-path ./gemma4_26b_amt_adapter \
    --mask-prompt \
    --max-seq-length 1024 \
    --steps-per-report 10 \
    --steps-per-eval 200 \
    --save-every 200 \
    --grad-checkpoint
```

### Option 2: YAML Config (Recommended)
```bash
# Create config file (see gemma4_26b_training_config.yaml)
backend/venv/bin/python -m mlx_lm.lora \
    --config gemma4_26b_training_config.yaml
```

---

## Training Process

### What to Expect:
1. **Model Loading**: ~30-60 seconds
   - Downloads if not cached (already cached ✓)
   - Loads 4-bit quantized weights
   
2. **Training Speed**: 
   - Estimated: 2-5 iterations/second
   - 2000 iterations ≈ 7-17 minutes
   
3. **Progress Output**:
   ```
   Iter 10: Train loss 1.234, Val loss 1.456
   Iter 20: Train loss 0.987, Val loss 1.234
   ...
   ```

4. **Checkpoints Saved**:
   - `0000200_adapters.safetensors`
   - `0000400_adapters.safetensors`
   - ...
   - `adapters.safetensors` (final)

---

## Monitoring Training

### In Another Terminal:
```bash
# Monitor memory usage
sudo powermetrics --samplers gpu_power -i 1000

# Monitor system resources
top -l 5 -s 2 | grep -E "PhysMem|CPU"
```

### Training Metrics to Watch:
- **Train Loss**: Should decrease steadily
- **Val Loss**: Should decrease (watch for overfitting)
- **Memory**: Should stay under 60GB
- **Speed**: iterations/second

---

## After Training

### Test the Adapter:
```bash
backend/venv/bin/python -m mlx_lm.generate \
    --model mlx-community/gemma-4-26b-a4b-it-4bit \
    --adapter-path ./gemma4_26b_amt_adapter \
    --prompt "Market state: INITIATIVE
Location: above VAH
Distance_to_POC: -5 ticks
Delta: 6265
CVD: neutral
Volume_spike: yes
Orderbook_imbalance: balanced
Absorption: no
Question: What is the trade decision?" \
    --max-tokens 50 \
    --temp 0.4
```

### Evaluate Accuracy:
```bash
backend/venv/bin/python evaluate_accuracy.py
# (Update script to use gemma4_26b model)
```

### Merge Adapter (Optional):
```bash
backend/venv/bin/python -m mlx_lm.fuse \
    --model mlx-community/gemma-4-26b-a4b-it-4bit \
    --adapter-path ./gemma4_26b_amt_adapter \
    --save-path ./gemma4_26b_amt_fused
```

---

## Troubleshooting

### Out of Memory:
```bash
# Reduce these parameters:
--batch-size 1          # Already minimal
--lora-layers 8         # Reduce from 16
--max-seq-length 512    # Reduce from 1024
--rank 16               # Reduce from 32
```

### Metal GPU Crash:
```bash
# Disable Metal (slower but stable)
export MLX_DISABLE_METAL=1

# Then run training
```

### Slow Training:
```bash
# Close other applications
# Ensure no other GPU-intensive processes running
# Check: activity monitor > GPU
```

---

## Integration with Backend

### Update .env:
```bash
MLX_MODEL_PATH="mlx-community/gemma-4-26b-a4b-it-4bit"
MLX_ADAPTER_PATH="./gemma4_26b_amt_adapter"
```

### Or Update Config:
```yaml
# backend/config/base.yaml
llm:
  model_id: "gemma-4-26b-amt-finetuned"
  reasoning_model_id: "Jackrong/Qwen3.5-4B-Claude-4.6-Opus-Reasoning-Distilled"
  temperature_entry: 0.4
  temperature_overseer: 0.3
  max_tokens: 120
  timeout_seconds: 30  # Increase for larger model
```

---

## Expected Results

### Compared to Current Models:

| Metric | poc4 (0.8B) | Gemma 4 4B | Gemma 4 26B |
|--------|-------------|------------|-------------|
| Speed | 1.36s | ~3s | ~8-12s |
| Accuracy | 4% | ~60-70% | **80-90%** |
| Memory | 2GB | 6GB | 13GB |
| Quality | Poor | Good | **Excellent** |

### Why 26B Will Be Better:
1. **More Parameters**: 26B vs 0.8B (32x larger)
2. **Better Reasoning**: More capacity for complex patterns
3. **Instruction Following**: Better at following STATE/TRADE format
4. **AMT Knowledge**: Can learn nuanced market structures

---

## Training Timeline

| Step | Time | Status |
|------|------|--------|
| Setup config | 5 min | ⏳ Ready |
| Start training | 1 min | ⏳ Ready |
| Training (2000 iters) | 10-20 min | ⏳ Pending |
| Test adapter | 5 min | ⏳ Pending |
| Evaluate accuracy | 30 min | ⏳ Pending |
| Deploy to backend | 5 min | ⏳ Pending |
| **Total** | **~1 hour** | |

---

## Next Steps

1. ✅ Model already cached locally
2. ✅ Training data ready (fabio_amt_dataset)
3. ✅ Scripts created
4. ⏳ **Run training** (next action)
5. ⏳ Evaluate accuracy
6. ⏳ Deploy to backend

---

## References

- [MLX-LM LoRA Documentation](https://github.com/ml-explore/mlx-lm/blob/main/mlx_lm/LORA.md)
- [Gemma 4 26B Model Card](https://huggingface.co/mlx-community/gemma-4-26b-a4b-it-4bit)
- [MLX Fine-Tuning Guide](https://levelup.gitconnected.com/fine-tuning-llms-locally-using-mlx-lm-a-comprehensive-guide-6049fd3014bb)

---

**Created**: April 9, 2026
**Hardware**: Apple M1 Max, 64GB RAM
**Framework**: MLX-LM with QLoRA
