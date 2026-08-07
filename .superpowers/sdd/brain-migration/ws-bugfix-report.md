# WS-BUGFIX — Report

**Worktree:** `/Users/apple/Documents/wt-ws-bugfix` (branch `migration/ws-bugfix`)
**Date:** 2026-08-07

## Status: COMPLETE

All 4 sanctioned brain bug fixes done, each in its own commit with a regression test (Bug 4 verified via existing tests per brief). Nothing in the main repo touched.

## Commits (4)

| Commit | Message | Bug |
|---|---|---|
| `186f8a2` | `fix(quant): single VWAP accumulation per bar (B-20)` | 1 |
| `d5fcaab` | `fix(quant): drive_decay record-before-assign` | 2 |
| `2cc12ce` | `fix(quant): drive undefined tick_size` | 3 |
| `84e94b5` | `fix(quant): remove dead code tail in break_detector` | 4 |

## Bug 1 — RED→GREEN evidence (audit B-20, Critical)

Fix: removed the second `_update_session_vwap(current, typical_price)` call in `analyze()` (analyzer.py:1096) which double-accumulated volume + quote-volume per bar. The single update at analyzer.py:1029 now feeds both `detect_market_state` (via `vwap_deviation_sigmas`) and the returned-state VWAP bands.

Regression test: `tests/quant/amt/test_analyzer.py::TestVWAPDoubleAccumulationRegression` — feeds a known 2-candle series through `AMTAnalyzer.analyze` and asserts the session VWAP accumulators/bands equal the single-pass expectation.

**RED** (before fix):
```
tests/quant/amt/test_analyzer.py::TestVWAPDoubleAccumulationRegression::test_session_vwap_not_double_accumulated FAILED
E   assert 400.0 == 200.0 ± 2.0e-04
E     comparison failed
E     Obtained: 400.0        # double-accumulated volume (2 bars × 2 sites)
E     Expected: 200.0 ± 2.0e-04
4 failed in 0.67s
```

**GREEN** (after fix):
```
tests/quant/amt/test_analyzer.py::TestVWAPDoubleAccumulationRegression tests/quant/amt/orderflow/test_drive_decay.py::TestDriveDecayRegression tests/quant/amt/orderflow/test_drive.py::TestDriveTrackerTickSizeRegression
....                                                                     [100%]
4 passed in 0.19s
```

## Bugs 2–4

- **Bug 2** (`drive_decay.py`): `validate_drive_2` referenced `record` before assignment (UnboundLocalError). Fixed by resolving the record by matching the tick-rounded bucket against stored keys. Regression: `TestDriveDecayRegression::test_validate_drive_2_with_recorded_drive_1` (was RED with `UnboundLocalError`, now passes).
- **Bug 3** (`drive.py`): `is_level_exhausted` / `get_drive_count` used undefined `tick_size`. Added the parameter with the module default `tick_size=0.05`. Regression: `TestDriveTrackerTickSizeRegression` (2 tests; were RED with `NameError`, now pass).
- **Bug 4** (`break_detector.py`): deleted unreachable duplicated tail (lines 205–286) after the terminal `return` in `check_ib_break_tick`. Public behavior verified unchanged — existing `tests/quant/amt/market/test_break.py` passes.

## Test counts

- `tests/quant`: **1357 passed, 30 skipped** (baseline 1353 passed, 30 skipped → +4 new regression tests)
- `backend/tests/unit`: **1322 passed, 60 skipped, 1 failed, 9 errors** — byte-identical to the pre-change baseline (verified via `git stash`), i.e. no regressions. The 1 failure (`test_trade_journal::test_completed_trades_prefer_entry_timestamp_for_duration`) and the 9 setup errors (`TestValentiniEnv`, `TestDebugMemoryEndpoint`) are pre-existing environment failures, unrelated to these fixes.

## Concerns

- The 9 backend errors (gymnasium env setup) and 1 backend failure are pre-existing and outside the WS-BUGFIX scope.
- `validate_drive_2` now resolves the stored record by scanning `_drive_1_records` keys; functionally equivalent to the intended single-bucket lookup but tolerant of the per-record `tick_size`. If the module later wants a tighter contract, consider storing a `tick_size` default at init.
- Bug 1's returned VWAP value is ratio-invariant to uniform doubling, so the regression test asserts the absolute accumulator counters (`_vwap_cum_vol`/`_vwap_cum_quote_vol`) — the true observable corruption — in addition to `result.session_vwap`.
