# Spec — Remove the LLM / AI-Inference Layer (stable_5)

Date: 2026-08-13
Branch: `stable_5`

## Goal

Remove the LLM advisory layer, `PredictionEngine`, and RL training from GlassyTrade AI
completely. The deterministic Fabio AMT engine (QuantEngine → 4-gate pipeline → SignalBuilder
→ PaperOMS) is the decision core and is **unchanged**. Nothing after this work calls a model
(MLX/GGUF/cloud), builds a prompt, or runs RL.

## Non-Goals

- No change to the deterministic decision path (gates 1–4, SignalBuilder, ExitEngine, PaperOMS).
- No change to market data, broker, storage, or WS gameloop behavior.
- No change to the AMT analyzer or auction-state machine.

## Scope

### Delete entirely

| Path | Contents |
|---|---|
| `quant/inference/` | `mlx_inference_adapter.py`, `gguf_inference_adapter.py`, `generative_ai.py`, `prompt_builder.py`, `llm_contract.py`, `prediction.py`, `formatting.py`, `models.py`, `rl/` (trainer, valentini_env, data_loader, reward_shaper) |
| `backend/app/api/routers/ai.py` | `/api/ai/*` endpoints |
| `backend/app/api/routers/rl.py` | `/api/rl/*` endpoints |
| `backend/app/application/services/ai_command_service.py` | AI command handling |
| `backend/app/application/services/analysis_service.py` | PredictionEngine-based analysis |
| `backend/app/infrastructure/adapters/gguf_inference_adapter.py` | GGUF adapter |
| `backend/scripts/generate_mcx_data.py`, `eval_lfm.py`, `dataset_render.py` | LLM dataset/training tools |
| `tests/quant/inference/` | inference cluster tests |
| `backend/tests/unit/domain/test_generative_ai_service.py`, `test_prompt_builder.py`, `test_prompt_builder_fixes.py`, `test_prediction_engine.py` | LLM/prediction tests |

### Strip (keep file, remove LLM)

| File | Remove |
|---|---|
| `quant/runtime.py` | `_llm_executor`, `_schedule_llm`, `_llm_instruction`, `_llm_input`, `_llm_consensus_state`, `_inference_loading`, advisory fold-back in `_on_bar_closed`, `_last_llm_bar_index`, `_llm_entry_temperature`, `_llm_execution_enabled` |
| `quant/coordinator.py` | `inference=` param, `llm_sink`, `history_loader`, `llm_history()`, `_on_llm_analysis`, `LLMAnalysisProduced` subscription |
| `backend/app/main.py` | `GenerativeAIService` init, `ILLMInference` resolve, AI router include |
| `backend/app/application/di/composition_root.py` | `_llm_inference_port()`, `_create_llm_adapter`, `NullLLMInference`, ILLMInference resolve + fallback |
| `backend/app/api/routers/health.py` | `ILLMInference` import, LLM readiness checks |
| `backend/app/infrastructure/storage/database.py` | `llm_decisions` table, `save_llm_decision`, `query_llm_decisions`, `idx_llm_created` |
| `backend/app/infrastructure/serialization/schemas.py` | `ModelWeights` import (line 401) |
| `backend/config/base.yaml`, `nse_options.yaml`, `mcx_options.yaml`, `feature_flags.yaml`, `live.yaml` | `llm:` blocks, `llm_*` feature flags |
| `backend/app/config_models/*` | `llm_pre_candle_advisory`, `llm_overseer`, `llm_post_trade`, `LLM_EXECUTION_ENABLED`, WARN-5 |
| `quant/decision/context.py` | `llm_direction`, `llm_confidence`, `llm_fresh`, `llm_execution_enabled` fields |
| `quant/decision/decision_service.py`, `result.py` | LLM references in docstrings only |
| `quant/events.py` | `LLMAnalysisProduced` event |
| `frontend/components/ModelStateBanner.tsx` | delete |
| `frontend/components/AIAnalysisPanel.tsx` | re-back to deterministic `quantDecision`/`blockReasons` (no `llm.*`) |
| `frontend/hooks/useServerTradingSystem.ts`, `frontend/App.tsx`, `frontend/types.ts` | strip LLM types/state; panel renders deterministic decision data |
| `.freebuff/run.md` | remove LLM model-selection + retraining sections |

### Keep (not LLM)

- `quant/probability/features.py` (deterministic feature extraction, no model call)
- `quant/amt/*`, `quant/decision/*`, `quant/execution/*`, broker hexagon, market data
- `backend/app/api/routers/analysis.py` **if** it only wraps AMT/footprint (verify; the
  PredictionEngine endpoint lives in `analysis_service.py` which is deleted)

## Behavior after removal

- Engine emits decisions identically (deterministic path never depended on the LLM).
- WS gameloop payloads drop `llm*` fields; frontend panel shows `blockReasons`/decision data.
- `/health/ready` reports `llm: "disabled"` (no model state).
- No `MLX_MODEL_PATH`, `DHAN_*` LLM env, or model artifacts are read at startup.
