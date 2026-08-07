# Track A3 Report — Order flow cluster → `quant/amt/orderflow/` + `quant/amt/compute.py`

**Track:** Phase 1 Track A3 of the quant brain migration (from `docs/superpowers/plans/2026-08-06-quant-brain-migration.md`).
**Branch:** `stable_4`
**Status:** DONE

## Commit hashes (in order, deps first)

| Commit | Hash | Description |
|---|---|---|
| 1 | `66f25d7` | `refactor(quant): move mlx_compute from backend brain` — `mlx_compute.py` → `quant/amt/compute.py` + shim + ported `test_compute.py` |
| 2 | `d18e442` | `refactor(quant): resolve mlx_compute TODO in classifier + structure` — classifier.py + structure.py switch to `quant.amt.compute`, TODOs dropped |
| 3 | `75e3a48` | `refactor(quant): move cvd_tracker from backend brain` → `quant/amt/orderflow/cvd.py` |
| 4 | `21ef3e4` | `refactor(quant): move orderflow_detectors from backend brain` → `quant/amt/orderflow/detectors.py` |
| 5 | `42a28ba` | `refactor(quant): move aggression_scorer from backend brain` → `quant/amt/orderflow/aggression.py` |
| 6 | `8737010` | `refactor(quant): move aggressive_prints from backend brain` → `quant/amt/orderflow/aggressive_prints.py` |
| 7 | `9346c28` | `refactor(quant): move tick_delta from backend brain` → `quant/amt/orderflow/tick_delta.py` |
| 8 | `9362978` | `refactor(quant): move drive_tracker from backend brain` → `quant/amt/orderflow/drive.py` |
| 9 | `afa697b` | `refactor(quant): move drive_decay from backend brain` → `quant/amt/orderflow/drive_decay.py` |
| 10 | `087eb34` | `refactor(quant): move footprint_analyzer from backend brain` → `quant/amt/orderflow/footprint.py` |
| 11 | `64c2d81` | `refactor(quant): move order_flow_service from backend brain` → `quant/amt/orderflow/service.py` |
| 12 | `495c0dd` | `test(quant): add mlx_compute parity coverage` — `test_compute_parity.py` |

Note: the mlx_compute parity test (`tests/quant/amt/test_compute_parity.py`) was committed as a standalone follow-up (`495c0dd`) because the mlx_compute move commit was already in the branch when the parity coverage was finalized. It is functionally part of module commit #1.

## mlx_compute-resolution commit details (`d18e442`)

`quant/amt/profile/classifier.py`:
```diff
 from quant.contracts.value_objects import VolumeProfileLevel
-# TODO(migration): switch to quant.amt.compute once Track A3 lands
-from app.domain.fabio_ai.services import mlx_compute as mc
+from quant.amt import compute as mc
```

`quant/amt/market/structure.py`:
```diff
 from quant.contracts.value_objects import OHLC
-# TODO(migration): switch to quant.amt.compute once Track A3 lands
-from app.domain.fabio_ai.services import mlx_compute as mc
+from quant.amt import compute as mc
```
No other files touched. Both suites stayed green immediately after this commit.

## MLX import guard verification (`quant/amt/compute.py`)

Confirmed the MLX import is optional and the numpy/pure-Python fallback is the default:
- `_HAS_MLX = False` and `mx = None` at module top (MLX disabled; Metal GPU init crashes on this system).
- `_ensure_mlx()` returns `False` (no `import mlx` anywhere in the file).
- Every `batch_*` function checks `if not _HAS_MLX or len(x) < _MLX_MIN_SIZE:` before touching `mx`, so MLX is never a hard import. No change to this behavior was made — moved byte-identical.

## Import-rewrite map applied

- `app.domain.trading.models.value_objects` → `quant.contracts.value_objects`
- `app.domain.constants` → `quant.contracts.constants`
- `app.shared.timezones` → `quant.contracts.timezones`
- `app.domain.fabio_ai.services.mlx_compute` → `quant.amt.compute`
- `app.domain.fabio_ai.services.cvd_tracker` → `quant.amt.orderflow.cvd`
- `app.domain.fabio_ai.services.orderflow_detectors` → `quant.amt.orderflow.detectors`
- `app.domain.fabio_ai.services.aggression_scorer` → `quant.amt.orderflow.aggression`
- `app.domain.services.aggressive_prints` → `quant.amt.orderflow.aggressive_prints`
- `app.domain.services.tick_delta` → `quant.amt.orderflow.tick_delta`
- `app.domain.fabio_ai.services.footprint_analyzer` → `quant.amt.orderflow.footprint`
- `app.domain.fabio_ai.services.order_flow_service` → `quant.amt.orderflow.service`
- `app.domain.services.tick_utils` (in drive.py / drive_decay.py) → `quant.contracts.tick_utils` (maps under the `app.domain.* → quant.contracts.*` convention)

All logic byte-identical — only import rewrites. `git mv` used for all 10 source files to preserve history. Shim files created at every legacy path:
- `backend/app/domain/fabio_ai/services/mlx_compute.py`
- `backend/app/domain/fabio_ai/services/cvd_tracker.py`
- `backend/app/domain/fabio_ai/services/orderflow_detectors.py`
- `backend/app/domain/fabio_ai/services/aggression_scorer.py`
- `backend/app/domain/services/aggressive_prints.py`
- `backend/app/domain/services/tick_delta.py`
- `backend/app/domain/fabio_ai/services/drive_tracker.py`
- `backend/app/domain/fabio_ai/services/drive_decay.py`
- `backend/app/domain/fabio_ai/services/footprint_analyzer.py`
- `backend/app/domain/fabio_ai/services/order_flow_service.py`

