# Pre-Deploy Convergence Plan — Merge Spine + Review Hardening

> **For agentic workers:** REQUIRED SUB-SKILL: use `superpowers:subagent-driven-development` (recommended) or `superpowers:executing-plans` to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax. The coordinator owns all merges, conflict resolutions, and full-suite gates; implementation agents own lanes.

**Date:** 2026-09-04
**Branch:** `feat/fractal-half-trend-signals` (pinned `32e723af` at write time; 9 commits unpushed, tree clean except the review report added this session)
**Supersedes nothing:** the live tracker stays `docs/architecture/predeploy-refactor-execution-plan.md` (B1–B7, G1, C, D, G2, P8/P9). This document is the master schedule that sequences the merge spine against every remaining review finding.

**Goal:** Bring the two unmerged hardening branches (`fix/w5-money-safety`, `fix/event-sourced-architecture`) onto the feat branch without losing this week's money-boundary work, then close every remaining review finding (paper duplication, CI gaps, Day-1 alerting, G1/G2 gates) to reach a conditional GO for one-lot live shadow.

**Architecture:** One sequential merge spine (M1 w5 → M2 event-sourced → M3 G1 gate) because both branches rewrite the same quant-core and broker-boundary files the feat branch hardened this week; all other lanes are scheduled parallel-safe (no overlap with the 25-file conflict set) or gated until the spine lands.

**Tech stack:** Python 3.11+ (quant engine, FastAPI backend, Dhan SDK), pytest, git worktrees, SQLite, TypeScript/React frontend.

## Global Constraints

1. **No live deployment and no real-capital order during this program.** One-lot canary (P9) requires explicit human approval after every gate passes.
2. **Feat-branch behavior wins every conflict unless the incoming branch provably supersedes it.** This week's hardening is newer than both merge sources: B1 fail-closed sizing, B2 uuid5 identity (`compare=False`), B3 UNKNOWN-durable ledger, `6adf6b8f` risk-chain, `32e723af` single-position-per-root. A merge resolution that silently drops any of these is a release blocker.
3. **One failing test before every behavior fix** (TDD); commit after each green cycle.
4. **Never use broad staging.** Agents stage only files they own.
5. **The quant suite must stay deterministic**: `signal_id` identity equality stays `compare=False`; no wall-clock in decision logic.
6. **No new dependency** unless an existing repo capability cannot meet the requirement.
7. **Push requires explicit user approval.** Commits are authorized; pushing to `origin/feat/fractal-half-trend-signals` is not.
8. **Every deliberate limit or deferred migration carries a `# ponytail:` comment** (repo convention).
9. Do not touch other agents' worktrees, the `.worktrees/` dirs, or files owned by an in-flight lane (ownership map §below).

## Current Assessment (verified 2026-09-04)

**Already landed on the feat branch (regression-green):**
- B1 quantity authority: adapter requires risk-approved `metadata["order_quantity"]`, fail-closed before `place_order` (`b1410214` tree, earlier commits).
- B2 restart-stable identity: `signal_id = uuid5(content)` in both `Signal` dataclasses + payload-boundary suite (`193bc147`).
- B3 ledger truthfulness at timeout: cancel-fail → durable `UNKNOWN`; fill-race honored (`b1410214`).
- B7 passive hot-path trace via EventBus subscriber (`3850de9c`).
- Risk chain single-authority (`6adf6b8f`), thesis-flip polarity fixes (`5ec7caca`, `f51ad811`), single active position per underlying root + chart-marker isolation (`32e723af`).
- Verified-zero-caller deletions: one-minute bar engine, RL observation models.

**The review's "merge is conflict-free" claim is DISPROVEN.** Proper `git merge-tree --write-tree` results:
- `fix/w5-money-safety`: **9 conflicting files**, exit 1 (see M1).
- `fix/event-sourced-architecture`: **25 conflicting files**, exit 1 (see M2).
- Common base is `2602fe09`; feat branch is **110 commits ahead**, w5 is 12 ahead, event-sourced is a multi-sub-branch integration. The merge spine is real integration work with per-file reconciliation, not a clean apply.

