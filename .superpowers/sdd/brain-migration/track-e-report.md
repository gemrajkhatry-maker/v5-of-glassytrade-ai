# Track E — Inference & RL cluster → `quant/inference/`

**Status:** COMPLETE
**Worktree:** `/Users/apple/Documents/wt-gt-track-E` (branch `migration/track-E`)
**Verification:** `tests/quant`: **915 passed, 23 skipped** · backend `tests/unit` (with `--continue-on-collection-errors`): **1625 passed, 60 skipped, 4 errors** (the 4 errors are the pre-existing `gymnasium`/`httpx` collection/setup errors; the plain command aborts on the known `test_valentini_rl.py` gymnasium collection error — unchanged from baseline).

## Commits (13, newest first)

| Commit | Message |
| --- | --- |
| `6f5c656` | test(quant): add inference cluster parity tests |
| `27b7f48` | test(quant): port inference/RL unit tests from backend tests |
| `d084542` | refactor(quant): move trainer from backend brain |
| `bda991c` | refactor(quant): move valentini_env from backend brain |
| `f7dd1dc` | refactor(quant): move data_loader from backend brain |
| `7901d49` | refactor(quant): move reward_shaper from backend brain |
| `6c483bc` | refactor(quant): move generative_ai_service from backend brain |
| `709c4cc` | refactor(quant): move learning_engine from backend brain |
| `b7928ad` | refactor(quant): move prediction_engine from backend brain |
| `7c5d346` | refactor(quant): move predictions from backend brain |
| `b631d4e` | refactor(quant): move prompt_builder from backend brain |
| `0209659` | refactor(quant): move llm_contract from backend brain |
| `2ff8a7b` | refactor(quant): move observation from backend brain |

All moves via `git mv`; each moved file verified byte-identical to its legacy source except the intended import rewrites (see diff checks below). Re-export shims left at every legacy path (`from quant.<...> import *  # noqa: F401,F403`).

## Module map

| Legacy path | Moved to |
| --- | --- |
| `services/llm_contract.py` | `quant/inference/llm_contract.py` |
| `services/prompt_builder.py` | `quant/inference/prompt_builder.py` |
| `models/predictions.py` | `quant/inference/models.py` |
| `services/prediction_engine.py` | `quant/inference/prediction.py` |
| `services/learning_engine.py` | `quant/inference/learning_engine.py` |
| `services/generative_ai_service.py` | `quant/inference/generative_ai.py` |
| `rl/reward_shaper.py` | `quant/inference/rl/reward_shaper.py` |
| `rl/data_loader.py` | `quant/inference/rl/data_loader.py` |
| `rl/valentini_env.py` | `quant/inference/rl/valentini_env.py` |
| `rl/trainer.py` | `quant/inference/rl/trainer.py` |
| `models/observation.py` | `quant/amt/models/observation.py` (Track A5 dependency) |

## TODO(migration) legacy imports (sanctioned)

- `quant/inference/rl/valentini_env.py:22-25` — `from app.domain.fabio_ai.services.amt_analyzer import (AMTAnalyzer, AMTConfig, compute_aggression_sigma)` with `# TODO(migration): switch to quant.amt.analyzer once Track A5 merges.` (A5 runs in parallel; amt_analyzer not in this worktree).
- Pre-existing (not mine): `quant/amt/profile/factory.py:17`, `quant/contracts/trading_context.py:24-25`, `quant/contracts/ports/exchange_strategy.py:21`.

Zero-backend-import grep on `quant/` confirms **no other** `import app.`/`from app.` lines.

### Import-rewrite details / deviations
- `prompt_builder.py` TYPE_CHECKING block: `OHLC/AMTResult/FootprintCandle` → `quant.contracts.value_objects`; the `SessionInfo` TYPE_CHECKING import (backend `session_context`, not migrated by any track) was dropped — it is only a postponed annotation (never evaluated at runtime). Behavior unchanged. Noted here so a future track that migrates `session_context` can restore a clean type reference.
- Shims additionally re-export underscore names consumed by legacy importers: `prompt_builder` shim re-exports `_build_narrative_{session_context,market_state,order_flow}` + `_build_core_amt_narrative` (used by `app.domain.probability`); `generative_ai_service` shim re-exports `_DEFAULT_INSTRUCTION` (used by `scripts/dataset_render` tests and `test_prompt_builder`).

## Pydantic decision for `OverseerAction`

**Kept pydantic** (as the brief preferred). `pydantic 2.12.5` imports cleanly in the worktree env (`quant.inference.prompt_builder` imports `from pydantic import BaseModel`). No dataclass conversion performed — zero logic change, matches the brief's "PREFER keeping pydantic".

## Tests ported (`backend/tests/` → `tests/quant/inference/`)

