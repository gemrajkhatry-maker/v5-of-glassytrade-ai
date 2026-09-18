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
