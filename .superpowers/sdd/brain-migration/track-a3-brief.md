# Phase 1 Track A3 — Order flow cluster → `quant/amt/orderflow/` + `quant/amt/compute.py`

**From:** docs/superpowers/plans/2026-08-06-quant-brain-migration.md — Phase 1, Track A3.

**Goal:** Port the order-flow cluster from the backend brain into `quant/amt/orderflow/`, and `mlx_compute.py` into `quant/amt/compute.py`. Same move-with-shim + parity recipe as Tracks A1/A2. One commit per module; every commit leaves quant + backend suites green.

**Modules to move — strict order (deps first):**

1. `backend/app/domain/fabio_ai/services/mlx_compute.py` → `quant/amt/compute.py`
   - Exports: `gaussian_weights`, `smooth_array`, `ema`, `linreg_slope`, `atr`, `candle_overlap_pct`, `weighted_moments`, `count_peaks`, `aggression_sigma`, `divergence_detect`, `std`, `batch_*` variants.
   - Verify the MLX import is guarded (optional dependency) and the numpy fallback is the default. Do NOT make MLX a hard import. This is the last of the three `# TODO(migration)` legacy deps (Track A1 classifier + Track A2 structure import `mlx_compute`).
   - **After this commit, update** `quant/amt/profile/classifier.py` and `quant/amt/market/structure.py`: replace their `from app.domain.fabio_ai.services import mlx_compute as mc` with `from quant.amt.compute import <...> as mc` and drop the `# TODO(migration)` comments. Commit that as its own commit `refactor(quant): resolve mlx_compute TODO in classifier + structure`.
2. `backend/app/domain/fabio_ai/services/cvd_tracker.py` → `quant/amt/orderflow/cvd.py` (imports `mlx_compute` → `quant.amt.compute`)
3. `backend/app/domain/fabio_ai/services/orderflow_detectors.py` → `quant/amt/orderflow/detectors.py`
4. `backend/app/domain/fabio_ai/services/aggression_scorer.py` → `quant/amt/orderflow/aggression.py`
5. `backend/app/domain/services/aggressive_prints.py` → `quant/amt/orderflow/aggressive_prints.py`
6. `backend/app/domain/services/tick_delta.py` → `quant/amt/orderflow/tick_delta.py`
7. `backend/app/domain/fabio_ai/services/drive_tracker.py` → `quant/amt/orderflow/drive.py`
8. `backend/app/domain/fabio_ai/services/drive_decay.py` → `quant/amt/orderflow/drive_decay.py` (imports `app.shared.timezones.IST` → `quant.contracts.timezones.IST`)
9. `backend/app/domain/fabio_ai/services/footprint_analyzer.py` → `quant/amt/orderflow/footprint.py` (imports `mlx_compute` → `quant.amt.compute`)
10. `backend/app/domain/fabio_ai/services/order_flow_service.py` → `quant/amt/orderflow/service.py` (imports cvd_tracker, orderflow_detectors, aggression_scorer, aggressive_prints — all now in `quant.amt.orderflow.*`)

**Import-rewrite map (for moved files):**
- `app.domain.trading.models.*` → `quant.contracts.*`
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

**Shims** at each legacy path: `from quant.amt.orderflow.<name> import *  # noqa: F401,F403` (and `from quant.amt.compute import *` for mlx_compute). Consumers that must keep working via shims: `candle_aggregator.py` (TickFootprintAccumulator, TickDeltaClassifier), `amt_analyzer.py` (CVDTracker, detectors, AggressionScorer, AggressivePrintRegistry), `dhan_adapter.py` (market_data_utils — not this track), `infrastructure/adapters/delta_profile_adapter.py` (delta_profile — A1).

**Tests to port** (find under `backend/tests/`; port ALL hits): mlx_compute, cvd_tracker, orderflow_detectors, aggression_scorer, order_flow_service, footprint_analyzer, drive_tracker, drive_decay, tick_delta, aggressive_prints → `tests/quant/amt/orderflow/` (mlx_compute → `tests/quant/amt/test_compute.py`).

**Parity tests** via `assert_parity` (legacy shim vs moved) on fixed inputs:
- `mlx_compute`: `ema`, `linreg_slope`, `atr`, `gaussian_weights`, `aggression_sigma` on small fixed arrays (include an edge: len < window, zero array).
- `CVDTracker`: a fixed 30-candle delta series → `update`/`state`/`value`.
- `AggressionScorer.score`: the boolean-mask combos (all-False, all-True, mixed).
- `find_aggressive_prints`: a candle series with a clear sigma spike.
- `TickDeltaClassifier.classify`: a few (price, volume, bid, ask) tuples.
- `drive_tracker` / `drive_decay`: fixed touch sequences.
- `footprint_analyzer.detect_absorption` / `detect_contested_zone`: synthetic candle sets.
- `OrderFlowService.compute_metrics`: a fixed candle + order book input.

**Verification (after EACH module):**
```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant -q --tb=short
cd backend && /Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/unit -q --tb=short
```
Report pass/skip/error counts; the 4 pre-existing errors (gymnasium + 3 httpx) must be unchanged.

**Zero-backend-import rule:** after the mlx_compute resolution commit, `grep -rn "import app\.\|from app\." quant/amt --include=*.py` must show ONLY `quant/amt/profile/factory.py`'s sanctioned `amt_analyzer` `# TODO(migration)` (Track A5). All other tracks' TODOs must be gone.

## Report contract

Write your report to `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/track-a3-report.md`: commit hashes, the mlx_compute-resolution commit details, test tails, parity-case→result map, remaining `# TODO(migration)` imports. Return: status, commits, one-line test summary, concerns.
