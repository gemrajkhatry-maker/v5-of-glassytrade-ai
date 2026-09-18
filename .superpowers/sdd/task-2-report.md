# Task 2 Report: Block Proxy AMT Entries in Live Mode

## Files

- `quant/decision/decision_service.py`
  - Added decision metadata support so provenance mode is retained on the existing `QuantDecision` contract.
- `quant/engine/decision_loop.py`
  - Detects the injected OMS-backed live mode before option translation, sizing, or OMS submission.
   - Blocks every non-`TICK_EXACT` quality with `PROXY_FLOW_BLOCKED`.
  - Preserves the existing certification and `DecisionProduced` paths.
  - Marks non-exact paper/replay decisions with `PROXY_MODE` metadata.
- `quant/runtime.py`
  - Supplies live-mode detection from the composition root's `LiveOMS`/`PaperOMS` boundary.
- `tests/quant/decision/test_proxy_live_entry_block.py`
   - Covers every non-exact live quality, exact live pass, real `LiveOMS` broker non-submission, paper proxy approval/metadata, and pre-translation ordering.

## TDD Results

Red:

```text
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_proxy_live_entry_block.py -q
8 failed, 2 passed
```

The failures showed that non-exact qualities were not all blocked, the proxy decision reached the real submission path, and the gate ran after option translation.

Green:

```text
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_proxy_live_entry_block.py -q
10 passed
```

Focused affected suites:

```text
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_proxy_live_entry_block.py tests/quant/test_decision_loop.py tests/quant/test_submission_handler.py tests/quant/test_certification.py -q -k 'not s5_conviction_formula_is_explicit'
69 passed, 1 skipped, 1 deselected
```

The deselected certification test is the known unrelated dirty-worktree DTO consumer failure in `test_s5_conviction_formula_is_explicit`, not a proxy-gate failure.

## Rationale

The existing runtime distinguishes live and paper/replay through the injected OMS implementation. `IOMS.is_live` is the narrow capability boundary, implemented by `LiveOMS` and `PaperOMS`, and the composition root passes it through without class-name inspection. The gate is applied in `_build_decision()` immediately after deterministic strategy evaluation and context construction, before option translation, sizing, and `SubmissionHandler`. It reuses `DataQuality` and `normalize_data_quality`; certification recording and `DecisionProduced` emission remain unchanged and observe the blocked decision.

## Review Fix

- Live mode permits only `DataQuality.TICK_EXACT`; every other canonical or unknown value fails closed with `PROXY_FLOW_BLOCKED`.
- Added a real `LiveOMS` broker-boundary test proving proxy entries do not reach the broker, plus exact live pass, paper proxy metadata/pass, and pre-translation coverage.
- Replaced class-name live detection with the explicit `IOMS.is_live` capability.

## Concerns

- The broader certification suite retains the known unrelated failure described above.
- `PROXY_MODE` is carried in `QuantDecision.metadata` and certification records; no broader DTO/UI schema change was made in Task 2.
