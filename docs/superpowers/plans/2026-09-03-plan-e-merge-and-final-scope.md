# Plan E — Merge, Settle, and Close Remaining Scope

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Clear every remaining item from the audit program: triage the dirty tree, push the branch, execute the architect's decisions on deferred scope, and apply logged follow-ups.

**Architecture:** Triage before merge (dirty tree committed separately or stashed — never mixed into refactor commits); investigation → ADR → implementation for the two structural items (ports, OMS); contract-pinning (not merging) where splits are intentional.

**Tech Stack:** Python 3, pytest (`pythonpath = . backend`, `--import-mode=importlib`), ruff, git, `gh`.

## Global Constraints

- `pytest.ini`: `pythonpath = . backend`, `testpaths = tests backend/tests`, `--import-mode=importlib`.
- Root tests: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/ -q --no-header`.
- Backend tests: `cd backend && PYTHONPATH=..:. ../.venv/bin/python -m pytest tests/ -q --no-header`.
- Brokers tests: `cd brokers && PYTHONPATH=..:. ../.venv/bin/python -m pytest -q --no-header`.
- Lint gate covers all touched files (system ruff if `.venv/bin/python -m ruff` missing; report binary).
- Test imports must be TOP-LEVEL (ruff E402 gate).
- NEVER mix dirty-tree content into refactor commits or vice versa. NEVER delete others' work without explicit user sign-off.
- DRY, YAGNI, TDD, frequent commits.

---

## File Structure

| File | Responsibility after plan |
|---|---|
| (dirty tree, 21 files) | Committed as `refactor: replace StateProjector with LiveQuoteCache` (iff suites green) |
| `docs/adr/0001-entity-boundary.md` (new) | Decision record: engine/broker/wire types stay split, boundary contracts named |
| `docs/adr/0002-broker-ports.md` (new) | Decision record: quant IBroker retires into IBrokerPort; IOMS stays |
| `docs/adr/0003-telemetry-split.md` (new) | Decision record: metrics/logging dispositions |
| `quant/execution/oms_conformance.py` or test-only suite | Shared OMS conformance (both implementations, same expectations) |
| `quant/reconciliation_service.py` (new) | Single DB/journal/broker reconciliation (QUARANTINE default) |
| `tests/architecture/test_no_layer_bypass.py` (extend) | Hardened LOT regex (`[\s\S]*?`), engine-boundary rule |

---

### Task 0: Dirty-tree triage (verify → commit separately or stash)

**Files:** the 21 dirty files ONLY. Touch nothing else.

**Verified facts (controller):** zero file overlap between dirty tree and all Plan A–D commits (`comm` on name lists = empty); dirty tree touches no Plan C/D seam files; coordinator methods pinned by `ICoordinatorView` are intact in the dirty diff (`snapshot(symbols…)` signatures unchanged; internals `projector→live_cache` renamed, which transport never touches).

- [ ] **Step 1: Run the affected suites on the dirty tree as-is**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/state tests/quant/runtime tests/quant/test_ws_contract.py tests/quant/test_ws_contract_parity.py tests/system/test_quant_runtime_e2e.py tests/system/test_paper_protocol.py -q --no-header`
Expected: record exact pass/fail. KNOWN: 2 failures in `tests/quant/runtime/test_state.py` were attributed to this tree during Plan B Task 3 (isolation-verified). If those same 2 fail and nothing else: proceed to Step 2. If MORE failures: STOP, report BLOCKED with the full failure list (migration is incomplete → needs finish-or-stash user call, do not commit red).

- [ ] **Step 2: Commit the dirty tree as its own commit(s)**

