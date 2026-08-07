# WS-REPLAY report — golden-file replay harness + recorder (§5.2, §5.4)

**Branch:** `migration/ws-replay` (worktree `/Users/apple/Documents/wt-ws-replay`)
**Date:** 2026-08-07

## Status: DONE — all three deliverables implemented, tested, committed

## Commits (worktree `migration/ws-replay`)

- `cf62110` `feat(quant): replay harness + golden capture/replay` — `quant/tools/replay.py` (+ `quant/tools/__init__.py`)
- `2b84640` `test(quant): replay determinism + drift detection` — `tests/quant/replay/test_replay.py`, `tests/fixtures/replay/session_120.jsonl` (committed 120-bar golden), `.gitignore` exception `!tests/fixtures/replay/*.jsonl`
- `43a20e6` `feat(backend): QUANT_RECORD_REPLAY live-capture hook` — `backend/app/application/services/quant_bridge.py`, `backend/tests/unit/application/test_quant_bridge.py`

Nothing in `.superpowers/`, `docs/` was touched or committed. Report intentionally
lives only in the main repo.

## Deliverables

### 1. `quant/tools/replay.py` — pure, deterministic, no backend imports

- `capture(bars, analyzer=None, golden_path=None) -> list[AuctionState]` — feeds
  bars through an analyzer, optionally writes a JSONL golden file of
  `{bar, state}` per line, returns the state series.
- `replay(source, analyzer=None) -> list[AuctionState]` — replays a golden path
  (or a bare Bar sequence) through a fresh `AuctionCoordinator`; two replays of
  the same source are byte-identical.
- `assert_replay_equal(golden_path, analyzer=None, *, bars=None)` — replays the
  golden session and raises `ReplayMismatch` on ANY field divergence
  (floats within `1e-9` via `math.isclose`; enums/strings/bools exact). The
  `bars=` override feeds a different stream to prove drift detection.
- Helpers: `write_golden`, `read_golden`, `states_to_jsonl_bytes` (stable
  `sort_keys` compact JSONL), `FLOAT_ATOL = 1e-9`.
- Serialization is explicit per dataclass (all six detectors), so the golden
  file captures the full `AuctionState` — VP levels/POC/VA, VWAP, order-flow
  CVD/prints, absorption, location, Triple-A.

### 2. `tests/quant/replay/test_replay.py` — determinism + drift detection (7 tests)

Deterministic 120-bar session extending the `test_golden_file._session_bars()`
shape: quiet bars, four absorption spikes (2 BUY, 2 SELL), near-POC
accumulation, breakouts/breakdowns to AGGRESSION, and VA-edge bars that push
closes past vah/val (`ABOVE_VA`/`BELOW_VA` zones observed). Tests:

- `test_capture_matches_committed_golden` — fresh capture reproduces the
  committed `session_120.jsonl` **byte-for-byte** (capture-side drift gate).
- `test_fixture_is_varied` — asserts all 4 Triple-A phases, both VA-edge zones,
  and both absorption sides appear in the fixture.
- `test_replay_committed_golden_is_byte_identical` — `assert_replay_equal` on
  the committed fixture (replay-side drift gate).
- `test_replay_is_deterministic_across_fresh_analyzers` — two fresh analyzers
  → byte-equal.
- `test_drift_detection_catches_mutated_bar_volume` — mutating `t60` volume ×2
  makes `assert_replay_equal` raise `ReplayMismatch` (proves the gate fires).
- `test_replay_mismatch_on_empty_golden`, `test_float_tolerance_is_strict`.

### 3. Live-capture recorder hook (`backend/.../quant_bridge.py`)

`on_bar_close` now, when `QUANT_RECORD_REPLAY=1`, appends one JSONL line
`{"symbol", "time", "open", "high", "low", "close", "volume", "buy_volume",
"delta", "oi", "auction": <auction DTO>}` to
`backend/live_trading_logs/replay_<symbol>_<date>.jsonl` (dir auto-created).
Guarded and cheap: env read is a single `os.environ.get`; the main path is
byte-identical when the env is unset; duplicates (dedup'd bar times) are not
recorded; appends serialized under a module lock. Date extracted from the ISO
bar time (`na` fallback).

Unit tests (4 new, in `backend/tests/unit/application/test_quant_bridge.py`):
env set → file written with the full schema; duplicate bar skipped; env unset →
no write (dir not even created); ISO date used in the filename. All monkeypatch
`_REPLAY_LOG_DIR` to `tmp_path`.

## Verification

- `pytest tests/quant/replay -q --tb=short` → **7 passed**
- `pytest backend/tests/unit/application/test_quant_bridge.py -q --tb=short` → **12 passed** (8 existing + 4 new)
- `pytest backend/tests/unit/application/test_quant_execution_mode.py test_quant_signal_mapper.py` → **19 passed** (bridge consumers unaffected)
- Full `pytest tests/quant -q --tb=short` → **1368 passed, 30 skipped** (pre-replay baseline 1361; all still green)

## Concerns

1. **A real-day capture is intentionally unavailable.** The backend databases
   hold 0 ticks and no live session was run, so the §5.2 byte-for-byte gate is
   **enabled but not yet filled with a real session**. The hook
   (`QUANT_RECORD_REPLAY=1`) is ready; a live/golden day capture must be
   recorded into `tests/fixtures/replay/` and wired into
   `assert_replay_equal` to close the gate against real VP/VWAP/absorption/Triple-A
   drift. Until then, the committed 120-bar *synthetic* golden is the gate.
2. **The brief's exact combined verify command does not run in this repo.**
   `pytest tests/quant/replay backend/tests/unit/application/test_quant_bridge.py`
   fails at collection with `No module named 'tests.quant'` — a **pre-existing**
   repo condition: `backend/pytest.ini` sets `rootdir=backend` for the combined
   run and `backend/tests/__init__.py` shadows the root `tests/` package via
   `backend/tests/conftest.py`'s `sys.path.insert(0, backend)`. The existing
   `tests/quant/test_golden_file.py` fails identically in the combined run.
   The two suites pass independently (the repo's actual convention). No repo
   infra was changed to keep scope tight.
3. `replay`'s first arg is a golden **path** (or bare bars) rather than the
   brief's ambiguous `replay(states, analyzer)` signature — a path is required
   to "feed the same bars back"; `analyzer` defaults to a fresh
   `AuctionCoordinator` for determinism.
4. Fixture is JSONL (gitignored repo-wide) — added an explicit
   `!tests/fixtures/replay/*.jsonl` exception so the golden is committed.
