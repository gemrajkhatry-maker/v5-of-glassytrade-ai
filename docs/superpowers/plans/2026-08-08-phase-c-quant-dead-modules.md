# Phase C — Delete Quant Legacy Decision/Execution/Probability/Contracts Dead Modules

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development or superpowers:executing-plans to implement this plan. Steps use checkbox (`- [x]`) syntax.

**Goal:** Delete the 48 truly-dead quant modules (fresh reachability analysis, post-Phase-B2) + relocate 1 test fixture, spanning 4 sub-waves executed and reviewed sequentially. Removes the legacy "second brain" (dead `quant/decision/gates/*` + `quant/probability/agent_pipeline`) and the legacy execution cluster, leaving `quant/decision/pipeline.py`, `decision/signal_builder.py`, `execution/exits.py` as the canonical runtime path.

**IMPORTANT — fresh analysis replaces the stale audit:** The 2026-08-08 audit was built at `ef7469d4`, BEFORE B2 deleted backend modules that were evidence for some quant KEEPs. A coordinator re-ran full import-reachability from production roots (`backend/app`, `brokers`, `shared`) at HEAD `5b6508c`:
- **49 dead modules** (zero production reachability, verified)
- **24 pure-dead test files** (test only dead modules → delete whole file)
- **60 mixed test files** (test dead + live → surgical trim)
- Zero production imports of any dead module (grep-verified) — the DI binding removals in Phase A + adapter deletions in Phase B2 eliminated the last prod refs.

**Special cases (user-approved, 2026-08-08):**
1. `quant/brokers/synthetic.py` is a **test fixture for LIVE runtime tests** (7 files: test_runtime, test_golden_runtime, test_llm_hook, test_full_stack, test_paper_protocol, test_quant_runtime_e2e, test_synthetic) — **MOVE to `tests/helpers/`**, do NOT delete.
2. `tests/quant/consolidation/test_gate_divergence.py` is a **divergence harness comparing live vs legacy brains** — obsolete once legacy is gone → **DELETE whole file**.
3. `backend/tests/runtime_validation/test_phase1_leaf_components.py` (kept in B2, has the known float flake) tests the **dead** legacy path (`gates.signal_builder.build_entry_signal` + `execution.exit_engine.ExitEngine`). The LIVE equivalents have different interfaces (`decision.signal_builder.SignalBuilder.build(ctx, pipeline_results)`; `execution.exits.ExitEngine.evaluate`). **REWRITE against the LIVE pipeline** — the live path already has coverage (`test_signal_builder_guards.py`, `test_exits.py`, `test_pipeline_e2e.py`), so the rewrite should adapt the phase1 assertions to live interfaces OR, where a leaf is only-legacy, drop that leaf test.
4. `tests/quant/execution/test_parity.py` — audit confirms dead execution modules were "parity-moved from removed app.domain shims"; this file tests only the dead cluster → **DELETE whole file**.
5. `tests/quant/test_full_stack.py` tests LIVE coordinator/pipeline but uses dead `advisory.entry_journal`/`chat` → **surgical trim**.

**Execution model:** 4 sub-waves (C1→C4), each a separate implementer dispatch with its own commit(s), verification, and coordinator review before the next. This plan doc is the reference for all four.

## Global Constraints

- **quant purity is a hard constraint:** `quant.*` may NEVER import `app.*`. Verify after each wave.
- **NEVER `git add -A` / `git add .`.** Stage exact paths only. `graphify-out/`, `backend/graphify-out/`, `.superpowers/`, `docs/superpowers/plans/*.md` must NEVER be committed.
- Backend tests: `cd backend && ../.venv/bin/python3 -m pytest <path> -q --no-header`. Quant tests: `.venv/bin/python3 -m pytest tests/quant -q --no-header` (from repo root).
- Never commit failing tests. The 2 KNOWN pre-existing failures are `TestAIHistory::test_history_endpoint_exists` (order-dependent flake) and `test_long_signal_builds_valid_rr` (float precision) — the latter is IN a file being rewritten in C4; after rewrite it must be resolved or the float test dropped.
- If any safety-gate grep finds a REAL production importer, STOP and report.