```bash
git add quant/decision/decision_service.py quant/multi_engine.py quant/runtime.py quant/state.py quant/ws_adapter.py tests/qa/qa_sanity_full_infra.py tests/quant/decision/test_block_reasons.py tests/quant/integration/test_desync.py tests/quant/llm/test_advisor_integration.py tests/quant/runtime/test_golden_runtime.py tests/quant/runtime/test_no_llm_hook.py tests/quant/runtime/test_state.py tests/quant/runtime/test_ws_adapter.py tests/quant/state/test_projector_events.py tests/quant/test_projector_replacement.py tests/quant/test_state_tick_interval.py tests/quant/test_ws_contract.py tests/quant/test_ws_contract_parity.py tests/system/test_paper_protocol.py tests/system/test_quant_runtime_e2e.py tests/system/test_quant_system_e2e.py
git commit -m "refactor: replace StateProjector with LiveQuoteCache"
```
If the 2 test_state failures persist: commit anyway ONLY with `git commit` message trailer `Known: 2 test_state failures pre-existing from migration (see report)` AND explicit user approval recorded in the report. Default without approval: DO NOT commit red — report NEEDS_CONTEXT (finish vs stash) and stop the plan.

- [ ] **Step 3: Verify post-commit tree clean + seams green**

Run: `git status --short` (expect clean), then `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/contracts/test_money_parity.py tests/quant/contracts/test_order_domain.py tests/quant/contracts/test_services_boundaries.py tests/quant/contracts/test_telemetry_standards.py tests/architecture/test_no_layer_bypass.py -q --no-header`
Expected: PASS (refactor seams unaffected by the migration commit).

---

### Task 1: Push branch + open PR (backup first, merge later)

- [ ] **Step 1: Push**

```bash
git push origin feat/fractal-half-trend-signals
```
Expected: branch now tracks origin (was ahead 32). If push rejected (remote moved): STOP, report BLOCKED with remote log (never force-push without explicit user approval).

- [ ] **Step 2: Open PR (DO NOT merge)**

```bash
gh pr create --title "Audit refactor: vocabulary, domain, services, telemetry (REF-01-13)" --body-file /tmp/pr-body.md
```
`/tmp/pr-body.md` content (write first): audit→plan traceability (4 plan paths + what each closed), the 2 deliberate behavior changes (Task 4 fill marker; quarantine default + opt-out env), known items (2 test_state failures if committed red; deferred scope → Plan E Tasks 2–4). Base: `main`. Report the PR URL. Merging to main is a RELEASE decision (767-commit divergence) — explicitly out of scope.

---

### Task 2: Entity boundary ADR + conformance (contract, not merge)

**Architect decision (locked):** engine-float / broker-Decimal / wire-canonical types STAY SPLIT. The float/Decimal divide is intentional (hot-loop speed vs money precision); merging risks both. The defect was implicit crossing, already fixed by `broker_mapper` + `fills` + row converters (Plan B). This task formalizes the boundary.

**Files:**
- Create: `docs/adr/0001-entity-boundary.md`
- Test: extend boundary coverage (no new impl files)

- [ ] **Step 1: Inventory every engine→broker crossing**

Grep: `to_broker_signal|broker_position_to_fill|position_to_row|row_to_position|BrokerSignal|contracts.entities import` across `quant/ backend/app`. Record each call site + direction in the report.

- [ ] **Step 2: Write ADR 0001** (one page: context, decision, crossing table, rule: "engine types cross into broker calls ONLY via broker_mapper/fills/row converters; new crossings fail review").

- [ ] **Step 3: Add roundtrip conformance** for any crossing lacking it (mapper long+short, fill fallbacks already covered; row roundtrip covered — add only genuine gaps found in Step 1).

- [ ] **Step 4: Commit** `docs: ADR-0001 entity boundary (contract over merge)` + tests.

---

### Task 3: Broker-port collapse (3→2) + OMS conformance

**Architect decision (locked):** retire quant `IBroker`; engine→`IOMS`→(`LiveOMS`)→`IBrokerPort`→broker. `IBrokerPort` (13-method hexagon) is the canonical broker abstraction; quant `IBroker` (3 methods) is redundant. `IOMS` stays (engine seam).

**Files:** TBD by investigation (expected: `quant/contracts/ports/broker.py`, `quant/execution/live_oms.py`, `backend/app/infrastructure/adapters/*`, `backend/app/application/di/composition_root.py`, backend `main.py`/`dependencies.py` IBroker references).