**Open review findings this plan closes:** w5 + event-sourced unmerged (blocker); `load_inflight_orders()` restart-restore caller absent on this branch; paper-simulator duplication (`PaperOMS` vs `PaperBrokerAdapter`); `runtime_audit/` not executed anywhere and hangs standalone; `tests/e2e` excluded from CI; IBroker/IMarketData error contracts not conformance-tested; no Day-1 alert set; G1 (crash-window/restart-restore) not executable until M2.

## Dependency Graph

```text
Phase 0 (baseline snapshot — docs only)
   │
Phase 1  ── M1 merge fix/w5-money-safety ──────────────┐  (sequential spine, coordinator only)
   │         9-file conflict resolution + full gate    │
   │                                                  │
   ├────────────► M2 merge fix/event-sourced-architecture
   │                 25-file resolution + full gate   │
   │                                                  │
   ├────────────► M3 G1 money-safety gate             │
   │                 (crash-window restart-restore)   │
   │                                                  │
Phase 2 (parallel lanes; gate placement in table)      │
   │  L1 runtime_audit CI      │ parallel-safe NOW      │
   │  L2 conformance extension │ parallel-safe NOW      │
   │  L5a G2 importer scans    │ parallel-safe NOW      │
   │  L5b deletions            │ after M2 (25-file set) │
   │  L3 paper consolidation   │ after M1 (paper_broker)│
   │  L4 Day-1 alerting        │ after M1 (tick-drop)   │
   │  L6 tests/e2e decision    │ parallel-safe NOW      │
   │                                                  │
Phase 3  ── P8 paper-shadow day → P9 one-lot canary → final GO/NO-GO record
```

## File Ownership Map (who may touch what)

| Files | Owner |
|---|---|
| `docs/architecture/predeploy-refactor-execution-plan.md`, all merge commits | Coordinator |
| `quant/runtime.py`, `state.py`, `event_store.py`, `live_oms.py`, `position_manager.py`, `portfolio_risk.py`, `multi_engine.py`, `signal_builder.py`, `amt/analyzer.py`, `contracts/value_objects.py` | M2 integration agent until M2 lands; then per-lane |
| `backend/.../dhan_broker_adapter.py`, `composition_root.py`, `http_client.py`, `websocket_client.py`, `main.py`, `startup_reconciliation.py`, config YAMLs | M1/M2 integration agents until spine lands |
| `backend/.../paper_broker.py`, `quant/execution/oms.py` | L3 (after M1) |
| `runtime_audit/`, `.github/workflows/*.yml`, `pytest.ini` | L1 |
| `tests/` new conformance files | L2 |
| `docs/reviews/` (review report committed in Phase 0) | Coordinator |
| Everything else (frontend, storage, metrics, journals) | Only after spine lands; coordinate with coordinator |

---

## Phase 0 — Baseline snapshot

### Task 0.1: Commit review report and this plan (docs only)

**Files:**
- Commit: `docs/reviews/2026-09-04-in-depth-duplication-predeploy-review.md`, `docs/superpowers/plans/2026-09-04-predeploy-convergence.md`

**Interfaces:**
- Consumes: clean working tree at `32e723af`
- Produces: pinned baseline commit the merge spine can always return to

- [ ] **Step 1: Confirm tree state**
  Run: `git status --short && git log --oneline -3`
  Expected: only the two docs untracked; HEAD at `32e723af`.
- [ ] **Step 2: Commit docs only**
  ```bash
  git add docs/reviews/2026-09-04-in-depth-duplication-predeploy-review.md docs/superpowers/plans/2026-09-04-predeploy-convergence.md
  git commit -m "docs: pin in-depth pre-deploy review and convergence plan"
  ```
- [ ] **Step 3: Record the snapshot in the tracker**
  Append to `docs/architecture/predeploy-refactor-execution-plan.md` Execution handoff: baseline commit hash, w5 = 9 conflicts, event-sourced = 25 conflicts, both re-verified.

