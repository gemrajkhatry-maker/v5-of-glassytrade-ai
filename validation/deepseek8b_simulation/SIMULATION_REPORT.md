# DeepSeek R1 Qwen3 8B - Market Simulation Report

**Evaluation Date**: 2026-04-19 23:04:13
**Model**: DeepSeek-R1-Qwen3-8B-MLX-8bit
**Adapter**: poc_deepseek8b/deepseek8b_amt_adapter
**Dataset**: 200 realistic market scenarios

## Overall Performance

| Metric | Score |
|--------|-------|
| Direction Accuracy | 96.00% |
| Confidence Accuracy | 60.50% |
| Joint Accuracy | 56.50% |
| Parse Errors | 0 |
| Speed | 0.35 examples/sec |

## Scenario Performance

| Scenario | Accuracy | Correct/Total |
|----------|----------|---------------|
| balanced_rotation | 96.0% | 24/25 |
| bearish_breakdown_val | 100.0% | 25/25 |
| bearish_rejection | 100.0% | 25/25 |
| bullish_breakout | 100.0% | 25/25 |
| bullish_retest_val | 100.0% | 25/25 |
| false_breakout_trap | 100.0% | 25/25 |
| poc_battle | 100.0% | 25/25 |
| strong_trend_continuation | 72.0% | 18/25 |

## Confusion Matrix

| Actual \ Predicted | FLAT | LONG | SHORT |
|---|---|---|---|
| FLAT | 49 | 0 | 1 |
| LONG | 0 | 59 | 7 |
| SHORT | 0 | 0 | 84 |
