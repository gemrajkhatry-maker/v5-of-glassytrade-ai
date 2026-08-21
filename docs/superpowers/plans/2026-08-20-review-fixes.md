# Review Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the defects and smells surfaced in the project review (broken frontend build, SetupEvidence phantom-field bug, MarketState typing, dead code/imports).

**Architecture:** The decision path is `QuantEngine._decide → DecisionContextBuilder → DecisionService → GatePipeline → SignalBuilder`. The uncommitted refactor added `SetupEvidence` (Fabio 4-setup state machine) wired from the AMT DTO, but reads ~13 DTO keys that do not exist. Frontend `AgentDecision.probability`/`confidence` were replaced by `modelLabel` without updating consumers.

**Tech Stack:** Python 3.13 (dataclasses, enum), pytest; React + TypeScript (vite, vitest).

## Global Constraints

- Do NOT change trade-approval *behavior* beyond fixing the identified bugs, unless a task says otherwise. This is a live-trading decision path.
- Run `pytest tests/ tests/quant/ backend/tests/ -m "not slow and not live"` and `cd frontend && npx tsc --noEmit` after each task.
- Keep diffs minimal; no new dependencies.

---

### Task 1: Fix frontend TypeScript build (7 errors)

**Files:**
- Modify: `frontend/components/MarketSidebar.tsx:215-216`
- Modify: `frontend/tests/components/ai/QuantDecisionCard.test.tsx:10,64`
- Modify: `frontend/tests/components/AIAnalysisPanel.test.tsx:79`
- Modify: `frontend/tests/components/ChartScene.test.tsx:186`
- Modify: `frontend/tests/components/MarketSidebar.test.tsx:151`

**Interfaces:**
- Consumes: `AgentDecision` (`types.ts:49`) — `probability` removed, `modelLabel: string` and `sizeFraction: number` present.
- Produces: passing `npx tsc --noEmit`.

- [ ] **Step 1:** In `MarketSidebar.tsx`, replace `probability` sort proxy with `sizeFraction` (only remaining numeric conviction proxy):
```ts
const pA = instA.agentDecision?.sizeFraction || 0;
const pB = instB.agentDecision?.sizeFraction || 0;
```
- [ ] **Step 2:** In the 4 test files, replace stale `confidence: X` on `signal` with `modelLabel: 'Triple-A'`, and `probability: X` on `agentDecision` with `modelLabel: 'Triple-A'` (keep direction/timing/regime/sizeFraction intact).
- [ ] **Step 3:** Run `cd frontend && npx tsc --noEmit` → expect exit 0.
- [ ] **Step 4:** Run `cd frontend && npm test` → expect pass.
- [ ] **Step 5:** Commit `fix(frontend): replace removed probability/confidence fields with modelLabel`.

---

### Task 2: Fix SetupEvidence phantom-field wiring (root cause of `acceptance` bug)

**Files:**
- Modify: `quant/decision_context_builder.py:139-174`
- Possibly Modify: `quant/amt/dto.py` (add `driveNumber`, `legLvn` keys)
- Test: `tests/quant/decision/test_context_builder_behavior.py`

**Interfaces:**
- Consumes: `amt_result_to_dto` output (`quant/amt/dto.py`) — real keys: `acceptanceAbove`, `acceptanceBelow`, `rejectionAtHigh`, `rejectionAtLow`, `isSecondDrive`, `legLvns`, `absorptionSide`, `aggression`, `breakType`, `breakDirection`.
- Produces: `SetupEvidence` whose `acceptance`/`rejection`/`drive_number` are populated from real DTO fields.

**Decision required** (see scoping question): minimal (`acceptance`→`get("acceptance", True)` + map `rejection` from `rejectionAtHigh/Low`) vs. full rewire (add `driveNumber`/`legLvn` to DTO, derive all fields correctly).

---

### Task 3: MarketState "DEAD" mixed typing

**Files:**
- Modify: `quant/decision_context_builder.py:132-137`
- Modify: `quant/contracts/enums.py:161-169` (add `DEAD = "DEAD"` to `MarketState`)

**Steps:** add `DEAD` to the `MarketState` enum; replace `amt_market_state = "DEAD"` string with `MarketState.DEAD`; remove the `getattr(..., "value", ...)` workarounds in `decision_service.py:94` and `gates_edge.py:46`.

---

### Task 4: Cleanups (ruff + dead code)

**Files:**
- Modify: `quant/decision/decision_service.py` (remove unused `MarketState` import + `field`/`Optional` imports; drop `decide()` alias or keep — per user)
- Modify: `quant/execution/risk.py` (remove unused `date` import)
- Modify: `quant/decision/context.py` (remove unused `Optional` import)
- Modify: `quant/state.py:153` (move `import threading` to top)
- Delete/repurpose: `tests/quant/runtime/golden/decide_long.json` (no longer asserted)

- [ ] **Step 1:** Run `ruff check quant backend/app brokers shared` → fix all F401/E402.
- [ ] **Step 2:** Decide golden file: remove the file + its write test, or keep. Recommend deleting the write test's snapshot write and the unused golden JSON.
- [ ] **Step 3:** Run full pytest + tsc; commit.
