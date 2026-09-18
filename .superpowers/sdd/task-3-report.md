# Task 3 Report

## Files

- `quant/execution/exposure.py`: explicit unknown exposure, durable reconciliation outcomes, and query-failure preservation.
- `quant/execution/execution_state_machine.py`: partial fill transition to reconciliation.
- `quant/engine/submission_handler.py`: unknown broker outcomes preserve exposure and risk reservation.
- `quant/execution/live_oms.py`: reconciliation exception and durable close intent propagation.
- `backend/app/infrastructure/adapters/dhan_broker_adapter.py`: partial/unknown entry normalization and shared collar/fallback close identity.
- `quant/runtime.py`: restore unresolved inflight broker orders before decisions.
- `quant/multi_engine.py`: startup wiring for unresolved order restoration.
- Focused execution tests plus the existing close idempotency test.

## Red / Green

- Red: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/test_live_partial_fill_reconciliation.py tests/quant/execution/test_restart_reconciliation.py tests/quant/execution/test_close_identity.py -q` -> `4 failed, 1 passed`.
- Green focused: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/test_exposure_state.py tests/quant/execution/test_execution_state_machine.py tests/quant/execution/test_live_partial_fill_reconciliation.py tests/quant/execution/test_restart_reconciliation.py tests/quant/execution/test_close_identity.py tests/quant/execution/test_live_oms.py tests/quant/execution/test_paper_restart_reconciliation.py backend/tests/unit/infrastructure/test_close_order_idempotency.py tests/quant/test_submission_handler_integration.py -q` -> `57 passed`.
- Broader execution/recovery run -> `442 passed, 10 failed, 1 skipped`; the ten failures are unrelated pre-existing risk-sizing/tier expectations in the dirty baseline.

## Lifecycle Decisions

- Partial and unknown live entry outcomes raise or map to `RECONCILIATION_REQUIRED`; they do not become rejection or flat.
- Risk reservation remains held on unresolved outcomes; entry guards already reject while exposure is not openable.
- Inflight durable order rows restore unresolved exposure during engine construction before decision processing.
- Broker query failure leaves unresolved exposure intact; explicit `OPEN` and `FLAT` snapshots resolve it.
- Collar and market fallback close attempts use one economic close intent ID; broker transport IDs remain separate.

## Concerns

- Live broker reconciliation still depends on the host supplying an actual broker status query and invoking `ExposureState.reconcile()` with its normalized result.
- The broader suite has unrelated failures from concurrent dirty baseline changes; no live-readiness claim is made.
- `tests/quant/execution/test_pyramid_integration.py` had an unrelated pre-existing modification and was not touched.
