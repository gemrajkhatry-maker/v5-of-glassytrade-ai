# Phase 1 Track A1 — Profile & structure cluster → `quant/amt/profile/`

**From:** docs/superpowers/plans/2026-08-06-quant-brain-migration.md — Phase 1, Track A1.

**Goal:** Port the volume-profile / delta-profile / LVN-HVN / profile-classification cluster from the backend brain into `quant/amt/profile/`, using the move-with-shim + parity recipe established by Task 0.4 (`tests/quant/decision/test_vwap_breakout_parity.py` is the worked example). One commit per module (or per 2 tightly-coupled modules); every commit leaves quant + backend suites green.

**Recipe (from T0.4):** `git mv` → rewrite `app.*` imports to `quant.*` → leave re-export shim at legacy path → port existing backend unit tests to `tests/quant/amt/profile/` → add `assert_parity` test (compare legacy shim vs moved module on fixed inputs) → run quant suite + backend unit suite → commit `refactor(quant): move <module> from backend brain`.

**Modules to move (leaf-deps-first):**

1. `backend/app/domain/services/volume_profile.py` → `quant/amt/profile/volume_profile.py`
   - Exports: `VolumeProfileSnapshot`, `compute_bucket_index`, `compute_poc`, `compute_value_area`, `build_snapshot`, `compute_optimal_buckets`, `create_profile`, `IncrementalVolumeProfile`.
   - Zero brain imports (pure). No import rewrites needed.
2. `backend/app/domain/services/delta_profile.py` → `quant/amt/profile/delta_profile.py`
   - Exports: `detect_high_delta_zones`. Pure.
3. `backend/app/domain/services/lvn_detector.py` → `quant/amt/profile/lvn.py`
   - Exports: `LVNLevel`, `HVNLevel`, `find_lvns`, `find_hvns`, `LVNPersistenceTracker`. Imports `app.domain.constants` → `quant.contracts.constants`.
4. `backend/app/domain/fabio_ai/ports/three_align.py` → `quant/amt/profile/three_align_input.py`
   - Exports: `ThreeAlignInput` (protocol). No deps.
5. `backend/app/domain/fabio_ai/services/profile_factory.py` → `quant/amt/profile/factory.py`
   - Exports: `IncrementalProfileFactory`. Imports `IncrementalVolumeProfile` from `amt_analyzer` (NOT yet moved — Track A5). Keep that import pointing at the **legacy** `app.domain.fabio_ai.services.amt_analyzer` with a `# TODO(migration): switch to quant.amt.analyzer once Track A5 lands` comment. `IncrementalVolumeProfile` is re-exported by `quant.amt.profile.volume_profile` for now.
6. `backend/app/domain/fabio_ai/services/profile_classifier.py` → `quant/amt/profile/classifier.py`
   - Exports: `ProfileShape`, `POCMigration`, `classify_shape`, `extract_bimodal_lvn`, `POCMigrationTracker`. Imports `mlx_compute` (Track A3 — NOT moved yet): keep the **legacy** import `from app.domain.fabio_ai.services import mlx_compute as mc` with `# TODO(migration): switch to quant.amt.compute once Track A3 lands`.

**Import-rewrite map (for moved files):**
- `app.domain.trading.models.*` → `quant.contracts.*`
- `app.domain.constants` → `quant.contracts.constants`
- `app.domain.services.volume_profile` → `quant.amt.profile.volume_profile`
- `app.domain.services.delta_profile` → `quant.amt.profile.delta_profile`
- `app.domain.services.lvn_detector` → `quant.amt.profile.lvn`
- `app.domain.fabio_ai.ports.three_align` → `quant.amt.profile.three_align_input`
- `app.domain.fabio_ai.services.profile_factory` → `quant.amt.profile.factory`
- `app.domain.fabio_ai.services.profile_classifier` → `quant.amt.profile.classifier`

**Shims to leave** at each legacy path (delete in Phase 3): `from quant.amt.profile.<name> import *  # noqa: F401,F403`. Include `__all__` if the source defines it. For `volume_profile.py`, the legacy consumers (e.g. `fabio_ai/services/amt_analyzer.py`) import `create_profile`, `compute_value_area`, `IncrementalVolumeProfile` — the shim must re-export all three.

**Tests to port** (find exact names under `backend/tests/`; port ALL hits for these modules): volume profile, delta profile, lvn detector, profile classifier, profile factory. Copy into `tests/quant/amt/profile/`, rewriting imports to `quant.amt.profile.*`.

**Parity tests** (`tests/quant/amt/profile/test_*_parity.py`) — compare legacy (via shim) vs moved on fixed inputs; use `assert_parity` from `tests.quant.parity`:
- `create_profile`: empty list, single candle, a 60-bar synthetic session (reuse the shape from `tests/quant/test_golden_file.py::_session_bars`), and a concentrated/edge case.
- `compute_value_area`: POC at an edge bucket (boundary-pair regression) + a wide profile.
- `find_lvns` / `find_hvns`: default profile + a profile with an obvious bimodal valley.
- `classify_shape`: P-shape, b-shape, D-shape synthetic profiles.
- `detect_high_delta_zones`: a synthetic bucket map with a clear high-delta zone.

**Verification (after EACH module, then once more at the end):**
```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant -q --tb=short        # stays green
cd backend && /Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/unit -q --tb=short   # stays green via shims
```
Backend suite: note the known pre-existing collection errors (`gymnasium`, `httpx` memory endpoints) — those are unchanged; count the pass numbers and report them.

**Zero-backend-import rule:** `grep -rn "import app\.\|from app\." quant/amt --include=*.py` must show ONLY the sanctioned `# TODO(migration)` legacy imports (`mlx_compute`, `amt_analyzer`) in `factory.py`/`classifier.py`.

## Report contract

Write your report to `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/track-a1-report.md`: commit hash(es) per module, the moved-file targets, the exact `# TODO(migration)` imports left, test tails (quant + backend unit), and the parity-case→result map. Return: status, commits, one-line test summary, concerns.