- [ ] **Step 1: Investigation (no code changes)**

Read `brokers/broker/ports.py:IBrokerPort` fully + list every `IBroker` importer (grep `contracts.ports.broker import|IBroker[^P]`). Record: method-by-method mapping (execute_order/close_position/cancel_order → IBrokerPort equivalents), which adapters implement what, DI wiring points. Report BLOCKED with the mapping table if any IBroker method has NO IBrokerPort equivalent (then the collapse needs a port extension first — separate decision).

- [ ] **Step 2: Write ADR 0002** with the mapping table + migration order (adapters → LiveOMS → DI → delete).

- [ ] **Step 3 (only if Step 1 maps cleanly): characterization tests** pinning LiveOMS behavior against the new port, then migrate one adapter (paper first), then live, then delete `quant/contracts/ports/broker.py`. Each sub-step commits separately. If Step 1 does NOT map cleanly: stop after ADR, report NEEDS_CONTEXT.

**OMS conformance (same task, independent):** write ONE conformance suite (submit/close/close_partial/add_pyramid incl. S10 half-up, pyramid fractions, zero-size close) run against BOTH `PaperOMS` and `LiveOMS` (live via fake IBrokerPort). Divergences found → normalize via shared helpers (fills/lots pattern), never by weakening the suite. Commit `test: OMS conformance suite + normalizations`.

---

### Task 4: Single reconciliation service + telemetry dispositions

**Reconciler merge (approved, unblocked by quarantine policy):**
- Create `quant/reconciliation_service.py` (or backend domain home — decide by Read: if engine watchdogs need it without backend imports, it lives in `quant/`; else `backend/app/domain/ops/`). Single stale/orphan/size-mismatch policy (QUARANTINE default from Plan C), DB-vs-journal roles documented. `quant/reconciliation.py` (dead raw-compare class per ledger) → delete after callers migrate. Engine watchdogs (`_intraday/_periodic`) + startup path call it. Matrix test: DB-only / broker-only / journal-only / mismatch → one outcome each.

**Telemetry dispositions (locked):**
- Metrics: KEEP SPLIT (different purposes per header; contracts pinned in Plan D) — write ADR 0003 saying so, close.
- Logging: single facade for NEW code (ruff rule on touched files only), grandfather existing 50× `getLogger` (no mass migration — YAGNI).
- `shared/conversion.py`: inventory callers; if zero/near-zero, re-point + delete; else leave with deprecation docstring pointing at `shared.money`.
- `NETWORK_CONFIG`: KEEP mirror (backend-generated config adds a startup fetch dependency to a pure renderer — YAGNI rejected). Close.

- [ ] Steps: inventory → ADR 0003 → reconciler service + matrix test → conversion.py inventory/delete → commit per sub-step.

---

### Task 5: Ratchet hardening + isort cosmetics

- [ ] **Step 1:** Harden LOT regex in `test_no_layer_bypass.py` (`[^}]*` → `[\s\S]*?` per reviewer note) and re-run — expect same failure set (file allowlist unchanged).
- [ ] **Step 2:** `ruff check --select I --fix` limited to files touched by Plans A–E (never repo-wide), re-run affected suites, commit `fix: import-sort on refactor-touched files`.
- [ ] **Step 3:** Full verification: all four parity/contract suites + bypass + affected domain suites green; commit plan doc.

---

## Self-Review

- Spec coverage: pending-group-1 (Task 0) ✅, group-2 (Task 1) ✅, group-3 six items → Tasks 2 (entity), 3 (ports+OMS), 4 (reconciler+telemetry four) ✅, group-4 → Task 5 ✅.
- No placeholders: Tasks 0/1/5 fully verbatim; Tasks 2–4 use investigate→ADR→implement with explicit STOP conditions (proven pattern from Plans B–D).
- Safety invariants: never mix trees, never force-push, never commit red without recorded approval, never delete without sign-off.
