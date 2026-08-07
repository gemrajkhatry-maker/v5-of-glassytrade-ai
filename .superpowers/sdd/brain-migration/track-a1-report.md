# Track A1 Report — Profile & structure cluster → `quant/amt/profile/`

**Branch:** `stable_4`
**Status:** DONE
**Date:** 2026-08-06

## Summary

Ported the volume-profile / delta-profile / LVN-HVN / profile-classification cluster from the backend brain into `quant/amt/profile/` using the move-with-shim + parity recipe from Task 0.4. Six modules moved, one commit each, all logic byte-identical (only import rewrites). Both suites stay green throughout.

## Commits (per module)

| Module | Legacy path → quant target | Commit |
|---|---|---|
| volume_profile | `backend/app/domain/services/volume_profile.py` → `quant/amt/profile/volume_profile.py` | `10e9fa1` |
| delta_profile | `backend/app/domain/services/delta_profile.py` → `quant/amt/profile/delta_profile.py` | `a739d3a` |
| lvn_detector | `backend/app/domain/services/lvn_detector.py` → `quant/amt/profile/lvn.py` | `3f5e02c` |
| three_align port | `backend/app/domain/fabio_ai/ports/three_align.py` → `quant/amt/profile/three_align_input.py` | `dcfdf41` |
| profile_factory | `backend/app/domain/fabio_ai/services/profile_factory.py` → `quant/amt/profile/factory.py` | `e8e9139` |
| profile_classifier | `backend/app/domain/fabio_ai/services/profile_classifier.py` → `quant/amt/profile/classifier.py` | `54231d3` |

All moves used `git mv` (history preserved). Each legacy path now holds a re-export shim:
`from quant.amt.profile.<name> import *  # noqa: F401,F403` with a "Delete in Phase 3" docstring. The `volume_profile` shim re-exports `create_profile`, `compute_value_area`, `IncrementalVolumeProfile`, and all other public names (via `import *`, no `__all__` in source) — `amt_analyzer.py`, `displacement_detector.py`, and `delta_profile_adapter.py` keep working through it.

## Sanctioned `# TODO(migration)` imports left (the ONLY backend imports in `quant/amt/`)

`quant/amt/profile/factory.py`:
```python
# TODO(migration): switch to quant.amt.analyzer once Track A5 lands
from app.domain.fabio_ai.services.amt_analyzer import IncrementalVolumeProfile
```

`quant/amt/profile/classifier.py`:
```python
# TODO(migration): switch to quant.amt.compute once Track A3 lands
from app.domain.fabio_ai.services import mlx_compute as mc
```

Zero-backend-import check:
`grep -rn "import app\.\|from app\." quant/amt --include=*.py` → exactly the 2 lines above.

## Import rewrites applied (all other imports → `quant.*`)

- `app.domain.trading.models.value_objects` → `quant.contracts.value_objects` (volume_profile, lvn, classifier)
- `app.domain.constants` → `quant.contracts.constants` (volume_profile: `VALUE_AREA_PCT`; delta_profile: `DELTA_ZONE_SIGMA_MULT`)
- three_align_input / factory: no intra-cluster import rewrites beyond the sanctioned legacy import.

## Tests

### Ported backend unit tests → `tests/quant/amt/profile/` (git mv, imports rewritten to `quant.amt.profile.*` / `quant.contracts.*`)

- `test_volume_profile.py` (from `backend/tests/unit/domain/`)
- `test_volume_profile_dynamic_buckets.py` (from `backend/tests/unit/domain/`)
- `test_lvn_detector.py` (from `backend/tests/unit/domain/`)
- `test_profile_classifier.py` — ported `TestProfileClassifier` + `TestPOCMigrationTracker` from `backend/tests/unit/domain/test_valentini_rl.py` (the rest of that file exercises CVD/session/env, out of Track A1 scope).
- `test_delta_profile.py` — new unit tests for the domain `detect_high_delta_zones` (the only backend test hit, `backend/tests/unit/test_delta_profile.py`, covers the infra `DeltaProfileAdapter`, which is not part of this track).

### Parity tests (`tests/quant/amt/profile/test_*_parity.py`, via `assert_parity` from `tests.quant.parity`)

| Parity test file | Cases | Result |
|---|---|---|
| `test_volume_profile_parity.py` | `create_profile`: empty list, single candle, 60-bar `_session_bars()` auto-buckets, 60-bar explicit buckets, concentrated/edge case, flat-range single-candle | PASS (parity + expected shapes) |
| | `compute_value_area`: POC-at-edge boundary-pair regression, wide 20-bucket profile, default-pct fallback, POC-at-top-edge | PASS |
| `test_delta_profile_parity.py` | `detect_high_delta_zones`: clear LONG zone, clear SHORT zone, empty map, default `sigma_mult` | PASS; LONG zone found at 100.0 |
| `test_lvn_parity.py` | `find_lvns`/`find_hvns`: uniform profile, single dip/spike, bimodal V-valley profile (default + `min_separation` variants) | PASS; bimodal valley LVN found at price 11.0 |
| `test_profile_classifier_parity.py` | `classify_shape`: P-shape, b-shape, D-shape, empty, 1-bucket; `POCMigrationTracker.state` rising + stable | PASS; letters verified (P, b, D) |
| `test_profile_factory_parity.py` | same class identity; config props; engine `get_profile()` from 8 shared candles; engine is `IncrementalVolumeProfile` | PASS |
| `test_three_align_input_parity.py` | same protocol class at both paths; is a `Protocol`; member surface | PASS |

## Test tails

- **Quant suite** (repo root, `tests/quant`): `394 passed` — baseline was `289 passed`; +105 (ported/parity tests). Run: `/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant -q --tb=short`.
- **Backend unit suite** (`backend/tests/unit`): `1680 passed, 61 skipped, 4 errors` — baseline was `1742 passed, 61 skipped, 4 errors`. The −62 is the git-mv'd profile tests (30 + 19 + 13). The 4 errors are the unchanged pre-existing collection/fixture failures (`gymnasium` missing in `test_valentini_rl.py`; 3 `httpx`-dependent `TestDebugMemoryEndpoint` errors in `test_optimizations.py`). Run: `/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/unit -q --tb=short --continue-on-collection-errors` (plain run is interrupted by the known `gymnasium` collection error; identical to baseline).

## Concerns

1. **`amt_analyzer` re-export cycle:** `factory.py` imports `IncrementalVolumeProfile` from legacy `amt_analyzer`, which in turn imports it from the `volume_profile` shim (which is the moved module). Same class object end-to-end, so parity is exact — but the factory import becomes circular-ish once Track A5 moves `amt_analyzer`; the TODO comment marks the switch point.
2. **`test_valentini_rl.py` collection error:** pre-existing (`gymnasium` not installed). The classifier tests I ported came from it; the file itself cannot collect in this env regardless of Track A1.
3. **No dedicated backend unit test for `detect_high_delta_zones` existed** — the backend test hits were for the infra adapter. Coverage for the moved domain function comes from the new `test_delta_profile.py` + parity test.
4. **Bimodal parity case needed a V-shaped valley**, not a flat plateau — a flat mid-profile produces no strict local minima (by design of `find_lvns`), so the "obvious bimodal valley" in the parity test uses a descending/ascending valley that yields an LVN at the center.