Shim consumers verified resolving: `app.application.candle_aggregator` (TickFootprintAccumulator, TickDeltaClassifier), `app.domain.fabio_ai.services.amt_analyzer` (CVDTracker, BigTradeDetector, AggressionScorer, AggressivePrintRegistry).

## Tests ported into `tests/quant/amt/orderflow/`

- `test_compute.py` (from `test_mlx_compute.py`)
- `test_cvd.py` (from `test_valentini_rl.py` TestCVDTracker + `test_session_reset.py` TestCVDSessionReset)
- `test_detectors.py` (from `test_orderflow_detectors.py`)
- `test_aggression.py` (from `test_aggression_scorer.py`)
- `test_aggressive_prints.py` (from `test_aggressive_prints.py` — signal-sigma, delta-threshold, find_aggressive_prints, EMA warm-up, registry)
- `test_tick_delta.py` (from `test_tick_delta.py`)
- `test_drive.py` (from `test_drive_tracker.py`)
- `test_drive_decay.py` (from `test_live_trading_safeguards.py` TestDriveDecay — kept the `pytest.mark.skip` the backend suite already had)
- `test_footprint.py` (from `test_footprint_analyzer.py`)
- `test_footprint_gaps.py` (from `test_footprint_gaps.py`)
- `test_service.py` (from `test_order_flow_service.py`)

## Parity-case → result map

| File | Case | Result |
|---|---|---|
| `test_compute_parity.py` | `ema` (incl. len < window, empty) | PASS |
| | `linreg_slope` (incl. single, empty, zero array) | PASS |
| | `atr` (incl. single candle, empty, zero array, period<window) | PASS |
| | `gaussian_weights` (incl. empty, zero sigma) | PASS |
| | `aggression_sigma` (incl. len < window, empty, zero volume) | PASS |
| `test_cvd_parity.py` | 30-candle delta series `update`/`state`/`value`; session reset | PASS |
| `test_detectors_parity.py` | BigTrade (3 candles), Bubble sequence, OFI sequence, Absorption sequence | PASS |
| `test_aggression_parity.py` | `AggressionScorer.score` all-False, all-True, mixed bitmasks + `direction_sign` | PASS |
| `test_aggressive_prints_parity.py` | `find_aggressive_prints` sigma-spike series (full + incremental), registry | PASS |
| `test_tick_delta_parity.py` | `classify` quote/tick/zero/first-tick tuples + reset; `candle_delta_proxy` | PASS |
| `test_drive_parity.py` | D1→D2(valid after rejection)→D3 sequence; D2-no-rejection sequence | PASS |
| `test_drive_decay_parity.py` | `_drive_1_records` state after record+update_rotation (see concern) | PASS |
| `test_footprint_parity.py` | `generate` (full + incremental), `detect_absorption`, `detect_contested_zone` | PASS |
| `test_service_parity.py` | `compute_metrics` empty + candle+orderbook, metrics dict diff | PASS |

## Test tails

Quant suite (repo root):
```
672 passed, 4 skipped in 1.75s
```

Backend unit suite (`--ignore=tests/unit/domain/test_valentini_rl.py`):
```
1625 passed, 60 skipped, 3 errors in 4.99s
```
The 3 errors are the pre-existing httpx-starlette errors in `tests/unit/test_optimizations.py::TestDebugMemoryEndpoint`. The 4th pre-existing error (gymnasium `ModuleNotFoundError` in `test_valentini_rl.py` collection) is unchanged — confirmed by running the suite including it (`ERROR tests/unit/domain/test_valentini_rl.py`, `1 skipped, 1 error`). These 4 pre-existing errors were verified present before this track began and are environment issues (missing `httpx`/`gymnasium`), unrelated to the migration.

## Remaining `# TODO(migration)` imports in `quant/amt/`

```
quant/amt/profile/factory.py:16:# TODO(migration): switch to quant.amt.analyzer once Track A5 lands
quant/amt/profile/factory.py:17:from app.domain.fabio_ai.services.amt_analyzer import IncrementalVolumeProfile
```

`grep -rn "import app\.\|from app\." quant/amt --include=*.py` (via `grep -rn` without the include flag on zsh) shows ONLY `quant/amt/profile/factory.py` → `amt_analyzer` (sanctioned Track A5). This satisfies the zero-backend-import rule.

## Concerns

1. **`drive_decay.py` pre-existing bug preserved:** `validate_drive_2()` has an `UnboundLocalError` (`record` used before assignment at what is now `quant/amt/orderflow/drive_decay.py:115`). Logic was kept byte-identical per the brief. The backend suite already had these tests `pytest.mark.skip`-ped, and the ported test preserves that skip. The parity test therefore compares the `_drive_1_records` state (record/update_rotation path) instead of the crashing `validate_drive_2` method. Track A5 or a later bugfix track should fix this — it makes `DriveDecay.validate_drive_2` unusable.
2. **`drive.py` pre-existing bug preserved:** `is_level_exhausted()` and `get_drive_count()` reference an undefined local `tick_size` (byte-identical move). Not exercised by the ported tests; the legacy tests didn't cover them either.
3. **Order of commits vs parity test:** the mlx_compute parity test landed as `495c0dd` after the module commit `66f25d7` (a dedicated `test(quant):` commit) rather than inside it. Everything else follows the strict one-commit-per-module ordering from the brief.
4. **`test_compute_parity.py` imports via `from quant.amt import compute as mc` and `from app.domain.fabio_ai.services import mlx_compute as legacy_mc`** — both resolve identically since the legacy path is now a shim.
