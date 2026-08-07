# P2.1 — Application services: brain import swap report

**Track:** P2.1 — `backend/app/application/services/*`
**Worktree:** `/Users/apple/Documents/wt-gt-P21` (branch `migration/P21`)
**Status:** ✅ Complete

## Commit

- `f64f0fa` — `refactor(backend): application services import brain from quant.*` (15 files, +84/-84, import paths only)

## Files changed (15)

`amt_service.py`, `analysis_service.py`, `entry_coordinator.py`, `exit_coordinator.py`,
`session_event_router.py`, `session_phase_manager.py`, `session_risk_coordinator.py`,
`session_state_manager.py`, `phase_manager.py`, `trading_session.py`,
`state_snapshot_builder.py`, `engine_lifecycle.py`, `experiment_context.py`,
`quant_signal_mapper.py`, `trading_query_service.py`.

No logic changes. All swaps verified against canonical symbols in the worktree `quant/`.

## Files listed in brief with no swap needed

- `startup_contracts.py` — only brain-adjacent import is `app.domain.services.startup_reconciliation` (stays in backend per recipe).
- `quant_bridge.py` — only `app.config.settings`; no brain imports.
- `ai_command_service.py` — only `app.core.async_boundary` (stays in backend per recipe).

## Imports intentionally kept on legacy/staying paths (per recipe)

- `trading_session.py`: `app.domain.services.mobile_alerts`, `app.domain.services.self_healing`
- `startup_contracts.py`: `app.domain.services.startup_reconciliation`
- All `app.application.*`, `app.infrastructure.*`, `app.shared.*`, `app.core.async_boundary` imports untouched.

## `# TODO(p2)` fallbacks

**None.** Every `app.domain.*` brain import had a canonical `quant.*` target that resolved. No circular-import cases (no `quant.*` module imports `app.*` back into the backend), and no unmigrated strategy modules were needed by these files.

Note: `session_event_router.py` already had a `quant.decision.signal_builder.Signal` import in `_try_execute_quant_decision`; left untouched per brief. Only `app.domain.*` imports were swapped there.

## Verification (recipe commands)

1. `backend`: `pytest tests/unit -q --tb=short --continue-on-collection-errors`
   → **1324 passed, 60 skipped, 4 errors** (4 errors are the pre-existing env failures: `test_valentini_rl.py` gymnasium + 3× httpx in `test_optimizations.py`; identical to baseline expectation).
2. worktree root: `pytest tests/quant -q --tb=short`
   → **1448 passed, 30 skipped, 0 errors** (1 pre-existing RuntimeWarning in `test_sync_boundary.py`).

All 18 service modules in scope also import cleanly via `PYTHONPATH` (smoke check).

## Concerns

- None blocking. Remaining legacy `app.domain.*` references in these files are intentionally-staying ops modules (`mobile_alerts`, `self_healing`, `startup_reconciliation`) — Phase 3 shim deletion must preserve those.
- `quant_signal_mapper.py` docstring updated to reference `quant.contracts.entities.Signal` (documentation only, not logic).
