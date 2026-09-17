# AMT Single-Authority Convergence — Execution Report

**Date:** 2026-09-17 · **Base:** `7b3dfecc` (`architecture/design-level-refactoring`)
**Plan:** `docs/superpowers/plans/2026-09-17-amt-single-authority-convergence.md`
**Merges:** `904382e0` (WS-D) → `edc35828` (WS-A) → `24049bef` (WS-B) → `d3bf606b` (WS-C)

## Outcome

The deterministic Fabio AMT gate pipeline is now the single entry authority, the
Trend/Mean-Reversion transition is real and enforced in one place, VA-fade
semantics require an actual failed-auction reclaim, and the dead second decision
path plus stale scaffolding are gone.

Net diff: **48 files, +673 / −1410 (net −737 lines)**.

## Decisions delivered

| # | Decision | Evidence |
|---|---|---|
| D1 | AMT gates are the only entry authority; TimesFM demoted to a forecast provider | `quant/strategies/selection.py`, `quant/runtime.py` (no `TIMESFM_END_TO_END` branch), `quant/decision/forecast_provider.py` |
| D2 | State selects model, evidence overrides, enforced once | `quant/decision/model_router.py`; `DecisionService.evaluate()` (`select_model` / `allows`) |
| D3 | Full prune | `quantv2/` importers = 0; 8 stale worktrees removed (dirty ones preserved as WIP commits); `live_oms` −72 unreachable lines; dead `forecast` param removed |
| D4 | Sizing stays deterministic | `SessionRisk.position_size` no longer accepts an unread `forecast` |
| D5 | Forecasts kept as a provider | `TimesFMEngine.last_forecast_for` via `fresh_forecast()`; `TimesFMTradingStrategy` deleted |

## Structural proof

- `grep "def should_enter" quant/` → exactly one implementation (`amt_scalping.py:46`) plus the protocol declaration.
- `grep "TimesFMTradingStrategy"` across the repo → 0 hits.
- `grep "TIMESFM_END_TO_END" quant/` → 0 reads (one stale comment fixed).
- `grep "import quantv2"` → 0 hits.
- `model_router` is imported only by `decision_service.py`.

## Verification

- Baseline failure set captured at `7b3dfecc` for the affected files: **40 pre-existing failures**.
- Post-merge and post-fix: **identical-or-better; 0 new regressions** (≤ 45-failure ledger baseline).
- Two regressions found during integration and fixed:
  - `test_timesfm_sizing::test_session_risk_delegation_to_timesfm` asserted the removed no-op `forecast=` param → rewritten to the deterministic contract (`80f8477b`).
  - `test_fabio_india_scenarios::test_scenario_value_area_fade_day` fixture closed *above* VAH (still outside VA) → fixture corrected to a true reclaim close (`1c90643c`).
- D2-obsolete tests updated to the new contract: `tests/test_fabio_alignment.py` now 7/7 pass (`f72daec2`), previously 2 failing.
- Full decision suite green after resolving one merge conflict in `test_decision_service.py`.

## Behaviour changes (intended, per D1/D2)

1. `TIMESFM_END_TO_END=true` no longer swaps the entry strategy — deployments
   that relied on the E2E path now trade the deterministic gates.
2. Trend setups are blocked in a BALANCED auction unless certified evidence or
   an initiative break overrides; mean-reversion fades are blocked in IMBALANCED.
3. VA fades only fire after a reclaim close inside the VA, and always target POC.

## Known remaining risks / follow-ups

- The two pre-existing `tests/quant/certification` / `test_production_correctness`
  failures were red at base; they encode pre-D2 expectations and should be
  re-examined when the certification goldens are next touched.
- `scripts/pre_release_decision_check.py` lost its dead E2E probes; doc
  references to the deleted `scripts/audit_e2e_entry_probe.py` may dangle.
- Determinism/certification goldens were NOT re-golded because no golden
  references a VA-fade decision and the affected traces were already failing.

## Rollback

Revert the four merge commits in reverse order (WS-C → WS-B → WS-A → WS-D). The
superseded half-built `analyzer_setup_type` router is preserved in `git stash`
(`stash@{0}`) if it is ever needed as reference.
