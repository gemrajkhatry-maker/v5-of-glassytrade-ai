# AMT Live Safety Verification

**Date:** 2026-09-18
**Scope:** Task 5 verification after the approved Task 1-4 commits + corrective fixes
**Production behavior:** Corrective fixes applied for 3 high-severity design gaps

## Directional AMT (Corrected)

The AMT scoring no longer uses bar delta as a substitute for strategy direction.
Directional aggression/CVD qualification now occurs in the decision pipeline
(`quant/decision/gates_edge.py::rescore_aggression_with_direction`) where the
resolved `agent_direction` is available. The AMT engine computes raw components
without direction gating.

Focused regression: `tests/quant/amt/orderflow/test_directional_compute.py`,
`tests/quant/amt/test_amt_engine_direction.py` pass. The prior approach of
passing bar delta as `candidate_direction` has been removed.

## Proxy Live-Entry Gate

The proxy gate suite passed its direct gate and submission assertions. The
combined command produced `68 passed, 1 failed, 1 skipped`; the sole failure was
`tests/quant/test_certification.py::test_s5_conviction_formula_is_explicit`,
which is the known certification/DTO baseline failure documented by Tasks 1 and
2. The proxy-specific tests did not fail. Paper/replay proxy approval and
`PROXY_MODE` metadata are covered by the approved Task 2 evidence.

## Partial/Unknown/Restart Reconciliation

The targeted reconciliation and decision integration command produced
`88 passed, 1 failed, 1 skipped`. The failure was the legacy
`TestPositionIdMismatch::test_pyramid_close_mismatch_raises` assertion in
`tests/quant/chaos/test_crash_recovery.py`. Task 4 deliberately makes unmatched
close replay tolerant while emitting structured diagnostics, so this assertion
expects the superseded behavior; no production fix was made.

The approved Task 3 focused reconciliation set remains green (`21 passed` in
the final focused report, including partial, unknown, restart, and close
identity cases). Live broker readiness is still not proven: startup requires a
real broker status provider and durable risk-reservation data, and unresolved
startup issues remain entry-blocking.

## Per-Evidence-Family Provenance (Corrected)

Per-family provenance is now populated in `AMTResult.evidence_provenance` for
all five required families: footprint_imbalance, cvd_delta, ofi_depth,
absorption, stacked_imbalance. The AMT analyzer computes provenance from
available data sources (live tick footprint, CVD tracker source, order book
depth, absorption detector, contested zone). Live gating via
`live_evidence_exact()` requires every family to be `TICK_EXACT`; one non-exact
family blocks an otherwise exact aggregate. Paper/replay retains `PROXY_MODE`.

## CVD Divergence Direction-Awareness (Corrected)

CVD divergence confirmation is now direction-aware in all market states.
`gate_triple_a_edge` explicitly checks `cvd_divergence` against
`agent_direction`: BULLISH_DIV only confirms LONG, BEARISH_DIV only confirms
SHORT. This replaces the prior IMBALANCED-only check.

## Durable Event/Projection

The targeted durable lifecycle command passed: `18 passed in 0.40s` across
EventStore failure consistency, snapshot projection, event round-trip, and
architecture artifact contract coverage. The approved Task 4 regression set
also passed `43` tests. Append failure remains degraded and fail-closed for
canonical lifecycle state; snapshot fold failure does not fall back to mutable
operational state.

## Architecture Artifact

`tests/architecture/test_gap_architecture_contract.py` passed as part of the
`18 passed` targeted command. The tested artifact contains the durable order
intent, OMS/broker, normalized fill, reconciliation, position manager,
EventStore, canonical projection, WebSocket/UI, and dashed advisory narrative
edges. It does not claim exact Fabio parity.

## Tests

Commands were run from the repository root with the existing virtualenv.

| Command | Result |
|---|---|
| `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt tests/quant/decision tests/quant/execution tests/quant/runtime tests/quant/test_certification.py -q` | `1516 passed, 39 failed, 3 skipped` |
| `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/architecture -q` | `33 passed, 4 failed` |
| `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt/orderflow tests/quant/amt/market backend/tests/unit/domain/test_amt_analyzer.py tests/architecture/test_amt_dto_contract.py -q` | `247 passed, 6 skipped, 2 failed` |
| `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_proxy_live_entry_block.py tests/quant/test_decision_loop.py tests/quant/test_submission_handler.py tests/quant/test_certification.py -q` | `68 passed, 1 skipped, 1 failed` |
| `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/test_exposure_state.py tests/quant/execution/test_live_partial_fill_reconciliation.py tests/quant/execution/test_restart_reconciliation.py tests/quant/execution/test_close_identity.py tests/quant/chaos/test_crash_recovery.py tests/quant/test_decision_loop.py tests/quant/test_submission_handler_integration.py -q` | `88 passed, 1 skipped, 1 failed` |
| `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/runtime/test_eventstore_failure_consistency.py tests/quant/runtime/test_snapshot_projection.py tests/quant/test_event_store_roundtrip_real.py tests/architecture/test_gap_architecture_contract.py -q` | `18 passed` |
| `make test-quant` | **FAIL**, `87 failed, 2609 passed, 11 skipped`; exit 1 |

The exact `make test-quant` target is the Makefile release command and was run
to completion. An earlier invocation was tool-timeout terminated after 120
seconds; it was rerun with a longer timeout and the result above is the
authoritative result.

## Failure Classification

### Known Baseline Failures

- DTO consumer drift: missing `legLvn`, `legLvns`, stacked-imbalance, and
  `time` keys across the known consumers. This is outside Task 5 and the
  requested DTO consumer failure was not changed.
- Dirty-worktree architecture failures: `quant/engine/submission_handler.py`
  host import and unannotated silent exceptions in existing modified files.
- Dirty-baseline risk failures: lot sizing, risk tiers, day-of-week sizing,
  and house-money expectations.
- Dirty-baseline runtime failures: MagicMock risk fixtures fail while building
  `DecisionContext` because `consecutive_wins` is not numeric, alongside
  telemetry, approval, golden, and latch failures.
- Certification failure: `s5_conviction_formula_is_explicit` reaches no gate
  record because the current data-quality/DTO baseline path blocks it early.
These failures were inspected and classified; no unrelated production or test
fixes were applied.

### Intentional Behavior/Test Debt

- `tests/quant/chaos/test_crash_recovery.py::TestPositionIdMismatch::test_pyramid_close_mismatch_raises`
  expects unmatched close replay to raise. The approved Task 4 contract
  intentionally changed this behavior to replay-tolerant handling with
  structured diagnostics. The failure is stale/conflicting test debt, not a
  baseline production failure.

### Pre-existing Branch Scope Contamination

- Commit `cc8baa9c` introduced CHOP position-management and stacked-imbalance
  exit behavior, plus related range-bar/feed telemetry and risk-reset work.
  Those commits predate this remediation branch scope. They were preserved and
  not destructively reverted; no additional unrelated behavior was added here.

### Unresolved Regressions

- The release gate remains red with the failures reported below, including DTO
  consumer drift and broader dirty-worktree failures. These remain unresolved.

## Explicit Live Status

**NO-GO for live trading.**

The proxy live-entry boundary and durable projection contracts have focused
evidence, and paper/replay proxy behavior is covered. Live readiness is not
proven because the exact project release gate fails, the DTO and broader
baseline failures remain unresolved, certification is incomplete, and broker
readiness/partial-unknown-restart reconciliation still depends on a real broker
status provider and durable risk-reservation restoration. No live-readiness
claim is made. Continued paper/replay validation is the supported status.
