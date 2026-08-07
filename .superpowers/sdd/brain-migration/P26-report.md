# Phase 2 — P2.6 Track Report: DI + config

**Worktree:** `/Users/apple/Documents/wt-gt-P26` (branch `migration/P26`)
**Commit:** `7908647` — `refactor(backend): di + config import brain from quant.*`
**Status:** COMPLETE

## Files changed

- `backend/app/application/di/composition_root.py` — swapped all brain imports:
  - `app.domain.ports.{market_data,broker,storage,llm_inference,probability_inference,notifications,delta_profile,npoc,exchange_strategy}` → `quant.contracts.ports.*`
  - `app.domain.fabio_ai.services.gate_pipeline` → `quant.decision.gates.legacy_gate_pipeline` (wires `GatePipeline` singleton in `_gate_pipeline()` / `_create_gate_pipeline`)
  - `app.domain.fabio_ai.services.generative_ai_service` → `quant.inference.generative_ai` (wires `GenerativeAIService` singleton in `_generative_ai_service()` / `_create_generative_ai_service`)
  - `app.domain.models.exchange_config` → `quant.contracts.exchange_config`
  - Kept STAY per recipe: `app.domain.models.exchange`, `app.domain.services.{gate_rejection_tracker,latency_tracker}`
- `backend/app/main.py` — swapped top-level `app.domain.ports.*` → `quant.contracts.ports.*`, `app.domain.fabio_ai.services.generative_ai_service` → `quant.inference.generative_ai`, and lazy `option_scanner` import → `quant.amt.session.scanner`. Kept STAY per recipe: `app.domain.services.startup_reconciliation`.
- `backend/app/application/di/container.py` — no brain imports; no change.
- `backend/app/config_models/settings_adapter.py` — no brain imports; no change.
- `backend/app/config.py` — no brain imports; no change.

Shims NOT deleted (per recipe, Phase 3 deletes them).

## Circular-import fallbacks (`# TODO(p2)`)

None. All canonical modules verified import-free of `app.*` (grepped `quant.contracts.ports/*`, `quant/decision/gates/legacy_gate_pipeline.py`, `quant/inference/generative_ai.py`, `quant/contracts/exchange_config.py`, `quant/amt/session/scanner.py` and all package `__init__` files). A full smoke test importing `app.main` (which runs `create_application()` → `compose_container()` → resolves the entire DI graph, building `GatePipeline` and `GenerativeAIService` singletons) completed without circular imports.

## Verification (recipe commands)

**Backend unit tests** (`backend`: `pytest tests/unit -q --tb=short --continue-on-collection-errors`):
- **1324 passed, 60 skipped, 4 errors**
- The 4 errors are the pre-existing env errors (1 gymnasium in `tests/unit/domain/test_valentini_rl.py` + 3 httpx in `tests/unit/test_optimizations.py`). No new failures.

**Quant tests** (worktree root: `pytest tests/quant -q --tb=short`):
- **1448 passed, 30 skipped, 0 errors**

## Concerns

- `quant.contracts.ports.storage` defines `IStorage` as a multi-interface composite; the backend `app.domain.ports.storage` shim re-exports it via `*`, so identity/behavior is unchanged.
- `composition_root.py` swaps are all inside lazy function-level getters/factories, so no startup-order risk; `main.py` top-level swaps are safe since quant never imports `app.*`.
