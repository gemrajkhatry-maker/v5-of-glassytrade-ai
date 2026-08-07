# P2.4 Report — API layer brain imports (`quant.*`)

## Status
COMPLETE. All brain imports in `backend/app/api/` swapped from legacy `app.domain.*` shim paths to canonical `quant.*` paths. No logic changes. Shims untouched.

## Commit
- `c66663c` — `refactor(backend): api layer imports brain from quant.*` (branch `migration/P24`, worktree `/Users/apple/Documents/wt-gt-P24`)

## Files changed (6)
| File | Swap |
|------|------|
| `backend/app/api/routers/health.py` | `app.domain.fabio_ai.services.llm_contract` → `quant.inference.llm_contract`; `app.domain.probability.features` → `quant.probability.features`; lazy `app.domain.fabio_ai.services.option_scanner` → `quant.amt.session.scanner` |
| `backend/app/api/routers/ai.py` | `app.domain.fabio_ai.services.generative_ai_service` → `quant.inference.generative_ai` |
| `backend/app/api/routers/rl.py` | `app.domain.fabio_ai.rl.{trainer,data_loader,valentini_env}` → `quant.inference.rl.*` (all kept lazy) |
| `backend/app/api/routers/trading.py` | `app.domain.ports.storage` → `quant.contracts.ports.storage` |
| `backend/app/api/routers/market.py` | `app.domain.ports.market_data` → `quant.contracts.ports.market_data` |
| `backend/app/api/websocket/gameloop.py` | `app.domain.trading.models.value_objects` → `quant.contracts.value_objects` |

## Files in brief with no brain imports (no change needed)
- `backend/app/api/routers/analysis.py`
- `backend/app/api/routers/observability.py`
- `backend/app/api/dependencies.py`

## Not swapped (intentional, per recipe)
- `backend/app/api/routers/metrics.py` imports `app.domain.services.{gate_rejection_tracker,latency_tracker}` — these are ops modules that STAY in backend (recipe line 38). Left untouched.

## `# TODO(p2)` fallbacks
None. Every symbol was found at its canonical `quant.*` path (verified by grep: `llm_contract`, `probability.features`, `amt.session.scanner`, `inference.generative_ai`, `inference.rl.{trainer,data_loader,valentini_env}`, `contracts.ports.{storage,market_data}`, `contracts.value_objects`). No `app.*` imports exist anywhere in `quant/`, so no circular-import risk on this track.

## Test counts
Run in worktree root `/Users/apple/Documents/wt-gt-P24`.

- **Backend** (`cd backend && python -m pytest tests/unit -q --tb=short --continue-on-collection-errors`):
  **1324 passed, 60 skipped, 4 errors** in 6.59s.
  - All 4 errors are the pre-existing env failures: 3× httpx (starlette TestClient) in `test_optimizations.py`, 1× gymnasium missing in `test_valentini_rl.py` (reached via the untouched `app.domain.fabio_ai.rl.valentini_env` shim → `quant.inference.rl.valentini_env`). No NEW failures from the swap.
- **Quant** (`python -m pytest tests/quant -q --tb=short`):
  **1448 passed, 30 skipped, 0 errors** in 3.62s.

## Concerns
- `tests/unit/domain/test_valentini_rl.py` error is env-broken (gymnasium not installed); its traceback now flows through the quant canonical module because the legacy shim re-exports from `quant.*`. Expected, matches the pre-existing baseline of "gymnasium + 3 httpx".
- No other concerns.
