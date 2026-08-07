# Task 0.2 Report — Move shared models + ports into `quant/contracts/` (with shims)

**Status:** DONE_WITH_CONCERNS

## Commit

- `13735e1f50af1a1a4ca18abc48b700930d20d53d` — `refactor(quant): move trading models + ports into quant/contracts`
  (single commit for the whole batch, per brief)
- No `.superpowers/` or `docs/superpowers/plans/` files included in the commit (un-staged pre-existing scratch before committing).

## Files moved → target

| # | Legacy path (now a shim) | Target |
|---|---|---|
| 1 | `backend/app/domain/trading/models/enums.py` | `quant/contracts/enums.py` |
| 2 | `backend/app/domain/trading/models/value_objects.py` | `quant/contracts/value_objects.py` |
| 3 | `backend/app/domain/constants.py` | `quant/contracts/constants.py` |
| 4 | `backend/app/domain/trading/models/utils.py` | `quant/contracts/utils.py` |
| 5 | `backend/app/domain/trading/models/volume_profile.py` | `quant/contracts/volume_profile_models.py` |
| 6 | `backend/app/domain/trading/models/vwap_bands.py` | `quant/contracts/vwap_bands.py` |
| 7 | `backend/app/domain/trading/models/cvd.py` | `quant/contracts/cvd.py` |
| 8 | `backend/app/domain/trading/models/initial_balance.py` | `quant/contracts/initial_balance.py` |
| 9 | `backend/app/domain/fabio_ai/services/exit_signal.py` | `quant/execution/exit_signal.py` |
| 10 | `backend/app/domain/fabio_ai/services/exit_rules.py` | `quant/execution/exit_rules.py` |
| 11 | `backend/app/domain/trading/models/entities.py` | `quant/contracts/entities.py` |
| 12 | `backend/app/domain/trading/models/aggregates.py` | `quant/contracts/aggregates.py` |
| 13 | `backend/app/domain/trading/models/trading_context.py` | `quant/contracts/trading_context.py` |
| 14 | `backend/app/domain/trading/events.py` | `quant/contracts/events.py` |
| 15 | `backend/app/domain/trading/event_store.py` | `quant/contracts/event_store.py` |
| 16 | `backend/app/domain/models/exchange_config.py` | `quant/contracts/exchange_config.py` |
| 17 | every `backend/app/domain/ports/*.py` (11 modules + `__init__.py`) | `quant/contracts/ports/<same>.py` |
| 18 | `backend/app/shared/timezones.py` | `quant/contracts/timezones.py` |
| 19 | `backend/app/domain/services/decimal_utils.py` | `quant/contracts/decimal_utils.py` |
| 20 | `backend/app/domain/services/tick_utils.py` | `quant/contracts/tick_utils.py` |
| 21 | `backend/app/domain/services/market_data_utils.py` | `quant/contracts/market_data_utils.py` |
| 22 | `backend/app/domain/services/candle_metrics.py` | `quant/contracts/candle_metrics.py` |

Every legacy path above is a re-export shim:
```python
"""Re-export shim — moved to <quant target>. Delete after importers switch (Phase 3)."""
from quant.<target> import *  # noqa: F401,F403
```
`quant/contracts/ports/__init__.py` re-exports all port modules and defines `__all__` mirroring the legacy `app.domain.ports` namespace; the legacy `backend/app/domain/ports/__init__.py` is itself a shim (`from quant.contracts.ports import *` + `__all__`).

No logic was changed in any moved file except `constants.py` (see Surprises). Diff verification: every moved file differs from its `HEAD` original ONLY on the import lines (verified via `git show HEAD:<src> | diff - <target>`).

## Ported tests (added to quant, backend copies left in place)

- `tests/quant/contracts/` ← `backend/tests/unit/domain/test_entities.py`, `test_aggregates.py`, `test_value_objects.py`, `test_trading_context.py` (from `tests/unit/`), `tests/unit/domain/trading/models/test_cvd.py`, `tests/unit/test_side_normalize.py`, `tests/unit/domain/test_phase4_enums.py`, `tests/unit/domain/test_event_store.py`
- `tests/quant/execution/test_exit_rules.py` ← `backend/tests/unit/domain/test_exit_rules.py`

Notes on porting:
- `test_value_objects.py` imported `ModelWeights, FactorBreakdown, AIAnalysisResult` from `app.domain.fabio_ai.models.predictions`; that module only re-exports from `value_objects`, so the quant copy imports them from `quant.contracts.value_objects`.
- `backend/tests/unit/domain/test_volume_profile.py` and `test_vwap_bands.py` were NOT ported: they exercise unmoved backend code (`app.domain.services.volume_profile`, `AMTAnalyzer`), not the moved value objects.
- No `test_constants*.py` / `test_exit_signal*.py` / dedicated `initial_balance` or `utils` model tests exist in the backend to port.

