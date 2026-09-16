# High-Complexity Function Refactoring Plan

> **For agentic workers:** Use superpowers:subagent-driven-development with multi-agent parallel execution.

**Goal:** Reduce cyclomatic complexity from 177 high-complexity functions to <20 by systematic refactoring with regression safety.

**Architecture:** Multi-agent parallel refactoring with golden tape verification, incremental commits, and automated regression detection.

**Tech Stack:** Python refactoring, pytest, golden tape/replay, subagent-driven development

## Global Constraints

- Each refactored function must pass golden tape/replay byte-exact verification
- No behavior changes — pure structural refactoring only
- Complexity threshold: max 10 cyclomatic complexity per function
- Each agent works on isolated files to avoid conflicts
- Regression tests run after every commit
- Maximum 5 functions per agent to maintain focus

---

## Phase 0: Regression Safety Net

### Task 0: Establish Golden Tape Baseline

**Files:**
- Create: `tests/e2e/golden/refactoring_baseline/`
- Create: `scripts/capture_golden_baseline.sh`

**Goal:** Capture golden tape/replay baseline before any refactoring.

- [ ] **Step 1: Run full test suite and capture baseline**

```bash
# Capture current test results
python -m pytest tests/ -v --tb=short > tests/e2e/golden/refactoring_baseline/test_results.txt

# Capture golden tape if available
python -m pytest tests/e2e/test_golden_tape.py -v > tests/e2e/golden/refactoring_baseline/golden_tape.txt

# Capture complexity baseline
python -c "
from automation.quality.scanner import CodeQualityScanner
scanner = CodeQualityScanner('automation/config/quality_rules.yaml')
report = scanner.scan('quant')
complexity = [i for i in report.issues if i.rule == 'complexity.cyclomatic']
print(f'Baseline complexity issues: {len(complexity)}')
with open('tests/e2e/golden/refactoring_baseline/complexity.txt', 'w') as f:
    f.write(f'{len(complexity)}\n')
"
```

- [ ] **Step 2: Commit baseline**

```bash
git add tests/e2e/golden/refactoring_baseline/
git commit -m "test: establish golden tape baseline for refactoring"
```

---

## Phase 1: Top 10 Highest Complexity Functions (Parallel Agents)

### Task 1: Refactor timesfm_agents.py:410 (complexity 95 → <10)

**Agent:** Lane A (isolated worktree)
**Files:**
- Modify: `quant/decision/timesfm_agents.py`
- Test: `tests/quant/decision/test_timesfm_agents.py`

**Refactoring Strategy:**
1. Extract `TimesFMPositionAgent.evaluate()` into separate methods:
   - `_check_stop_loss()`
   - `_check_take_profit()`
   - `_check_thesis_flip()`
   - `_check_risk_zero_ratchet()`
   - `_check_time_stop()`
   - `_build_active_position_payload()`
   - `_build_rationale()`
2. Use early returns instead of deep nesting
3. Extract repeated rationale construction into helper

**Regression Gate:**
```bash
# Run focused tests
python -m pytest tests/quant/decision/test_timesfm_agents.py -v

# Run golden tape
python -m pytest tests/e2e/test_golden_tape.py -v

# Check complexity
python -c "
from automation.quality.scanner import CodeQualityScanner
scanner = CodeQualityScanner('automation/config/quality_rules.yaml')
report = scanner.scan('quant/decision/timesfm_agents.py')
complexity = [i for i in report.issues if i.rule == 'complexity.cyclomatic']
assert len(complexity) < 5, f'Still {len(complexity)} high-complexity functions'
"
```

- [ ] **Step 1: Create worktree and refactor**
- [ ] **Step 2: Run regression tests**
- [ ] **Step 3: Verify complexity reduced**
- [ ] **Step 4: Commit and report**

### Task 2: Refactor context_builder.py:286 (complexity 79 → <10)

**Agent:** Lane B (isolated worktree)
**Files:**
- Modify: `quant/decision/context_builder.py`

**Refactoring Strategy:**
1. Extract large methods into focused helpers
2. Use guard clauses for early returns
3. Extract repeated logic into utility functions

**Regression Gate:** Same as Task 1

### Task 3: Refactor scanner.py:276 (complexity 71 → <10)

