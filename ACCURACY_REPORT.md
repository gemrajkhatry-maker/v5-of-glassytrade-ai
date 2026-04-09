# Model Accuracy & Performance Evaluation Report
Generated: April 9, 2026

## Executive Summary

**Tested Models:**
1. poc4/qwen35_mlx_adapters (Qwen3.5 0.8B, 1000 iterations)
2. poc3/lora_adapter_options_mlx (Options Model, 800 iterations)
3. poc8/adapters (Qwen 4B, 300 iterations)

**Test Dataset:** fabio_amt_dataset/test.jsonl (50 samples)

---

## Speed Benchmark Results

| Rank | Model | Size | Load Time | Inference | Total | Speed Rating |
|------|-------|------|-----------|-----------|-------|--------------|
| 🥇 | **poc4/qwen35_mlx_adapters** | 0.8B | 1.42s | 1.36s | **2.78s** | ⚡⚡⚡ FAST |
| 🥈 | poc3/lora_adapter_options_mlx | Unknown | 1.64s | 2.30s | **3.94s** | ⚡⚡ MODERATE |
| 🥉 | poc8/adapters | 4B | 3.81s | 3.99s | **7.80s** | ⚡ SLOW |

---

## Accuracy Evaluation Results

### Overall Accuracy (50 test samples)

| Model | STATE Accuracy | TRADE Accuracy | Grade | Status |
|-------|---------------|----------------|-------|--------|
| poc4/qwen35_mlx_adapters | 6.0% (3/50) | 4.0% (2/50) | **D (Poor)** | ❌ FAILED |
| poc3/lora_adapter_options_mlx | Not tested | Not tested | - | - |
| poc8/adapters | Not tested | Not tested | - | - |

### Confusion Matrix - poc4/qwen35_mlx_adapters

**Trade Decisions:**

| Expected \ Predicted | FLAT | LONG | SHORT | UNKNOWN |
|---------------------|------|------|-------|---------|
| FLAT | 0 | 0 | 0 | 11 |
| LONG | 3 | 1 | 3 | 14 |
| SHORT | 1 | 1 | 1 | 15 |

**Key Issues:**
- 80% of predictions returned UNKNOWN (no clear STATE/TRADE format)
- Model outputs verbose explanations instead of concise decisions
- Training data format mismatch detected

---

## Root Cause Analysis

### Why Low Accuracy?

1. **Training Data Format Mismatch**
   - Test data format: `"STATE: BREAKOUT\nTRADE: LONG"`
   - Model output: Verbose explanations like "A: Balance and Extend, B: Reduce Volume..."
   - Model was trained on different data (training_data_nse_v2.jsonl), not fabio_amt_dataset

2. **Wrong Training Dataset**
   - poc4 config shows: `"data": "./mlx_data_clean"`
   - Expected: fabio_amt_dataset
   - The model learned a different output format

3. **Insufficient Training**
   - Only 1000 iterations with LoRA rank=8 (very low capacity)
   - Low rank (8) limits model's ability to learn complex patterns
   - Alpha=16 (2x rank) is conservative

4. **Output Format Issues**
   - Model doesn't output STATE:/TRADE: format consistently
   - Generates conversational responses instead of structured decisions
   - Prompt format during training likely differed from test format

---

## Model Quality Assessment

### 1. poc4/qwen35_mlx_adapters

**Strengths:**
- ✅ Fastest inference (1.36s average)
- ✅ Smallest model size (0.8B = low memory)
- ✅ Quick load time (1.42s)
- ✅ Well-structured code and training pipeline

**Weaknesses:**
- ❌ Very poor accuracy (4% trade decisions)
- ❌ Wrong output format (verbose vs structured)
- ❌ Trained on wrong dataset
- ❌ Low LoRA rank (8) limits learning capacity
- ❌ Not production-ready

**Sample Output:**
```
Expected: STATE=BREAKOUT, TRADE=LONG
Got: "A: Balance and Extend, B: Reduce Volume, C: Reduce Volume..."
```

