# Phase 3 Report — Delete the legacy brain + shims (audit "kill legacy + delete shims")

**Worktree:** `/Users/apple/Documents/wt-gt-P3` · **Branch:** `migration/P3`
**Base:** `74f1f6a` (clean checkout confirmed via `git status --short` + `git log --oneline -1`)

## Status

**DONE_WITH_CONCERNS** — all brief steps executed, all verification green. The single
material deviation is that the brief's "~18 stragglers" scope undercounted the true
dependency surface: ~57 test files under `tests/quant` / `tests/system` and 5 files under
`backend/config` / `backend/scripts` also imported the legacy `app.domain.*` brain and had
to be migrated to keep both verification suites green. All were handled; details below.

## Commits

| # | hash | message |
|---|---|---|
| 1 | `6765b10` | `refactor(backend): swap straggler imports to quant.*` |
| 2 | `4e12bfa` | `refactor(backend): relocate ops modules to app.domain.ops` |
| 3 | — (skipped) | brief's commit 3 was `move strategy detectors to quant.amt.strategy (if moved)` — strategy files were **deleted**, not moved (see decision) |
| 4 | `ccf7903` | `refactor(backend): delete legacy brain + shims` |
| 5 | `43e6dd5` | `chore(backend): update scripts/config for brain migration` |

No commit touches `.superpowers/`, `docs/superpowers/plans/`, or `docs/*.md` (verified via
`git show --name-only` on each commit).

## Step 1 — Straggler swaps (production)

18 `backend/app` stragglers swapped from `app.domain.*` → `quant.*` (the 17 enumerated in
the brief plus `application/services/trading_session.py`, discovered by grep). Additional
stragglers found and swapped:
- `application/services/session_state_manager.py` — two `__import__("app.domain.trading.models.aggregates" / "app.domain.fabio_ai.services.learning_engine")` runtime strings.
- `application/services/trade_journal.py`, `application/services/gap_detector.py`,
  `application/stream_manager.py` + `tests/unit/application/test_lee_ready_spike.py` — `app.shared.timezones` shim (required empty before Step 6 deletion).
- `backend/config/consolidated.py` — `app.domain.models.exchange_config`.
- `backend/scripts/dataset_render.py`, `verify_scanner_goldm_silverm.py`,
  `walkthrough_architecture.py`, `oi_wall_integration_example.py` — `app.domain.fabio_ai.*` / `app.domain.services.*`.

All swaps are path-only (no logic changes). Canonical paths were taken from each shim's
own "moved to …" docstring and verified against `quant/`. No circular-import fallbacks
were needed (`quant` imports zero `app.*`).

## Step 2 — Zero stragglers

`grep "from app.domain\|import app.domain" backend/app` (outside `backend/app/domain/`)
returns **only**: `app.domain.ops.*` and `app.domain.models.exchange` (the two allowed
KEEP sets). No other references remain in `backend/app`, `backend/tests`, or `backend/config`.
`grep "app.shared.timezones"` is empty.

## Step 3 — Ops relocation

`git mv` of the 6 ops modules from `backend/app/domain/services/` → `backend/app/domain/ops/`
(created `ops/__init__.py`). Fixed internal imports: `mobile_alerts.py` now imports
`quant.contracts.ports.notification_adapter`; other five had no `app.domain` imports.
Swapped all importers (`metrics.py`, `composition_root.py`, `watchdog_manager.py`,
`startup_contracts.py`, `trading_session.py`, `main.py`, plus 5 test files) to
`app.domain.ops.<same>`.

## Step 4 — Strategy modules: **DELETED** (not moved)

`backend/app/domain/fabio_ai/strategy/{protocols,setup_detector,fabio_detectors}.py` have
**no production importer** — `backend/app/config_models/loader.py` does not import them
(verified by grep + direct inspection). They are real (non-shim) files whose logic is
superseded: `quant/amt/analyzer.py` carries its own private
`_extract_session_open` / `_classify_day_type` / `_compute_effective_market_state`, and
`quant.amt.profile.volume_profile.compute_value_area` covers the VA math. Per the brief's
"if dead (no real importers besides each other), `git rm` them and report" branch, the three
files were deleted. `squeeze_detector.py` is a shim (`→ quant.amt.market.squeeze`) with zero
importers and died with the `fabio_ai/` tree.

Because 4 `backend/tests/unit/domain/` files (`test_strategy.py`, `test_fabio_detectors.py`,
`test_fabio_detectors_extended.py`, `test_failed_auction_detector.py`, **32 tests**) test
exclusively this deleted code, they were deleted with it (keeping them would break
collection = a new failure).

## Step 5 — trade_aggregate: **KEPT** at `app.domain.ops/trade_aggregate.py`

Real consumers exist (`backend/tests/unit/domain/test_invariants.py`,
`backend/tests/unit/domain/test_trade_aggregate.py` — heavy `Trade` / `create_trade` /
`create_trade_from_snapshot` usage). `quant.contracts.aggregates` provides only
`Portfolio`/`PortfolioConfig`/constants — **no `Trade`/`create_trade`**, so the API does
not match and the "swap to quant.contracts.aggregates" branch is not viable. Moved the file
to `app.domain.ops/trade_aggregate.py`, fixed its internal `enums` import to
`quant.contracts.enums`, and repointed the two test files.

