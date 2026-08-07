# Track A5 Report — AMT Analyzer hub → `quant/amt/analyzer.py`

**Worktree:** `/Users/apple/Documents/wt-gt-track-A5` (branch `migration/track-A5`)
**Status:** ✅ DONE — all commits landed, both verification suites green.

## Commits

| Hash | Message |
|---|---|
| `e8d8b44` | `refactor(quant): move amt_analyzer from backend brain` |
| `40b758a` | `refactor(quant): resolve amt_analyzer TODO in profile factory` |
| `83f59a5` | `test(quant): port amt_analyzer unit + parity tests` |

`git log --follow quant/amt/analyzer.py` confirms full history is preserved through the `git mv`.

## What was done

1. `git mv backend/app/domain/fabio_ai/services/amt_analyzer.py → quant/amt/analyzer.py` (1,383 lines).
2. Rewrote the ~40 `app.*` imports to `quant.*` per the brief map:
   - `quant.amt.compute` (was `mlx_compute`), `quant.amt.orderflow.{cvd,detectors,aggression,aggressive_prints,drive}`,
   - `quant.amt.profile.{classifier,volume_profile,lvn}`, `quant.amt.market.{state_engine,structure,opening,displacement,break_detector,lvn_play,acceptance_rejection}`,
   - `quant.amt.session.{context,ib_engine}`, `quant.contracts.{value_objects,enums,entities,constants,ports.config_port}`.
   - Logic left byte-identical (only import lines + stale path comments updated).
3. Shim at legacy path: `backend/app/domain/fabio_ai/services/amt_analyzer.py` = `from quant.amt.analyzer import *  # noqa: F401,F403`. All consumers (`amt_service.py`, `amt_handler.py`, `analysis_service.py`, `valentini_env.py`, `serialization/schemas.py`, `api/routers/analysis.py`) import OK via the shim.
4. Resolved the last `# TODO(migration)`: `quant/amt/profile/factory.py` now imports `IncrementalVolumeProfile` from `quant.amt.analyzer` (legacy import dropped).
5. Ported `backend/tests/unit/domain/test_amt_analyzer.py` (738 lines, 41 tests) → `tests/quant/amt/test_analyzer.py`, rewriting imports to `quant.*`. All 41 test names verified identical. 5 pre-existing skips (`TestIncrementalProfile`) preserved.
6. Wrote `tests/quant/amt/test_analyzer_parity.py` using `tests.quant.parity.assert_parity`.

## Observation TODO decision

`quant/amt/models/observation.py` **did NOT exist** in this worktree (Track E parallel). Per brief, imported `AMTObservation` from legacy with:

```python
# TODO(migration): switch to quant.amt.models.observation once Track E merges
from app.domain.fabio_ai.models.observation import AMTObservation
```

The file was NOT created. This is the only `app.*` import inside `quant/` introduced by this track (plus pre-existing ones in `quant/contracts/trading_context.py` / `quant/contracts/ports/exchange_strategy.py` from earlier tracks). The root `conftest.py` appends `backend/` to `sys.path`, so the legacy import resolves under pytest.

## Verification (after EACH commit)

```bash
/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant -q --tb=short
# → 864 passed, 10 skipped, 1 warning

cd backend && /Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/unit -q --tb=short
# → 1625 passed, 60 skipped, 3 errors (run with --ignore tests/unit/domain/test_valentini_rl.py)
```

- The 3 `test_optimizations.py` errors (`httpx` missing) and the `test_valentini_rl.py` collection error (`gymnasium` missing) are the pre-existing env errors noted in the brief — verified unchanged.
- `tests/quant` grew from 825→864 passed and 5→10 skipped with the ported tests.
- Ported tests: `tests/quant/amt/test_analyzer.py` + `test_analyzer_parity.py` → **39 passed, 5 skipped**.
- `backend/tests/validation/test_amt_validation.py` passes via shim (27 passed / 4 skipped).
- `backend/tests/validation/test_amt_stability_fixes.py::TestStructureHysteresis::test_hysteresis_parameters_increased` FAILS — **pre-existing** (verified failing on the base commit too; references `market_structure_classifier._DWELL_TICKS`, a module not touched by this track).

## Parity-case → result map (fixed 60-bar session, fresh `AMTAnalyzer()` per side)

`AMTAnalyzer.analyze(_session_bars())` — same OHLC shape as `tests/quant/test_golden_file.py::_session_bars`:

| Field | Value |
|---|---|
| `market_state` | `'BALANCED'` |
| `poc` | `100.1734` |
| `value_area_high` | `101.0404` |
| `value_area_low` | `98.9768` |
| `cvd_slope` | `0.0` |
| `aggression` | `0.5` |
| `ib_high` | `101.0` |
| `ib_low` | `99.0` |
| `profile_shape` | `'B'` |

`find_lvns` / `find_hvns` on a fixed 21-bucket profile → identical lists both sides (empty on this profile shape). All 3 parity tests PASS (`test_parity_analyze_key_fields`, `test_parity_find_lvns`, `test_parity_find_hvns`).

## Zero-backend-import rule

`grep -rn "import app\.\|from app\." quant/ --include="*.py"` in THIS worktree:

```
quant/amt/analyzer.py:31:from app.domain.fabio_ai.models.observation import AMTObservation   # TODO(migration) — Track E
quant/contracts/trading_context.py:24-25  # TODO(migration) — pre-existing from earlier tracks
quant/contracts/ports/exchange_strategy.py:21  # TODO(migration) — pre-existing from earlier tracks
```

The analyzer import is the sanctioned observation TODO (resolved when Track E merges `quant/amt/models/observation.py`); the `quant/contracts/*` ones predate this track.

## Concerns

1. **Observation TODO**: `quant/amt/analyzer.py` retains one `app.*` import (observation) until Track E lands `quant/amt/models/observation.py`. Must be switched then to satisfy the strict zero-import rule.
2. **Stash hygiene**: while verifying the pre-existing `test_amt_stability_fixes.py` failure I briefly popped the repo's pre-existing WIP stash (`stash@{0}`: "On stable_4: WIP: OI-feed/streaming/MLX before brain migration"). It was re-verified as preserved in the stash list and the worktree was returned to a clean HEAD state (all stray stash-pop files removed). No impact on the track commits.
3. **Pre-existing failure** in `backend/tests/validation/test_amt_stability_fixes.py` (`_DWELL_TICKS`) — not caused by this track; outside the brief's required `tests/unit` scope.