## Zero-backend-import proof

Brief's exact command (quoted `--include` for zsh):
```bash
$ grep -rn "import app\.\|from app\." quant/contracts quant/execution/exit_signal.py quant/execution/exit_rules.py --include='*.py'
quant/contracts/trading_context.py:24:    from app.domain.fabio_ai.services.session_context import SessionInfo  # TODO(migration)
quant/contracts/trading_context.py:25:    from app.domain.probability.agent_pipeline import AgentDecision  # TODO(migration)
quant/contracts/ports/exchange_strategy.py:21:    from app.domain.services.symbol_registry import SymbolRegistry  # TODO(migration)
```
All three are lazy `if TYPE_CHECKING:` imports annotated `# TODO(migration)` — the brief's explicit exceptions. No runtime `app.*` imports anywhere in the moved code.

## Test output tails

Backend unit (`backend/`, run after final state):
```
=========================== short test summary info ============================
ERROR tests/unit/test_optimizations.py::TestDebugMemoryEndpoint::test_memory_endpoint_returns_rss
ERROR tests/unit/test_optimizations.py::TestDebugMemoryEndpoint::test_memory_endpoint_returns_gc_stats
ERROR tests/unit/test_optimizations.py::TestDebugMemoryEndpoint::test_memory_endpoint_returns_gc_objects
================== 1747 passed, 61 skipped, 3 errors in 5.49s ==================
```
(Identical to the pre-change baseline: 1747 passed / 61 skipped / 3 errors. The 3 errors are pre-existing `httpx`-missing env issues in `test_optimizations.py`, unchanged by this task. `tests/unit/domain/test_valentini_rl.py` also fails collection pre-existing — missing `gymnasium` — and was `--ignore`d, same as baseline.)

Quant (`repo root`):
```
278 passed in 1.65s
```
(146 pre-existing quant tests + 132 newly ported tests.)

Per-move backend spot checks: the full backend unit suite was run after each logical group (enums/value_objects/constants; utils→initial_balance; exit_signal/exit_rules; entities/aggregates/trading_context; events/event_store/exchange_config; ports; timezones+tick_utils+market_data_utils+candle_metrics) and stayed at the baseline 1747-passed result throughout.

## Surprises & resolutions

1. **`constants.py` config path breaks on move (the only logic change).** `_load_globals_dict()` computes `config_dir` from `os.path.dirname(__file__)`. After the move to `quant/contracts/`, `../../config` resolves to the repo-root `config/` (which has no `base.yaml`), so every `_get()` would silently fall back to hardcoded defaults — and YAML differs from defaults for `lvn_min_persistence_bars` (3 vs 1) and `lvn_removal_threshold` (0.30 vs 0.50). To keep the backend behavior identical through the shim, I changed the path to `os.path.join(os.path.dirname(__file__), "..", "..", "backend", "config")` with an explanatory comment. This is the single deviation from "only import rewrites", and it is required to preserve constant values. Verified at runtime: `LVN_MIN_PERSISTENCE_BARS=3`, `LVN_REMOVAL_THRESHOLD=0.3` (from YAML, not defaults). Flagged as a future cleanup (Phase 3 should move config into `quant`).

2. **`entities.py` (move #11) depends on `decimal_utils` (move #19).** The brief's order puts entities before decimal_utils, but `quant/contracts/entities.py` needs `quant.contracts.decimal_utils.to_decimal` at import time. Moved `decimal_utils.py` ahead of schedule (with the rest of the batch) — no conflict, just out of the nominal order.

3. **`ports/exchange_strategy.py` imports `SymbolRegistry`, which is not in the move list.** `SymbolRegistry` is used only in a type annotation (module already has `from __future__ import annotations`, and `from app.domain.services.symbol_registry import SymbolRegistry` was only referenced there). Moved it under `if TYPE_CHECKING:` with `# TODO(migration)` so the moved module has zero runtime backend imports; it resolves once `symbol_registry` migrates in Phase 3.

4. **Test porting required import-target surgery.** Several "model" test files were actually exercising unmoved backend code (`test_volume_profile.py`, `test_vwap_bands.py`) and were not portable; `test_value_objects.py` needed `fabio_ai.models.predictions` → `quant.contracts.value_objects` since predictions merely re-exports.

5. **Pre-existing environment failures are unrelated to this task.** `gymnasium` (test_valentini_rl collection) and `httpx` (3 test_optimizations errors) are missing from the `amt_313` env and fail identically before and after the change.