---

## Phase 1 — Merge spine (sequential, coordinator-owned)

### Task M1: Merge `fix/w5-money-safety`

**Files (conflict set, verified):**
- Resolve: `backend/app/application/di/composition_root.py`, `backend/app/infrastructure/adapters/dhan_broker_adapter.py`, `backend/config/base.yaml`, `backend/config/strategies/nse_options.yaml`, `backend/tests/unit/infrastructure/test_dhan_broker_adapter.py`, `brokers/broker/dhan/infrastructure/http_client.py`, `brokers/broker/dhan/infrastructure/websocket_client.py`, `quant/execution/portfolio_risk.py`, `quant/multi_engine.py`

**Interfaces:**
- Consumes: feat HEAD (post-Phase-0), `fix/w5-money-safety` tip `0a69b389`
- Produces: merged tree where w5's transport-UNKNOWN handling, tick-drop counters, shared capital book, and config-risk removal coexist with feat's B1/B2/B3/risk-chain/single-position work

**Reconciliation rules (decide each conflict against Global Constraint 2):**
- `dhan_broker_adapter.py`: w5's `1ffc68b0`/`dcd9b2e1`/`34e0af26` (timed-out POST → UNKNOWN, never REJECT, never retry non-idempotent POST) and feat's B3 timeout-ledger truthfulness address the SAME boundary. Merge must produce ONE UNKNOWN path: B3's `_poll_for_terminal_status` timeout branch must hand off to w5's transport UNKNOWN state, not define a second one. Any duplicated UNKNOWN persistence = release blocker.
- `composition_root.py`: keep feat's `6adf6b8f` fail-closed `_require_risk_value` guard; adopt w5's removal of unsafe risk overrides and its capital-book wiring. Feat guard wraps w5 config.
- `portfolio_risk.py` + `multi_engine.py`: keep feat's `32e723af` single-active-position-per-underlying-root; adopt w5's shared capital book across engines and config-derived ceilings (`7c64f151`, `d696843c`). Verify they compose with a test: two engines sharing one book still enforce per-root single position.
- Config YAMLs: adopt w5's removal of unsafe risk overrides; keep feat strategy keys.
- Test files: keep BOTH branches' tests; where they assert contradictory UNKNOWN semantics, delete only the assertion that contradicts the merged path.

- [ ] **Step 1: Create the integration worktree**
  ```bash
  git worktree add .worktrees/merge-w5 HEAD
  cd .worktrees/merge-w5
  ```
- [ ] **Step 2: Run the baseline suites before merging (gate)**
  Run: `.venv/bin/python -m pytest tests/quant -q` then `.venv/bin/python -m pytest backend/tests/unit -q`
  Expected: 1,742+ passed quant / 697 passed backend (match Phase-0 recorded numbers). Any delta = stop.
- [ ] **Step 3: Merge**
  Run: `git merge fix/w5-money-safety -m "merge: bring fix/w5-money-safety transport-UNKNOWN + shared capital onto feat"`
  Expected: 9 conflicted files. Do NOT resolve blind; per-file:
- [ ] **Step 4: Resolve each conflict against the reconciliation rules, one file at a time**
  For each of the 9 files: open conflict hunks, apply the rule, then `git add <file>`. After each file, re-run its focused test file:
  Run (per file): `.venv/bin/python -m pytest <matching test path> -q`
- [ ] **Step 5: Prove each w5 capability survived the merge with its own test**
  - Tick-drop counter: run the w5 tick-drop test (search `test_dhan_broker_adapter.py` for dropped-tick counter assertions) — Expected: PASS
  - Transport UNKNOWN: run `tests/quant/execution` + backend adapter suite — Expected: no duplicated UNKNOWN path, PASS
  - Shared capital: run `tests/quant/execution/test_risk_persistence.py` equivalents — Expected: PASS
