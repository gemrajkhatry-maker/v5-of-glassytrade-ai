# WS-CLEANBE — Backend suite: 0 failed / 0 errors (fix pre-existing env + date-drift issues)

**Worktree:** `/Users/apple/Documents/wt-ws-cleanbe` (branch `migration/ws-cleanbe`). Work ONLY there.

**Goal:** make `backend/tests/unit` run with **0 failed and 0 errors** (only clean passes + skips), by fixing three PRE-EXISTING issues (all verified failing/erroring on the base commit before this migration):

1. **`tests/unit/application/test_trade_journal.py`** — currently `1 failed`: `test_completed_trades_prefer_entry_timestamp_for_duration` (date-dependent; fails on `stable_4` because a date hardcoded to a past day vs `_now_ist()`). Read the failing test, find the hardcoded/absolute date, and make it RELATIVE to `_now_ist()` (or mock the clock consistently), so it passes on any day. Do not weaken the assertion — it must still verify the entry-timestamp-preference behavior.

2. **`tests/unit/domain/test_valentini_rl.py`** — currently `6 errors` because `gymnasium` isn't installed. Add a module-level `gymnasium = pytest.importorskip("gymnasium")` (after the `import pytest`) so the 6 tests SKIP cleanly instead of ERRORing when the optional dep is missing. Preserve real behavior when gymnasium IS present (run the tests).

3. **`tests/unit/test_optimizations.py::TestDebugMemoryEndpoint`** — currently `3 errors` because `httpx` isn't installed. Make those tests skip gracefully when `httpx` is missing (`pytest.importorskip("httpx")` or a `skipif` guard inside the test method) instead of ERRORing. Do not weaken the assertions when httpx IS present.

**Verify (worktree root, from its `backend/`):**
```bash
cd /Users/apple/Documents/wt-ws-cleanbe/backend
/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/unit -q --tb=short --continue-on-collection-errors
```
Expected: **0 failed, 0 errors** (passes + skips only). Also run `tests/validation` and `tests/integration` to confirm no new issues.

**Commits:** one per fix: `fix(test): make trade_journal duration test date-relative`, `fix(test): skip valentini RL tests when gymnasium missing`, `fix(test): skip memory-endpoint tests when httpx missing`.

**Report:** `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/ws-cleanbe-report.md`. Reply: status, commits, before/after error+failed counts, concerns.