**Agent:** Lane C (isolated worktree)
**Files:**
- Modify: `quant/amt/session/scanner.py`

**Refactoring Strategy:**
1. Break into smaller focused methods
2. Extract condition checks into predicates
3. Use strategy pattern for different scan modes

**Regression Gate:** Same as Task 1

### Task 4: Refactor multi_engine.py:781 (complexity 59 → <10)

**Agent:** Lane D (isolated worktree)
**Files:**
- Modify: `quant/multi_engine.py`

**Refactoring Strategy:**
1. Extract `snapshot()` into separate methods
2. Use composition over nested conditionals
3. Extract data transformation into helpers

**Regression Gate:** Same as Task 1

### Task 5: Refactor timesfm_client.py:25 (complexity 59 → <10)

**Agent:** Lane E (isolated worktree)
**Files:**
- Modify: `quant/decision/timesfm_client.py`

**Refactoring Strategy:**
1. Extract initialization logic
2. Use factory pattern for different client types
3. Separate configuration from execution

**Regression Gate:** Same as Task 1

---

## Phase 2: Next 10 High-Complexity Functions

### Task 6-10: Refactor functions with complexity 45-57

**Files:**
- `quant/amt/analyzer.py:388` (57)
- `quant/decision/timesfm_agents.py:259` (55)
- `quant/amt/market/half_trend.py:147` (53)
- `quant/multi_engine.py:1428` (52)
- `quant/decision/gates_edge.py:151` (52)

**Strategy:** Same as Phase 1, parallel agents

---

## Phase 3: Remaining High-Complexity Functions

### Task 11-20: Refactor functions with complexity 40-50

Continue with next batch of 10 functions.

---

## Phase 4: Final Cleanup

### Task 21: Fix remaining unused imports (46 issues)

**Strategy:** Manual review and removal with test verification

### Task 22: Document remaining silent except blocks (3 issues)

**Strategy:** Add `# silent-except` comments with rationale

### Task 23: Final verification

- [ ] Run full test suite
- [ ] Verify complexity < 20
- [ ] Run golden tape byte-exact
- [ ] Generate final report

---

## Execution Strategy

### Multi-Agent Parallel Execution

1. **Phase 1:** 5 agents in parallel (Lanes A-E)
   - Each agent works on isolated worktree
   - Each agent refactors 1-2 functions
   - Each agent runs regression tests
   - Merge with cherry-pick -x

2. **Phase 2:** 5 agents in parallel (Lanes F-J)
   - Same strategy

3. **Phase 3:** 5 agents in parallel (Lanes K-O)
   - Same strategy

### Regression Safety

After each merge:
```bash
# Full test suite
python -m pytest tests/ -q

# Golden tape
python -m pytest tests/e2e/test_golden_tape.py -v

# Complexity check
python -c "
from automation.quality.scanner import CodeQualityScanner
scanner = CodeQualityScanner('automation/config/quality_rules.yaml')
report = scanner.scan('quant')
complexity = [i for i in report.issues if i.rule == 'complexity.cyclomatic']
print(f'Complexity issues: {len(complexity)}')
assert len(complexity) < previous_count, 'Regression detected'
"
```

### Conflict Resolution

- Agents work on disjoint file sets
- Merge with cherry-pick -x
- Resolve conflicts manually if needed
- Re-run regression tests after merge

---

## Success Criteria

- [ ] Complexity issues reduced from 177 to <20
- [ ] All tests pass (no regressions)
- [ ] Golden tape byte-exact
- [ ] No behavior changes
- [ ] Code is more readable and maintainable

---

## Risk Mitigation

1. **Behavior changes:** Golden tape verification catches any behavior drift
2. **Test failures:** Regression tests run after every commit
3. **Merge conflicts:** Disjoint file sets minimize conflicts
4. **Complexity not reduced:** Each agent verifies complexity before commit

---

## Estimated Effort

- Phase 0: 30 minutes (baseline)
- Phase 1: 2 hours (5 agents × 24 min each)
- Phase 2: 2 hours
- Phase 3: 2 hours
- Phase 4: 1 hour

**Total: ~7 hours**

---

## Execution Handoff

**Plan complete. Execute using subagent-driven-development with multi-agent parallel execution.**

**Start with Phase 0 (baseline), then dispatch 5 agents in parallel for Phase 1.**