- [ ] **Step 6: Full regression gate (sequential, may exceed 600 s — split)**
  Run: `.venv/bin/python -m pytest tests/quant -q` (expected ≥1,742 passed) then `.venv/bin/python -m pytest backend/tests/unit -q` (expected ≥697 passed)
- [ ] **Step 7: Commit any stragglers and record handoff**
  ```bash
  git commit -am "merge: resolve w5 transport/risk conflicts keeping feat hardening"   # only if resolution edits remain
  ```
  Update `predeploy-refactor-execution-plan.md` handoff with M1 result. Coordinator merges worktree branch back to feat.
  **Acceptance:** all suites green; grep confirms one UNKNOWN persistence site in the adapter; tick-drop counters observable.

### Task M2: Merge `fix/event-sourced-architecture`

**Files (conflict set, verified — 25):**
- Resolve: `backend/app/application/di/composition_root.py`, `backend/app/domain/ops/startup_reconciliation.py`, `backend/app/infrastructure/adapters/dhan_broker_adapter.py`, `backend/app/main.py`, `backend/tests/runtime_validation/test_phase1_leaf_components.py`, `backend/tests/unit/infrastructure/test_dhan_broker_adapter.py`, `frontend/components/ChartScene.tsx`, `frontend/components/ai/TradePlanCard.tsx`, `frontend/hooks/useServerTradingSystem.ts`, `frontend/types.ts`, `quant/amt/analyzer.py`, `quant/amt/models/observation.py`, `quant/contracts/value_objects.py`, `quant/decision/signal_builder.py`, `quant/event_store.py`, `quant/execution/live_oms.py`, `quant/execution/portfolio_risk.py`, `quant/multi_engine.py`, `quant/position_manager.py`, `quant/runtime.py`, `quant/state.py`, `tests/quant/coordinator/test_dynamic_rotation.py`, `tests/quant/coordinator/test_strike_migration.py`, `tests/quant/decision/test_signal_builder_guards.py`, `tests/quant/execution/test_risk_persistence.py`

**Interfaces:**
- Consumes: M1 result, `fix/event-sourced-architecture` tip `c48914d6`
- Produces: merged tree where restart restore (`load_inflight_orders` caller, position fold-back, risk re-register), recovery guards, and event-sourced state coexist with all feat hardening

