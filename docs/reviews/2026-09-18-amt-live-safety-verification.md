# AMT Live Safety Verification

**Date:** 2026-09-18
**Scope:** Task 5 verification after the approved Task 1-4 commits
**Production behavior:** No production files were changed for this verification

## Directional AMT

The focused AMT regression command completed with `247 passed, 6 skipped, 2
failed`. The two failures are the known dirty-baseline DTO contract drift:
`quant/execution/exit_checks.py` reads stacked-imbalance keys that
`amt_result_to_dto` does not emit, and the decision-loop scanner no longer sees
the expected `legLvns` consumer. The approved Task 1 directional tests remain
covered by the prior Task 1 report (`6 passed` for the corrected engine,
directional compute, and analyzer propagation set).

The numerical AMT parity work remains deferred. This verification does not
change the 68.2% value-area, LVN, absorption, or range-bar thresholds.

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

## Known Baseline Failures

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
- One chaos assertion still expects unmatched close replay to raise, while the
  approved Task 4 behavior is replay-tolerant with structured diagnostics.

These failures were inspected and classified; no unrelated production or test
fixes were applied.

## Explicit Live Status

**NO-GO for live trading.**

The proxy live-entry boundary and durable projection contracts have focused
evidence, and paper/replay proxy behavior is covered. Live readiness is not
proven because the exact project release gate fails, the DTO and broader
baseline failures remain unresolved, certification is incomplete, and broker
readiness/partial-unknown-restart reconciliation still depends on a real broker
status provider and durable risk-reservation restoration. No live-readiness
claim is made. Continued paper/replay validation is the supported status.
