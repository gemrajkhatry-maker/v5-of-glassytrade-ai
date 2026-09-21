# Release Gate Convergence Implementation Plan

> **For agentic workers:** REQUIRED SUB-SILLIPOWER: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Bring the project release gate (`make test-quant`) to green by addressing the remaining 87 test failures, building on the 3 corrected high-severity AMT safety fixes.

**Architecture:** Fix failures in dependency order: (1) commit current verified fixes, (2) fix DTO consumer drift to unblock multiple test suites, (3) fix dirty-worktree architecture issues, (4) fix runtime/risk baseline failures, (5) fix certification and chaos test debt. Each task is independently testable.

**Tech Stack:** Python 3.x, pytest, dataclasses, AMT order-flow analysis

## Global Constraints

- NO live-readiness claims until `make test-quant` passes with exit 0
- Preserve unrelated dirty-worktree changes (don't revert user work)
- Each task ends with a passing focused regression run
- TDD: failing test first, then minimal implementation
- Commit after each task
- NO comments unless explicitly requested

---

## Current State

**Commit boundary:** After `45344243` (docs: record AMT live safety verification) + uncommitted corrective fixes

**Verified passing focused suites (107 tests):**
- AMT directional compute/engine/flow: 20 passed
- Decision proxy gate: 15 passed
- CVD tests: 11 passed
- Exposure/restart/close identity: 20 passed
- EventStore/projection/architecture: 18 passed
- Full AMT suite: 643 passed, 2 skipped

**Known failing gate:** `make test-quant` → 87 failed, 2609 passed, 11 skipped

**Failure categories (from verification report):**
1. DTO consumer drift: missing `legLvn`, `legLvns`, stacked-imbalance, `time` keys
2. Dirty-worktree architecture: host import, unannotated silent exceptions
3. Dirty-baseline risk: lot sizing, risk tiers, day-of-week sizing, house-money
4. Dirty-baseline runtime: MagicMock fixtures, telemetry, approval, golden, latch
5. Certification: `s5_conviction_formula_is_explicit`
6. Chaos test debt: unmatched-close expects old raise behavior

---

### Task 1: Commit Current Corrective Fixes

**Files:**
- Modify: `quant/amt/orderflow/compute.py` (candidate_direction removed, raw CVD, aggression_components)
- Modify: `quant/amt/analyzer.py` (evidence_provenance, order_book param)
- Modify: `quant/amt/dto.py` (aggressionComponents, cvdState, ofiResult, normDelta)
- Modify: `quant/contracts/value_objects.py` (new AMTResult fields)
- Modify: `quant/amt_engine.py` (candidate_direction removed)
- Modify: `quant/decision/context.py` (aggression_components, cvd_state, ofi_result, norm_delta)
- Modify: `quant/decision/context_builder.py` (thread new fields)
- Modify: `quant/decision/gates_edge.py` (rescore_aggression_with_direction, CVD divergence check)
- Modify: `tests/quant/amt/orderflow/test_directional_compute.py` (updated for new arch)
- Modify: `tests/quant/amt/test_amt_engine_direction.py` (updated for new arch)
- Modify: `tests/quant/amt/orderflow/test_analyzer_flow_propagation.py` (updated for new arch)

**Interfaces:**
- Consumes: Current working tree state
- Produces: Clean commit with all 3 high-severity fixes

- [ ] **Step 1: Verify all focused regression tests pass**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt/orderflow/test_directional_compute.py tests/quant/amt/test_amt_engine_direction.py tests/quant/amt/orderflow/test_analyzer_flow_propagation.py tests/quant/decision/test_proxy_live_entry_block.py tests/quant/execution/test_exposure_state.py tests/quant/execution/test_live_partial_fill_reconciliation.py tests/quant/execution/test_restart_reconciliation.py tests/quant/execution/test_close_identity.py tests/quant/runtime/test_eventstore_failure_consistency.py tests/quant/runtime/test_snapshot_projection.py tests/quant/test_event_store_roundtrip_real.py tests/architecture/test_gap_architecture_contract.py -q`
Expected: All pass

- [ ] **Step 2: Stage and commit corrective fixes**

```bash
git add quant/amt/orderflow/compute.py quant/amt/analyzer.py quant/amt/dto.py quant/contracts/value_objects.py quant/amt_engine.py quant/decision/context.py quant/decision/context_builder.py quant/decision/gates_edge.py tests/quant/amt/orderflow/test_directional_compute.py tests/quant/amt/test_amt_engine_direction.py tests/quant/amt/orderflow/test_analyzer_flow_propagation.py .superpowers/sdd/task-1-report.md .superpowers/sdd/task-2-report.md .superpowers/sdd/task-5-report.md docs/reviews/2026-09-18-amt-live-safety-verification.md
git commit -m "fix(amt): enforce candidate direction and evidence provenance

Three high-severity fixes from whole-branch review:
1. Remove bar-delta candidate_direction from AMT engine; direction-gated
   re-scoring moved to gate_triple_a_edge via rescore_aggression_with_direction()
2. Populate per-evidence-family provenance in AMTResult.evidence_provenance
   for footprint, CVD, OFI, absorption, stacked imbalance
3. CVD divergence confirmation direction-aware in all market states"
```

- [ ] **Step 3: Verify commit and tests still pass**

Run: `git log --oneline -1`
Expected: Shows the new commit
Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt/ -q`
Expected: 643+ passed

---

### Task 2: Fix DTO Consumer Drift (legLvn/legLvns/stacked-imbalance/time keys)

**Files:**
- Modify: `quant/amt/dto.py` (add missing keys to DTO output)
- Modify: `quant/execution/exit_checks.py` (add missing stacked-imbalance keys)
- Modify: `tests/architecture/test_amt_dto_contract.py` (verify new keys)

**Interfaces:**
- Consumes: Current AMT DTO output, consumer expectations
- Produces: DTO with all required keys for decision layer consumers

- [ ] **Step 1: Identify all missing DTO keys**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/architecture/test_amt_dto_contract.py -q 2>&1 | head -40`
Expected: Shows which keys are missing

- [ ] **Step 2: Write failing test for missing keys**

```python
def test_dto_contains_leg_lvn_key():
    """DTO must contain legLvn for decision consumers."""
    from quant.amt.dto import amt_result_to_dto
    # Build a minimal AMTResult and verify legLvn is in DTO
    ...
```

- [ ] **Step 3: Add missing keys to amt_result_to_dto()**

In `quant/amt/dto.py`, add the missing keys:
- `legLvn` (singular, for backward compat)
- `legLvns` (plural, list)
- `stackedImbalanceDirection`
- `stackedImbalanceMagnitude`
- `stackedImbalancePriceLow`
- `stackedImbalancePriceHigh`
- `time` (ISO timestamp)

- [ ] **Step 4: Add stacked-imbalance fields to exit_checks.py**

In `quant/execution/exit_checks.py`, ensure the stacked imbalance exit logic reads the new DTO keys correctly.

- [ ] **Step 5: Run DTO contract tests**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/architecture/test_amt_dto_contract.py -q`
Expected: All pass (or only pre-existing unrelated failures remain)

- [ ] **Step 6: Commit**

```bash
git add quant/amt/dto.py quant/execution/exit_checks.py tests/architecture/test_amt_dto_contract.py
git commit -m "fix(dto): add missing legLvn/legLvns/stacked-imbalance/time keys"
```

---

### Task 3: Fix Dirty-Worktree Architecture Issues

**Files:**
- Modify: `quant/engine/submission_handler.py` (fix host import)
- Modify: `quant/brokers/multiplexed_feed.py` (add silent-except markers)
- Modify: `backend/app/api/routers/observability.py` (add silent-except markers)
- Modify: `tests/architecture/test_no_layer_bypass.py` (fix import issues)
- Modify: `tests/architecture/test_no_silent_except_pass.py` (verify markers)

**Interfaces:**
- Consumes: Current dirty-worktree state
- Produces: Architecture tests passing

- [ ] **Step 1: Run architecture tests to identify failures**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/architecture/ -q 2>&1 | tail -20`
Expected: Shows 4 failures (test_amt_dto_contract x2, test_no_layer_bypass, test_no_silent_except_pass)

- [ ] **Step 2: Fix submission_handler.py host import**

In `quant/engine/submission_handler.py`, fix any import that references host application paths. Use relative imports within quant/.

- [ ] **Step 3: Add silent-except markers to multiplexed_feed.py**

In `quant/brokers/multiplexed_feed.py:472,476`, add `# silent-except - <reason>` markers.

- [ ] **Step 4: Add silent-except markers to observability.py**

In `backend/app/api/routers/observability.py:38`, add `# silent-except - <reason>` marker.

- [ ] **Step 5: Run architecture tests**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/architecture/test_no_silent_except_pass.py tests/architecture/test_no_layer_bypass.py -q`
Expected: Pass

- [ ] **Step 6: Commit**

```bash
git add quant/engine/submission_handler.py quant/brokers/multiplexed_feed.py backend/app/api/routers/observability.py
git commit -m "fix(arch): resolve host imports and silent-except markers"
```

---

### Task 4: Fix Dirty-Baseline Runtime and Risk Failures

**Files:**
- Modify: `tests/quant/runtime/` (fix MagicMock fixtures for DecisionContext)
- Modify: `tests/quant/test_production_correctness.py` (fix risk/lot-sizing expectations)
- Modify: `tests/quant/test_stress_and_portfolio_risk.py` (fix house-money expectations)

**Interfaces:**
- Consumes: Current failing test expectations
- Produces: Passing runtime and risk tests

- [ ] **Step 1: Identify specific runtime failures**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/runtime/ -q 2>&1 | tail -30`
Expected: Shows which runtime tests fail

- [ ] **Step 2: Fix MagicMock risk fixtures**

In the failing runtime tests, ensure `consecutive_wins` is numeric (int/float) not string. Fix the MagicMock setup for `DecisionContext` builders.

- [ ] **Step 3: Identify specific risk failures**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/test_production_correctness.py tests/quant/test_stress_and_portfolio_risk.py -q 2>&1 | tail -30`
Expected: Shows which risk tests fail

- [ ] **Step 4: Fix risk tier/lot-sizing/day-of-week expectations**

Update test expectations to match current production behavior. Do NOT change production code to match stale tests unless the production behavior is actually wrong.

- [ ] **Step 5: Run targeted tests**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/runtime/ tests/quant/test_production_correctness.py tests/quant/test_stress_and_portfolio_risk.py -q`
Expected: Pass (or only pre-existing unrelated failures remain)

- [ ] **Step 6: Commit**

```bash
git add tests/quant/runtime/ tests/quant/test_production_correctness.py tests/quant/test_stress_and_portfolio_risk.py
git commit -m "fix(tests): update runtime fixtures and risk expectations"
```

---

### Task 5: Fix Certification Test (s5_conviction_formula_is_explicit)

**Files:**
- Modify: `tests/quant/test_certification.py` (fix conviction formula test)
- Modify: `quant/decision/signal_builder.py` (ensure conviction formula is explicit)

**Interfaces:**
- Consumes: Current certification test expectations
- Produces: Passing certification test

- [ ] **Step 1: Run certification test to see failure**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/test_certification.py::test_s5_conviction_formula_is_explicit -v 2>&1 | tail -30`
Expected: Shows specific assertion failure

- [ ] **Step 2: Fix the conviction formula**

In `quant/decision/signal_builder.py`, ensure the S5 conviction formula is explicit (not implicit from data quality/DTO path). The formula should be clearly defined and not depend on the data-quality/DTO baseline path.

- [ ] **Step 3: Run certification test**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/test_certification.py -q`
Expected: Pass (or only pre-existing unrelated failures remain)

- [ ] **Step 4: Commit**

```bash
git add quant/decision/signal_builder.py tests/quant/test_certification.py
git commit -m "fix(cert): make s5 conviction formula explicit"
```

---

### Task 6: Update Chaos Test for Unmatched-Close Behavior

**Files:**
- Modify: `tests/quant/chaos/test_crash_recovery.py` (update unmatched-close test)

**Interfaces:**
- Consumes: Current Task 4 replay-tolerant behavior
- Produces: Chaos test that matches new contract

- [ ] **Step 1: Run chaos test to see failure**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/chaos/test_crash_recovery.py::TestPositionIdMismatch::test_pyramid_close_mismatch_raises -v 2>&1 | tail -30`
Expected: Shows that the test expects raise but new behavior is replay-tolerant

- [ ] **Step 2: Update test to match new replay-tolerant behavior**

Replace `pytest.raises(...)` with assertion that the function returns unchanged state and emits structured diagnostics:

```python
def test_pyramid_close_mismatch_is_replay_tolerant():
    """Unmatched close replay returns unchanged state with diagnostics (Task 4)."""
    result = handle_unmatched_close(ctx, event)
    assert result.state == ctx.state  # unchanged
    assert result.diagnostics["event_type"] == "POSITION_CLOSED"
    assert result.diagnostics["position_id"] == event.position_id
```

- [ ] **Step 3: Run chaos test**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/chaos/test_crash_recovery.py -q`
Expected: Pass

- [ ] **Step 4: Commit**

```bash
git add tests/quant/chaos/test_crash_recovery.py
git commit -m "fix(chaos): update unmatched-close test for replay-tolerant contract"
```

---

### Task 7: Final Release Gate Verification

**Files:**
- None (verification only)

**Interfaces:**
- Consumes: All fixes from Tasks 1-6
- Produces: Green release gate

- [ ] **Step 1: Run full quant test suite**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/ -q 2>&1 | tail -10`
Expected: All pass (0 failed)

- [ ] **Step 2: Run architecture tests**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/architecture/ -q 2>&1 | tail -10`
Expected: All pass (0 failed)

- [ ] **Step 3: Run make test-quant**

Run: `make test-quant 2>&1 | tail -20`
Expected: Exit 0, all tests pass

- [ ] **Step 4: Update verification report**

Update `docs/reviews/2026-09-18-amt-live-safety-verification.md` with final status. If gate is green, update live status from NO-GO to the appropriate level.

- [ ] **Step 5: Final commit**

```bash
git add docs/reviews/2026-09-18-amt-live-safety-verification.md
git commit -m "docs: update verification report with green release gate"
```

---

## Task Dependencies

```
Task 1 (Commit fixes)
  ├── Task 2 (DTO drift) ──┐
  ├── Task 3 (Architecture) ──┤
  ├── Task 4 (Runtime/Risk) ──┼── Task 7 (Final verification)
  ├── Task 5 (Certification) ──┤
  └── Task 6 (Chaos test) ──┘
```

Tasks 2-6 are independent and can be done in parallel after Task 1.

## Execution Strategy

1. **Task 1 first** - commit the verified corrective fixes
2. **Tasks 2-6 in parallel** - independent fixes, can be batched
3. **Task 7 last** - final verification after all fixes

## Risk Assessment

- **DTO drift (Task 2):** Low risk, additive changes
- **Architecture (Task 3):** Low risk, marker additions and import fixes
- **Runtime/Risk (Task 4):** Medium risk, test expectation changes need care
- **Certification (Task 5):** Medium risk, may require production code clarity
- **Chaos test (Task 6):** Low risk, test-only change

## Success Criteria

- `make test-quant` exits 0
- All 3 high-severity AMT fixes preserved
- No unrelated behavior changes
- NO live-readiness claim (paper/replay only until broker readiness proven)
