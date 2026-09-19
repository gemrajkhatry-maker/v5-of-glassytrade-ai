# Task 5 Report: AMT Live Safety Verification

## Status

Verification completed with an explicit **NO-GO for live trading**. Corrective
fixes applied for 3 high-severity design gaps identified in whole-branch review:
1. AMT scoring now uses resolved strategy direction (not bar delta)
2. Per-evidence-family provenance populated for live gating
3. CVD divergence direction-awareness in all market states

## Commands and Results

- `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt tests/quant/decision tests/quant/execution tests/quant/runtime tests/quant/test_certification.py -q`
  - `1516 passed, 39 failed, 3 skipped`.
- `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/architecture -q`
  - `33 passed, 4 failed`.
- `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt/orderflow tests/quant/amt/market backend/tests/unit/domain/test_amt_analyzer.py tests/architecture/test_amt_dto_contract.py -q`
  - `247 passed, 6 skipped, 2 failed`.
- `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_proxy_live_entry_block.py tests/quant/test_decision_loop.py tests/quant/test_submission_handler.py tests/quant/test_certification.py -q`
  - `68 passed, 1 skipped, 1 failed`; only the known `s5_conviction_formula_is_explicit` certification/DTO baseline failure remained.
- `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/test_exposure_state.py tests/quant/execution/test_live_partial_fill_reconciliation.py tests/quant/execution/test_restart_reconciliation.py tests/quant/execution/test_close_identity.py tests/quant/chaos/test_crash_recovery.py tests/quant/test_decision_loop.py tests/quant/test_submission_handler_integration.py -q`
  - `88 passed, 1 skipped, 1 failed`; the failure was the legacy unmatched-close-raises chaos assertion, conflicting with the approved Task 4 replay-tolerant behavior.
- `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/runtime/test_eventstore_failure_consistency.py tests/quant/runtime/test_snapshot_projection.py tests/quant/test_event_store_roundtrip_real.py tests/architecture/test_gap_architecture_contract.py -q`
  - `18 passed in 0.40s`.
- `make test-quant`
  - Exact Makefile command, completed with exit 1: `87 failed, 2609 passed, 11 skipped`.
  - An earlier run was tool-timeout terminated after 120 seconds; it was rerun to completion with a longer timeout. The latter result is authoritative.
- Final remediation focused run: `21 passed`; the broader AMT/decision/DTO
  run remains `150 passed, 2 failed`, with only the documented pre-existing
  DTO consumer drift failures.
- `git diff --check -- docs/amt/fabio_decision_pipeline.md docs/reviews/2026-09-11-full-system-adversarial-review.md docs/reviews/2026-09-18-amt-live-safety-verification.md .superpowers/sdd/task-5-report.md`
  - No output after the files were created; the check passed.

## Classification

- Directional AMT (corrected: scoring uses resolved strategy direction), 
  per-family provenance, CVD divergence direction-awareness, and proxy 
  live-entry blocking are covered by the corrective fixes.
- Known baseline failures: DTO consumer drift, dirty-worktree architecture
  findings, risk/runtime/telemetry/golden/certification failures, and the
  broader release-gate failures listed below. These remain unresolved.
- Proxy live-entry blocks and paper/replay proxy mode are covered; the only
  combined-suite failure is the known certification baseline defect.
- Partial, unknown, restart, and close identity focused tests remain covered by
  the approved Task 3 report. Broker readiness is still unresolved.
- Intentional behavior/test debt: the unmatched-close chaos assertion still
  expects an exception, while the approved Task 4 contract is replay-tolerant
  and emits structured diagnostics. This is stale/conflicting test debt, not
  a baseline production failure.
- The CHOP and stacked-imbalance behavior in `cc8baa9c` is pre-existing branch
  scope contamination, not new remediation behavior. It was preserved rather
  than destructively reverted; no additional CHOP/stacked behavior was added.
- Durable EventStore/projection and architecture contract tests passed.
- The full release gate fails due to known dirty-baseline DTO, risk, runtime,
  telemetry, architecture, and certification failures.
- Numerical AMT parity remains deferred.
- Broker readiness is not proven because real broker status and durable risk
  reservation restoration remain required for live startup reconciliation.

## Document Paths

- `docs/reviews/2026-09-18-amt-live-safety-verification.md`
- `docs/amt/fabio_decision_pipeline.md` (not modified; existing status was not
  factually contradicted)
- `docs/reviews/2026-09-11-full-system-adversarial-review.md` (not modified;
  existing NO-GO status remains accurate)
- `.superpowers/sdd/task-5-report.md`
