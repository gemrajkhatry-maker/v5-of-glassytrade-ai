# WS-TTL Report

**Date:** 2026-08-07
**Worktree:** `/Users/apple/Documents/wt-ws-ttl` (branch `migration/ws-ttl`)
**Interpreter:** `/Users/apple/miniconda3/envs/amt_313/bin/python`

## Status: DONE

## Changes

1. **`quant/contracts/constants.py:125`** — `SIGNAL_TTL_SECONDS` changed `600 → 60`, with comment `# 60s scalar-session default; runtime override via SIGNAL_STALE_SECONDS setting`, aligning the quant validator default with the backend `SIGNAL_STALE_SECONDS` (60s) runtime default.

2. **`quant/execution/signal_validator.py`** — `validate_staleness(max_age_seconds=SIGNAL_TTL_SECONDS)` default stays; docstring updated (`default: 600s = 10min` → `default: 60s = 1min`). The `max_age_seconds` override is unchanged, so callers can still pass longer windows explicitly.

3. **Other `600` usages — audited, deliberately left unchanged (not stale-signal windows):**
   - `quant/execution/exit_rules.py:37` `EXPIRY_TIME_STOP = 600` — position time-stop (expiry day), unrelated to signal staleness; asserted by `tests/quant/execution/test_trade_manager.py:298`.
   - `quant/amt/market/acceptance_rejection.py:87` `if 0 < dt < 600:` — sanity bound on estimated candle duration, not a signal window.
   - `quant/probability/features.py:411` `if total_min < 600:` — clock time (600 min = 10:00), unrelated.
   - No other production callers of `validate_staleness`/`validate_all`/`SIGNAL_TTL_SECONDS` exist (only `signal_validator.py` itself). No production caller needs an explicit `max_age_seconds=600`; the override remains available and is exercised in tests.

4. **Tests** (`tests/quant/execution/test_signal_validator.py`, `test_signal_validator_extended.py`):
   - Tightened `test_signal_validator_validate_staleness_stale` from a weak `result in (True, False)` to `is False` (300s-old signal, 60s default).
   - Added deterministic boundary tests: default rejects a 61s-old signal, accepts a 59s-old signal, and explicit `max_age_seconds=600` still accepts a 300s-old signal (override preserved).
   - Fixed `test_signal_validator_extended.py` `_make_signal` default timestamp (10:00:00Z → 10:04:30Z) so `test_validate_staleness_fresh_signal` and `test_validate_all_passes` remain valid under the 60s default (they were implicitly asserting the old 600s boundary).

## Commits

- `44989ff` `fix(quant): align SignalValidator TTL default with 60s runtime setting` (4 files, +43/−9)

## Test counts

`/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant -q --tb=short`

- **1371 passed, 30 skipped, 1 warning** (4.51s)

## Concerns

- The boundary comparison in `validate_staleness` is strict (`age > max_age_seconds`), so exactly 60.0s is still accepted (fresh). This matches the backend `_is_signal_stale` logic in `trading_session.py:474` (also strict `>`), so the two sides stay consistent. Tests assert 59s accepted / 61s rejected to avoid the exact-boundary ambiguity.
- The runtime default lives in `backend/app/config_models/settings_adapter.py` (`SIGNAL_STALE_SECONDS` env, default `"60"`); the quant constant is now a matching fallback default for the validator. If the env default ever changes, `SIGNAL_TTL_SECONDS` should follow.
