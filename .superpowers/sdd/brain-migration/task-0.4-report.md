# Task 0.4 — Reference port: `vwap_breakout.py` (worked example)

**Status:** DONE
**Commit:** `a276015ab64a05f60ffde882d415778951d0c2f2` — `refactor(quant): move vwap_breakout from backend brain`

## What was done

1. `git mv backend/app/domain/fabio_ai/services/vwap_breakout.py quant/decision/vwap_breakout.py` — history preserved (`git log --follow quant/decision/vwap_breakout.py` shows the original `258e45c feat(gates): add VWAP-breakout detector`).
2. Confirmed the module is pure: `grep -n "app\." quant/decision/vwap_breakout.py` is empty. No logic rewritten — file is byte-identical to the original.
3. Shim at legacy path `backend/app/domain/fabio_ai/services/vwap_breakout.py`:
   ```python
   """Re-export shim — moved to quant/decision/vwap_breakout.py. Delete in Phase 3."""
   from quant.decision.vwap_breakout import *  # noqa: F401,F403
   ```
4. Ported the existing backend tests (`backend/tests/unit/domain/test_vwap_breakout.py`, 5 tests) via `git mv` to `tests/quant/decision/test_vwap_breakout.py`, import switched to `quant.decision.vwap_breakout`.
5. Wrote parity test `tests/quant/decision/test_vwap_breakout_parity.py` comparing legacy shim vs moved module via `assert_parity` from `tests.quant.parity`.
6. Added `tests/__init__.py` + `tests/quant/__init__.py` and repo-root `conftest.py` — required infrastructure (see Concerns).

## Moved module body (unchanged)

```python
"""VWAP-band breakout detector with volume confirmation.

Pure, dependency-free signal detection for the AMT scalper backend.
"""


def detect_vwap_breakout(
    vwap: float, std: float, price: float, volume: float, avg_volume: float
) -> str | None:
    """Return 'LONG'/'SHORT' on a VWAP-band breakout with volume confirmation, else None."""
    if vwap <= 0 or std <= 0 or avg_volume <= 0:
        return None
    if price > vwap + std and volume > avg_volume * 1.2:
        return "LONG"
    if price < vwap - std and volume > avg_volume * 1.2:
        return "SHORT"
    return None
```

## Branch map (case → return)

The function has four outcomes. Cases below are from `test_vwap_breakout_parity.py::CASES`; each was chosen by reading the body first.

| # | kwargs | outcome | branch exercised |
|---|--------|---------|------------------|
| 1 | `vwap=100, std=1, price=102, volume=500, avg_volume=100` | `LONG` | `price > vwap+std` && `volume > 1.2*avg` (high volume) |
| 2 | `vwap=100, std=1, price=98, volume=500, avg_volume=100` | `SHORT` | `price < vwap-std` && `volume > 1.2*avg` (high volume) |
| 3 | `vwap=100, std=1, price=100.5, volume=50, avg_volume=100` | `None` | in-band, low volume → fall-through |
| 4 | `vwap=100, std=0, price=100, volume=0, avg_volume=0` | `None` | guard: `std <= 0` |
| 5 | `vwap=100, std=1, price=102, volume=150, avg_volume=100` | `LONG` | LONG just above volume threshold (150 > 120) |
| 6 | `vwap=50, std=0.5, price=49, volume=121, avg_volume=100` | `SHORT` | SHORT just above volume threshold (121 > 120) |
| 7 | `vwap=100, std=1, price=102, volume=120, avg_volume=100` | `None` | volume exactly at threshold — strict `>` fails → fall-through |
| 8 | `vwap=0, std=1, price=102, volume=500, avg_volume=100` | `None` | guard: `vwap <= 0` |
| 9 | `vwap=100, std=1, price=102, volume=500, avg_volume=0` | `None` | guard: `avg_volume <= 0` |

**Adjustment vs brief:** the brief's case 6 (`vwap=50, std=0.5, price=49, volume=90, avg_volume=100`) is commented "SHORT edge" but actually returns `None` — `volume=90` is not `> 120`. Changed to `volume=121` so it truly hits the SHORT branch, and added case 7 to pin the strict `>` volume threshold and guard cases 8/9.

