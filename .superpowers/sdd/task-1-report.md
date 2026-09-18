# Task 1 Report: Directional AMT Flow and Provenance

## Files Changed

- `quant/amt/orderflow/compute.py`
- `quant/amt/analyzer.py`
- `quant/amt/dto.py`
- `tests/quant/amt/orderflow/test_directional_compute.py`
- `tests/quant/amt/orderflow/test_analyzer_flow_propagation.py`
- `tests/architecture/test_amt_dto_contract.py`

The worktree already contained unrelated edits in several approved Task 1 files. No unrelated paths were reverted or modified. `quant/amt_engine.py` and `quant/contracts/value_objects.py` were intentionally excluded from the Task 1 change.

## Tests Added

- Directional CVD confirmation for LONG and SHORT candidates.
- Opposing signed flow does not confirm CVD or receive scorer inputs without direction.
- Active analyzer forwarding of candidate direction.
- DTO provenance normalization: a footprint object does not imply `TICK_EXACT`.

## Commands and Results

- `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt/orderflow/test_directional_compute.py -q`
  - Initial red run: `3 failed`, expected `TypeError` because `candidate_direction` was not accepted.
- `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt/orderflow/test_analyzer_flow_propagation.py -q`
  - Initial red run: `1 failed`, compute was not called by the insufficient-data fixture.
- `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/architecture/test_amt_dto_contract.py -k footprint_presence -q`
  - Initial red run: test fixture import/name error, corrected before implementation.
- `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt/orderflow/test_directional_compute.py tests/quant/amt/orderflow/test_aggression_direction.py tests/quant/amt/orderflow/test_analyzer_flow_propagation.py -q`
  - `24 passed`.
- `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/architecture/test_amt_dto_contract.py -k 'footprint_presence or option_scale_merge_keys or scan_still_sees_the_known_consumers' -q`
  - `7 passed, 1 deselected`.
- `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt/orderflow backend/tests/unit/domain/test_amt_analyzer.py -q`
  - `153 passed, 5 skipped`; skips are the existing incremental-profile assertion skips.
- `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt/orderflow tests/quant/amt/market backend/tests/unit/domain/test_amt_analyzer.py tests/architecture/test_amt_dto_contract.py -q`
  - `247 passed, 6 skipped, 1 failed`.
- `git diff --check -- ...Task 1 paths...`
  - Passed with no whitespace errors.

## Design Decisions

- `candidate_direction` is optional, preserving directionless display-only compute/scorer behavior.
- In `IMBALANCED`, CVD confirms positive slope for `LONG`, negative slope for `SHORT`, and either non-zero sign only when no direction is supplied.
- The active compute path forwards candidate direction, signed CVD slope, OFI, normalized delta, and absorption side to the existing directional scorer API.
- Provenance uses the existing `DataQuality` vocabulary and normalizer. The DTO falls back to `CANDLE_DISTRIBUTED` for explicit candle CVD sources or `CANDLE_GAUSSIAN` otherwise; footprint presence is not treated as tick provenance.

## Concerns

- The full focused command has one failure caused by pre-existing dirty-worktree DTO reads in `quant/execution/exit_checks.py` for four missing stacked-imbalance keys. That file is outside Task 1 and was not changed.
- Existing unrelated edits remain interleaved in approved Task 1 production files and are preserved.
- The broader plan's context-builder fields already exist and were not changed because Task 1 behavior is covered by the existing normalized `DataQuality` and flow fields.

## Review Fix

### Files

- `quant/amt_engine.py` — pass the closed bar's deterministic signed delta as
  `candidate_direction` before AMT scoring; zero delta remains directionless.
- `quant/amt/dto.py` — only infer candle provenance when the DTO has no explicit
  quality; an explicit unknown value remains `UNAVAILABLE`.
- `tests/quant/amt/test_amt_engine_direction.py` — production engine handoff,
  opposing-flow scoring, and context-direction regression coverage.
- `tests/architecture/test_amt_dto_contract.py` — unknown provenance regression
  coverage for underlying and option CVD sources.

### Red/Green Results

- `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt/test_amt_engine_direction.py tests/architecture/test_amt_dto_contract.py -k 'engine_handoff or unknown_provenance' -q`
  - Initial red run: `2 failed`; the first failures exposed fixture issues
    (`AggressionScorer` lacked the persistent scorer hook and `AMTResult` has no
    `data_quality` field), then the corrected tests failed until the fixes were
    implemented.
  - Green run: `2 passed, 8 deselected`.
- `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt/test_amt_engine_direction.py tests/quant/amt/orderflow/test_directional_compute.py tests/quant/amt/orderflow/test_analyzer_flow_propagation.py tests/architecture/test_amt_dto_contract.py -q`
  - `13 passed, 1 failed`.
  - The remaining failure is the pre-existing architecture DTO consumer failure
    for four missing stacked-imbalance keys in `quant/execution/exit_checks.py`.

### Implementation Rationale

`AMTEngine.analyze()` runs before `DecisionContextBuilder`, so context-derived
direction cannot be fed backward into AMT without a circular dependency. The
closed bar's signed delta is already available at the engine boundary and is the
earliest deterministic direction source. It is mapped to `LONG`/`SHORT` only
when nonzero and passed through the existing analyzer/order-flow directional
contract. The context path then remains LONG while opposing CVD is not credited.

DTO provenance now distinguishes absent quality (legacy source inference) from
explicit unknown quality (fail closed as `UNAVAILABLE`). No DTO consumers were
changed for the unrelated stacked-imbalance failure.

### Remaining Concerns

- Pre-existing unrelated changes remain interleaved in approved Task 1 files,
  including `quant/amt_engine.py` and `quant/amt/dto.py`; they were not reverted
  and cannot be cleanly separated without reverting user work.
- The architecture DTO test still fails on the known stacked-imbalance keys in
  `quant/execution/exit_checks.py`; that unrelated consumer was intentionally
  left untouched.

## Review Follow-up

### Changes

- Removed the unrelated history-seed `cvd_source` arguments and `latest_is_forming=True` argument introduced by `dc143eb0` from `quant/amt_engine.py`.
- Preserved the closed live-bar `candidate_direction` handoff from `AMTEngine.analyze()` to `AMTAnalyzer.analyze()`.
- Replaced the misleading combined test with an explicit engine handoff test and a real `compute_order_flow_metrics()` plus `PersistentAggressionScorer` assertion for opposing CVD.

### Commands and Results

- `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt/test_amt_engine_direction.py -q`
  - Inadequate pre-review test: `1 passed`; it patched the analyzer and computed opposing flow outside the engine.
  - Corrected focused tests: `2 passed`.
- `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt/test_amt_engine_direction.py tests/quant/amt/orderflow/test_directional_compute.py tests/quant/amt/orderflow/test_analyzer_flow_propagation.py -q`
  - `6 passed`.
- `git diff --check -- quant/amt_engine.py tests/quant/amt/test_amt_engine_direction.py`
  - Passed with no whitespace errors.

### Remaining Concerns

- The unrelated architecture DTO consumer failure for four missing stacked-imbalance keys in `quant/execution/exit_checks.py` remains and was not touched.
- Other pre-existing dirty-worktree changes remain preserved.