**Verdict:** ❌ **NOT SUITABLE FOR PRODUCTION**

---

### 2. poc3/lora_adapter_options_mlx

**Known:**
- 800 training iterations
- Options-specific training data
- Moderate speed (2.30s inference)

**Issues:**
- Output contains garbled text ("b-b-b pattern", "VW-up")
- Less coherent structure
- Not tested for accuracy yet

**Verdict:** ⚠️ **NEEDS EVALUATION**

---

### 3. poc8/adapters

**Known:**
- 300 training iterations (undertrained)
- 4B parameter model (largest)
- Slowest (3.99s inference)

**Issues:**
- Repetitive output ("TRADE: FLAT" repeated 20+ times)
- Appears stuck in generation loop
- Severely undertrained (only 300 iters)

**Verdict:** ❌ **WORST PERFORMANCE**

---

## Recommendations

### Immediate Actions:

1. **Retrain poc4/qwen35_mlx_adapters with Correct Data**
   ```bash
   # Use fabio_amt_dataset instead of mlx_data_clean
   # Increase LoRA rank from 8 to 32 or 64
   # Train for 2000-3000 iterations
   ```

2. **Update Training Configuration**
   ```yaml
   model: poc4/mlx_model/qwen35-0.8b-4bit
   data: fabio_amt_dataset  # Correct dataset
   iters: 2000              # More iterations
   lora_parameters:
     rank: 32               # Higher capacity
     alpha: 64              # 2x rank
   max_seq_length: 1024     # Allow longer contexts
   mask_prompt: true        # Better learning
   ```

3. **Standardize Output Format**
   - Ensure all training data uses: `STATE: <state>\nTRADE: <decision>`
   - Add format enforcement in prompts
   - Validate outputs during training

### Alternative Approaches:

1. **Use Base Gemma 4 Model (Current Production)**
   - `mlx-community/gemma-4-e4b-it-nvfp4`
   - Better instruction following
   - More capable base model (4B vs 0.8B)
   - No fine-tuning artifacts

2. **Fine-tune Gemma 4 Instead**
   - Start from better base model
   - Use fabio_amt_dataset
   - Higher LoRA rank (32-64)
   - More iterations (2000+)

3. **Try Different Architecture**
   - Qwen3.5 4B instead of 0.8B
   - More parameters = better accuracy
   - Still fast on Apple Silicon

---

## Performance Targets for Production

| Metric | Current (poc4) | Target | Gap |
|--------|---------------|--------|-----|
| Trade Accuracy | 4% | ≥80% | ❌ -76% |
| STATE Accuracy | 6% | ≥75% | ❌ -69% |
| Inference Time | 1.36s | ≤2.0s | ✅ PASS |
| Model Size | 0.8B | ≤4B | ✅ PASS |
| Load Time | 1.42s | ≤5.0s | ✅ PASS |

---

## Conclusion

**Current Status:** ❌ **NONE of the fine-tuned models are production-ready**

**Best Option Right Now:**
- Use the base **Gemma 4 4B** model (mlx-community/gemma-4-e4b-it-nvfp4)
- It has better instruction-following capabilities
- No fine-tuning artifacts or format mismatches

**Next Steps:**
1. Retrain poc4 model with correct dataset (fabio_amt_dataset)
2. Increase LoRA rank to 32-64
3. Train for 2000+ iterations
4. Validate output format matches expected STATE:/TRADE: pattern
5. Re-evaluate accuracy (target: ≥80% trade accuracy)

**Estimated Time to Production-Ready Fine-tuned Model:** 2-4 hours of training + evaluation

---

## Files Generated

- `benchmark_adapters.py` - Speed benchmark script
- `benchmark_results.json` - Speed benchmark data
- `evaluate_accuracy.py` - Accuracy evaluation script
- `accuracy_results.json` - Accuracy evaluation data
- `ACCURACY_REPORT.md` - This report

---

**Evaluated By:** Automated Benchmark Suite
**Date:** April 9, 2026
**Hardware:** Apple Silicon (M-series)
**Framework:** MLX-LM
