# Remove the LLM / AI-Inference Layer — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove the LLM advisory layer, `PredictionEngine`, and RL training from GlassyTrade AI with zero change to the deterministic Fabio decision engine.

**Architecture:** Delete `quant/inference/` and the AI routers/services; strip LLM wiring from the engine (`quant/runtime.py`, `quant/coordinator.py`), backend composition root, storage, and configs; re-back the frontend panel to the deterministic decision stream. Tasks are ordered so each leaves all four test suites (root `tests/`, `backend/tests/`, `brokers/tests/`, frontend vitest) green.

**Tech Stack:** Python 3.13, FastAPI, SQLite, React/Vite, pytest, vitest.

## Global Constraints

- The deterministic decision path (`quant/decision/*`, `quant/runtime.py` gates, SignalBuilder, PaperOMS) must be byte-identical in behavior — only LLM code is removed.
- Every task ends with its test suite green.
- All removed modules are deleted with `rm`, never stubbed — except where the spec says "strip" (keep file, remove LLM parts).
- `quant/probability/features.py` is NOT LLM — keep it.
- Do not touch `brokers/` (no LLM there).
- Run tests with the project venv: `PYTHONPATH=backend:. .venv/bin/python -m pytest <path>`, frontend via `cd frontend && node node_modules/.bin/vitest run`.

---

### Task 0: Baseline verification

**Files:**
- (none modified)

- [ ] **Step 1: Verify current suite health**

Run:
```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/ -q 2>&1 | tail -3
cd backend && PYTHONPATH=..:. ../.venv/bin/python -m pytest tests/unit tests/runtime_validation -q 2>&1 | tail -3
cd brokers && PYTHONPATH=..:. ../.venv/bin/python -m pytest tests/ -q 2>&1 | tail -3
cd frontend && node node_modules/.bin/vitest run 2>&1 | tail -3
```
Expected: all pass (root ~1055, backend ~1000, brokers ~439, frontend ~160). Record counts.

- [ ] **Step 2: Confirm branch**

Run: `git branch --show-current`
Expected: `stable_5`.

- [ ] **Step 3: Commit (if changes exist)**

```bash
git add -A && git commit -m "chore: baseline before LLM-layer removal"
```

---

### Task 1: Delete `quant/inference/` + its tests + LLM scripts

**Files:**
- Delete: `quant/inference/` (whole directory)
- Delete: `tests/quant/inference/` (whole directory)
- Delete: `backend/scripts/generate_mcx_data.py`, `backend/scripts/eval_lfm.py`, `backend/scripts/dataset_render.py`
- Delete: `backend/tests/unit/domain/test_generative_ai_service.py`, `test_prompt_builder.py`, `test_prompt_builder_fixes.py`, `test_prediction_engine.py`
- Delete: `backend/tests/unit/infrastructure/test_mlx_inference_adapter.py`
- Delete: `backend/tests/unit/scripts/test_dataset_render.py`
- Test: run full suites

- [ ] **Step 1: Delete the directories and files**

```bash
rm -rf quant/inference tests/quant/inference
rm backend/scripts/generate_mcx_data.py backend/scripts/eval_lfm.py backend/scripts/dataset_render.py
rm backend/tests/unit/domain/test_generative_ai_service.py backend/tests/unit/domain/test_prompt_builder.py backend/tests/unit/domain/test_prompt_builder_fixes.py backend/tests/unit/domain/test_prediction_engine.py
rm backend/tests/unit/infrastructure/test_mlx_inference_adapter.py backend/tests/unit/scripts/test_dataset_render.py
```

- [ ] **Step 2: Find remaining importers of the deleted modules**

```bash
grep -rn "quant.inference\|from quant import inference" --include="*.py" quant/ backend/ tests/ 2>/dev/null | grep -v __pycache__ | grep -v graphify-out
```
Expected: matches only in files that Tasks 2–4 strip (runtime.py, coordinator.py, main.py, composition_root.py, ai.py, rl.py, analysis_service.py, health.py, schemas.py, ai_command_service.py). Do NOT fix them here — later tasks handle each. If any OTHER file imports, note it.

