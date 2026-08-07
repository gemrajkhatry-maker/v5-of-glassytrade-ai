# P2.3 — Engine & Orchestrators: Import Swap Report

**Worktree:** `/Users/apple/Documents/wt-gt-P23` (branch `migration/P23`)
**Date:** 2026-08-06

## Status
Complete. All brain imports swapped from `app.domain.*` / `app.shared.*` shim paths to canonical `quant.*` paths. No logic changes. No shims deleted. No circular-import fallbacks required.

## Commit
- `b51c49a` — `refactor(backend): engine + orchestrators import brain from quant.*`

## Files changed (5)
| File | Swap |
|---|---|
| `backend/app/application/engine.py` | `value_objects` → `quant.contracts.value_objects` (module + lazy); `ports.market_data` → `quant.contracts.ports.market_data`; `ports.broker` → `quant.contracts.ports.broker`; `shared.timezones` → `quant.contracts.timezones` (module + lazy); `underlying_futures_provider` → `quant.amt.session.futures_provider` (lazy) |
| `backend/app/application/candle_aggregator.py` | `value_objects` → `quant.contracts.value_objects`; `footprint_analyzer` → `quant.amt.orderflow.footprint`; `tick_delta` → `quant.amt.orderflow.tick_delta`; `shared.timezones` → `quant.contracts.timezones` |
| `backend/app/application/watchdog_manager.py` | `trading.models.utils safe_side` → `quant.contracts.utils safe_side`; `shared.timezones` → `quant.contracts.timezones` |
| `backend/app/application/utils.py` | `shared.timezones` → `quant.contracts.timezones` |
| `backend/app/application/services/session_orchestrator.py` | `domain.constants AGENT_DECISION_THRESHOLD` → `quant.contracts.constants` |

`backend/app/application/services/session_runtime_contracts.py` was inspected — it has **no brain imports**, so no changes were made.

`backend/app/application/services/trading_query_service.py` was **not touched** — it belongs to P2.1 (explicitly listed in that brief), not this track.

## Kept as legacy / STAY (per recipe)
- `app.domain.services.position_reconciliation` — ops module, stays in backend (recipe rule).
- `app.shared.mode`, `app.core.async_boundary`, `app.config`, `app.application.*`, `app.infrastructure.*` — backend modules, unchanged.

## `# TODO(p2)` fallbacks
**None.** Verified `quant` never imports `app.*` (0 matches in `grep -rn "from app\." quant`), so no swap creates a circular import. No unmigrated `app.domain.fabio_ai.strategy.*` symbols were used by these files.

## Verification (recipe commands)
Backend unit suite:
```
cd backend
python -m pytest tests/unit -q --tb=short --continue-on-collection-errors
1324 passed, 60 skipped, 4 errors
```
The 4 errors are the pre-existing environment errors (gymnasium missing in `tests/unit/domain/test_valentini_rl.py` + 3 httpx/starlette TestClient errors in `tests/unit/test_optimizations.py`). No new failures.

Quant suite:
```
python -m pytest tests/quant -q --tb=short
1448 passed, 30 skipped
```

`py_compile` on all 6 files: OK.

## Concerns
- None. Diff is strictly import-path changes (15 insertions / 15 deletions), all mapped per the recipe's canonical map.
