# Phase 1 Track A5 — AMT Analyzer hub → `quant/amt/analyzer.py`

**Worktree:** `/Users/apple/Documents/wt-gt-track-A5` (branch `migration/track-A5`). Do ALL work inside this worktree. Commit there. Do NOT touch `/Users/apple/Documents/v5-of-glassytrade-ai`.

**From:** docs/superpowers/plans/2026-08-06-quant-brain-migration.md — Phase 1, Track A5. This is the LAST analysis module — the hub that imports most of the analysis cluster. It must resolve the final `# TODO(migration)` in `quant/amt/profile/factory.py`.

**Module to move:**
- `backend/app/domain/fabio_ai/services/amt_analyzer.py` (1,383 lines) → `quant/amt/analyzer.py`
  - Exports: `AMTConfig`, `AMTAnalyzer`, `IncrementalVolumeProfile` (re-export), `find_lvns`, `find_hvns`.

**Dependencies (all already in `quant/*` in this worktree — the worktree is based on stable_4 which includes Tracks A1–A4 + Phase 0):**
- `quant.amt.compute` (was mlx_compute)
- `quant.amt.orderflow.{cvd,detectors,aggression,aggressive_prints,footprint,tick_delta,drive}`
- `quant.amt.profile.{classifier,volume_profile,factory,lvn}`
- `quant.amt.market.{state_engine,structure,opening,regime,displacement,break_detector,lvn_play,acceptance_rejection}`
- `quant.amt.session.{context,context_factory,eia,ib_engine,npoc,one_min_bar}` (+ symbol_registry, futures_provider, selector as needed)
- `quant.contracts.{value_objects,enums,constants,timezones,candle_metrics,tick_utils,decimal_utils}`
- `quant/amt/models/observation.py` — **NOTE:** Track E (parallel) is moving `observation.py` to `quant/amt/models/observation.py`. It may not exist in your worktree when you start. If it is missing, import `AMTObservation` from the legacy `app.domain.fabio_ai.models.observation` with `# TODO(migration): switch to quant.amt.models.observation once Track E merges`. Do NOT create the file yourself.

**Rewrites to make inside `amt_analyzer.py`:**
- `app.domain.fabio_ai.services.mlx_compute` → `quant.amt.compute`
- `app.domain.fabio_ai.services.cvd_tracker` → `quant.amt.orderflow.cvd`
- `app.domain.fabio_ai.services.orderflow_detectors` → `quant.amt.orderflow.detectors`
- `app.domain.fabio_ai.services.aggression_scorer` → `quant.amt.orderflow.aggression`
- `app.domain.services.aggressive_prints` → `quant.amt.orderflow.aggressive_prints`
- `app.domain.fabio_ai.services.footprint_analyzer` → `quant.amt.orderflow.footprint`
- `app.domain.fabio_ai.services.drive_tracker` → `quant.amt.orderflow.drive`
- `app.domain.fabio_ai.services.profile_classifier` → `quant.amt.profile.classifier`
- `app.domain.fabio_ai.services.profile_factory` → `quant.amt.profile.factory`
- `app.domain.fabio_ai.services.market_state_engine` → `quant.amt.market.state_engine`
- `app.domain.fabio_ai.services.market_structure_classifier` → `quant.amt.market.structure`
- `app.domain.fabio_ai.services.opening_classifier` → `quant.amt.market.opening`
- `app.domain.fabio_ai.services.regime_detector` → `quant.amt.market.regime`
- `app.domain.fabio_ai.services.session_context*` → `quant.amt.session.context*`
- `app.domain.fabio_ai.services.npoc_tracker` → `quant.amt.session.npoc`
- `app.domain.services.<x>` (volume_profile, lvn_detector, delta_profile, initial_balance_engine, ib_breakout_scalp, displacement_detector, break_detector, lvn_play_detector, acceptance_rejection, tick_delta, one_min_bar_engine, candle_metrics, tick_utils, decimal_utils, market_data_utils) → `quant.amt.*` / `quant.contracts.*` per the established map
- `app.domain.trading.models.*` / `app.domain.constants` / `app.domain.ports.*` / `app.shared.timezones` → `quant.contracts.*`
- `app.domain.fabio_ai.models.observation` → `quant.amt.models.observation` (or legacy with TODO, per above)

**RESOLVE the last TODO:** after moving `amt_analyzer.py`, update `quant/amt/profile/factory.py` to import `IncrementalVolumeProfile` from `quant.amt.analyzer` (drop its `# TODO(migration)` legacy import). Commit this as its own commit `refactor(quant): resolve amt_analyzer TODO in profile factory`.

**Shim** at legacy path: `from quant.amt.analyzer import *  # noqa: F401,F403`. Consumers that must keep working via shims: `amt_service.py` (AMTAnalyzer), `amt_handler.py` (AMTAnalyzer, IncrementalVolumeProfile), `analysis_service.py` (AMTAnalyzer), `valentini_env.py` (AMTAnalyzer — Track E parallel), `serialization/schemas.py` (lazy), `api/routers/analysis.py`.

**Tests to port:** `backend/tests/unit/domain/fabio_ai/test_amt_analyzer*.py` (all hits) → `tests/quant/amt/test_analyzer.py` (rewrite imports). Also any `backend/tests/validation/*` that exercise the analyzer directly.

**Parity tests** via `assert_parity` (legacy shim vs moved) on fixed inputs:
- `AMTAnalyzer.analyze`: run on a fixed synthetic 60-bar session (reuse the shape from `tests/quant/test_golden_file.py::_session_bars`) and assert parity of the output `AMTResult` key fields: `market_state`, `poc`, `value_area_high`, `value_area_low`, `cvd_slope`, `aggression`, `ib_high`, `ib_low`, `profile_shape`. Use a fresh `AMTAnalyzer()` per side (the class is stateful).
- `find_lvns`/`find_hvns` on a fixed profile.
Note: `AMTAnalyzer` is documented "NOT internally thread-safe" — that is fine here; do not change it.

**Verification (after EACH commit):**
```bash
cd /Users/apple/Documents/wt-gt-track-A5
/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant -q --tb=short
cd backend && /Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/unit -q --tb=short
```
(The worktree has its own `backend/`. 4 pre-existing env errors unchanged. The `test_valentini_rl.py` collection error is pre-existing.)

**Zero-backend-import rule:** after this track, `grep -rn "import app\.\|from app\." quant/ --include=*.py` must be EMPTY except Track-B's `gate_runner` loss_tracker TODO and Track-E's `valentini_env` amt_analyzer TODO (which live in other worktrees and will be resolved after merge). In THIS worktree, `quant/` must have zero `app.*` imports.

**Report:** write to `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/track-a5-report.md` (commit hashes, the observation.py TODO decision, test tails, parity-case→result map). Reply: status, commits, one-line test summary, concerns.