- [ ] **Step 3: Run root tests to confirm no surprise importers break collection**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/ -q --co 2>&1 | tail -5`
Expected: collection succeeds (some tests may import LLM modules at runtime — those failures surface in Task 2/3).

- [ ] **Step 4: Commit**

```bash
git add -A && git commit -m "refactor: delete quant/inference cluster, LLM scripts, and their tests"
```

---

### Task 2: Strip LLM from the engine and coordinator

**Files:**
- Modify: `quant/runtime.py`
- Modify: `quant/coordinator.py`
- Modify: `quant/events.py`
- Modify: `quant/decision/context.py`
- Test: `tests/quant/runtime/`, `tests/quant/test_coordinator.py`, `tests/quant/decision/`, `tests/test_fabio_alignment.py`

**Interfaces:**
- Consumes: none (removal)
- Produces: `QuantEngine(inference=None, llm_history=None, llm_consensus_gate=None)` signature becomes `QuantEngine()` with no LLM params; `DecisionContext` loses `llm_direction`/`llm_confidence`/`llm_fresh`/`llm_execution_enabled`; `LLMAnalysisProduced` event removed from `quant/events.py`.

- [ ] **Step 1: Strip `quant/runtime.py`**

Remove every symbol in this list (verified present): `_llm_executor`, `_schedule_llm`, `_llm_instruction`, `_llm_input`, `_llm_consensus_state`, `_inference_loading`, `_last_llm_bar_index`, `_llm_state_lock`, `_llm_entry_temperature`, `_llm_execution_enabled`, `llm_history` init param, `llm_consensus_gate` param, the `self._inference is not None` block in `_on_bar_closed`, and the `llm_direction=...`/`llm_confidence=...`/`llm_fresh=...`/`llm_execution_enabled=...` kwargs in the `_decide` context construction.

- [ ] **Step 2: Strip `quant/coordinator.py`**

Remove: `inference=None` param, `llm_sink`, `history_loader`, `llm_history()` method, `_on_llm_analysis`, `LLMAnalysisProduced` subscription, and the `inference=self.inference`/`llm_history=...` kwargs when constructing engines.

- [ ] **Step 3: Strip `quant/events.py`**

Remove the `LLMAnalysisProduced` event class.

- [ ] **Step 4: Strip `quant/decision/context.py`**

Remove fields `llm_direction`, `llm_confidence`, `llm_fresh`, `llm_execution_enabled` and their comment block. Update the docstring.

- [ ] **Step 5: Update `tests/quant/runtime/test_llm_hook.py`**

Rewrite the file to assert the engine emits decisions WITHOUT any LLM: rename to `test_no_llm_hook.py` (delete old), assert `QuantEngine()` constructs with no LLM params and `_decide` produces a decision purely from auction state. Replace LLM assertions with `assert not hasattr(engine, "_llm_executor")`.

- [ ] **Step 6: Run the affected suites**

Run:
```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/runtime tests/quant/test_coordinator.py tests/quant/decision tests/test_fabio_alignment.py -q 2>&1 | tail -5
```
Fix any residual references until green.

- [ ] **Step 7: Commit**

```bash
git add -A && git commit -m "refactor: strip LLM advisory wiring from QuantEngine, coordinator, and decision context"
```

---

### Task 3: Strip LLM from the backend (routers, DI, storage, configs)

**Files:**
- Delete: `backend/app/api/routers/ai.py`, `backend/app/api/routers/rl.py`
- Delete: `backend/app/application/services/ai_command_service.py`, `backend/app/application/services/analysis_service.py`
- Delete: `backend/app/infrastructure/adapters/gguf_inference_adapter.py`
- Modify: `backend/app/main.py`
- Modify: `backend/app/application/di/composition_root.py`
- Modify: `backend/app/api/routers/health.py`
- Modify: `backend/app/infrastructure/storage/database.py`
- Modify: `backend/app/infrastructure/serialization/schemas.py`
- Modify: `backend/app/config_models/loader.py`, `__init__.py`, `settings_adapter.py`, `validator.py`
- Modify: `backend/config/base.yaml`, `feature_flags.yaml`, `environments/live.yaml`, `strategies/nse_options.yaml`, `strategies/mcx_options.yaml`
- Modify: `backend/app/api/dependencies.py`
- Test: backend unit + integration (non-live)

- [ ] **Step 1: Delete routers/services/adapters**

```bash
rm backend/app/api/routers/ai.py backend/app/api/routers/rl.py
rm backend/app/application/services/ai_command_service.py backend/app/application/services/analysis_service.py
rm backend/app/infrastructure/adapters/gguf_inference_adapter.py
```

- [ ] **Step 2: Strip `backend/app/main.py`**

Remove: `from quant.contracts.ports.llm_inference import ILLMInference`, `from quant.inference.generative_ai import GenerativeAIService`, the `GenerativeAIService(llm_adapter=...)` init (pass nothing / remove arg), the AI router `include_router` lines. Keep `ai_history`/history endpoints only if they serve deterministic decisions — otherwise remove.

- [ ] **Step 3: Strip `composition_root.py`**

Remove: `_llm_inference_port()`, `NullLLMInference`, `_create_llm_adapter`, the `container.register_singleton(_llm_inference_port(), ...)` line, and the `ILLMInference` resolve/except block in `_create_quant_coordinator` (set `inference=None` — the engine no longer accepts it anyway).

- [ ] **Step 4: Strip `health.py`**

Remove `from quant.inference.llm_contract import ...` and the LLM readiness check from the health payload; report `"llm": "disabled"`.

- [ ] **Step 5: Strip storage `database.py`**

Remove the `llm_decisions` CREATE TABLE, `idx_llm_created` index, `save_llm_decision`, `query_llm_decisions`, and the `llm_analysis` column from the analysis table (verify the column isn't written elsewhere first).

- [ ] **Step 6: Strip schemas + configs**

Remove `from quant.inference.models import ModelWeights` from `schemas.py`; remove `llm:` blocks and `llm_*` flags from all listed YAMLs; remove `llm_pre_candle_advisory`/`llm_overseer`/`llm_post_trade` from `config_models/loader.py` `FeatureFlags` and `settings_adapter.py` properties; remove WARN-5 from `validator.py`.

- [ ] **Step 7: Fix backend tests**

Update: `backend/tests/unit/api/test_runtime_contracts.py`, `test_coordinator_endpoints.py` (drop AI/RL endpoint tests), `backend/tests/integration/test_frontend_integration.py` (TestAIHistory → assert deterministic history or remove), `test_schemas_serialization.py` (ModelWeights references), `backend/tests/unit/application/test_llm_consistency_guard.py` (delete — tests deleted gate), `test_trade_journal.py` (LLM rows).

- [ ] **Step 8: Run backend suites**

Run:
```bash
cd backend && PYTHONPATH=..:. ../.venv/bin/python -m pytest tests/unit tests/runtime_validation tests/integration -q --ignore=tests/integration/test_dhan_live.py 2>&1 | tail -5
```
Fix until green.

- [ ] **Step 9: Commit**

```bash
git add -A && git commit -m "refactor: remove LLM routers, services, storage, and config from backend"
```

---

### Task 4: Frontend — re-back panel to deterministic stream, delete model banner

**Files:**
- Delete: `frontend/components/ModelStateBanner.tsx`
- Modify: `frontend/components/AIAnalysisPanel.tsx` (render `quantDecision`/`blockReasons`, no `llm.*`)
- Modify: `frontend/components/ai/DecisionHistoryPanel.tsx`
- Modify: `frontend/hooks/useServerTradingSystem.ts` (drop llm state fields)
- Modify: `frontend/App.tsx`, `frontend/types.ts`, `frontend/stores/ui.ts`
- Test: `cd frontend && node node_modules/.bin/vitest run`

- [ ] **Step 1: Remove LLM fields from types and state**

In `frontend/types.ts` and `useServerTradingSystem.ts`, delete `llmDirection`/`llmConfidence`/`llmFresh`/`modelState`/`llm*` fields.

- [ ] **Step 2: Re-back AIAnalysisPanel**

Panel now consumes the deterministic decision (`approved`, `signal`, `reason`, `block_reasons`, `phase`) already emitted as `quantDecision`. Remove LLM-narrative rendering; show gate results and block reasons.

- [ ] **Step 3: Delete ModelStateBanner**

Remove the component and its import in `App.tsx`.

- [ ] **Step 4: Update frontend tests**

Update `frontend/tests/components/AIAnalysisPanel.test.tsx`, `frontend/tests/hooks/useServerTradingSystem.test.tsx`, `frontend/tests/components/ai/*` for the deterministic payloads.

- [ ] **Step 5: Run vitest**

Run: `cd frontend && node node_modules/.bin/vitest run 2>&1 | tail -5`
Fix until green.

- [ ] **Step 6: Commit**

```bash
git add -A && git commit -m "refactor: frontend panel consumes deterministic decision stream, drop LLM UI"
```

---

### Task 5: Full verification + docs

**Files:**
- Modify: `.freebuff/run.md` (remove LLM model-selection + retraining sections)
- Modify: `PRINCIPAL_REVIEW.md` (note the LLM layer is gone)
- Test: all four suites

- [ ] **Step 1: Sweep for residual LLM references in code (not docs)**

```bash
grep -rn "quant.inference\|ILLMInference\|GenerativeAIService\|llm_decisions\|_schedule_llm\|LLMAnalysisProduced\|MLXInferenceAdapter\|PredictionEngine\|ValentiniTrainer" --include="*.py" --include="*.ts" --include="*.tsx" quant/ backend/ frontend/ tests/ 2>/dev/null | grep -v __pycache__ | grep -v graphify-out
```
Expected: no matches. If matches remain in code, fix them.

- [ ] **Step 2: Update run doc and review doc**

Remove the LLM sections from `.freebuff/run.md`; note removal in `PRINCIPAL_REVIEW.md`. Also fix the stale comment in `quant/decision/result.py:7-8` (it says "the LLM stays advisory-only" — after removal it should say the LLM layer was deleted entirely).

- [ ] **Step 3: Run all four suites**

Run (expect green):
```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/ -q 2>&1 | tail -3
cd backend && PYTHONPATH=..:. ../.venv/bin/python -m pytest tests/unit tests/runtime_validation tests/integration -q --ignore=tests/integration/test_dhan_live.py 2>&1 | tail -3
cd brokers && PYTHONPATH=..:. ../.venv/bin/python -m pytest tests/ -q 2>&1 | tail -3
cd frontend && node node_modules/.bin/vitest run 2>&1 | tail -3
```

- [ ] **Step 4: Smoke-test the app boots**

Run the backend (paper, NSE) per `.freebuff/run.md` and confirm `/health/ready` returns `"llm": "disabled"` and the scanner/WS come up with 4 symbols.

- [ ] **Step 5: Commit**

```bash
git add -A && git commit -m "docs: reflect LLM-layer removal in run doc and principal review"
```

---

## Execution Handoff

After the plan is approved, two execution options:

**1. Subagent-Driven (recommended for the multi-agent team you asked for)** — dispatch a fresh agent per task (Tasks 1–5 are independent enough that 1–3 can run in parallel after Task 0), review between tasks.

**2. Inline Execution** — run tasks in this session with superpowers:executing-plans.
