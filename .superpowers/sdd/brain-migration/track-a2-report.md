# Track A2 Report — Market state & structure cluster → `quant/amt/market/`

**Date:** 2026-08-06 · **Branch:** `stable_4` · **Status:** DONE_WITH_CONCERNS

All 9 modules moved leaf-first, one commit each, with `git mv` (history preserved),
re-export shims left at legacy paths, byte-identical logic (import rewrites only),
port tests green, parity tests green, and both quant + backend suites green.

## Commit hashes per module

| # | Legacy path | Moved to | Commit |
|---|---|---|---|
| 1 | `fabio_ai/services/market_state_engine.py` | `quant/amt/market/state_engine.py` | `c46b80e` |
| 2 | `fabio_ai/services/market_structure_classifier.py` | `quant/amt/market/structure.py` | `fd883ee` |
| 3 | `fabio_ai/services/opening_classifier.py` | `quant/amt/market/opening.py` | `2e0ba89` |
| 4 | `fabio_ai/services/regime_detector.py` | `quant/amt/market/regime.py` | `ddd4f01` |
| 5 | `domain/services/displacement_detector.py` | `quant/amt/market/displacement.py` | `4cde014` |
| 6 | `domain/services/break_detector.py` | `quant/amt/market/break_detector.py` (renamed, see Concern 1) | `2aba69a` |
| 7 | `domain/services/lvn_play_detector.py` | `quant/amt/market/lvn_play.py` | `3e11086` |
| 8 | `domain/services/acceptance_rejection.py` | `quant/amt/market/acceptance_rejection.py` | `fe681c5` |
| 9 | `fabio_ai/strategy/squeeze_detector.py` | `quant/amt/market/squeeze.py` | `35b9929` |

Each commit message: `refactor(quant): move <module> from backend brain`.

## `# TODO(migration)` imports left

Zero-backend-import rule check (`grep -rn "import app\.\|from app\." quant/amt --include=*.py`):

- `quant/amt/market/structure.py:18` — `from app.domain.fabio_ai.services import mlx_compute as mc`
  with `# TODO(migration): switch to quant.amt.compute once Track A3 lands` (sanctioned).
- `quant/amt/profile/factory.py:17` — `from app.domain.fabio_ai.services.amt_analyzer import IncrementalVolumeProfile`
  with `# TODO(migration)` (Track A1 sanctioned, Track A5).
- `quant/amt/profile/classifier.py:13` — `mlx_compute` (Track A1 sanctioned, Track A3).

No other legacy imports in `quant/amt/`.

## Test tails

Final suite runs (interpreter `/Users/apple/miniconda3/envs/amt_313/bin/python`):

| Suite | Command | Result |
|---|---|---|
| Track A2 market tests | `pytest tests/quant/amt/market -q --tb=short` | 109 passed, 1 skipped |
| Quant (repo root) | `pytest tests/quant -q --tb=short` | 503 passed, 1 skipped |
| Backend unit | `cd backend && pytest tests/unit -q --tb=short --continue-on-collection-errors` | 1625 passed, 60 skipped, 4 errors |

The 4 errors are the pre-existing environment failures, unchanged from baseline:
`tests/unit/domain/test_valentini_rl.py` (`ModuleNotFoundError: gymnasium`) plus
3× `tests/unit/test_optimizations.py::TestDebugMemoryEndpoint::test_memory_endpoint_returns_*`
(`ModuleNotFoundError: httpx`). `git diff 54231d3..HEAD -- backend/tests/unit/domain/test_valentini_rl.py backend/tests/unit/test_optimizations.py` is empty — these files were untouched.

Note: plain `pytest tests/unit` reports `Interrupted: 1 error during collection` because the
gymnasium error is a *collection* error; the pre-existing condition is identical pre/post-track.

### Ported backend tests (now `tests/quant/amt/market/`)

| Ported from `backend/tests/unit/domain/` | Moved to |
|---|---|
| `test_market_state_engine.py` | `test_state_engine.py` |
| `test_market_structure_classifier.py` | `test_structure.py` |
| `test_regime_detector.py` | `test_regime.py` |
| `test_regime_detector_gaps.py` | `test_regime_gaps.py` |
| `test_displacement_detector.py` | `test_displacement.py` |
| `test_squeeze_detector.py` | `test_squeeze.py` |