## Test tails

- **Parity test** (`tests/quant/decision/test_vwap_breakout_parity.py`): `1 passed in 0.01s`
- **Full quant suite** (`python -m pytest tests/quant -q`): `289 passed in 1.54s` (283 baseline on HEAD + 5 ported + 1 parity)
- **Backend unit suite** (`cd backend && python -m pytest tests/unit -q`): `1742 passed, 61 skipped, 3 errors` — identical to the HEAD baseline. All errors are pre-existing and unrelated:
  - `tests/unit/domain/test_valentini_rl.py` — collection error, `ModuleNotFoundError: No module named 'gymnasium'` (confirmed on clean HEAD worktree).
  - `tests/unit/test_optimizations.py::TestDebugMemoryEndpoint::test_memory_endpoint_returns_{rss,gc_stats,gc_objects}` — `ModuleNotFoundError: No module named 'httpx'` (confirmed on clean HEAD worktree).
- **Shim importer verified**: `app.domain.fabio_ai.services.vwap_breakout.detect_vwap_breakout` is the same function object as `quant.decision.vwap_breakout.detect_vwap_breakout`; `gate_runner._detect_vwap_breakout` (lazy `from app.domain.fabio_ai.services.vwap_breakout import detect_vwap_breakout`) resolves and returns LONG/SHORT/None correctly.
- System tests `tests/system`: `8 passed` (untouched, sanity check).

## Files in commit

- `quant/decision/vwap_breakout.py` (moved, unchanged)
- `backend/app/domain/fabio_ai/services/vwap_breakout.py` (shim)
- `tests/quant/decision/test_vwap_breakout.py` (ported backend tests)
- `tests/quant/decision/test_vwap_breakout_parity.py` (new)
- `tests/__init__.py`, `tests/quant/__init__.py` (new — see Concerns)
- `conftest.py` at repo root (new — see Concerns)

Not committed (per instructions): `.superpowers/`, `docs/superpowers/plans/`, `docs/AMT_ARCHITECTURE_PROPOSAL.md`.

## Concerns

1. **Repo-root `conftest.py` + `tests/__init__.py`/`tests/quant/__init__.py` are new files beyond the brief's list**, added because the brief's parity-test recipe (`from tests.quant.parity import assert_parity` + `from app.domain.* import ...`, run from repo root) cannot work otherwise:
   - `app.*` is not importable from repo root — `backend/` must be on `sys.path`. A conftest is the central place; the brief's Files list has no conftest entry.
   - `tests.quant` is a **namespace package** (no `__init__.py`). Under pytest's prepend import mode + assertion rewriter, adding any test module that imports `tests.quant.*` breaks the full-suite run with `ModuleNotFoundError: No module named 'tests.quant'` (reproduced: 3 collection errors on HEAD+new files, zero on HEAD alone). Making `tests` and `tests.quant` real packages fixes it deterministically. The conftest **appends** (not prepends) `backend/` so `backend/tests/` cannot shadow the `tests` package.
   - Recommendation: later port tasks should treat this exact supporting set (root `conftest.py` + `tests/__init__.py` + `tests/quant/__init__.py`) as part of the recipe, or the plan owner should split a dedicated "test harness packaging" task.
2. **`git mv` + shim shows as M+A, not R** in the commit (legacy path legitimately becomes the shim, so git cannot record a pure rename). Content is byte-identical and `git log --follow` on the new path resolves the full pre-move history, so this is cosmetic.
3. **Pre-existing backend failures** (6, unrelated to this task): `gymnasium` and `httpx` missing from `amt_313` env. Suite is green modulo these, matching HEAD exactly.
4. The moved backend test file was **moved** (not copied) out of `backend/tests`; the legacy direct-test coverage now lives only in `tests/quant/decision/test_vwap_breakout.py`. Backend gate tests still reference the shim indirectly; shim import verified explicitly.