---

## Wave C1 — Delete decision/gates + probability dead modules (19 modules)

### C1-A: Delete 8 dead `decision/gates` modules

**Files (delete):**
- `quant/decision/gates/confirmation_bundle.py`
- `quant/decision/gates/gate_runner.py`
- `quant/decision/gates/grading.py`
- `quant/decision/gates/legacy_gate_pipeline.py`
- `quant/decision/gates/scalp.py`
- `quant/decision/gates/short.py`
- `quant/decision/gates/signal_builder.py`
- `quant/decision/gates/three_align.py`

- [x] **Step 1: Safety-gate — confirm only tests import these (no prod)**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
grep -rln "decision.gates\|from quant.decision.gates\|gates.legacy_gate_pipeline\|gates.signal_builder\|gates.three_align\|gates.confirmation_bundle\|gates.gate_runner\|gates.grading\|gates.scalp\|gates.short" --include="*.py" backend/app brokers shared | grep -v __pycache__
```
Expected: empty (no production importers). If any hit, STOP.

- [x] **Step 2: Record quant baseline**

Run: `.venv/bin/python3 -m pytest tests/quant -q --no-header 2>&1 | tail -2` → record pass/skip counts. **Baseline: 1459 passed, 29 skipped.**

- [x] **Step 3: Delete the 8 modules**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
git rm quant/decision/gates/confirmation_bundle.py quant/decision/gates/gate_runner.py quant/decision/gates/grading.py quant/decision/gates/legacy_gate_pipeline.py quant/decision/gates/scalp.py quant/decision/gates/short.py quant/decision/gates/signal_builder.py quant/decision/gates/three_align.py
```
(Note: if `quant/decision/gates/__init__.py` re-exports any, trim it after — check first: `cat quant/decision/gates/__init__.py`.) — `__init__.py` was empty; no trim needed.

- [x] **Step 4: Delete the pure-dead test files for these modules**

```bash
git rm tests/quant/decision/gates/test_gate_runner_dynamic_risk.py tests/quant/decision/gates/test_scalp.py tests/quant/decision/gates/test_short.py
```
(These 3 are PURE dead — verified only-dead imports.)

- [x] **Step 5: Run quant suite — expect failures in MIXED files (trim next)**

Run: `.venv/bin/python3 -m pytest tests/quant -q --no-header 2>&1 | tail -6`
Expected: collection errors / import failures in the mixed files that import the deleted gates (e.g. `tests/quant/decision/gates/test_confirmation_bundle.py`, `test_gates_entry_signal_builder.py`, `test_three_align.py`, `test_golden_week1.py`, `test_gate_runner_entry_signal_chain.py`, `tests/quant/amt/test_analyzer.py`, `backend/tests/unit/domain/test_amt_analyzer.py`, `backend/tests/unit/domain/test_entry_gate.py`, etc.). This is expected — C1-C trims them.

### C1-B: Delete 4 dead `decision` (non-gates) modules

**Files (delete):**
- `quant/decision/signal_coordinator.py`
- `quant/decision/sizer.py`
- `quant/decision/trade_thesis.py`
- `quant/decision/vwap_breakout.py`