## Step 6 — Legacy brain deleted

`git rm -r`: `backend/app/domain/{fabio_ai,probability,trading,ports,services}`,
`backend/app/domain/constants.py`, `backend/app/domain/models/exchange_config.py`,
`backend/app/shared/timezones.py`. Kept: `backend/app/domain/__init__.py`,
`backend/app/domain/models/{__init__,exchange,market_state}.py`,
`backend/app/domain/ops/`. `models/__init__.py` had its `exchange_config` re-export removed
(no external consumers of `app.domain.models` package existed).
Post-deletion grep for the deleted module names in `backend/app` is **empty**.

## Step 7 — Scripts/config

- `backend/start_preflight.sh` — globs `backend_root.rglob("*.py")` safely; no path refs to
  deleted dirs. Ran it: **0 errors, 2 warnings** (paper-mode credentials + MLX model path — env).
- `backend/.importlinter` — kept 3 contracts (domain, application, infrastructure).
  Removed the stale `app.application.range_bar_builder` entry from contract 2 (module deleted
  in an earlier chore commit `f123553`, which had left import-linter **unrunnable** —
  pre-existing breakage). Ran `lint-imports`: **3 kept, 0 broken**.
- `backend/pytest.ini` — no references to deleted modules; unchanged.
- `conftest.py` (repo root) — updated stale docstring (no longer about legacy-shim parity);
  code kept because quant/system tests still import live `app.application.*` / `app.infrastructure.*`.
- `backend/STARTUP_RUNBOOK.md` — no brain path references; unchanged.

## Step 8 — Verification (exact counts)

- `backend/tests/unit`: **1292 passed, 60 skipped, 4 errors** (`--continue-on-collection-errors`).
  The 4 errors are the pre-existing env ones (gymnasium `test_valentini_rl` + 3 httpx
  `TestDebugMemoryEndpoint`). Baseline was 1324 passed; **−32 = exactly the 32 deleted
  strategy tests** — no other test regression.
- `tests/quant`: **1455 passed, 30 skipped, 0 errors** — exactly matches the baseline
  (`74f1f6a`) count (verified by stash-and-run diff; the two identity-only parity tests
  whose bodies were removed were restored with canonical-identity assertions).
- `python -c "import app.main; import quant; import app.domain.ops"` → OK (requires
  `backend/` on `PYTHONPATH`, same as the test harness; `app.domain.ops.startup_reconciliation`
  executes on import).

## Scope-expansion detail (the "~18 stragglers" was an underestimate)

`tests/quant` / `tests/system` contained **57 files / 98 import lines / ~107 parity calls**
that imported the legacy brain through the re-export shims. Because the brief's own Step 8
hard-requires `pytest tests/quant` green while Step 6 deletes the brain, these had to be
migrated. Since every shim is `from quant.X import *`, the "legacy" side was byte-identical
to the `quant` side, so all `assert_parity(legacy_*, quant_*, …)` differential comparisons
were converted to quant-only execution (smoke) or quant-only assertions; all
`Legacy*`/`legacy_*` imports and legacy-side constructions were removed. 200 + 95 + 52
script-driven rewrites plus ~20 per-file manual repairs. The `tests/quant/parity.py`
harness is now unused (zero callers) but kept, and its own unit test still passes.

## Concerns / flags

1. **Unanticipated scope:** ~57 `tests/quant`/`tests/system` files + 5 `backend/config`/`backend/scripts`
   files imported the legacy brain and required migration. The brief described ~18 files.
   All handled; suites match baseline counts. This should be recorded so reviewers know the
   parity-test surface was intentionally de-scoped (legacy-vs-quant differential tests are
   meaningless once the legacy side is deleted).
2. **32 strategy tests deleted** with the dead strategy modules (Step 4). They tested only
   deleted legacy code; no `tests/quant` equivalents existed.
3. **Dead pre-existing references left untouched** (not collected by either verification
   suite; broken before this phase):
   - `tests/test_fabio_alignment.py:28` → `backend.app.domain.services.session_phase_gate`
     (module never existed in the tree).
   - `backend/scripts/oi_wall_integration_example.py` and `backend/scripts/demo_oi_wall_detection.py`
     → `backend.app.domain.services.oi_wall_detector` (module never existed).
4. **trade_aggregate** is a 770-line Q-02 duplicate that had to be *kept* (real test
   consumers, no `quant` equivalent). It now lives at `app.domain.ops/trade_aggregate.py`.
   A future consolidation onto `quant.contracts.aggregates` (or a new `quant` Trade aggregate)
   would let it be deleted.
5. The brief's `import app.main` command requires `backend/` on `PYTHONPATH`; run with
   `PYTHONPATH=backend` (matches how the test harness resolves `app`).
