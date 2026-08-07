# WS-CLEANBE Report

## Status
**COMPLETE** — `backend/tests/unit` runs with **0 failed, 0 errors** (1323 passed, 64 skipped).

## Commits (branch `migration/ws-cleanbe`, worktree `/Users/apple/Documents/wt-ws-cleanbe`)
1. `a12b01d` `fix(test): make trade_journal duration test date-relative`
2. `289a98e` `fix(test): skip valentini RL tests when gymnasium missing`
3. `ecf7332` `fix(test): skip memory-endpoint tests when httpx missing`

Each commit touches exactly one test file; nothing in `.superpowers/`, `docs/superpowers/plans/`, or `docs/*.md` was committed.

## Before / After
| Suite | Before | After |
|---|---|---|
| `tests/unit` | 1 failed + 9 errors | **0 failed, 0 errors** (1323 passed, 64 skipped) |
| `tests/validation` | clean | clean (52 passed, 4 skipped) |
| `tests/integration` | 5 errors (pre-existing) | 5 errors (pre-existing, untouched) |

Breakdown of the 9 pre-existing unit errors fixed:
- `test_trade_journal.py::test_completed_trades_prefer_entry_timestamp_for_duration` — 1 failed. Entry timestamp was hardcoded to a past day (`2026-08-06`) while `_now_ist()` returned the current day, breaking both the `exit_time.startswith` and `duration_s < 86400.0` assertions. Now the entry timestamp is computed as `_now_ist() - 60s`; assertions unchanged in strength (exact entry_time match, positive sub-24h duration, pnl_pct == 4.0).
- `test_valentini_rl.py::TestValentiniEnv` — 6 errors. Added module-level `gymnasium = pytest.importorskip("gymnasium")` right after `import pytest`; module skips cleanly when the optional dep is absent, tests run normally when present.
- `test_optimizations.py::TestDebugMemoryEndpoint` — 3 errors. Added `pytest.importorskip("httpx")` inside the `client` fixture so the 3 tests skip when httpx is missing; assertions unchanged when present.

## Concerns
- **Pre-existing integration errors (out of scope):** `tests/integration` has 5 errors — all `starlette.testclient` requiring `httpx` (missing in `amt_313` env). Same root cause as unit fix #3 but in integration suites; not addressed per brief scope. Installing `httpx` into the env would resolve both unit-skip and integration-error behavior.
- **Gymnasium skip is whole-module:** `pytest.importorskip` at module level skips the *entire* `test_valentini_rl.py` (including the ~33 non-gym tests) when gymnasium is absent. This matches the brief's instruction and satisfies 0 failed/0 errors; if finer-grained skipping is later desired (only `TestValentiniEnv`), a `pytest.importorskip` inside that class or a `skipif` would be needed.
- `test_completed_trades_prefer_entry_timestamp_for_duration` still has the same theoretical midnight-crossing edge case as other date-relative tests in the file (entry computed from `_now_ist()` and `log_exit` calls `_now_ist()` again) — ~1s window, negligible.
