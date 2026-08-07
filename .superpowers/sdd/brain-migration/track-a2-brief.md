# Phase 1 Track A2 — Market state & structure cluster → `quant/amt/market/`

**From:** docs/superpowers/plans/2026-08-06-quant-brain-migration.md — Phase 1, Track A2.

**Goal:** Port the market-state / structure / regime / detector cluster from the backend brain into `quant/amt/market/`, using the same move-with-shim + parity recipe as Task 0.4 and Track A1. One commit per module; every commit leaves quant + backend suites green.

**Modules to move (leaf-first):**

1. `backend/app/domain/fabio_ai/services/market_state_engine.py` → `quant/amt/market/state_engine.py`
   - Exports: `MarketStateResult`, `detect_market_state`, `classify_zone`, `log_state_transition`. Imports `app.domain.trading.models.enums` (contracts) + constants.
2. `backend/app/domain/fabio_ai/services/market_structure_classifier.py` → `quant/amt/market/structure.py`
   - Exports: `MarketStructure`, `MarketStructureClassifier`. Imports `mlx_compute` (Track A3 — NOT moved): keep **legacy** import `from app.domain.fabio_ai.services import mlx_compute as mc` with `# TODO(migration): switch to quant.amt.compute once Track A3 lands`.
3. `backend/app/domain/fabio_ai/services/opening_classifier.py` → `quant/amt/market/opening.py`
   - Exports: `OpeningTypeResult`, `OpeningTypeClassifier`. Pure.
4. `backend/app/domain/fabio_ai/services/regime_detector.py` → `quant/amt/market/regime.py`
   - Exports: `ContractionConfig`, `RegimeDetector`, `SqueezeSignal`. Uses trading models (contracts) + constants.
5. `backend/app/domain/services/displacement_detector.py` → `quant/amt/market/displacement.py`
   - Exports: `detect_displacement`, `detect_acceptance`, `detect_displacement_leg`. Pure (may use contracts utils).
6. `backend/app/domain/services/break_detector.py` → `quant/amt/market/break.py`
   - Exports: `BreakResult`, `detect_break`, `check_ib_break_tick`. Imports `app.domain.services.candle_metrics.body` → `quant.contracts.candle_metrics.body`.
7. `backend/app/domain/services/lvn_play_detector.py` → `quant/amt/market/lvn_play.py`
   - Exports: `detect_lvn_play`. Imports `app.domain.services.lvn_detector` → `quant.amt.profile.lvn` (moved in Track A1).
8. `backend/app/domain/services/acceptance_rejection.py` → `quant/amt/market/acceptance_rejection.py`
   - Exports: `AcceptanceRejectionEngine`, `ARResult`. Pure.
9. `backend/app/domain/fabio_ai/strategy/squeeze_detector.py` → `quant/amt/market/squeeze.py`
   - Exports: `SqueezeState`, `MomentumSqueezeDetector`. Pure.

**Import-rewrite map (for moved files):**
- `app.domain.trading.models.*` → `quant.contracts.*`
- `app.domain.constants` → `quant.contracts.constants`
- `app.domain.services.{candle_metrics,tick_utils,decimal_utils,market_data_utils}` → `quant.contracts.<same>`
- `app.domain.services.lvn_detector` → `quant.amt.profile.lvn`
- `app.domain.services.volume_profile` → `quant.amt.profile.volume_profile`
- `app.domain.services.delta_profile` → `quant.amt.profile.delta_profile`
- `app.domain.fabio_ai.strategy.squeeze_detector` → `quant.amt.market.squeeze`
- `app.domain.fabio_ai.services.mlx_compute` → KEEP legacy + `# TODO(migration)` (Track A3)

**Shims to leave** at each legacy path: `from quant.amt.market.<name> import *  # noqa: F401,F403` (+ docstring, + `__all__` if defined).

**Tests to port** (find under `backend/tests/`; port ALL hits for each module): market_state_engine, market_structure_classifier, opening_classifier, regime_detector, displacement_detector, break_detector, lvn_play_detector, acceptance_rejection, squeeze_detector → copy into `tests/quant/amt/market/`, imports → `quant.amt.market.*`.

**Parity tests** (`tests/quant/amt/market/test_*_parity.py`) via `assert_parity` (legacy shim vs moved) on fixed inputs:
- `detect_market_state`: a set of (price, poc, vah, val, tick_size, flags) tuples covering BALANCED/IMBALANCED + zones.
- `classify_zone`: above/below/inside.
- `classify_shape`-style: `MarketStructureClassifier.classify` on a synthetic candle series with clear structure.
- `OpeningTypeClassifier.classify`: a synthetic opening-drive series and a quiet open.
- `detect_displacement` / `detect_break`: synthetic data with a clear impulse vs noise.
- `detect_lvn_play`: synthetic profile with an LVN near price.
- `evaluate_scalp`-adjacent pure fns if trivial.
Only require parity for functions that are deterministic and take plain inputs (skip functions needing live session state — note which you skipped and why in the report).

**Verification (after EACH module):**
```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant -q --tb=short
cd backend && /Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/unit -q --tb=short
```
Report pass/skip/error counts; the 4 pre-existing errors (gymnasium + 3 httpx memory endpoints) must be unchanged.

**Zero-backend-import rule:** `grep -rn "import app\.\|from app\." quant/amt --include=*.py` → only sanctioned `# TODO(migration)` imports (`mlx_compute` in `market/structure.py`; `amt_analyzer` in `profile/factory.py` from Track A1).

## Report contract

Write your report to `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/track-a2-report.md`: commit hashes per module, `# TODO(migration)` imports left, test tails, parity-case→result map, any parity tests you skipped and why. Return: status, commits, one-line test summary, concerns.