- [x] **Step 1: Safety-gate**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
grep -rln "signal_coordinator\|trade_thesis\|vwap_breakout\|decision.sizer\|from quant.decision import sizer" --include="*.py" backend/app brokers shared | grep -v __pycache__
```
Expected: empty. (Only hit was a false positive — `trade_thesis` as a local dict parameter name in `backend/app/application/services/trade_journal.py`, not an import.)

- [x] **Step 2: Delete the 4 modules + their pure-dead tests**

```bash
git rm quant/decision/signal_coordinator.py quant/decision/sizer.py quant/decision/trade_thesis.py quant/decision/vwap_breakout.py
git rm tests/quant/decision/test_signal_coordinator.py tests/quant/decision/test_sizer_parity.py tests/quant/decision/test_vwap_breakout.py tests/quant/decision/test_vwap_breakout_parity.py
```

### C1-C: Delete 7 dead `probability` modules (except features.py)

**Files (delete):**
- `quant/probability/agent_pipeline.py`
- `quant/probability/direction_timing.py`
- `quant/probability/labels.py`
- `quant/probability/playbook.py`
- `quant/probability/regime.py`
- `quant/probability/regime_hysteresis.py`
- `quant/probability/sizing.py`

- [x] **Step 1: Safety-gate**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
grep -rln "probability.agent_pipeline\|probability.direction_timing\|probability.playbook\|probability.regime\|probability.sizing\|probability.labels\|probability.regime_hysteresis" --include="*.py" backend/app brokers shared | grep -v __pycache__
```
Expected: empty. **KEEP `quant/probability/features.py`** (live — health router + lgbm adapter path). Check `quant/probability/__init__.py` re-exports and trim if needed. — `__init__.py` rewritten to a package marker (all re-exports were from dead modules; `features.py` is NOT re-exported by the package root and no test imports the package root).

- [x] **Step 2: Delete the 7 modules + their pure-dead tests**

```bash
git rm quant/probability/agent_pipeline.py quant/probability/direction_timing.py quant/probability/labels.py quant/probability/playbook.py quant/probability/regime.py quant/probability/regime_hysteresis.py quant/probability/sizing.py
```
Pure-dead tests for probability: `tests/quant/probability/test_timing_probability.py` is MIXED (has live value_objects + agent_pipeline) — trim not delete. Check `tests/quant/probability/test_agent_decision_flat_output.py` + `test_agent_pipeline_playbooks.py` + `test_probability_parity.py` — these are MIXED (agent_pipeline dead + live contracts/value_objects/features) → trim.
**Actual outcome:** `test_agent_decision_flat_output.py`, `test_agent_pipeline_playbooks.py`, `test_timing_probability.py` DELETED whole (per C1-D Step 1 rule: ALL their tests exercise only dead `agent_pipeline`; the live value_objects/enums are just input builders, never the subject). `test_probability_parity.py` TRIMMED to the 2 live `features` smoke tests.

### C1-D: Trim the mixed test files for C1 modules

For each mixed file importing a C1-dead module, remove the dead imports + any test functions/classes whose ONLY purpose is testing a dead module. KEEP live-quant tests.

**backend/tests mixed (trim):**
- `backend/tests/unit/application/test_agent_guards.py` — remove `grading`, `gates.signal_builder`, `session_risk_manager` imports + their tests; keep enum/value_objects tests.
- `backend/tests/unit/domain/test_agent_decision_flat_output.py` — remove `agent_pipeline` import + its tests.
- `backend/tests/unit/domain/test_agent_pipeline_playbooks.py` — remove `agent_pipeline` import + tests.
- `backend/tests/unit/domain/test_aggressive_prints.py` — remove `gates.signal_builder` import + tests (keep amt.analyzer tests).
- `backend/tests/unit/domain/test_amt_analyzer.py` — remove `confirmation_bundle`/`three_align` imports + those tests (keep the many amt.analyzer tests).
- `backend/tests/unit/domain/test_cushion_sl.py` — remove `gates.signal_builder` + tests.
- `backend/tests/unit/domain/test_entry_gate.py` — remove `confirmation_bundle`, `grading`, `gates.signal_builder`, `three_align` imports + tests.
- `backend/tests/unit/domain/test_ib_and_short.py` — remove `gates.short` import + short tests (keep ib_engine tests).
- `backend/tests/unit/domain/test_timing_probability.py` — remove `agent_pipeline` import + tests.
- `backend/tests/unit/test_p1_p10_fixes.py` — remove `three_align` import + tests (keep prompt_builder).
- `backend/tests/test_mcx_offsets.py` — remove `confirmation_bundle`, `three_align`, `agent_pipeline` imports + those tests.
- `backend/tests/validation/test_amt_stability_fixes.py` — remove `legacy_gate_pipeline` import + tests (keep amt.analyzer/state_engine).
- `backend/tests/validation/test_amt_validation.py` — remove `three_align` import + tests.
- `backend/tests/integration/test_raci_bindings.py` — remove `legacy_gate_pipeline` import + its test.

