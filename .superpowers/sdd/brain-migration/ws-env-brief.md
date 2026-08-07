# WS-ENV — Close the test-env gaps: integration + brokers suites green

**Worktree:** `/Users/apple/Documents/wt-ws-env` (branch `migration/ws-env`). Work ONLY there.

**Context:** `httpx` (0.28.1) and `pyotp` (2.10.0) were JUST installed into the `amt_313` env, which previously blocked the integration suite (5 starlette.testclient errors) and TOTP paths. Now the real test outcome is visible.

**Tasks:**
1. Run the previously-blocked suites and fix any REAL failures (not live-market flakes):
   - `cd backend && /Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/integration -q --tb=short --continue-on-collection-errors`
   - `cd /Users/apple/Documents/wt-ws-env && /Users/apple/miniconda3/envs/amt_313/bin/python -m pytest brokers/tests -q --tb=short` (from repo root so `brokers` resolves)
2. `brokers/tests/test_integration_market_data.py` has `_skip_if_no_creds()` guards but its `test_stream_ticker_2_ticks` (and any MCX-evening tests) FAIL outside market hours even WITH creds. Make the live-data tests robust: add a market-hours guard to `_skip_if_no_creds` (or a sibling `_skip_if_market_closed`) that checks IST time — NSE: 09:15–15:30 IST, MCX evening: 17:00–23:00 IST — and skips when the relevant market is closed. Ticks from IST: use `quant.contracts.timezones.IST` (not hardcoded offsets). Goal: `brokers/tests` = 0 failed (live tests SKIP when market closed).
3. Re-run `backend tests/unit` and `tests/validation` — confirm still 0 failed / 0 errors after any changes.
4. Fix any test that was only passing because httpx/pyotp were absent (a test asserting an ImportError is now wrong).

**Verify:** all four suites report green (passes + skips, 0 failed, 0 errors). Report exact counts per suite.

**Commits:** `fix(test): market-hours guard for live streaming tests`, plus any real integration fixes.

**Report:** `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/ws-env-report.md`. Reply: status, commits, per-suite counts, concerns.
