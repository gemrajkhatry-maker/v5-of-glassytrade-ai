# Gemma-4-E4B Fine-Tuning for AMT Options Scalper

Model: `mlx-community/gemma-4-e4b-it-nvfp4`  
Base accuracy: **88%** | Target after fine-tuning: **≥95%**  
Avg latency: **1.18s** | System timeout budget: **30s**

## Quick Start

```bash
cd /Users/apple/Downloads/v5-of-glassytrade-ai
source backend/venv/bin/activate
KMP_DUPLICATE_LIB_OK=TRUE python poc_gemma4_e4b/finetune_gemma4.py
```

## What the Pipeline Does

1. **Generate training data** → `poc_gemma4_e4b/data/train.jsonl` + `valid.jsonl`
2. **LoRA fine-tune** → `poc_gemma4_e4b/adapters/`
3. **Fuse adapter** → `poc_gemma4_e4b/adapters_fused/`
4. **Validate** → 24-case AMT test suite + JSON format check

## Training Data Stats

| Category | Examples (base) | After Augment |
|---|---|---|
| Triple-A setups | 4 | 32+ |
| Second drive / First touch | 3 | 24+ |
| Mean reversion | 2 | 16+ |
| Squeeze setups | 3 | 24+ |
| VWAP / CVD filters | 4 | 24+ |
| Risk management rules | 4 | 24+ |
| Session timing rules | 4 | 24+ |
| Abort / Exit signals | 4 | 32+ |
| Transcript-specific insights | 8 | 64+ |
| MCX CRUDEOIL specific | 3 | 24+ |
| Overseer / trade mgmt | 3 | 18+ |
| **Total** | **~420+** | **≥500** |

## Output Format (per llm_contract.py entry-json-v1)

The model will output:
```
<think>
[Fabio's step-by-step reasoning: Aggression → Structure → Decision]
</think>
{"direction": "LONG|SHORT|FLAT", "confidence": "High|Medium|Low", "rationale": "brief justification"}
```

## New Scenarios from Transcript

Based on the Fabio Valentini live trading transcript, added:
- **"Punch on the wall"** — aggressive effort with zero result = narrative flip to buy
- **Round number reactions** — pause/reversal at 22000, 48000, 6000
- **"Don't marry your bias"** — invalidation levels flip the day's direction
- **LVN-first approach** — plot profile, find LVN, wait for aggression at that exact level
- **World cup cushion method** — build profit, then risk profits on directional days
- **Stop loss INSIDE cluster** — 1-2 ticks below aggressive prints (minimizes slippage)
- **Second drive only** — "wait for the first breakout, then wait for the retracement"

## Options Changes

```bash
# More iterations (if time permits)
python poc_gemma4_e4b/finetune_gemma4.py --iters 1500 --adapter-path poc_gemma4_e4b/adapters_v2

# Quick test (dry run — prints commands, no execution)
python poc_gemma4_e4b/finetune_gemma4.py --dry-run

# Validate base model (before fine-tuning reference)
python poc_gemma4_e4b/validate_gemma4.py --base

# Validate fine-tuned adapter
python poc_gemma4_e4b/validate_gemma4.py --model poc_gemma4_e4b/adapters
```

## Production Integration

After fine-tuning, set in `.env`:
```
MLX_MODEL_PATH=poc_gemma4_e4b/adapters_fused    # fused model
# OR
MLX_ADAPTER_PATH=poc_gemma4_e4b/adapters         # separate adapter (uses BASE_MODEL)
```

The `<think>` reasoning block will be visible in the AI panel for every trade decision.