**tests/quant mixed (trim):**
- `tests/quant/decision/gates/test_confirmation_bundle.py` — remove `confirmation_bundle` import + tests (only dead → likely delete whole file; it imports live value_objects for types but tests only confirmation_bundle).
- `tests/quant/decision/gates/test_gate_runner_entry_signal_chain.py` — remove `gate_runner`+`gates.signal_builder` imports + tests.
- `tests/quant/decision/gates/test_gates_entry_signal_builder.py` + `test_gates_entry_signal_builder_parity.py` — remove `gates.signal_builder` imports + tests (these test the DEAD signal_builder; only live enums/value_objects remain → likely delete whole files).
- `tests/quant/decision/gates/test_golden_week1.py` — remove `gates.signal_builder` + `three_align` imports + tests.
- `tests/quant/decision/gates/test_grading.py` — remove `grading` import + tests (only dead → delete whole file).
- `tests/quant/decision/gates/test_three_align.py` — remove `three_align` import + tests (only dead → delete whole file).
- `tests/quant/decision/gates/test_gate_13_session_filter.py`, `test_gate_pipeline.py`, `test_gate_pipeline_slim.py`, `test_gate_pipeline_soft_gates.py` — all import ONLY `legacy_gate_pipeline` (dead) + live enums → **DELETE whole files** (they test the dead legacy pipeline).
- `tests/quant/amt/test_analyzer.py` — remove `confirmation_bundle`/`three_align` imports + those tests (keep amt.analyzer).
- `tests/quant/probability/test_agent_decision_flat_output.py` — remove `agent_pipeline` import + tests.
- `tests/quant/probability/test_agent_pipeline_playbooks.py` — remove `agent_pipeline` import + tests.
- `tests/quant/probability/test_probability_parity.py` — remove `agent_pipeline` import + tests (keep features).
- `tests/quant/probability/test_timing_probability.py` — remove `agent_pipeline` import + tests.
- `backend/tests/runtime_validation/test_phase1_leaf_components.py` — **DEFERRED to C4** (full rewrite).

- [x] **Step 1: For each mixed file, verify each test function's dependency before deleting** — grep the file for the dead symbol; if ALL tests in the file use only the dead module, delete the whole file; otherwise remove just those imports + test functions.
**Outcome:** Whole-file DELETES (all tests only exercise C1-dead modules): `tests/quant/decision/gates/test_confirmation_bundle.py`, `test_gate_runner_entry_signal_chain.py`, `test_golden_week1.py`, `test_gates_entry_signal_builder.py`, `test_gates_entry_signal_builder_parity.py`, `test_grading.py`, `test_three_align.py`, `test_gate_13_session_filter.py`, `test_gate_pipeline.py`, `test_gate_pipeline_slim.py`, `test_gate_pipeline_soft_gates.py`, `tests/quant/probability/test_agent_decision_flat_output.py`, `test_agent_pipeline_playbooks.py`, `test_timing_probability.py`, `backend/tests/unit/domain/test_agent_decision_flat_output.py`, `test_agent_pipeline_playbooks.py`, `test_cushion_sl.py`, `test_entry_gate.py`, `test_timing_probability.py`, `backend/tests/test_mcx_offsets.py`. TRIMMED (kept live tests): `tests/quant/amt/test_analyzer.py`, `tests/quant/probability/test_probability_parity.py`, `backend/tests/unit/application/test_agent_guards.py`, `test_aggressive_prints.py`, `test_amt_analyzer.py`, `test_ib_and_short.py`, `test_p1_p10_fixes.py`, `backend/tests/validation/test_amt_stability_fixes.py`, `test_amt_validation.py`, `backend/tests/integration/test_raci_bindings.py`. C4-DEFERRED (module-level `pytest.skip`): `tests/quant/consolidation/test_gate_divergence.py` + `backend/tests/runtime_validation/test_phase1_leaf_components.py`.

