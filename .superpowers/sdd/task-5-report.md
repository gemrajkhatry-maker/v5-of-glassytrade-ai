# Task 5 Report: AMT Live Safety Verification

## Status

Verification completed with an explicit **NO-GO for live trading**. No
production behavior or production source was changed.

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
- `git diff --check -- docs/amt/fabio_decision_pipeline.md docs/reviews/2026-09-11-full-system-adversarial-review.md docs/reviews/2026-09-18-amt-live-safety-verification.md .superpowers/sdd/task-5-report.md`
  - No output after the files were created; the check passed.

## Classification

- Directional AMT focused behavior is covered by the approved Task 1 report;
  current failures are DTO consumer drift outside Task 5.
- Proxy live-entry blocks and paper/replay proxy mode are covered; the only
  combined-suite failure is the known certification baseline defect.
- Partial, unknown, restart, and close identity focused tests are covered by
  the approved Task 3 report; the current chaos failure expects superseded
  unmatched-close behavior.
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