**Reconciliation rules:**
- **Staged resolution order — broker/backend first, then quant core, then frontend, then tests.** Each stage has its own green gate before the next begins.
- `quant/amt/models/observation.py`: modify/delete conflict (feat deleted it, verified zero callers). Resolution: **delete** — feat deletion stands.
- `signal_builder.py` + `contracts/value_objects.py` + `live_oms.py` + `runtime.py` + `position_manager.py`: feat behavior wins per Global Constraint 2 — keep uuid5 identity (`compare=False`), B3 ledger, polarity fixes, single-position root. Adopt event-sourced's fold-back/restore logic ONLY where it does not re-introduce pre-B2/B3 semantics.
- `event_store.py`/`state.py`: event-sourced is authoritative here (its core contribution); verify feat's B7 trace + determinism suites still pass on the merged fold.
- Frontend: event-sourced's frontend is older than feat's (`TradePlanCard`, `ChartScene`, `types.ts`, `useServerTradingSystem` carry this week's UI work). Resolution: **keep feat frontend files wholesale** unless event-sourced adds a ws-contract generation file that the frontend must consume.
- `startup_reconciliation.py` + `main.py`: adopt event-sourced restore; verify against feat's ledger truthfulness tests.

- [ ] **Step 1: Create worktree and pre-merge gate** (same commands as M1 Steps 1–2; base is M1 result). Expected: all green at M1 numbers.
- [ ] **Step 2: Merge**
  Run: `git merge fix/event-sourced-architecture -m "merge: bring event-sourced restart restore + recovery guards onto feat"`
- [ ] **Step 3: Stage A — broker/backend boundary** resolve `dhan_broker_adapter.py`, `composition_root.py`, `main.py`, `startup_reconciliation.py`, backend tests. Gate: `.venv/bin/python -m pytest backend/tests/unit/infrastructure backend/tests/unit/application -q` green.
- [ ] **Step 4: Stage B — quant core** resolve `runtime.py`, `state.py`, `event_store.py`, `live_oms.py`, `position_manager.py`, `portfolio_risk.py`, `multi_engine.py`, `signal_builder.py`, `analyzer.py`, `observation.py` (delete), `value_objects.py`, quant test files. Gate: `.venv/bin/python -m pytest tests/quant/execution tests/quant/decision tests/quant/coordinator -q` green, then full `tests/quant -q` (≥1,742 + new recovery tests).
- [ ] **Step 5: Stage C — frontend** keep feat files wholesale per rule. Gate: `cd frontend && npx tsc --noEmit` clean; frontend tests green.
- [ ] **Step 6: Prove restart restore now has a production caller**
  Run: grep for `load_inflight_orders` in `backend/app` — Expected: ≥1 caller in `main.py`/`startup_reconciliation.py` restore path. If absent, M2 is incomplete — stop.
- [ ] **Step 7: Full regression + determinism** quant full, backend full, hot-path trace suite (`tests/quant/test_hotpath_trace.py`). Expected: all green, determinism parity exact.
- [ ] **Step 8: Commit and record handoff.** Update tracker: M2 result + new test counts.

### Task M3: G1 money-safety gate (executable only after M2)

**Files:**
- Test (create if missing): `tests/quant/integration/test_crash_window_restart_restore.py` — check whether event-sourced already ships one; if yes, adapt to feat semantics.
- Modify: `docs/architecture/predeploy-refactor-execution-plan.md` (G1 record)

**Interfaces:**
- Consumes: M2 merged tree with restore path live
- Produces: formal G1 PASS/FAIL record with evidence

- [ ] **Step 1: Crash-window test** — simulate: order SUBMITTED durably, process killed before terminal status, restart → engine must fold back the in-flight order, re-register risk reservation, and reconcile to broker truth. One failing test first if the suite is new.
- [ ] **Step 2: Single-position + shared-capital invariant** — two engines, one capital book, one active position per underlying root: multi-root and same-root scenarios.
- [ ] **Step 3: Ledger truthfulness on restart** — a durable `UNKNOWN` row from M1's path must be reconcile-required and never blind-retried.
- [ ] **Step 4: Record GO/NO-GO in tracker.** NO-GO halts Phase 2/3 until the failing invariant is fixed with a fresh failing test.

---

## Phase 2 — Parallel hardening lanes

### Task L1: Make `runtime_audit` executable and CI-gated (parallel-safe NOW)

**Files:**
- Modify: `runtime_audit/` (boot path that hangs — diagnose first), `.github/workflows/*.yml` (add system suite step), possibly `pytest.ini`

**Interfaces:**
- Consumes: nothing from the spine (boots the real app — must not run concurrently with M1/M2 in the same worktree)
- Produces: a system-test suite that boots the app with lifecycle on and exits, wired into CI

- [ ] **Step 1: Reproduce the hang** — run `.venv/bin/python -m pytest runtime_audit -q --no-header -x --timeout=120` under idle load; capture where it blocks (lifespan? feed thread? capture window).
- [ ] **Step 2: One failing test first** for the hang cause (e.g., a test asserting the app reaches READY within N seconds).
- [ ] **Step 3: Fix the boot/capture path** — minimal change (event wait instead of sleep, teardown ordering).
- [ ] **Step 4: Add CI step** mirroring existing workflow style: `PYTHONPATH=backend:. python -m pytest runtime_audit -q --tb=short`.
- [ ] **Step 5: Gate** — suite exits green locally; CI config linted.
  **Acceptance:** `runtime_audit` no longer a silent gap; CI command list in the review report §5 is outdated → update that doc line.

### Task L2: Extend the conformance pattern to IBroker/IMarketData (parallel-safe NOW)

**Files:**
- Create: `tests/quant/execution/test_broker_conformance.py` (IBroker error-contract table), `backend/tests/unit/infrastructure/test_market_data_conformance.py` (IMarketData)

**Interfaces:**
- Consumes: `quant/contracts/ports/broker.py` (3-method ABC), `quant/contracts/ports/market_data.py` (documented error semantics: `fetch_history` → `[]` on no data but raises on API failure; `get_ltp` → `0.0` on unavailable), both adapters
- Produces: table tests pinning every adapter's behavior to the port docstring

- [ ] **Step 1: Write the conformance table for `IBroker`** — for `DhanBrokerAdapter` and `PaperBrokerAdapter`: execute with invalid quantity → raises before venue; cancel of unknown id → defined outcome; close with no position → defined outcome. One failing assertion per gap first.
- [ ] **Step 2: Write the `IMarketData` table** — each method × (empty result, API failure, timeout) → documented return/raise.
- [ ] **Step 3: Fix adapter gaps** (only where a table row fails and the port docstring demands the behavior).
- [ ] **Step 4: Gate** — new suites + `backend/tests/unit/infrastructure` green.
  **Acceptance:** every error-semantics sentence in both port docstrings has a test row.

### Task L3: One paper-execution path (start after M1; commit after M2)

**Files:**
- Decide: keep `PaperOMS` (`quant/execution/oms.py`) and delete `PaperBrokerAdapter` paper path, OR route paper through `IBroker`. Default ruling from the duplication review: **paper mode routes through the injected OMS; the DI `PaperBrokerAdapter` is only a startup-reconciliation/one-shot IBroker** — if that is still true post-merge, delete the adapter and its DI branch; if any live caller exists, keep and delete `PaperOMS` instead.
- Modify: `quant/multi_engine.py` (paper OMS selection), `backend/app/application/di/composition_root.py` (adapter branch), delete the redundant simulator + its tests
- Test: consolidation suite proving paper fill semantics identical before/after

- [ ] **Step 1: Post-merge caller scan** — grep every `PaperBrokerAdapter` and `PaperOMS` reference in the M1 tree; write the decision with evidence into the tracker.
- [ ] **Step 2: One failing test first** capturing today's paper fill semantics (quantity, partial, pyramid) on the surviving path.
- [ ] **Step 3: Delete the redundant simulator and its DI branch** per the ruling.
- [ ] **Step 4: Gate** — paper-mode end-to-end + full quant + backend suites green.
  **Acceptance:** exactly one paper answer; review report §4 row resolved.

### Task L4: Day-1 alert set (after M1)

**Files:**
- Create: alert sink module under `backend/app/domain/ops/` or extend metrics — follow existing `metrics.py` patterns
- Test: alert tests

- [ ] **Step 1: Wire the five Day-1 alerts** from the review report §8: (1) any durable `UNKNOWN` row; (2) engine/broker/ledger position-set delta ≠ 0 (reconciliation output); (3) SessionRisk daily loss approaching `absolute_ceiling_pct`; (4) tick-drop/stale-feed counter (w5 capability — after M1); (5) WS disconnect/reconnect.
- [ ] **Step 2: One failing test per alert trigger**, then implement.
- [ ] **Step 3: Gate** — alert unit tests green; manual trigger check.
  **Acceptance:** each alert fires with symbol/severity context; no alert is swallowed (test asserts logger/metric emission).

### Task L5: G2 deletion gates (L5a scans NOW; L5b deletions after M2)

**Files:**
- Scan: `coordinator_view`, `ws_contract` legacy seams, duplicate types/constants (D5 list)
- Delete (after M2): verified-unimported modules only

- [ ] **Step 1: L5a importer scans (NOW, read-only)** — caller-scan `coordinator_view`, `ws_contract`, duplicate `Position`/`Bar`/`Signal` helper modules; record findings in tracker.
- [ ] **Step 2: L5b (after M2)** — delete each verified-unimported module with a fresh failing test proving no importer, mirroring the `fc35eb56` deletion lane.
- [ ] **Step 3: Gate** — full suites green post-deletion.
  **Acceptance:** deletion list matches the review report §5 exactly; nothing "kept just in case".

### Task L6: `tests/e2e` CI decision (parallel-safe NOW)

**Files:**
- Modify: `.github/workflows/*.yml` or `docs/architecture/predeploy-refactor-execution-plan.md`

- [ ] **Step 1: Inventory** — list `tests/e2e` tests; check which need a live broker/live gate.
- [ ] **Step 2: Decide** — wire the non-live subset into CI, or mark the whole dir manual with a `# ponytail:` note at the top of each file. Default: wire the subset that passes hermetically.
- [ ] **Step 3: Gate** — CI yaml lint + chosen subset green locally.
  **Acceptance:** no test directory is silently unexecuted; review report §5 row resolved.

---

## Phase 3 — Shadow and final gate

### Task P8: Paper-shadow day (after Phase 2)

- [ ] **Step 1:** Run the merged stack in paper mode for a full session against recorded/live ticks; verify trace parity (B7 passive trace events == folded state) and the Day-1 alert set fires only on true anomalies.
- [ ] **Step 2:** Record shadow report (entries, fills, risk book, alert log) into `docs/reviews/`.
- **Acceptance:** zero unexplained divergences between trace, journal, ledger, and UI snapshot.

### Task P9: Final GO/NO-GO record

- [ ] **Step 1:** Re-run every gate suite from Phase 1 M1/M2/M3 at HEAD.
- [ ] **Step 2:** Write the final GO/NO-GO in the tracker with the seven-part review format of the review report §1–§9 updated to the merged tree.
- **Acceptance:** a dated, evidence-backed decision; NO-GO lists exactly which invariant failed.

---

## Parallelism Schedule

| Lane | Start | Files overlap risk | Gate |
|---|---|---|---|
| M1 (coordinator) | Phase 0 done | — | full suites |
| L1, L2, L5a, L6 | NOW (separate worktrees/branches) | none in the 25-file conflict set | local suites + CI |
| M2 (coordinator) | M1 green | — | staged gates + full suites |
| L3 | M1 green; commit after M2 | `paper_broker.py`, `multi_engine.py`, `composition_root.py` | consolidation suite |
| L4 | M1 green | `metrics.py` patterns only | alert tests |
| L5b | M2 green | quant-core deletions | full suites |
| M3, P8, P9 | sequential after prior | — | G1 record → shadow → GO/NO-GO |

## Agent Launch Prompts (coordinator dispatches)

- **Merge agent (M1):** "Merge `fix/w5-money-safety` into the feat branch per Task M1: resolve the 9 listed conflicts applying the reconciliation rules (feat hardening wins; ONE UNKNOWN path), then pass the staged regression gates. Record the handoff."
- **Merge agent (M2):** "Merge `fix/event-sourced-architecture` per Task M2 in staged order A→B→C, keeping feat's B1/B2/B3/risk/single-position behavior in every conflict, deleting `observation.py` (modify/delete), and proving `load_inflight_orders` gained a production caller."
- **L1 agent:** "Diagnose and fix the `runtime_audit` boot hang, then wire the suite into CI per Task L1."
- **L2 agent:** "Write IBroker and IMarketData conformance tables per Task L2; fix only adapter rows the port docstring demands."
- **L3 agent:** "Resolve the paper-simulator duplication per Task L3: caller-scan, pick the surviving path with evidence, delete the other."
- **L4 agent:** "Implement the five Day-1 alerts per Task L4 with one failing test per trigger."
- **L5/L6 agents:** "Run the G2 importer scans / e2e CI decision per Task L5a/L6; deletions wait for M2."

## Final Release Gate

No commit on this program authorizes a live order. After M3 + Phase 2 all green and P8's shadow day shows trace parity, the coordinator presents the P9 record and a one-lot canary plan to the user for explicit approval. Push of the merged branch also requires explicit user approval (Global Constraint 7).