| Ported file | Source |
| --- | --- |
| `test_generative_ai_service.py` | `unit/domain/test_generative_ai_service.py` |
| `test_prompt_builder.py` | `unit/domain/test_prompt_builder.py` |
| `test_prompt_builder_fixes.py` | `unit/domain/test_prompt_builder_fixes.py` |
| `test_prediction_engine.py` | `unit/domain/test_prediction_engine.py` |
| `test_learning_engine.py` | `unit/domain/test_learning_engine.py` |
| `test_data_loader.py` | `unit/domain/test_data_loader.py` |
| `test_valentini_rl.py` | `unit/domain/test_valentini_rl.py` (covers reward_shaper + data_loader + valentini_env + trainer) |

Notes:
- No standalone `llm_contract` unit test exists in the backend; `llm_contract` symbols are exercised via the ported `prompt_builder` tests + parity (`build_entry_prompt` embeds `entry_response_schema_instruction`), and legacy wiring tests (`test_dataset_render.py`, `test_llm_input_contract.py`, `test_overseer_handler.py`) still pass through the shim (verified: 94 passed).
- `test_prediction_engine.py` keeps its pre-existing module-level skip; its `app.infrastructure.adapters.data_generator` dependency was swapped for a local deterministic OHLC generator so the port is self-contained.
- `test_valentini_rl.py` ported wholesale (CVD/profile/session/AMT-analyzer classes still import from legacy `app.domain` — those modules are not in this track's scope and remain in backend). **It is skipped in this env** via `pytest.importorskip("gymnasium")` so `tests/quant` stays collectible (avoids replicating the backend's interrupting collection error).
- Ported suite: **81 passed, 18 skipped** (skips: 7 prediction-engine module skip + 10 prompt_builder_fixes pre-existing class skips + 1 valentini_rl module skip).

## Parity tests

`tests/quant/inference/test_inference_parity.py` (9 tests) via `tests.quant.parity.assert_parity` (legacy shim vs moved module, fixed inputs):
- `build_entry_prompt` (5 fixed dicts × allow_short T/F), `build_overseer_prompt`, `build_advisory_prompt` → identical strings.
- `parse_entry_response` (6 fixed strings incl. JSON / codeblock / structured STATE:/TRADE: / keyword fallback / empty) and `parse_overseer_response` (5 fixed strings) → identical dicts / `OverseerAction`.
- `PredictionEngine.predict` (60-candle series + `ModelWeights`; and the <50-candle insufficient-data path) → identical `PredictionResult` fields.
- `ValentiniRewardShaper.compute` (3 fixed `TradeResult` incl. hit-target, drawdown+hesitation+fighting, breakeven) → identical float.
- `data_loader.split_data` (fixed 100-candle list) → identical counts and slice membership.

### Parity skips (noted)
- `GenerativeAIService.analyze_market` — LLM-adapter dependent; exercised by the ported unit tests with a mock adapter.
- `ValentiniAMTEnv` / `ValentiniTrainer` — need optional `gymnasium` / `stable_baselines3` (absent in this env); modules cannot be imported here. Same for the ported RL tests (skipped via `importorskip`).

## Verification

```bash
cd /Users/apple/Documents/wt-gt-track-E
/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant -q --tb=short
# 915 passed, 23 skipped
cd backend && /Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/unit -q --tb=short
# aborts on pre-existing gymnasium collection error (test_valentini_rl.py) — EXPECTED, unchanged
# with --continue-on-collection-errors: 1625 passed, 60 skipped, 4 errors (gymnasium + httpx only)
```

All listed shim consumers import cleanly: `llm_entry_handler`, `llm_overseer_handler`, `pre_candle_advisor`, `post_trade_analyst`, `rl_handler`, `api/routers/{ai,health,rl}.py`, `composition_root` (GenerativeAIService), `infrastructure/adapters/{mlx,gguf}_inference_adapter.py` (llm_contract), `serialization/schemas.py` (ModelWeights), and `app.domain.probability` (prompt_builder underscore re-exports).

## Concerns

1. **Merge with Track A5 (parallel worktree):** both tracks will touch `quant/amt/models/observation.py`'s neighborhood — A5 imports it; A5's `analyzer.py` will land at `quant/amt/analyzer.py`. `quant/inference/rl/valentini_env.py`'s `# TODO(migration)` must be resolved to `quant.amt.analyzer` on merge. The `quant/amt/models/__init__.py` I created may conflict if A5 also creates it (trivial to resolve).
2. **`session_context` TYPE_CHECKING hint dropped in prompt_builder** — a type-checker only; no runtime effect. Restore when `session_context` is migrated.
3. **RL modules cannot be exercised in this env** (`gymnasium`, `stable_baselines3` missing) — parity skips + `importorskip` in the ported RL test. Once those deps exist, run `tests/quant/inference/test_valentini_rl.py` to exercise the env/trainer.
4. **Backend unit suite stays interrupted** by the pre-existing `test_valentini_rl.py` collection error (unchanged from baseline, not caused by this track).
