# Phase 1 Track E — Inference & RL cluster → `quant/inference/`

**Worktree:** `/Users/apple/Documents/wt-gt-track-E` (branch `migration/track-E`). Do ALL work inside this worktree. Commit there. Do NOT touch `/Users/apple/Documents/v5-of-glassytrade-ai`.

**From:** docs/superpowers/plans/2026-08-06-quant-brain-migration.md — Phase 1, Track E. Recipe: `git mv` → rewrite imports → shim → port tests → parity → suites → commit `refactor(quant): move <module> from backend brain`.

**Modules to move (leaf-first):**
1. `backend/app/domain/fabio_ai/services/llm_contract.py` → `quant/inference/llm_contract.py`
2. `backend/app/domain/fabio_ai/services/prompt_builder.py` → `quant/inference/prompt_builder.py` (904 lines, pure string rendering; imports `llm_contract` → `quant.inference.llm_contract`; `trading.enums` → `quant.contracts.enums`; has pydantic `OverseerAction` — keep pydantic (it is already a dependency in the project) OR convert to a plain dataclass with identical fields; PREFER keeping pydantic to avoid logic change — verify `pydantic` imports cleanly in the worktree's env)
3. `backend/app/domain/fabio_ai/models/predictions.py` → `quant/inference/models.py` (exports `ModelWeights`, `FactorBreakdown`, `PredictionResult`, `AIAnalysisResult`)
4. `backend/app/domain/fabio_ai/services/prediction_engine.py` → `quant/inference/prediction.py` (imports `models.predictions` → `quant.inference.models`)
5. `backend/app/domain/fabio_ai/services/learning_engine.py` → `quant/inference/learning_engine.py` (imports `models.predictions` → `quant.inference.models`)
6. `backend/app/domain/fabio_ai/services/generative_ai_service.py` → `quant/inference/generative_ai.py` (imports `ports.llm_inference` → `quant.contracts.ports.llm_inference`; `prompt_builder` → `quant.inference.prompt_builder`)
7. `backend/app/domain/fabio_ai/rl/reward_shaper.py` → `quant/inference/rl/reward_shaper.py`
8. `backend/app/domain/fabio_ai/rl/data_loader.py` → `quant/inference/rl/data_loader.py`
9. `backend/app/domain/fabio_ai/rl/valentini_env.py` → `quant/inference/rl/valentini_env.py` (imports `amt_analyzer.AMTAnalyzer` + `models.observation.AMTObservation` + `reward_shaper`)
10. `backend/app/domain/fabio_ai/rl/trainer.py` → `quant/inference/rl/trainer.py` (imports `rl.valentini_env`, `rl.data_loader.split_data`)

**Sanctioned cross-track legacy imports (Track A5 runs in PARALLEL — amt_analyzer is NOT in this worktree yet):**
- `valentini_env.py`: keep `from app.domain.fabio_ai.services.amt_analyzer import AMTAnalyzer` (or its lazy import) with `# TODO(migration): switch to quant.amt.analyzer once Track A5 merges`.
- `valentini_env.py`/`trainer.py` need `AMTObservation` — it lives at `backend/app/domain/fabio_ai/models/observation.py`. Move `observation.py` → `quant/amt/models/observation.py` in THIS track (it is small, pure, and A5 will import it), then rewrite the import to `quant.amt.models.observation`. (A5's brief already expects `quant/amt/models/observation.py`.)

**Import-rewrite map:**
- `app.domain.trading.models.*` → `quant.contracts.*`
- `app.domain.constants` → `quant.contracts.constants`
- `app.domain.ports.<x>` → `quant.contracts.ports.<x>`
- `app.domain.fabio_ai.services.llm_contract` → `quant.inference.llm_contract`
- `app.domain.fabio_ai.services.prompt_builder` → `quant.inference.prompt_builder`
- `app.domain.fabio_ai.models.predictions` → `quant.inference.models`
- `app.domain.fabio_ai.services.prediction_engine` → `quant.inference.prediction`
- `app.domain.fabio_ai.services.learning_engine` → `quant.inference.learning_engine`
- `app.domain.fabio_ai.services.generative_ai_service` → `quant.inference.generative_ai`
- `app.domain.fabio_ai.models.observation` → `quant.amt.models.observation`
- `app.domain.fabio_ai.rl.<x>` → `quant.inference.rl.<x>`

**Shims** at each legacy path: `from quant.inference.<name> import *  # noqa: F401,F403` (and `rl/__init__`-style shims if any exist). Consumers that must keep working via shims: `llm_entry_handler.py`, `llm_overseer_handler.py`, `pre_candle_advisor.py`, `post_trade_analyst.py`, `rl_handler.py`, `api/routers/{ai,health,rl}.py`, `composition_root.py` (GenerativeAIService), `infrastructure/adapters/{mlx,gguf}_inference_adapter.py` (llm_contract), `serialization/schemas.py` (ModelWeights).

**Tests to port** (from `backend/tests/`; port ALL hits): generative_ai_service, prompt_builder, prediction_engine, learning_engine, llm_contract, valentini_env, trainer, reward_shaper, data_loader → `tests/quant/inference/`.

**Parity tests** via `assert_parity` (legacy shim vs moved) on fixed inputs:
- `prompt_builder.build_entry_prompt` / `build_overseer_prompt` / `build_advisory_prompt`: fixed dicts → assert identical strings.
- `parse_entry_response` / `parse_overseer_response`: fixed JSON/plain-text strings.
- `prediction_engine.PredictionEngine.predict`: fixed OHLC list + `ModelWeights` → assert identical `PredictionResult` fields.
- `reward_shaper.compute`: fixed `TradeResult`.
- `data_loader.split_data`: fixed count.
Skip parity for anything needing a loaded LLM model or `gymnasium` (those need optional deps) — note the skips.

**Verification (after EACH module):**
```bash
cd /Users/apple/Documents/wt-gt-track-E
/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant -q --tb=short
cd backend && /Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/unit -q --tb=short
```
(`gymnasium`/`httpx` collection errors are pre-existing and unchanged — the `test_valentini_rl.py` file may fail to collect in this env; that is expected.)

**Zero-backend-import rule:** `grep -rn "import app\.\|from app\." quant/ --include=*.py` → allowed: `valentini_env.py`'s `amt_analyzer` `# TODO(migration)` (Track A5), plus Track-A5's existing `quant/amt/profile/factory.py` TODO on stable_4. Nothing else new.

**Report:** write to `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/track-e-report.md` (commit hashes, TODO imports, parity skips, the pydantic decision for OverseerAction). Reply: status, commits, one-line test summary, concerns.
