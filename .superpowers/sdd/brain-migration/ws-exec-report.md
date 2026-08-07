# WS-EXEC Report — QUANT_EXECUTION_MODE (off|shadow|paper|live)

**Status:** ✅ Complete

**Worktree:** `/Users/apple/Documents/wt-ws-exec` (branch `migration/ws-exec`), clean.

## What was done

Replaced the `QUANT_DECISION_ENABLED` boolean gate with a `QUANT_EXECUTION_MODE` (`off|shadow|paper|live`, default `off`) that wires the quant decision path to execution behind an explicit mode. Default behavior is byte-identical to before (no decisions computed, no execution).

### Files changed (implementation)
- `backend/app/config_models/settings_adapter.py` — added `QUANT_EXECUTION_MODE` property. Resolution order: `QUANT_EXECUTION_MODE` env → `quant_execution_mode` in `feature_flags.yaml` → back-compat alias `QUANT_DECISION_ENABLED` (true→`shadow`) → `"off"`. Added cached `_feature_flags_yaml()` helper (tolerant of missing/parse-failed file). `QUANT_DECISION_ENABLED` kept as an alias.
- `backend/app/application/services/quant_bridge.py::on_bar_close_with_decision` — guard changed from `if not settings.QUANT_DECISION_ENABLED` to `if settings.QUANT_EXECUTION_MODE == "off"`: decision computed for shadow/paper/live, skipped for off.
- `backend/app/application/services/session_event_router.py::_try_execute_quant_decision` — mode gate after the existing approved-decision check:
  - `off` → return `False` (legacy path untouched)
  - `shadow` → log `SHADOW quant execution would execute <sym> dir=<dir> entry=...`, return `True` (legacy skipped, entry coordinator NOT called)
  - `paper`/`live` → existing `quant_signal_mapper` + `entry_coordinator.execute_signal` path
- `backend/config/feature_flags.yaml` — added `quant_execution_mode: "off"` under `features` (documented). Note: **quoted** because bare YAML 1.1 `off` parses as boolean `False` (caught during TDD red phase; property also hardened against non-string values).

### Files changed (tests)
- **New** `backend/tests/unit/application/test_quant_execution_mode.py` — 13 tests:
  - resolution: default off, env>yaml, yaml fallback, legacy flag true→shadow, false→off
  - bridge computes for shadow/paper/live, skips for off
  - router: off→False; shadow→True+log+no `execute_signal`; paper/live→mapped domain signal routed once
- `backend/tests/unit/application/test_quant_bridge.py`, `test_session_event_router.py`, `tests/system/test_quant_execution_e2e.py` — migrated existing flag-based tests to the mode surface (test-only; the old flag is now an alias that maps to `shadow`, so execution-asserting tests now set the mode explicitly). System e2e gained: paper (executes, mapped signal), live (same path), shadow (computes+broadcasts, never executes), back-compat flag-true-without-mode behaves as shadow.

## Commits
- `676d675` `test(quant): QUANT_EXECUTION_MODE off|shadow|paper|live gate tests`
- `d75a244` `feat(backend): QUANT_EXECUTION_MODE off|shadow|paper|live wires quant decisions to execution`

## Test counts
- **`backend/tests/unit`**: `1335 passed, 60 skipped, 1 failed, 9 errors` (standalone).
  - The 1 failure is **pre-existing and date-dependent** (`test_trade_journal.py::test_completed_trades_prefer_entry_timestamp_for_duration` asserts `exit_time` starts with `2026-08-06`; today is `2026-08-07`). Confirmed failing on the base commit via `git stash`.
  - The 9 errors are **pre-existing env issues**: 6× `test_valentini_rl.py` (gymnasium), 3× `test_optimizations.py` (httpx/starlette.testclient missing).
- **`tests/system`**: `11 passed` (standalone) — includes 5 new/migrated quant-execution e2e tests.
- **`backend/tests/integration`**: `107 passed, 24 skipped, 5 errors` (httpx/starlette pre-existing).
- **Targeted**: `test_quant_execution_mode.py` + `test_quant_bridge.py` + `test_session_event_router.py` → 23 passed. `tests/system/test_quant_execution_e2e.py` → 5 passed.
- **Smoke**: `PYTHONPATH=backend python -c "import app.main"` → ok (from worktree root; `quant/` lives at repo root so bare `cd backend` import needs repo root on path, unrelated to this change).

The brief's single-invocation `pytest tests/unit tests/system` cannot collect both trees together: the repo-root `tests/` package collides with the pre-existing `backend/tests/` package (`No module named 'tests.system'`). This is pre-existing packaging (both have `__init__.py`); suites pass when run separately, and the affected system tests pass standalone.

## Concerns
1. **Back-compat alias is shadow-only.** `QUANT_DECISION_ENABLED=true` (with no explicit mode) now maps to `shadow` (compute + broadcast, **no execution**), whereas the old code executed when the flag was on. This is the safer paper→live protocol the brief prescribes, but anyone who previously ran with the flag on must set `QUANT_EXECUTION_MODE=paper`/`live` to restore execution. Documented in the code + yaml.
2. **`feature_flags.yaml` `off` must stay quoted** — bare `off` is YAML 1.1 `False` (boolean), which would silently make the mode resolve to the alias/default instead of a real mode. The settings property is defensive against non-string values, but a future `on`/`yes`/`no`/`off` mode value would need the same quoting.
3. **`feature_flags.yaml` is read directly** (not via `ModeConfig`'s strategy `feature_flags`), per the brief. Mode config merge (`strategies/*.yaml` → `scanner_config.feature_flags`) does not include this key; if deployers expect to set it in strategy/env yaml files, that path doesn't apply to this property (env var and `feature_flags.yaml` do).