- [x] **Step 2: Run full quant + backend suites**

Run: `.venv/bin/python3 -m pytest tests/quant -q --no-header 2>&1 | tail -3` → green (except C4-deferred phase1 if it still imports dead code — temporarily mark it with a skipif or fix imports in this wave to keep suite green).
Run: `cd backend && ../.venv/bin/python3 -m pytest tests/unit tests/integration -q --no-header 2>&1 | tail -3` → green except the 2 known flakes (one is in phase1 → see note).
**Results:** Quant green — 1253 passed, 29 skipped (gate_divergence module-skipped). Backend full suite green — 1088 passed, 61 skipped. The single order-dependent `TestAIHistory::test_history_endpoint_exists` flake reproduced once (passes in isolation) — the documented known flake; the phase1 float flake is masked by the C4 skip marker.

- [x] **Step 3: Commit**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
git add quant/ tests/
git add -u backend/tests/
git commit -m "refactor: delete legacy decision gates + probability agent pipeline (dead second brain)"
```
**CAUTION:** Stage EXACT paths. Verify `git status` before commit; if graphify-out/.superpowers staged, `git reset` them. — `docs/superpowers/plans/*.md` never staged; graphify-out artifacts left untracked.

---

## Wave C2 — Delete execution legacy dead modules (13 modules)

**Files (delete):**
- `quant/execution/circuit_breakers.py`
- `quant/execution/exit_engine.py`
- `quant/execution/kill_switch.py`
- `quant/execution/loss_tracker.py`
- `quant/execution/partition.py`
- `quant/execution/pyramid.py`
- `quant/execution/risk_manager.py`
- `quant/execution/risk_sizing.py`
- `quant/execution/risk_tier.py`
- `quant/execution/scale.py`
- `quant/execution/session_risk_manager.py`
- `quant/execution/signal_validator.py`
- `quant/execution/trail.py`

**KEEP (live runtime path):** `exits.py`, `oms.py`, `order.py`, `risk.py`, `trade_costs.py`.

- [x] **Step 1: Safety-gate**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
grep -rln "execution.circuit_breakers\|execution.exit_engine\|execution.kill_switch\|execution.loss_tracker\|execution.partition\|execution.pyramid\|execution.risk_manager\|execution.risk_sizing\|execution.risk_tier\|execution.scale\|execution.session_risk_manager\|execution.signal_validator\|execution.trail" --include="*.py" backend/app brokers shared | grep -v __pycache__
```
Expected: empty. **KEEP `quant/execution/exits.py`** (live ExitEngine). Note: `execution/__init__.py` may re-export — trim if needed.

- [x] **Step 2: Delete the 13 modules + pure-dead tests**

```bash
git rm quant/execution/circuit_breakers.py quant/execution/exit_engine.py quant/execution/kill_switch.py quant/execution/loss_tracker.py quant/execution/partition.py quant/execution/pyramid.py quant/execution/risk_manager.py quant/execution/risk_sizing.py quant/execution/risk_tier.py quant/execution/scale.py quant/execution/session_risk_manager.py quant/execution/signal_validator.py quant/execution/trail.py
```
Pure-dead tests to delete: `tests/quant/execution/test_circuit_breakers.py`, `test_kill_switch.py`, `test_loss_tracker.py`, `test_partition.py`, `test_pyramid.py`, `test_risk_sizing.py`, `test_risk_tier.py`, `test_session_risk_manager.py`, `test_parity.py` (entirely dead cluster — user-approved delete), `backend/tests/unit/domain/test_deterministic_engine.py` (only risk_sizing).

- [x] **Step 3: Trim mixed execution tests**

- `tests/quant/execution/test_parity.py` — **DELETE whole file** (user-approved; tests only dead cluster).
- `tests/quant/execution/test_exit_engine_pyramid.py` — remove `exit_engine` import + tests (only dead → likely delete whole file).
- `tests/quant/execution/test_pyramid_integration.py` — remove `pyramid` import + tests (keep aggregates/entities).
- `tests/quant/execution/test_risk_manager.py` + `test_risk_manager_enhanced.py` — remove `risk_manager` import + tests.
- `tests/quant/execution/test_scale.py` — remove `scale` import + tests.
- `tests/quant/execution/test_signal_validator.py` + `test_signal_validator_extended.py` — remove `signal_validator` import + tests.
- `tests/quant/execution/test_trade_manager.py` — remove `exit_engine` import + tests. **IMPORTANT (coordinator re-verify 2026-08-09): `exit_rules` + `exit_signal` are LIVE — imported by `quant/contracts/aggregates.py:20` and `quant/contracts/entities.py:22` (and `exit_rules` imports `exit_signal`). They MUST be KEPT and are NOT in the C2 delete list.** An earlier reachability scan mis-flagged them dead (missing the contracts→exit_rules edge); the corrected scan keeps them. The C4 phase1 rewrite must target the LIVE `exits.py` interface, NOT `exit_rules`.
- `tests/quant/execution/test_trail.py` — remove `trail` import + tests.
- `backend/tests/integration/test_e2e_broker_mock.py` + `test_trade_lifecycle_full.py` — remove `circuit_breakers`/`exit_engine` imports + tests.
- `backend/tests/unit/domain/test_tick_size_lifecycle.py` — remove `exit_engine`/`partition` imports + tests.
- `backend/tests/runtime_validation/test_phase1_leaf_components.py` — DEFERRED to C4.

- [x] **Step 4: Verify + commit**

Run both suites (green except known flakes), then:
```bash
git add quant/execution/ tests/quant/execution/ backend/tests/
git commit -m "refactor: delete legacy execution cluster (dead parity shims)"
```
Verify exact staging.

---

## Wave C3 — Delete advisory + contracts + ports dead modules (16 modules)

**Files (delete):**
- `quant/advisory/chat.py`
- `quant/advisory/entry_journal.py`
- `quant/advisory/overseer.py`
- `quant/contracts/cvd.py`
- `quant/contracts/event_store.py`
- `quant/contracts/events.py`
- `quant/contracts/initial_balance.py`
- `quant/contracts/trading_context.py`
- `quant/contracts/utils.py`
- `quant/contracts/vwap_bands.py`
- `quant/contracts/ports/delta_profile.py`
- `quant/contracts/ports/exchange_strategy.py`
- `quant/contracts/ports/notification_adapter.py`
- `quant/contracts/ports/notifications.py`
- `quant/contracts/ports/probability_inference.py`
- `quant/inference/learning_engine.py`

**KEEP:** `quant/advisory/__init__.py` (may be empty), `quant/contracts/ports/__init__.py` re-exports of KEPT ports (`config_port`, `storage`, `broker`, `market_data`, `llm_inference`), `quant/contracts/ports/npoc.py` (check reachability — the fresh scan did NOT list it dead, verify before touching).

- [x] **Step 1: Safety-gate**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
grep -rln "advisory.chat\|advisory.entry_journal\|advisory.overseer\|contracts.cvd\|contracts.event_store\|contracts.events\|contracts.initial_balance\|contracts.trading_context\|contracts.utils\|contracts.vwap_bands\|ports.delta_profile\|ports.exchange_strategy\|ports.notification_adapter\|ports.notifications\|ports.probability_inference\|inference.learning_engine" --include="*.py" backend/app brokers shared | grep -v __pycache__
```
Expected: empty. Trim `quant/contracts/ports/__init__.py` to remove the dead re-exports (lines for delta_profile, exchange_strategy, notification_adapter, notifications, probability_inference) — but FIRST check whether `test_exchange_abstraction.py` (Phase-A-modified) imports from `quant.contracts.ports`; if so update it to import the kept port only or drop the dead-port assertions.

- [x] **Step 2: Delete modules + pure-dead tests**

```bash
git rm quant/advisory/chat.py quant/advisory/entry_journal.py quant/advisory/overseer.py
git rm quant/contracts/cvd.py quant/contracts/event_store.py quant/contracts/events.py quant/contracts/initial_balance.py quant/contracts/trading_context.py quant/contracts/utils.py quant/contracts/vwap_bands.py
git rm quant/contracts/ports/delta_profile.py quant/contracts/ports/exchange_strategy.py quant/contracts/ports/notification_adapter.py quant/contracts/ports/notifications.py quant/contracts/ports/probability_inference.py
git rm quant/inference/learning_engine.py
```
Pure-dead tests to delete: `tests/quant/contracts/test_cvd.py`, `test_event_store.py`, `test_side_normalize.py`, `test_trading_context.py`, `backend/tests/unit/domain/trading/models/test_cvd.py`, `backend/tests/unit/domain/test_event_store.py`, `backend/tests/unit/test_side_normalize.py`, `backend/tests/unit/test_trading_context.py`.

- [x] **Step 3: Trim mixed files**

- `tests/quant/advisory/test_entry_journal.py` + `test_overseer.py` — DELETE whole files (test only dead advisory; the live imports auction_state/location/etc. are supporting, not the subject).
- `backend/tests/unit/domain/test_exchange_abstraction.py` — update/remove the dead-port imports (`ports.delta_profile`, `exchange_strategy`, `notification_adapter`, `notifications`, `probability_inference`) + their assertions; keep the Phase-A `test_di_container_wiring` (adjust to assert the kept ports only or drop the removed-port checks).
- `backend/tests/unit/domain/test_audit_fixes.py` — remove `contracts.events` import + tests (keep aggregates/entities/enums).
- `backend/tests/unit/domain/test_learning_engine.py` + `tests/quant/inference/test_learning_engine.py` — remove `learning_engine` import + tests (keep inference.models tests).
- `backend/tests/unit/domain/test_prompt_builder.py` + `tests/quant/inference/test_prompt_builder.py` — remove `inference.learning_engine` import + tests (keep prompt_builder).
- `backend/tests/unit/domain/test_amt_analyzer.py` — check `contracts.events`/`trading_context` refs; trim if present.
- `tests/quant/test_full_stack.py` — DEFERRED to C4 (trim advisory usage).

- [x] **Step 4: Verify + commit**

Run both suites (green except known flakes), then:
```bash
git add quant/advisory/ quant/contracts/ quant/inference/ tests/ backend/tests/
git commit -m "refactor: delete dead advisory/contracts/ports modules"
```

---

## Wave C4 — Special cases: fixture move + harness deletes + phase1 rewrite + full_stack trim

### C4-A: Move brokers.synthetic fixture to tests/helpers

- [x] **Step 1: Verify consumers are all tests**

```bash
cd /Users/apple/Documents/v5-of-glassytrade-ai
grep -rln "brokers.synthetic\|SyntheticGateway" --include="*.py" backend/app brokers shared quant | grep -v __pycache__ | grep -v "quant/brokers/synthetic.py"
```
Expected: only test files (tests/quant/runtime/*, tests/system/*, tests/quant/test_full_stack.py, tests/quant/brokers/test_synthetic.py). If any prod hit, STOP.

- [x] **Step 2: Move to tests/helpers/**

```bash
git mv quant/brokers/synthetic.py tests/helpers/synthetic.py
```
Update all test imports: `from quant.brokers.synthetic import SyntheticGateway` → `from tests.helpers.synthetic import SyntheticGateway` (backend tests: `from helpers.synthetic import` per B2 convention — match each file's existing convention). Ensure the moved file imports only quant (it imports `quant.brokers.gateway.Tick` — fine).

- [x] **Step 3: Delete tests/quant/brokers/test_synthetic.py** (its only subject is the fixture itself — its behavior is exercised via the live runtime tests).

### C4-B: Delete the divergence harness + parity shim tests

- [x] **Step 1: Delete `tests/quant/consolidation/test_gate_divergence.py`** (compares live vs legacy — obsolete; live path covered by test_pipeline_e2e/test_signal_builder_guards/test_exits).
- [x] **Step 2: Confirm no other test imports it** — grep `gate_divergence` → empty.

### C4-C: Rewrite test_phase1_leaf_components.py against the LIVE pipeline

- [x] **Step 1: Read the current file fully** and the live equivalents:
  - Live signal: `quant/decision/signal_builder.py` (`SignalBuilder.build(ctx, pipeline_results)`, guards `is_stop_too_thin`/`is_min_stop_met`/`clamp_quantity`).
  - Live exits: `quant/execution/exits.py` (`ExitEngine.evaluate`, `ExitDecision`).
  - Live context: `quant/decision/context.py` (`DecisionContext`).
- [x] **Step 2: Rewrite each leaf test to use the LIVE interfaces.** Map:
  - `compute_atr` (dead confirmation_bundle) → if the live path computes ATR elsewhere, use that; otherwise DROP the ATR leaf test (it was testing a dead module).
  - `update_excursions` (dead exit_rules) → live equivalent in `exits.py`/`oms.py` if any; else DROP.
  - `build_entry_signal` (dead gates.signal_builder) → `SignalBuilder().build(ctx, results)` with a constructed `DecisionContext` + minimal `GateResult` list.
  - `ExitEngine.is_valid_rr` (dead) → live `ExitEngine` in `execution/exits.py` (check if it has an RR helper; if not, assert the live stop/target semantics or DROP the RR assertion).
  - **Resolve the known float flake** `test_long_signal_builds_valid_rr`: after rewrite, either the assertion holds on live interfaces or the test is dropped/replaced.
- [x] **Step 3: The rewritten file must keep only tests that exercise LIVE code.** Any leaf with no live equivalent is deleted. The file stays at `backend/tests/runtime_validation/test_phase1_leaf_components.py`.

### C4-D: Trim test_full_stack.py

- [x] **Step 1: Remove the dead `advisory.entry_journal`/`chat` usage.** Replace `EntryJournal(FakeChat())` with a lightweight in-test stub that records entries (or drop the journal entirely if it only feeds a non-asserted path). Keep the live coordinator/pipeline/exit assertions intact.

### C4-E: Final verification

- [x] **Step 1: Full backend suite**
Run: `cd backend && ../.venv/bin/python3 -m pytest tests/unit tests/integration -q --no-header 2>&1 | tail -3`
Expected: green except the ONE remaining known flake (`TestAIHistory::test_history_endpoint_exists`). The phase1 float failure MUST be resolved by the C4 rewrite.

- [x] **Step 2: Full quant suite**
Run: `.venv/bin/python3 -m pytest tests/quant -q --no-header 2>&1 | tail -2` → green.

- [x] **Step 3: Reachability re-check** — rerun the coordinator's import-reachability scan; expect 0 dead modules remain (all 48 deleted, synthetic moved, features.py kept).

- [x] **Step 4: quant purity** — `grep -rn "from app\.\|import app\." --include="*.py" quant shared | grep -v __pycache__` → empty.

- [x] **Step 5: Git hygiene** — `git log --oneline -8` + `git status --short` → only untracked artifacts remain.

---

## Definition of Done

- [x] C1: 19 decision/gates + probability dead modules deleted + mixed tests trimmed
- [x] C2: 13 execution legacy modules deleted + tests trimmed (parity deleted)
- [x] C3: 16 advisory/contracts/ports dead modules deleted + tests trimmed
- [x] C4: brokers.synthetic moved to tests/helpers; gate_divergence + test_parity deleted; phase1 rewritten to live pipeline (float flake resolved); full_stack trimmed
- [x] All 48 dead modules gone; synthetic relocated; features.py kept
- [x] Full backend + quant suites green except the single documented order-dependent flake
- [x] quant + shared purity preserved
- [x] No artifacts in any commit
