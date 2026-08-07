# WS-DATA/INFRA — Report

Worktree: `/Users/apple/Documents/wt-ws-data` (branch `migration/ws-data`)
Interpreter: `/Users/apple/miniconda3/envs/amt_313/bin/python`

## Status

DONE — all three tasks implemented, tested, and committed. No forbidden paths
(`.superpowers/`, `docs/superpowers/plans/`, `docs/*.md`) touched; only the 6
source/test files below were changed.

## Commits

1. `0140ccf` **feat(backend): SQLite WAL + ticks index**
   - `backend/app/infrastructure/storage/database.py` — added explicit
     `PRAGMA busy_timeout=5000` to `_init_db()`.
   - `backend/tests/unit/infrastructure/test_database_wal.py` (new, 6 tests).
2. `e359d5f` **feat(backend): configurable signal stale TTL (default 60s)**
   - `backend/app/config_models/settings_adapter.py` — new `SIGNAL_STALE_SECONDS`
     property (env `SIGNAL_STALE_SECONDS`, default `60`).
   - `backend/app/application/services/trading_session.py` — `_is_signal_stale`
     now uses `settings.SIGNAL_STALE_SECONDS` instead of the literal `600`.
   - `backend/tests/unit/application/test_trading_session_unit.py` — 3 new tests
     (`TestSignalStaleTTL`): default-60 behavior, env override up, env override down.
3. `a975723` **test(quant): live prompt vs training livefmt format parity**
   - `tests/quant/inference/test_train_livefmt_parity.py` (new, 4 tests).

## Where the 600 constant lived / what changed (Task 2)

The stale-signal threshold was the literal `600` (seconds) in
`trading_session.py::_is_signal_stale` (`signal_age > 600`), plus stale comments
claiming "10 minutes". Note: `AGENT_DECISION_THRESHOLD` is a **probability**
threshold (not a time) — it was a red herring. Replaced the literal with
`settings.SIGNAL_STALE_SECONDS` (env-configurable, default 60s). Comments updated.

## Test counts

New tests added: 13 total — 6 (WAL/index) + 3 (TTL) + 4 (livefmt parity).

- `tests/quant` alone: **1357 passed, 30 skipped, 0 errors** (parity test: 4 passed).
- `backend/tests/unit` alone: **1331 passed, 60 skipped, 9 errors, 1 failed**
  (9 errors = pre-existing env: gymnasium missing for `test_valentini_rl`, psutil
  for `test_optimizations`, etc.; 1 failed = date-drift in `test_trade_journal`,
  hardcoded `2026-08-06` vs today 2026-08-07).
- Combined `pytest tests/quant backend/tests/unit` (as written in the brief):
  **1323 passed, 65 skipped, 387 errors, 1 failed** (same 1 date failure).
  Baseline without my changes: 1314 passed / 386 errors → my changes add +9
  passing tests and +1 collection error (see concerns).

## Livefmt status finding (Task 3)

- `amt_dataset/nifty_amt_data_livefmt/` is present and well-formed:
  `train.jsonl` (920 lines), `val.jsonl` (115), `test.jsonl` (115).
- Each line is OpenAI `messages` format; the **user** content is already the
  *rendered* AMT prose — the exact vocabulary emitted by
  `quant.inference.prompt_builder.render_entry_prompt` / `build_entry_prompt`
  (e.g. `SESSION: NSE_PRIMARY. MARKET STATE: BALANCED. ... --- ORDER FLOW & AGGRESSION --- ...`).
- Canonical shared section markers (present in 100% of train/val/test user
  messages): `SESSION:`, `MARKET STATE:`, `ORDER FLOW & AGGRESSION`.
- The brief's suggested markers `VALUE AREA:`, `CVD:`, and `TRIPLE-A PHASE:`
  **do not exist** as section labels in the live prompt OR the livefmt dataset
  (`CVD` only appears inline in order-flow prose, 44/920 train lines; the other
  two never). So the test asserts the markers that actually exist and are shared
  (data-driven, substring-based, wording-robust), and reports this deviation.

## Concerns

1. **Combined-run collection quirk (pre-existing).** Running `pytest tests/quant
   backend/tests/unit` together from the worktree root produces 387 collection
   errors (`ModuleNotFoundError: No module named 'tests.quant'`) for many
   root-level `tests/quant` modules (baseline: 386). Root cause is pytest
   rootdir resolving to `backend/` (pytest.ini) when both trees are passed, so
   module import names collide with `backend/tests`. My new parity test is
   affected identically to pre-existing files (e.g. `test_valentini_rl.py`); it
   passes when `tests/quant` is run alone. Fixing the rootdir/import collision
   is out of scope — flag for a future infra task.
2. **"4 pre-existing env errors" maps to the backend-only run.** The brief's
   "4 pre-existing env errors" matches `cd backend && pytest tests/unit` roughly
   (9 env errors + 1 date-drift failure). The date failure
   (`test_trade_journal::test_completed_trades_prefer_entry_timestamp_for_duration`)
   is date-sensitive and will fail whenever run not-on-2026-08-06.
3. **Task 1 was mostly pre-done.** `database.py` already enabled WAL,
   `synchronous=NORMAL`, `wal_autocheckpoint`, and already created a **UNIQUE**
   `idx_ticks_symbol_time` index (with a dedup migration in `_init_db`). Only
   `busy_timeout` was missing and added. The test asserts journal_mode=wal,
   synchronous=NORMAL, busy_timeout>0, index presence, column coverage, and
   uniqueness. The UNIQUE variant is slightly stronger than the brief's plain
   index — kept as-is (no behavior change).
4. **`SIGNAL_TTL_SECONDS = 600` still in `quant/contracts/constants.py`.** It is
   the default `max_age_seconds` for `quant.execution.signal_validator.
   SignalValidator.validate_staleness`. Left untouched (out of scope — separate
   behavior change), but not to be missed. Existing tests for it pass explicit
   `max_age_seconds=60`, so nothing regresses.