No dedicated backend tests existed for `opening_classifier`, `break_detector`,
`lvn_play_detector`, or `acceptance_rejection` (the brief's "port ALL hits" — hits were
zero; these are only referenced indirectly inside `test_amt_analyzer.py`). For those four,
new standalone unit tests were written mirroring the established port style.

## Parity-case → result map

`assert_parity` harness from `tests/quant/parity.py`; legacy side via re-export shim.

| Parity file | Cases | Result |
|---|---|---|
| `test_state_engine_parity.py` | `detect_market_state`: 12 tuples (BALANCED/IMBALANCED, NEAR_POC/NEAR_VAH/NEAR_VAL/OUTSIDE_VA, leg-VA override, vwap-deviation 3.5σ, IB flags) + defaults | PASS |
| | `classify_zone`: 9 (above/below/inside, boundaries at VAH/VAL/POC) | PASS |
| `test_structure_parity.py` | `MarketStructureClassifier.classify` 8-step series: balance / imbalance / chop / expansion / insufficient-data | PASS |
| `test_opening_parity.py` | `OpeningTypeClassifier.classify`: empty, 1-candle, drive-up, drive-down, quiet (auction), test-reject, rejection-reverse | PASS |
| `test_regime_parity.py` | `is_contracting` ×4, `detect_bollinger_squeeze` ×3, `is_atr_compressed` ×3, `_compute_atr` ×3 | PASS |
| `test_displacement_parity.py` | `detect_displacement` (impulse/noise/insufficient/multiplier), `detect_acceptance` (above/below/inside), `detect_displacement_leg` ×4 | PASS |
| `test_break_parity.py` | `detect_break` ×8, `check_ib_break_tick` ×7 (incl. sticky UP/DOWN) | PASS |
| `test_lvn_play_parity.py` | `detect_lvn_play` ×10 (rejection long/short, no-rejection, far LVN, HVN target, delta-flip, zero volume, no lvns) | PASS |
| `test_acceptance_rejection_parity.py` | `AcceptanceRejectionEngine.update` driven through 5 sequences of 1–3 candles (acceptance above/below, rejection high/low, sweep, rotation) | PASS |
| `test_squeeze_parity.py` | `MomentumSqueezeDetector.update`/`check_breakout` 7-step sequence (expansion→compression→breakout vol/no-vol) | PASS |

### Parity cases skipped and why

- **`RegimeDetector.should_trigger_llm` / `detect_squeeze` / `record_level_approach` /
  `is_second_drive` / `is_re_entry_blocked` / `record_failed_entry`** — skipped:
  they depend on accumulated live session state and `time.time()` (monkeypatched in the
  ported unit tests). Parity for stateful session logic adds no signal since both sides are
  the same code object via the shim; behavior is covered by the ported unit tests
  (`test_regime.py`, `test_regime_gaps.py`).
- **`log_state_transition`** — logging side-effect only, returns `None`; covered implicitly.

## Concerns

1. **Module name deviation:** `break_detector.py` was moved to `quant/amt/market/break_detector.py`,
   **not** `quant/amt/market/break.py` as the brief specified. `break` is a Python reserved word
   — `from quant.amt.market.break import ...` is a `SyntaxError`, so `break.py` can never be
   imported. The shim re-exports from `quant.amt.market.break_detector`. Track A3/Phase 3
   follow-ups should use `quant.amt.market.break_detector`.
2. **OHLC Decimal vs float in test fixtures:** parity fixtures construct `OHLC` directly with
   float fields (matching the module's arithmetic expectations), not via `OHLC.create()` which
   coerces to `Decimal` and breaks the classifier's float math. This matches the ported unit
   test convention.
3. **Backend test count dropped** from 1666 → 1625 passed as the six dedicated backend test
   files were moved into `tests/quant/amt/market/` (expected port behavior; all moved tests
   pass in the quant suite).
4. **Dead code preserved byte-identically:** `break_detector.py` retains the unreachable
   duplicated tail after `check_ib_break_tick` (present in the original); no cleanup performed
   to keep logic byte-identical.
