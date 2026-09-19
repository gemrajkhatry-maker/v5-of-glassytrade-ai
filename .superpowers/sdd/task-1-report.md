# Task 1 Report: Directional AMT Flow and Provenance

## Final Whole-Branch Remediation (Corrected)

**Correction from whole-branch review:** The original Task 1 implementation used
bar delta as `candidate_direction` in `AMTEngine.analyze()`. This was incorrect
because the AMT engine runs before the deterministic decision path resolves the
strategy candidate direction. The corrective fix moves directional aggression
scoring to the decision pipeline where `agent_direction` is available.

- Removed the `candidate_direction` parameter from `AMTEngine.analyze()`,
  `AMTAnalyzer.analyze()`, and `compute_order_flow_metrics()`. AMT analysis
  now computes raw components WITHOUT direction gating.
- Added `rescore_aggression_with_direction()` in `quant/decision/gates_edge.py`
  that re-computes the aggression score using the resolved `agent_direction`
  from `DecisionContextBuilder._resolve_direction()`.
- CVD confirmation is now raw in the AMT engine; direction-aware CVD divergence
  checking is enforced in `gate_triple_a_edge` for all market states.
- Added per-family provenance to `AMTResult.evidence_provenance` for footprint
  imbalance, CVD/delta, OFI/depth, absorption, and stacked imbalance. Live
  gating requires every family to be `TICK_EXACT`; missing or non-exact
  provenance fails closed. Paper/replay retains `PROXY_MODE`.
- Regression tests prove an exact aggregate with one `CANDLE_DISTRIBUTED`
  family is blocked.

## Files Changed

- `quant/amt/orderflow/compute.py` — removed `candidate_direction` param, raw CVD confirmation
- `quant/amt/analyzer.py` — added `_compute_evidence_provenance()`, populate `evidence_provenance`
- `quant/amt/dto.py` — emit `aggressionComponents`, `cvdState`, `ofiResult`, `normDelta`
- `quant/contracts/value_objects.py` — added `aggression_components`, `cvd_state`, `ofi_result`, `norm_delta`, `evidence_provenance` to `AMTResult`
- `quant/amt_engine.py` — removed `candidate_direction` from analyzer call
- `quant/decision/context.py` — added `aggression_components`, `cvd_state`, `ofi_result`, `norm_delta` fields
- `quant/decision/context_builder.py` — pass new fields from DTO to DecisionContext
- `quant/decision/gates_edge.py` — added `rescore_aggression_with_direction()`, CVD divergence direction check
- `tests/quant/amt/orderflow/test_directional_compute.py`
- `tests/quant/amt/test_amt_engine_direction.py`
- `tests/architecture/test_amt_dto_contract.py`

The worktree already contained unrelated edits in several approved Task 1 files. No unrelated paths were reverted or modified.

## Tests Added

- Directional CVD confirmation for LONG and SHORT candidates in decision pipeline.
- Opposing signed flow does not confirm CVD or receive scorer inputs without direction.
- Active analyzer forwarding of raw aggression components (no direction).
- DTO provenance normalization: a footprint object does not imply `TICK_EXACT`.
- Per-evidence-family provenance computation and live gating.

## Commands and Results

- `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt/orderflow/test_directional_compute.py -q`
  - `3 passed` (raw CVD confirmation, raw components, no direction gating).
- `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt/test_amt_engine_direction.py -q`
  - `2 passed` (engine handoff without direction, opposing CVD not confirmed).
- `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt/orderflow/test_analyzer_flow_propagation.py -q`
  - `1 passed` (evidence provenance populated).
- `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt/orderflow tests/quant/amt/market backend/tests/unit/domain/test_amt_analyzer.py tests/architecture/test_amt_dto_contract.py -q`
  - `247 passed, 6 skipped, 2 failed` (2 failures are pre-existing DTO consumer drift).
- `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/gates_edge.py -k rescore -q`
  - `2 passed` (rescore with direction, CVD divergence alignment).
- `git diff --check -- ...Task 1 paths...`
  - Passed with no whitespace errors.

## Design Decisions

- `candidate_direction` removed entirely; AMT engine is purely analytical.
- Direction-gated scoring moved to `gate_triple_a_edge` where `agent_direction` is resolved.
- CVD divergence alignment enforced for all market states (not just IMBALANCED).
- Provenance uses the existing `DataQuality` vocabulary and normalizer.
- No DTO consumers were changed for the unrelated stacked-imbalance failure.

## Concerns

- The full focused command has 2 failures caused by pre-existing dirty-worktree DTO reads in `quant/execution/exit_checks.py` for four missing stacked-imbalance keys. That file is outside Task 1 and was not changed.
- Existing unrelated edits remain interleaved in approved Task 1 production files and are preserved.
- The broader plan's context-builder fields already exist and were extended for the new provenance fields.

## Review Fix (Corrected Implementation)

### Files

- `quant/amt/orderflow/compute.py` — removed direction gating, raw components only
- `quant/amt/analyzer.py` — evidence provenance computation
- `quant/amt/dto.py` — new DTO fields for re-scoring
- `quant/contracts/value_objects.py` — new AMTResult fields
- `quant/decision/gates_edge.py` — `rescore_aggression_with_direction()`, CVD divergence check
- `quant/decision/context.py` / `context_builder.py` — thread new fields through
- `quant/amt_engine.py` — no direction passed to analyzer

### Red/Green Results

- `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt/orderflow/test_directional_compute.py tests/quant/amt/test_amt_engine_direction.py -q`
  - Initial red run: `5 failed`; tests expected direction gating in engine.
  - Green run after fixes: `5 passed`.

### Implementation Rationale

`AMTEngine.analyze()` runs before `DecisionContextBuilder._resolve_direction()`, so context-derived direction cannot be fed backward into AMT without a circular dependency. The correct architecture is:
1. AMT engine computes raw order-flow components (footprint, CVD, absorption, OFI, etc.)
2. DecisionContextBuilder resolves `agent_direction` from AMT state (break direction, triple-A signal, absorption, OBI, CVD, market state)
3. `gate_triple_a_edge` re-scores aggression with the resolved direction via `rescore_aggression_with_direction()`

This ensures the aggression score reflects the actual trade direction, not the observed bar delta.

## Remaining Concerns

- Pre-existing unrelated changes remain interleaved in approved Task 1 files, including `quant/amt_engine.py` and `quant/amt/dto.py`; they were not reverted and cannot be cleanly separated without reverting user work.
- The architecture DTO test still fails on the known stacked-imbalance keys in `quant/execution/exit_checks.py`; that unrelated consumer was intentionally left untouched.
