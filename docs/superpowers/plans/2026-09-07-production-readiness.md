# Production Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close every fail-live-readiness finding from the 2026-09-07 deep audit — session-state correctness, evidence-integrity gates, Greek/option chain truth, cost accounting, portfolio risk ceilings, and observability truth — so the paper system is accurate and live option execution can be certified.

**Architecture:** One owner per concept (Clean Architecture / Uncle Bob): the coordinator owns session boundaries, one fill-level cost authority prices every fill, one Greek port feeds option translation, one admission gate admits option entries, one metrics provider reports activity, one portfolio authority caps risk. Every new safety check is **fail-closed** and expressed as a frozen evidence dataclass built once and consumed by gates — never re-derived, never inferred. No new third-party dependencies.

**Tech Stack:** Python 3.11–3.12 (CI matrix; repo `.venv`), pytest, ruff, FastAPI (backend), existing quant/domain packages.

## Global Constraints

- Interpreter: `.venv/bin/python` (Makefile `PYTHON`). If missing: `python3 -m venv .venv && .venv/bin/pip install -e backend -e .` — never use system python for tests.
- Quant tests: `PYTHONPATH=backend:. $(CURDIR)/.venv/bin/python -m pytest tests/quant/... -q --no-header`
- Backend tests: `cd backend && PYTHONPATH=..:. ../.venv/bin/python -m pytest tests/... -q --no-header`
- Lint: `make lint` (ruff + tsc) must pass on every task.
- Golden parity: `make parity` must stay green on every task (determinism is the release gate).
- No new pip dependencies. No new config keys without a loader + validator + test.
- Every new gate FAILS CLOSED: missing data ⇒ reject, never default-to-trade.
- All cross-boundary evidence objects are `@dataclass(frozen=True)`.
- Single source of truth rule: when two modules compute the same fact, delete one. Each task below lists the duplicate it deletes.
- Live options remain **disabled** until the final certification gate is green, the paper acceptance window is complete, and a human owner records an explicit GO decision.
- The plan is intentionally a **strangler refactor**, not a rewrite: preserve deterministic behavior first, extract one responsibility at a time, and delete old paths only after runtime evidence proves they are unused.

## Principal-engineer review: what “production ready” means here

Production readiness is not “the tests pass” and it is not “the broker adapter can place an order.” For this system it means that, for every decision and every order, an operator can answer **what the system knew, what it decided, what it submitted, what actually filled, what it now believes, and whether that belief survived a restart**.

The release target is therefore a set of invariants, not a feature checklist:

1. **One truth per concept.** One owner for contract identity, position state, risk state, fill costs, session boundaries, option admission, reconciliation, metrics, and readiness.
2. **No silent degradation on the money path.** Missing, stale, ambiguous, corrupt, or contradictory evidence rejects new entries or blocks startup. It never becomes a guessed default.
3. **Every side effect is attributable and replayable.** A logical decision/order/fill ID, monotonic sequence, event time, receive time, source, and reason are persisted.
4. **State transitions are explicit.** Orders, positions, risk, sessions, and readiness use finite state machines or typed transitions; booleans and ad-hoc strings do not encode lifecycle.
5. **Readiness is an operational claim.** `/health` describes process health; `/health/ready` describes whether new trading is safe; metrics describe observed runtime activity. These contracts must not be interchangeable.
6. **Refactoring is behavior-preserving until an approved correctness change.** Golden replay, property tests, contract tests, and differential traces are the behavioral oracle.
7. **The system is simpler after each phase.** Every extracted collaborator must have one reason to change, a narrow interface, and direct tests. A new abstraction needs an adoption path and a deletion target for the old path.

### Clean Architecture / Uncle Bob guardrails

- Dependencies point inward: `quant/contracts` and decision/domain code never import FastAPI, SQLite, Dhan, environment variables, or frontend types.
- Ports contain capabilities, not vendor nouns. Adapters translate at the boundary and own retries, authentication, security IDs, payloads, and transport quirks.
- Use immutable value objects for cross-boundary evidence and commands; use mutable state only inside the component that owns its lifecycle.
- Keep orchestration thin. `QuantEngine`, `QuantCoordinator`, and `AMTAnalyzer` may compose collaborators, but they must not also own every calculation, persistence policy, and transport concern.
- Do not create “manager”, “helper”, or “service” modules as dumping grounds. Name a collaborator after the single decision it owns.
- Do not add compatibility aliases, duplicate DTOs, or fallback constructors to make migrations convenient. Migrate callers, run the gates, then delete the shim.
- Catch exceptions only at a boundary that can make a correct decision: retry transient I/O, quarantine uncertain state, halt unsafe execution, or return a typed failure. Never catch-and-continue on order, fill, risk, or persistence ambiguity.
- Prefer explicit data flow over hidden globals. Configuration is loaded once, validated once, and passed as a typed immutable snapshot.

### Current baseline and interpretation

The repository already contains several valuable building blocks: event storage, a paper simulator, broker-neutral `ContractRef`, risk-load statuses, a shared history seed scheduler, quarantine-oriented reconciliation, coordinator-backed activity metrics, and a bounded coordinator pool. The audit finding is that some are **partially adopted or semantically inconsistent**, not that they do not exist.

The current production risks are concentrated in:

- portfolio limits and failure breakers that are not yet a single required startup contract;
- paper/live execution paths that can disagree on fills, costs, and position projection;
- option evidence that can be missing, stale, mislabelled, or on the wrong price basis;
- session rollover and AMT evidence ownership that can retain stale state;
- readiness, metrics, and reconciliation surfaces that can report a healthier system than the runtime actually is;
- god modules and duplicated models that make safety changes shotgun surgery;
- operational controls that are not yet a complete deployable product: secrets, migrations, backups, alerting, rollback, access control, and incident procedures.

The uncommitted working-tree changes must be reviewed as implementation candidates, not treated as shipped behavior. A behavior is production-ready only after it is merged through the gates below and verified from a clean checkout.

## Release trains and dependency graph

The detailed Tasks 1–15 below remain the domain-correctness work package. The following release train is the controlling order because it adds the operational controls that the earlier audit plan did not fully specify:

| Train | Scope | Exit condition | Depends on |
|---|---|---|---|
| R0 | Baseline, ownership map, threat model, golden traces | clean baseline and risk register approved | none |
| R1 | Risk, order lifecycle, simulator, costs, position projection | money-path invariants pass under replay and restart | R0 |
| R2 | Session/AMT/option evidence correctness | no stale or inferred evidence can approve a protected setup | R1 |
| R3 | Reconciliation, readiness, metrics, feed/broker resilience | failure states are visible and entries fail closed | R1 |
| R4 | Security, persistence, migrations, deployment, backups, operator controls | reproducible deploy/rollback and recovery drill pass | R3 |
| R5 | Load, chaos, paper acceptance, certification | full battery green with signed evidence | R2, R3, R4 |
| R6 | Human go-live review and restricted canary | explicit GO; live remains off by default | R5 |

Parallel work is allowed only across disjoint ownership lanes. No two workers edit a money-path contract, event schema, or readiness contract concurrently without a coordinator-owned integration step.

## Workstream ownership map

| Concept | Single owner to establish | Current risk to remove |
|---|---|---|
| Runtime configuration | validated immutable configuration snapshot at composition root | YAML/env/default values are interpreted in multiple layers |
| Contract identity | broker-neutral `ContractRef`; adapter-private broker identity | Dhan/security fields can leak into engine objects |
| Order lifecycle | one normalized order state machine + durable order ledger | PaperOMS, PaperBrokerAdapter, and Dhan adapter can invent different semantics |
| Fill economics | one fill ledger/cost policy | cost helpers exist but can be bypassed or double-counted |
| Position book | one projection from fills/events | engine, portfolio, storage, and broker rows can disagree |
| Risk | one session authority plus one portfolio authority | unsafe aggregate defaults and separate per-engine budgets |
| Session boundary | coordinator/AMT owner with explicit reset event | analyzer and engine can independently infer rollover |
| Option admission | one fail-closed gate | scanner validation exists but is not necessarily on the execution path |
| Reconciliation | one policy and typed outcome | startup, intraday, and journal reconciliation can use different assumptions |
| Runtime activity | coordinator-backed provider | disconnected counters report zero or stale data |
| Readiness | one status model with reasons and entry permission | transport health can be mistaken for trading readiness |

## Non-functional release objectives

These are acceptance targets for R4/R5. Measure them in the deployed environment; do not infer them from local unit tests.

- **Safety:** no new entry when risk state, contract identity, option Greek, market data freshness, order outcome, persistence, or reconciliation is unknown.
- **Determinism:** identical replay input, configuration fingerprint, and dependency versions produce identical decisions, event ordering, fills, and risk deltas.
- **Durability:** after a crash at every order/fill transition, restart either reconstructs the exact state or enters `RECONCILE_REQUIRED` with entries blocked.
- **Liveness:** a dead engine, starved feed, stalled seed, failed journal, failed broker connection, and stale option quote become visible within one configured observation interval.
- **Latency:** record p50/p95/p99 tick-to-decision, decision-to-submit, submit-to-ack, and event-persist latency; define exchange-specific budgets before canary. A budget breach degrades or halts entries rather than silently increasing timeout.
- **Capacity:** sustain the maximum configured active contracts plus a 2× headroom test without unbounded queue growth, missed heartbeats, lock contention, or event-loss.
- **Recovery:** a documented restore from backup and a broker/DB reconciliation drill must complete within the declared RTO; the declared RPO must be no greater than the latest durable fill/order event.
- **Security:** no secrets in logs, journals, metrics, frontend payloads, exception text, or committed files; production endpoints require authenticated operator access and restrictive CORS.

## Definition of done for every implementation task

A task is incomplete unless all items apply:

1. A failing behavior test exists before production code changes (TDD).
2. The test names the invariant and the failure mode, not an implementation detail.
3. The smallest implementation passes the focused test and relevant regression suite.
4. The old duplicate path is removed or an explicit deletion issue and deadline is recorded.
5. The event/DTO/config contract is updated once at its canonical boundary.
6. Failure, restart, duplicate, timeout, partial-fill, and stale-data behavior are tested where relevant.
7. Logs contain a stable event name, correlation/logical ID, symbol/contract, and safe reason; no secret or raw broker payload is logged.
8. `ruff`, type checks, architecture/import checks, golden parity, and the relevant integration test pass.
9. The plan's acceptance evidence is attached to the change; “works locally” is not evidence.

## Additional operational work packages

The domain tasks below are necessary but not sufficient. These work packages must be executed before the final certification battery.

### O1 — Configuration, secret, and environment contract

- Define a typed schema for every runtime setting, including mode, exchange, risk, fill model, timeouts, data freshness, database path, journal path, CORS, and operator controls.
- Load environment variables only in the composition root; pass validated values into `QuantCoordinator`, adapters, and routers.
- Reject unknown keys, invalid ranges, contradictory mode combinations, missing live credentials, paper mode with a live adapter, and live mode with paper-only fallback.
- Add a redaction test that serializes configuration, exceptions, logs, journals, WebSocket snapshots, and metrics and proves credentials/tokens never appear.
- Add a startup fingerprint containing non-secret config hash, code version, schema version, and dependency lock hash; persist it with every session.
- Ensure `.env`, databases, journals, model files, and runtime artifacts are excluded from source control and deployment images.

**Gate:** a clean-room boot with paper settings is reproducible; a deliberately unsafe/live-mixed configuration fails before any engine or broker connection is created.

### O2 — Durable event and storage contract

- Choose the authoritative durable record: order/fill ledger plus append-only domain events; snapshots are rebuild accelerators, never the only truth.
- Add schema version, event ID, aggregate ID, sequence, event time, receive time, causation ID, correlation ID, and checksum to durable money-path events.
- Make writes idempotent with unique logical IDs and monotonic aggregate sequence numbers. Duplicate or out-of-order events must be rejected or safely ignored according to the state machine.
- Replace silent “best effort” persistence on safety-critical events with explicit `PERSISTENCE_UNAVAILABLE` state and entry halt. Best-effort logging is acceptable only for diagnostics.
- Add migration scripts, a schema version table, forward migration tests, backup verification, WAL/checkpoint policy, disk-space alarms, corruption handling, and restore tests.
- Define retention: raw ticks, bars, decisions, order transitions, fills, risk snapshots, and operator actions have separate retention and privacy policies.

**Gate:** crash-injection tests around every commit boundary reconstruct exact position, cash, costs, risk, and in-flight orders; restore succeeds from a backup in a clean environment.

### O3 — Unified order/fill/position lifecycle

- Define typed transitions for `INTENT → SUBMITTED → ACCEPTED/PARTIAL/FILLED/REJECTED/CANCELLED/UNKNOWN → RECONCILE_REQUIRED`.
- Use one logical order ID across decision, submission, broker correlation, fills, journal, and restart. A retry may reuse the logical ID but must never create a second position blindly.
- Distinguish requested quantity, accepted quantity, filled quantity, remaining quantity, and cancelled quantity. Position and P&L derive from filled quantity only.
- Make close operations idempotent and serialized per position; a timeout moves to unknown/reconciliation, not “failed and retry full size.”
- Make paper and live adapters pass the same conformance suite. Intentional behavior differences (fill model, network, broker statuses) are explicit ports, not separate business rules.
- Ensure costs are calculated per actual fill and aggregated exactly once; net P&L, session risk, portfolio risk, journal, and reports consume the same ledger output.

**Gate:** duplicate submit, lost response, partial fill, crash-before-ack, crash-after-fill, retry, restart, and manual broker intervention all produce a safe, explainable result.

### O4 — Market-data, time, and session integrity

- Establish one canonical clock policy: exchange timestamps are data; monotonic time drives timeouts/age; IST conversion is centralized; system clock skew is monitored.
- Validate tick ordering, duplicate timestamps, impossible prices/volumes, crossed books, stale depth, feed gaps, and reconnect sequence continuity.
- Make history seed status part of entry permission. “Degraded history” must be visible and must not silently use synthetic evidence for a high-conviction gate.
- Make session calendar, holidays, exchange close, expiry-day cutoffs, and square-off policy data-driven and tested for NSE/MCX separately.
- Emit a single `SessionRolledOver` transition. Reset all session-scoped state from that event; prior-session persistence happens before reset.
- Label AMT data quality (`TICK_EXACT`, candle-distributed, Gaussian/proxy, unknown) and enforce allowed quality per setup.

**Gate:** replay around midnight/holiday/late close/expiry, reconnect, duplicate ticks, and delayed packets produces no cross-session contamination or stale approval.

### O5 — Broker resilience and reconciliation

- Separate retryable transport failures, rate limits, authentication failures, validation rejects, unknown outcomes, and broker-side manual changes.
- Use bounded exponential backoff with jitter and broker-provided retry hints; never retry a non-idempotent order without a stable logical correlation key and reconciliation check.
- On startup, query broker state in live mode, compare signed quantities and contract identity, and block entries on mismatch or unknown response. Paper mode must report “broker not checked” honestly, not imply broker parity.
- Run periodic detect-only reconciliation during live sessions; configurable policy may halt new entries on confirmed drift, but must not auto-close based on transient reads.
- Add circuit breakers for repeated order failures, stale data, reconciliation drift, and persistence failure. Exits remain available; new entries are halted.
- Test authentication expiry, 429/DH-3001, websocket loss, REST loss, slow responses, duplicate updates, out-of-order updates, and broker maintenance.

**Gate:** fault injection proves the system neither duplicates an order nor abandons an open position, and every degraded state is visible to operators.

### O6 — API, operator, and frontend safety

- Require authentication/authorization for rescan, halt/unhalt, force-close, config, debug, metrics, and journal endpoints; separate read-only viewer from trading operator and administrator roles.
- Make destructive actions explicit, audited, idempotent, and protected by confirmation plus current-state checks. `unhalt` must require a reason and operator identity.
- Restrict CORS and WebSocket origins in production; remove dev tick injection and debug/memory routes from the production surface.
- Version and validate the WebSocket schema at the boundary. Parse-or-reject whole messages; do not merge arbitrary dictionaries across price scales.
- Show mode, readiness, data age, seed status, reconciliation status, risk halt reason, data quality, and last successful persistence in the UI. Never display “ready” when entries are blocked.
- Add an operator runbook for startup, pause, emergency flatten, broker outage, restart, restore, and contract quarantine.

**Gate:** an unauthenticated client cannot mutate trading state, and the UI makes every entry-blocking condition visible without reading logs.

### O7 — Observability, SLOs, and alerting

- Keep one runtime activity provider for `/health`, `/health/ready`, `/metrics`, logs, and dashboards; remove disconnected counters or mark them test-only.
- Emit structured events for startup phase, engine heartbeat, feed age, seed status, decisions, gate failures, order transitions, fills, reconciliation, persistence, and emergency actions.
- Use bounded labels: never use raw contract strings, order IDs, or user input as unbounded Prometheus labels. Put high-cardinality details in logs/traces.
- Define alerts: process down, readiness not ready, crashed/stale engine, feed age, seed failures/rate limit, broker auth, order unknown, repeated rejects, reconciliation drift, journal/storage failure, disk space, memory growth, and EOD position remaining.
- Add correlation IDs across HTTP/WS → decision → order → broker update → fill.
- Test alert emission and recovery, not only metric values.

**Gate:** a simulated failure produces one actionable alert with a runbook link and enough context to decide whether to halt, retry, or recover.

### O8 — Delivery, deployment, and rollback

- Pin Python/frontend dependencies with a reproducible lock and build artifact; compile/typecheck/lint/test in CI from a clean checkout.
- Build a versioned image/package with non-root execution, read-only application code, writable data directories only, timezone explicitly set, and no credentials baked into the artifact.
- Use a single-worker/single-coordinator production topology unless multi-process state ownership is explicitly designed. If scaling horizontally, enforce one trading leader and read-only replicas.
- Add startup probes, liveness probes, readiness probes, graceful shutdown, bounded drain time, and emergency flatten policy. Probe semantics must distinguish “process alive” from “safe to accept entries.”
- Release in stages: offline tests → replay → shadow → paper → restricted canary. Roll back on invariant breach, not just process failure.
- Document database migration ordering and rollback compatibility; never deploy code that cannot read the previous durable schema during a rolling transition.

**Gate:** deploy an old version, migrate to the new version, inject a failure, roll back, restart, and prove no order/fill/risk event is lost or duplicated.

### O9 — Performance, chaos, and longevity

- Benchmark tick ingestion, bar aggregation, AMT analysis, decision gates, snapshot composition, journal writes, and broker polling separately.
- Run soak tests for a full NSE and MCX session with maximum symbols, reconnects, and realistic tick volume. Track memory, queue depth, lock wait, file size, and event lag.
- Inject crashes at each money-path boundary, delayed/duplicate/out-of-order feed, partial fills, disk-full/read-only storage, broker timeout, stale option chain, clock jump, and thread termination.
- Add property tests for lot conservation, P&L/cost conservation, risk monotonicity, state-machine validity, replay determinism, and no negative/phantom positions.
- Put complexity budgets on new code: no new god class, no function with an unbounded parameter list, no duplicate calculation, and no broad exception swallowing on the money path.

**Gate:** the soak and chaos battery passes with zero invariant violations and bounded resource growth.

## Revised final certification matrix

Before R6, record evidence for every row; a green unit suite alone is insufficient.

| Area | Required evidence | Release blocker |
|---|---|---:|
| Configuration | clean-room paper boot, unsafe config rejection, secret-redaction test | yes |
| Contracts | valid/invalid contract matrix; no broker identity leakage | yes |
| Decision correctness | golden replay, gate truth tables, data-quality restrictions | yes |
| Execution | paper/live conformance, duplicate/unknown/partial-fill tests | yes |
| Economics | fill-level costs, net P&L, risk/journal/report parity | yes |
| Position state | lot conservation, partials, pyramids, restart reconstruction | yes |
| Risk | session and portfolio ceilings, failure breaker, emergency halt | yes |
| Sessions | rollover, holidays, expiry, EOD, timezone and clock tests | yes |
| Reconciliation | startup/intraday drift, quarantine, broker-checked status | yes |
| Persistence | migrations, backup/restore, corruption/disk-full behavior | yes |
| Observability | metrics/activity truth, structured logs, alerts, dashboards | yes |
| Security | auth/RBAC, CORS, redaction, dependency/vulnerability scan | yes |
| Operations | deploy/rollback, probes, runbooks, ownership/on-call | yes |
| Performance | maximum-symbol soak, latency budgets, memory/queue bounds | yes |
| Acceptance | gap/pin/chop + outage + restart + operator drills | yes |

## Go / no-go rules

A release is **NO-GO** if any one of these is true:

- live execution can be enabled by a single ambiguous environment value or an unvalidated default;
- an order/fill outcome can be unknown while new entries remain enabled;
- a persisted open position is dropped, silently deleted, or restored without contract/reconciliation proof;
- two components calculate different quantities, costs, P&L, risk, session date, or readiness status;
- a high-conviction option decision uses stale/missing Greeks, stale chain data, inferred footprint evidence, or a mismatched price scale;
- a crash can lose a durable order/fill event or duplicate a position after restart;
- operators cannot see why entries are blocked or who performed a destructive action;
- backups have not been restored successfully, or rollback has not been exercised;
- the paper acceptance window has not completed with real session data and no unresolved invariant breach remains.

A release is **GO** only when the complete evidence matrix is green, the responsible engineer and operator sign the decision, the live kill switch is tested, and the first canary has a predefined stop/rollback rule. Live remains opt-in and off by default even after GO.

---


## Execution protocol (mandatory for every workstream)

This is the implementation method, not optional process overhead. It prevents a large trading refactor from becoming a collection of locally green patches.

### Before coding

1. Create or update the ownership map for the concept being changed: canonical type, owner, port, adapter, persistence representation, read model, and deletion target.
2. Capture the current behavior with a deterministic fixture or golden trace. The trace must include configuration fingerprint, input bars/ticks, decision outputs, gate reasons, order requests, fills, costs, position state, risk state, and event sequence.
3. Write the failure-mode test first. Include at least one restart, duplicate, timeout, stale-data, or partial-fill case when the workstream touches money or lifecycle state.
4. Identify all callers and all alternate implementations before changing an interface. A new class is not complete until the old implementation has either been deleted or is isolated behind an explicitly temporary migration boundary.

### While coding

1. Preserve the dependency direction: domain contracts and pure calculations remain free of framework/vendor imports; adapters own I/O and translation.
2. Keep the change atomic around one invariant. Do not mix behavior changes, formatting, broad renames, and unrelated cleanup in one commit.
3. Make state transitions explicit and idempotent. Every retry must answer whether it is safe to repeat, reconcile, or halt.
4. Use immutable snapshots at boundaries. Do not pass mutable dictionaries between analyzer, decision, execution, persistence, and UI code without a typed normalization step.
5. Do not swallow exceptions on the money path. Convert them to a typed reject, quarantine, circuit-breaker transition, or startup failure with a stable reason.
6. Update only the canonical DTO/schema/config boundary. Regenerate or migrate consumers; do not add a second spelling for compatibility.

### After coding

1. Run the focused failing test and inspect the failure; then run the focused green test.
2. Run the affected quant/backend/frontend contract suites, architecture/import checks, and golden replay.
3. Run a failure-injection test for the changed boundary and verify the operator-facing state/alert.
4. Review the diff for duplication, hidden defaults, broad exception handling, high-cardinality labels, secret leakage, and new public APIs without tests.
5. Record evidence in the release ledger: change, invariant, test command, result, artifact/hash, reviewer, and unresolved risks.
6. Merge only from a clean working tree or with unrelated dirty files explicitly excluded. The current branch contains uncommitted runtime/test changes; they are not release evidence until reviewed and merged.

### Required artifacts

Maintain these versioned artifacts (or their repository-approved equivalents):

- `docs/architecture/ownership-map.md` — canonical owner and dependency map;
- `docs/architecture/runtime-state-machine.md` — order, fill, position, risk, readiness, and session transitions;
- `docs/architecture/threat-model.md` — assets, trust boundaries, threats, controls, residual risk;
- `docs/operations/release-ledger.md` — evidence and sign-offs for each release train;
- `docs/operations/runbooks/` — one runbook per alert and operator action;
- `tests/fixtures/replay/` — small deterministic tapes and expected traces;
- `scripts/` or CI jobs — reproducible validation commands, migrations, backup verification, and restore drills.

### Change-review checklist (Uncle Bob / Clean Code)

For each pull request, the reviewer must be able to answer “yes” to all of these:

- Does each changed class have one reason to change?
- Is each dependency supplied from outside rather than constructed in the policy code?
- Is the interface smaller than the implementation and expressed in domain language?
- Is there exactly one calculation for quantity, cost, P&L, session date, and readiness?
- Can the behavior be tested without a broker, database, clock, thread, or HTTP server?
- Does an uncertain outcome stop new entries rather than guess?
- Does the patch delete or retire the path it replaces?
- Is the resulting code simpler in control flow, state ownership, and vocabulary?

## Release Phases (dependency order)

| Phase | Tasks | Unlocks |
|---|---|---|
| 0 — Risk truth | 1, 2 | Real portfolio ceilings, execution breaker |
| 1 — Session correctness | 3, 4, 5 | Clean per-session profiles/IB/state |
| 2 — Evidence integrity | 6, 7, 8, 9 | Directional CVD, footprint gate, Triple-A truth, VA-fade reclaim |
| 3 — Option chain truth | 10, 11 | Fresh Greeks, single option admission gate |
| 4 — Execution/cost truth | 12, 13 | Cost-accurate paper fills, lot-safe live partials |
| 5 — Observability truth | 14 | One metrics surface, honest reconciliation |
| 6 — Certification | 15 | Replay battery green ⇒ live-options approval path |

---

## File Structure (new files only; everything else modifies existing files)

- `quant/contracts/risk_limits.py` — `PortfolioLimits` frozen dataclass + validation floors (single definition of portfolio ceilings).
- `quant/execution/failure_breaker.py` — `ExecutionFailureBreaker` (one consecutive-failure kill-switch).
- `quant/contracts/ports/greeks.py` — `GreekProvider` Protocol (the one option-Greek source).
- `quant/amt/session/greeks.py` — `ScannerGreekProvider` adapter (scanner → port).
- `quant/execution/option_gate.py` — `validate_option_entry` / `OptionAdmission` (the ONE option admission gate).
- `quant/execution/oms_factory.py` — `make_paper_oms` (the ONE cost-accurate paper OMS constructor).
- `quant/decision/evidence.py` — `FootprintEvidence`, `ReclaimEvidence` frozen evidence objects shared by builder + gates.
- `tests/quant/test_portfolio_limits.py`, `tests/quant/test_failure_breaker.py`, `tests/quant/amt/test_session_boundary.py`, `tests/quant/amt/test_ib_reanchor.py`, `tests/quant/decision/test_evidence_gates.py`, `tests/quant/decision/test_va_fade_reclaim.py`, `tests/quant/execution/test_option_gate.py`, `tests/quant/execution/test_oms_costs.py`, `tests/quant/certification/test_production_readiness.py`, `backend/tests/unit/test_metrics_truth.py`, `backend/tests/unit/domain/test_reconciliation_truth.py`.

---

### Task 1: PortfolioLimits — real portfolio ceilings, no 95% defaults

The audit verified `PortfolioRiskAuthority` defaults to 95% open-risk / 95% daily-loss (`quant/execution/portfolio_risk.py:29-30`), is constructed with no limits (`quant/multi_engine.py:388-390`), and `backend/config/base.yaml:521-528` ships `risk_per_trade_pct: 0.95`, `max_daily_loss_pct: 0.50`, `portfolio_notional_cap: 0.95`. `max_concurrent_positions` (default 5) is loaded but never enforced anywhere in `quant/`.

**Files:**
- Create: `quant/contracts/risk_limits.py`
- Modify: `quant/execution/portfolio_risk.py` (constructor + register/close/release)
- Modify: `quant/multi_engine.py:383-390` (pass limits, raise if absent)
- Modify: `backend/app/config_models/loader.py` (inject `portfolio_limits` into coordinator config)
- Modify: `backend/config/base.yaml:518-532` (replace 0.95-class values)
- Test: `tests/quant/test_portfolio_limits.py`

**Interfaces:**
- Produces: `PortfolioLimits(max_open_risk_pct: float, max_daily_loss_pct: float, max_drawdown_pct: float, max_concurrent_positions: int)` (frozen, validated in `__post_init__`).
- Produces: `PortfolioRiskAuthority(starting_equity: float, limits: PortfolioLimits)`; `register_open(risk_rupees, symbol="", is_pyramid=False, unrealized_book_pnl=0.0) -> bool`; `open_positions -> int`.
- Consumes: existing `root_token()` from `quant.contracts.instrument_registry`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/quant/test_portfolio_limits.py
import pytest
from quant.contracts.risk_limits import PortfolioLimits
from quant.execution.portfolio_risk import PortfolioRiskAuthority


def test_unsafe_limits_are_rejected_at_construction():
    with pytest.raises(ValueError):
        PortfolioLimits(max_open_risk_pct=0.95, max_daily_loss_pct=0.015,
                        max_drawdown_pct=0.015, max_concurrent_positions=5)
    with pytest.raises(ValueError):
        PortfolioLimits(max_open_risk_pct=0.06, max_daily_loss_pct=0.015,
                        max_drawdown_pct=0.015, max_concurrent_positions=0)


def test_concurrent_position_cap_is_enforced():
    limits = PortfolioLimits(max_open_risk_pct=0.06, max_daily_loss_pct=0.015,
                             max_drawdown_pct=0.015, max_concurrent_positions=2)
    auth = PortfolioRiskAuthority(starting_equity=1_000_000.0, limits=limits)
    assert auth.register_open(10_000, "NIFTY 8 SEP 23850 CALL")
    assert auth.register_open(10_000, "BANKNIFTY 8 SEP 51200 PUT")
    assert not auth.register_open(10_000, "CRUDEOIL 8 SEP 5900 CALL")
    assert auth.open_positions == 2


def test_drawdown_breaker_uses_realized_plus_book():
    limits = PortfolioLimits(max_open_risk_pct=0.06, max_daily_loss_pct=0.015,
                             max_drawdown_pct=0.015, max_concurrent_positions=5)
    auth = PortfolioRiskAuthority(starting_equity=1_000_000.0, limits=limits)
    auth.record_close(10_000, pnl=-10_000.0, symbol="NIFTY", is_full_close=True)
    # book unrealized -6k pushes combined drawdown past 1.5% (15k)
    assert not auth.register_open(10_000, "NIFTY", unrealized_book_pnl=-6_000.0)
    assert auth.register_open(10_000, "NIFTY", unrealized_book_pnl=-4_000.0)


def test_release_frees_position_count():
    limits = PortfolioLimits(max_open_risk_pct=0.06, max_daily_loss_pct=0.015,
                             max_drawdown_pct=0.015, max_concurrent_positions=1)
    auth = PortfolioRiskAuthority(starting_equity=1_000_000.0, limits=limits)
    assert auth.register_open(10_000, "NIFTY")
    auth.release(10_000, "NIFTY")  # C3 path: registered but submit failed
    assert auth.register_open(10_000, "BANKNIFTY 8 SEP 51200 PUT")
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/test_portfolio_limits.py -q`
Expected: FAIL — `ModuleNotFoundError: quant.contracts.risk_limits`.

- [ ] **Step 3: Implement `PortfolioLimits`**

```python
# quant/contracts/risk_limits.py
"""Portfolio-level risk ceilings. The ONLY definition — engines and the
backend loader both consume this; unsafe values raise at construction."""
from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class PortfolioLimits:
    max_open_risk_pct: float          # aggregate open risk vs starting equity
    max_daily_loss_pct: float         # realized daily loss kill
    max_drawdown_pct: float           # realized + marked-to-market kill
    max_concurrent_positions: int

    def __post_init__(self) -> None:
        if not (0.0 < self.max_open_risk_pct <= 0.10):
            raise ValueError(f"max_open_risk_pct={self.max_open_risk_pct} unsafe; expected <= 0.10")
        if not (0.0 < self.max_daily_loss_pct <= 0.05):
            raise ValueError(f"max_daily_loss_pct={self.max_daily_loss_pct} unsafe; expected <= 0.05")
        if not (0.0 < self.max_drawdown_pct <= self.max_daily_loss_pct):
            raise ValueError(f"max_drawdown_pct={self.max_drawdown_pct} must be <= max_daily_loss_pct")
        if self.max_concurrent_positions < 1:
            raise ValueError(f"max_concurrent_positions={self.max_concurrent_positions} unsafe")
```

- [ ] **Step 4: Refactor `PortfolioRiskAuthority`**

In `quant/execution/portfolio_risk.py`: make `limits` a **required** keyword (delete the `0.95` defaults), add position counting and the combined drawdown check:

```python
from quant.contracts.risk_limits import PortfolioLimits

class PortfolioRiskAuthority:
    def __init__(self, starting_equity: float, limits: PortfolioLimits) -> None:
        self._starting_equity = starting_equity
        self._max_open_risk = starting_equity * limits.max_open_risk_pct
        self._max_daily_loss = starting_equity * limits.max_daily_loss_pct
        self._max_drawdown = starting_equity * limits.max_drawdown_pct
        self._max_concurrent = limits.max_concurrent_positions
        self._lock = threading.RLock()
        self._open_risk = 0.0
        self._realized_pnl = 0.0
        self._open_count = 0
        self._active_roots: dict[str, str] = {}

    def register_open(self, risk_rupees: float, symbol: str = "",
                      is_pyramid: bool = False, unrealized_book_pnl: float = 0.0) -> bool:
        with self._lock:
            if self._realized_pnl + unrealized_book_pnl <= -self._max_drawdown:
                return False
            if self._realized_pnl <= -self._max_daily_loss:
                return False
            if self._open_risk + max(0.0, risk_rupees) > self._max_open_risk:
                return False
            if not is_pyramid and self._open_count >= self._max_concurrent:
                return False
            if symbol and not is_pyramid:
                root = root_token(symbol)
                if root and root in self._active_roots:
                    return False
                if root:
                    self._active_roots[root] = symbol
            self._open_risk += max(0.0, risk_rupees)
            if not is_pyramid:
                self._open_count += 1
            return True
```

`record_close` and `release` each add `self._open_count = max(0, self._open_count - 1)` for non-pyramid symbols (mirror the existing `is_full_close`/symbol guards exactly).

- [ ] **Step 5: Wire the coordinator — limits required, never defaulted**

`quant/multi_engine.py:383-390` becomes:

```python
from quant.contracts.risk_limits import PortfolioLimits
from quant.execution.portfolio_risk import PortfolioRiskAuthority
raw = self.config.get("portfolio_limits")
if not raw:
    raise RuntimeError(
        "portfolio_limits missing from coordinator config — refusing to start "
        "with unbounded portfolio risk (audit 2026-09-07 #11/#12)"
    )
self._portfolio_risk = PortfolioRiskAuthority(
    starting_equity=float(self.config.get("starting_equity", float(INITIAL_CAPITAL))),
    limits=PortfolioLimits(
        max_open_risk_pct=float(raw["max_open_risk_pct"]),
        max_daily_loss_pct=float(raw["max_daily_loss_pct"]),
        max_drawdown_pct=float(raw["max_drawdown_pct"]),
        max_concurrent_positions=int(raw["max_concurrent_positions"]),
    ),
)
```

`backend/app/config_models/loader.py` (near line 266 where `RiskConfig` is built) injects into the coordinator config dict:

```python
"portfolio_limits": {
    "max_open_risk_pct": min(0.06, 8 * float(risk_data.get("risk_per_trade_pct", 0.005))),
    "max_daily_loss_pct": float(risk_data.get("max_daily_loss_pct", 0.015)),
    "max_drawdown_pct": float(risk_data.get("max_drawdown_pct", 0.015)),
    "max_concurrent_positions": int(risk_data.get("max_concurrent_positions", 5)),
},
```

- [ ] **Step 6: Kill the dangerous base.yaml values**

`backend/config/base.yaml:518-532` becomes:

```yaml
risk:
  risk_per_trade_pct: 0.005
  max_daily_loss_pct: 0.015
  max_drawdown_pct: 0.015
  max_consecutive_losses: 3
  max_trades_per_session: 6
  max_concurrent_positions: 5
  kelly_fraction: 0.25
  kelly_win_prob: 0.55
  kelly_win_loss_ratio: 2.0
  bootstrap_trade_count: 30
```

Delete `portfolio_notional_cap` / `per_symbol_notional_cap` 0.95 keys (replaced by `portfolio_limits`; grep for readers first — `grep -rn "portfolio_notional_cap" backend/app backend/config` — migrate each reader to `portfolio_limits` in this task).

- [ ] **Step 7: Run all affected suites**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/test_portfolio_limits.py tests/quant/execution/ tests/quant/test_risk_config_propagation.py backend/tests/unit/test_paper_sizing_policy.py -q` (backend suite from `backend/` dir per Global Constraints).
Expected: PASS. Update `test_risk_config_propagation.py` fixtures to construct `PortfolioLimits(...)` explicitly (the old default-construction call sites are the only intended breakage).

- [ ] **Step 8: Commit**

```bash
git add quant/contracts/risk_limits.py quant/execution/portfolio_risk.py quant/multi_engine.py backend/app/config_models/loader.py backend/config/base.yaml tests/quant/test_portfolio_limits.py
git commit -m "risk: PortfolioLimits required at startup — kill 95% defaults, enforce concurrent cap + drawdown breaker"
```

---

### Task 2: ExecutionFailureBreaker — halt entries after consecutive OMS failures

Audit finding: submission/close failures are logged and retried with trading still enabled (`quant/runtime.py:1042` catches and moves on). No breaker exists anywhere in `quant/` or `backend/app`.

**Files:**
- Create: `quant/execution/failure_breaker.py`
- Modify: `quant/runtime.py` (engine holds breaker; entry path records ok/fail; pre-entry check)
- Modify: `quant/multi_engine.py` (construct ONE breaker, pass to every engine)
- Test: `tests/quant/test_failure_breaker.py`

**Interfaces:**
- Produces: `ExecutionFailureBreaker(max_consecutive_failures: int = 2, cooldown_sec: float = 300.0)` with `record_submit_ok()`, `record_submit_fail(now: float | None = None)`, `record_close_ok()`, `record_close_fail(now=None)`, `entries_allowed(now: float | None = None) -> tuple[bool, str]`.
- Consumes: engine pre-entry gate location in `quant/runtime.py` `_decide()` (same place `session_risk.can_trade()` is checked); OMS submit try/except at `runtime.py:~1042`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/quant/test_failure_breaker.py
from quant.execution.failure_breaker import ExecutionFailureBreaker


def test_two_consecutive_submit_failures_halt_entries():
    br = ExecutionFailureBreaker(max_consecutive_failures=2)
    br.record_submit_fail(); ok, why = br.entries_allowed(); assert ok
    br.record_submit_fail(); ok, why = br.entries_allowed()
    assert not ok and "EXECUTION_FAILURES" in why


def test_success_resets_streak_and_close_failures_count_separately():
    br = ExecutionFailureBreaker(max_consecutive_failures=2)
    br.record_submit_fail(); br.record_close_fail()
    assert br.entries_allowed()[0]          # 1 submit + 1 close = not consecutive
    br.record_close_fail()
    assert not br.entries_allowed()[0]
    br.record_submit_ok()                    # an OK submit clears the streak
    assert br.entries_allowed()[0]


def test_cooldown_reopens_entries_after_quiet_period():
    br = ExecutionFailureBreaker(max_consecutive_failures=2, cooldown_sec=300.0)
    br.record_submit_fail(now=1_000.0); br.record_submit_fail(now=1_000.5)
    assert not br.entries_allowed(now=1_100.0)[0]
    assert br.entries_allowed(now=1_400.0)[0]
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/test_failure_breaker.py -q`
Expected: FAIL — module not found.

- [ ] **Step 3: Implement**

```python
# quant/execution/failure_breaker.py
"""Portfolio-wide execution-health breaker (audit 2026-09-07 #13).

Two consecutive broker/OMS failures on ANY engine halt NEW entries
portfolio-wide until a success resets the streak or the cooldown elapses.
Manage exits of already-open positions normally — never trap capital.
"""
from __future__ import annotations

import threading
import time


class ExecutionFailureBreaker:
    def __init__(self, max_consecutive_failures: int = 2,
                 cooldown_sec: float = 300.0) -> None:
        self._max = max(1, int(max_consecutive_failures))
        self._cooldown = float(cooldown_sec)
        self._lock = threading.Lock()
        self._submit_streak = 0
        self._close_streak = 0
        self._halted_at: float | None = None

    def record_submit_ok(self) -> None:
        with self._lock:
            self._submit_streak = 0
            self._close_streak = 0
            self._halted_at = None

    def record_close_ok(self) -> None:
        with self._lock:
            self._close_streak = 0

    def record_submit_fail(self, now: float | None = None) -> None:
        with self._lock:
            self._submit_streak += 1
            if self._submit_streak >= self._max and self._halted_at is None:
                self._halted_at = time.time() if now is None else float(now)

    def record_close_fail(self, now: float | None = None) -> None:
        with self._lock:
            self._close_streak += 1
            if self._close_streak >= self._max and self._halted_at is None:
                self._halted_at = time.time() if now is None else float(now)

    def entries_allowed(self, now: float | None = None) -> tuple[bool, str]:
        with self._lock:
            if self._halted_at is None:
                return True, ""
            t = time.time() if now is None else float(now)
            if t - self._halted_at >= self._cooldown:
                self._submit_streak = self._close_streak = 0
                self._halted_at = None
                return True, ""
            return False, f"EXECUTION_FAILURES: halt after {self._max} consecutive OMS failures"
```

- [ ] **Step 4: Wire into coordinator + engine entry path**

`quant/multi_engine.py` (beside `self._portfolio_risk = ...`):

```python
from quant.execution.failure_breaker import ExecutionFailureBreaker
self._failure_breaker = ExecutionFailureBreaker(
    max_consecutive_failures=int(self.config.get("max_consecutive_exec_failures", 2)),
)
```

Pass it into each `QuantEngine(...)` call in `_spawn_engine` (same style as `portfolio_risk=self._portfolio_risk`): `failure_breaker=self._failure_breaker`.

`quant/runtime.py`:
1. `QuantEngine.__init__(..., failure_breaker=None)` → `self._failure_breaker = failure_breaker`.
2. In `_decide()`, immediately after the session-risk gate, add:

```python
if self._failure_breaker is not None:
    ok, why = self._failure_breaker.entries_allowed()
    if not ok:
        self._emit(DecisionProduced(symbol=self.symbol, time=bar.time, decision=QuantDecision(
            approved=False, signal=None, reason="EXECUTION_HALTED", phase="",
            gate_results=(), block_reasons=(why,), model_label="")))
        return
```

3. In the entry try/except that logs `"[ENTRY FAILED] ... OMS submit raised"` (`runtime.py:~1042`): call `self._failure_breaker.record_submit_fail()` in the except, `self._failure_breaker.record_submit_ok()` after a successful `self._oms.submit(...)`. Mirror `record_close_fail()`/`record_close_ok()` around the OMS close calls in the same file's close/flatten paths (full-close shared path at `runtime.py:~1222`).

- [ ] **Step 5: Run suites**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/test_failure_breaker.py tests/quant/test_emergency_halt.py tests/system/ -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add quant/execution/failure_breaker.py quant/runtime.py quant/multi_engine.py tests/quant/test_failure_breaker.py
git commit -m "risk: portfolio-wide ExecutionFailureBreaker — 2 consecutive OMS failures halt new entries"
```

---

### Task 3: One owner for the session boundary — clear profile state on rollover

Audit finding: `AMTEngine.analyze()` saves prior levels on rollover but never clears `_amt_candles`/`_amt_incremental` (`quant/amt_engine.py:403-444`), so the new session's POC/VA/LVNs include yesterday's volume (analyzer builds the profile from the engine-owned incremental profile, `quant/amt/analyzer.py:450-452`). Meanwhile the analyzer *also* detects rollover independently inside `_update_session_vwap` (`analyzer.py:352-376`) — duplicated ownership, the exact code smell to delete.

**Decision (single owner):** AMTEngine owns rollover detection (it already has `_session_date`). AMTAnalyzer exposes `reset_session()`; its internal detection is deleted. The tick footprint accumulator resets too (it is keyed by candle time and would otherwise serve stale diagonals).

**Files:**
- Modify: `quant/amt/profile/volume_profile.py:321+` (add `IncrementalVolumeProfile.reset()`)
- Modify: `quant/amt/analyzer.py:352-376` (public `reset_session()`; delete internal rollover detection)
- Modify: `quant/amt/orderflow/footprint.py:126+` (add `TickFootprintAccumulator.reset()`)
- Modify: `quant/amt_engine.py:403-444` (clear ring/profile/footprint + call `reset_session()`)
- Test: `tests/quant/amt/test_session_boundary.py`

**Interfaces:**
- Produces: `IncrementalVolumeProfile.reset() -> None`; `AMTAnalyzer.reset_session() -> None`; `TickFootprintAccumulator.reset() -> None`.
- Consumes: `session_date_key()` already used by `amt_engine.py`.

- [ ] **Step 1: Write the failing test**

```python
# tests/quant/amt/test_session_boundary.py
"""Rollover must produce a clean session: no prior candles, no prior profile
volume, reset trackers. Pins audit 2026-09-07 #1."""
from quant.amt.profile.volume_profile import IncrementalVolumeProfile
from quant.amt.orderflow.footprint import TickFootprintAccumulator
from quant.contracts.value_objects import OHLC


def _bar(time_s: str, close: float, volume: float = 100.0) -> OHLC:
    return OHLC(time=time_s, open=close, high=close + 2, low=close - 2,
                close=close, volume=volume, vwap=close,
                taker_buy_volume=volume * 0.6, delta=volume * 0.2)


def test_incremental_profile_reset_clears_volume():
    inc = IncrementalVolumeProfile()
    inc.update(_bar("2026-09-04T09:15:00+05:30", 24_000.0))
    assert inc.get_profile()
    inc.reset()
    assert not inc.get_profile() and not inc._candles and not inc._initialized


def test_engine_rollover_clears_ring_and_profile(monkey_patch_free_engine):
    eng = monkey_patch_free_engine  # fixture: AMTEngine with analyzer/history stubbed (see Step 4)
    for i in range(6):
        eng.analyze(_bar(f"2026-09-04T09:{15 + i}:00+05:30", 24_000.0 + i))
    assert len(eng._amt_candles) == 6
    day2 = _bar("2026-09-07T09:15:00+05:30", 24_100.0)
    dto = eng.analyze(day2)
    assert len(eng._amt_candles) == 1, "rollover must drop prior-session candles"
    assert eng._session_date == "2026-09-07"
    # profile rebuilt from the single new bar only
    assert all(p.volume == 0 or p.price == pytest.approx(24_100.0, abs=5.0)
               for p in _profile(eng))  # helper returns eng._amt_incremental.get_profile()


def test_analyzer_reset_session_clears_trackers():
    from quant.amt.analyzer import AMTAnalyzer
    a = AMTAnalyzer()
    a._vwap.update(_bar("2026-09-04T09:15:00+05:30", 100.0), 100.0)
    a._cvd_tracker.update(_bar("2026-09-04T09:15:00+05:30", 100.0))
    a.reset_session()
    assert a._vwap._last_time in ("", None)
    assert a._cvd_tracker.state().slope == 0.0
```

Add the missing fixture/helpers in the same file (a minimal `AMTEngine` with `history_source=None`, `seed_scheduler=None`, `market="NSE"`, depth/risk lambdas returning 0 — follow the construction pattern in `tests/quant/test_audit_regressions.py:740-760`).

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt/test_session_boundary.py -q`
Expected: FAIL — `AttributeError: ... reset` / rollover keeps 7 candles.

- [ ] **Step 3: Implement the three resets + engine wiring**

```python
# quant/amt/profile/volume_profile.py — inside IncrementalVolumeProfile
def reset(self) -> None:
    """Clear all accumulated volume state (new trading session)."""
    self._buckets = self._requested_buckets
    self._volumes = []
    self._min_price = self._max_price = self._step = 0.0
    self._initialized = False
    self._candles = []
```

```python
# quant/amt/orderflow/footprint.py — inside TickFootprintAccumulator
def reset(self) -> None:
    """Clear completed/in-progress footprint state (new trading session)."""
    self._current_candle_time = ""
    self._levels = {}
    self._completed = {}
    self._prev_ltp = 0.0
```

```python
# quant/amt/analyzer.py — replace _update_session_vwap (lines 352-376)
def reset_session(self) -> None:
    """Reset ALL session-scoped analytical state.

    Called by AMTEngine exactly once per session rollover — the engine is
    the single owner of the session boundary; the analyzer never detects
    rollover itself (deleted duplicate detection).
    """
    self._ib_tracker.reset()
    self._ib_break_direction = ""
    self._ar_engine.reset()
    self._persistent_agg_scorer.reset()
    self._lvn_tracker.reset()
    self._value_migration.reset()
    self._drive_tracker.reset()
    self._cvd_tracker.reset()
    self._triple_a.reset()
    self._vars_detector.reset()
    self._vwap.reset()
```

Delete `_update_session_vwap` and replace its call site with the direct `self._vwap.update(current, typical_price)` (grep `grep -n "_update_session_vwap" quant/` to catch all callers).

`quant/amt_engine.py` — inside `analyze()`, extend the existing rollover block (after `self._prior = self._session_levels.load_levels(...)`):

```python
# New session: the ring, profile and footprint belong to the NEW session
# only. Persisted levels above already captured the old session.
with self._amt_lock:
    self._amt_candles = []
    self._amt_incremental = IncrementalVolumeProfile()
    self._warm_bars = 0
self._footprint.reset()
self._amt_analyzer.reset_session()
self._last_amt_dto = {}   # stale DTO must not drive new-session decisions
```

(Place before `self._session_date = iso_date` so the appended bar starts the fresh ring; the existing `if not self._amt_candles` seed guard is untouched.)

- [ ] **Step 4: Run all AMT suites (expect pinned tests to confirm the fix)**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt/ tests/quant/test_audit_regressions.py backend/tests/unit/domain/test_amt_analyzer.py backend/tests/validation/ -q`
Expected: PASS. `tests/quant/amt/test_cold_start_prior_levels.py:52` asserts today-only candles after seed — it must still pass unchanged; if any test asserted cross-session accumulation, update it to the new spec (session-scoped profile) and note it in the commit body.

- [ ] **Step 5: Commit**

```bash
git add quant/amt/profile/volume_profile.py quant/amt/orderflow/footprint.py quant/amt/analyzer.py quant/amt_engine.py tests/quant/amt/test_session_boundary.py
git commit -m "amt: single session-boundary owner — engine clears ring/profile/footprint, analyzer.reset_session(); delete duplicate rollover detection"
```

---

### Task 4: IB re-anchors to the actual session open

Audit finding: `InitialBalanceEngine.update()` accepts `session_open` only once (`quant/amt/session/ib_engine.py:138-141`); after a rollover the anchor is yesterday's open, so elapsed ≥ 24h flips `_complete` on the first new-session bar and IB becomes a 1-bar high/low for the whole day. Task 3 removes the stale `data[0]`, but the engine must still defend itself: re-anchor when the candle's session date changes.

**Files:**
- Modify: `quant/amt/session/ib_engine.py:103-141` (reset + re-anchor)
- Test: `tests/quant/amt/test_ib_reanchor.py`

**Interfaces:**
- Produces: unchanged public API (`update(candle, session_open=None) -> IBState`); new private `_anchored_date: str`.

- [ ] **Step 1: Write the failing test**

```python
# tests/quant/amt/test_ib_reanchor.py
from quant.amt.session.ib_engine import InitialBalanceEngine
from quant.contracts.value_objects import OHLC


def _bar(time_s: str, high: float, low: float) -> OHLC:
    return OHLC(time=time_s, open=(high + low) / 2, high=high, low=low,
                close=(high + low) / 2, volume=100.0, vwap=(high + low) / 2,
                taker_buy_volume=60.0, delta=20.0)


def test_ib_reanchors_on_new_session_date():
    ib = InitialBalanceEngine(ib_minutes=30)
    ib.update(_bar("2026-09-04T09:15:00+05:30", 100.0, 90.0))
    ib.update(_bar("2026-09-04T09:45:00+05:30", 105.0, 89.0))
    assert ib.is_complete
    # Monday: anchor must reset — IB rebuilds from THIS session's bars
    st = ib.update(_bar("2026-09-07T09:15:00+05:30", 120.0, 110.0))
    assert not st.is_complete, "IB must rebuild on a new session date"
    assert st.ib_high == 120.0 and st.ib_low == 110.0
    st = ib.update(_bar("2026-09-07T09:45:00+05:30", 122.0, 109.0))
    assert st.is_complete and st.ib_high == 122.0 and st.ib_low == 109.0
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt/test_ib_reanchor.py -q`
Expected: FAIL — second session reports `is_complete=True` on the first bar.

- [ ] **Step 3: Implement**

```python
# ib_engine.py — __init__ and reset() gain: self._anchored_date: str = ""
def update(self, candle: OHLC, session_open: str | None = None) -> IBState:
    from quant.state import session_date_key
    candle_date = session_date_key(candle.time)
    if self._anchored_date and candle_date and candle_date != self._anchored_date:
        self.reset()  # session changed since the last bar — rebuild IB
    if session_open is not None and not self._session_open_time:
        self._session_open_time = session_open
    if not self._session_open_time:
        self._session_open_time = candle.time
    self._anchored_date = candle_date
    # ... unchanged body below
```

- [ ] **Step 4: Run suites**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt/ backend/tests/unit/domain/test_ib_and_short.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add quant/amt/session/ib_engine.py tests/quant/amt/test_ib_reanchor.py
git commit -m "amt: IB re-anchors per session date — first new-session bar can never complete IB"
```

---

### Task 5: Market state requires directional acceptance for trend

Audit finding: `detect_market_state()` returns IMBALANCED on `has_displacement OR outside_VA OR low balance_ratio` with no acceptance (`quant/amt/market/state_engine.py:72`); its own docstring (line 5) promises "displacement + acceptance". Correction per audit: IMBALANCED (trend) requires **outside VA AND displacement AND acceptance**.

**Files:**
- Modify: `quant/amt/market/state_engine.py:62-99`
- Test: extend `backend/tests/unit/domain/test_amt_analyzer.py` (add class `TestMarketStateAcceptance`)

**Interfaces:** unchanged `MarketStateResult`; only the classification predicate changes.

- [ ] **Step 1: Write the failing test**

```python
# backend/tests/unit/domain/test_amt_analyzer.py (append)
from quant.amt.market.state_engine import detect_market_state
from quant.contracts.enums import MarketState


class TestMarketStateAcceptance:
    def _detect(self, **kw):
        base = dict(price=100.0, poc=95.0, vah=99.0, val=91.0, tick_size=0.05,
                    has_displacement=True, has_acceptance=True, balance_ratio=0.9)
        base.update(kw)
        return detect_market_state(**base)

    def test_outside_va_displacement_acceptance_is_imbalanced(self):
        assert self._detect().state is MarketState.IMBALANCED

    def test_outside_va_without_acceptance_is_not_trend(self):
        assert self._detect(has_acceptance=False).state is MarketState.BALANCED

    def test_displacement_inside_va_is_not_trend(self):
        # price inside VA: not a trend auction regardless of displacement
        assert self._detect(price=95.0, has_acceptance=True).state is MarketState.BALANCED

    def test_trigger_string_records_missing_acceptance(self):
        r = self._detect(has_acceptance=False)
        assert "acceptance" in r.trigger
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && PYTHONPATH=..:. ../.venv/bin/python -m pytest tests/unit/domain/test_amt_analyzer.py::TestMarketStateAcceptance -q`
Expected: FAIL — current code returns IMBALANCED without acceptance.

- [ ] **Step 3: Implement**

```python
# state_engine.py — replace the predicate at line 72
outside_va = not inside_session_va
trending = outside_va and has_displacement and has_acceptance
if trending:
    trigger_parts = [f"outside session VA [{val:.2f}, {vah:.2f}]",
                     "active displacement leg", "directional acceptance"]
    ...  # unchanged MarketStateResult(IMBALANCED, ...) construction, conf as today
# fallthrough BALANCED: keep the existing zone/confidence block, but when
# outside_va and not trending append to trigger:
#   f"outside VA without {'displacement' if not has_displacement else 'acceptance'} — no trend"
```

Do **not** touch the B-shape override in `analyzer.py:645-647` or the DEAD override in `session/structure.py:120-141` — those remain independent guards.

- [ ] **Step 4: Run suites and reconcile pinned expectations**

Run: `cd backend && PYTHONPATH=..:. ../.venv/bin/python -m pytest tests/unit/domain/ -q` and `PYTHONPATH=backend:. ../.venv/bin/python -m pytest tests/quant/amt/ -q`
Expected: PASS. Any test that pinned "outside VA ⇒ IMBALANCED without acceptance" is updated to the audited spec — list each in the commit body.

- [ ] **Step 5: Commit**

```bash
git add quant/amt/market/state_engine.py backend/tests/unit/domain/test_amt_analyzer.py
git commit -m "amt: IMBALANCED (trend) requires outside-VA AND displacement AND acceptance — match documented Fabio spec"
```

---

### Task 6: Directional, volume-normalized CVD confirmation

Audit findings: `compute_order_flow_metrics()` sets `cvd_confirmed=True` for either slope sign in IMBALANCED (`quant/amt/orderflow/compute.py:88-91`), and the CVD kill threshold `2.0` is a raw cumulative-delta slope whose meaning varies with volume scale (`quant/runtime.py:292`). One fix, one place: emit a **directional** confirmation and a **volume-normalized** slope; gates and the exit kill consume the normalized values.

**Files:**
- Modify: `quant/amt/orderflow/compute.py:84-93` (directional + normalized)
- Modify: `quant/amt/dto.py` (`amt_result_to_dto` emits `cvdConfirmation`, `cvdSlopeNorm`)
- Modify: `quant/decision/context_builder.py` (context fields `cvd_confirmation`, `cvd_slope_norm`)
- Modify: `quant/decision/context.py` (two new frozen fields with safe defaults)
- Modify: `quant/decision/gates_edge.py:44-51` (guards use normalized slope)
- Modify: `quant/execution/exit_checks.py:35-44` (kill uses normalized)
- Modify: `quant/contracts/constants.py` (add `CVD_STRONG_SLOPE_NORM`, `CVD_KILL_NORM`)
- Test: `tests/quant/decision/test_evidence_gates.py` (class `TestCvdDirection`)

**Interfaces:**
- Produces: `result["cvd_confirmation"]: str` ∈ {"LONG","SHORT",""}; `result["cvd_slope_norm"]: float`; DTO keys `cvdConfirmation`/`cvdSlopeNorm`; `DecisionContext.cvd_confirmation: str = ""`, `DecisionContext.cvd_slope_norm: float = 0.0`.
- Constants: `CVD_STRONG_SLOPE_NORM = 0.30` (normalized slope = slope / (avg_vol × tick)); `CVD_KILL_NORM = 0.50`.

- [ ] **Step 1: Write the failing tests**

```python
# tests/quant/decision/test_evidence_gates.py (file created in this task)
from types import SimpleNamespace
from quant.amt.orderflow.compute import compute_order_flow_metrics


def _flow(slope: float, market_state="IMBALANCED", avg_vol: float = 1000.0):
    cvd = SimpleNamespace(slope=slope, has_divergence=False, divergence_type="")
    return compute_order_flow_metrics(
        recent_data=[], order_book=None,
        current=SimpleNamespace(delta=0, volume=0),
        agg_prints=[], market_state=market_state, lvns=[], vah=1, val=0,
        poc=0.5, tick_size=0.05, cvd_state=cvd, avg_candle_vol=avg_vol)


class TestCvdDirection:
    def test_positive_strong_slope_confirms_long_only(self):
        f = _flow(slope=300.0)
        assert f["cvd_confirmation"] == "LONG" and f["cvd_confirmed"] is True

    def test_negative_strong_slope_confirms_short_only(self):
        f = _flow(slope=-300.0)
        assert f["cvd_confirmation"] == "SHORT"

    def test_weak_slope_confirms_nothing(self):
        f = _flow(slope=50.0)
        assert f["cvd_confirmation"] == "" and f["cvd_confirmed"] is False

    def test_norm_is_volume_scaled(self):
        assert _flow(300.0, avg_vol=1000.0)["cvd_slope_norm"] > \
               _flow(300.0, avg_vol=10_000.0)["cvd_slope_norm"]
```

And in `tests/quant/execution/test_exits.py` (append):

```python
def test_cvd_kill_uses_normalized_slope_when_present():
    from quant.execution.exit_checks import check_cvd_kill
    pos = SimpleNamespace(size=10)  # long
    dto = {"cvdSlopeNorm": -0.9, "cvdSlope": -3_000_000.0}
    assert check_cvd_kill(pos, dto, cvd_kill_threshold=0.5) is not None
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_evidence_gates.py -q`
Expected: FAIL — `cvd_confirmation` key missing / both slopes confirmed.

- [ ] **Step 3: Implement**

```python
# compute.py — replace lines 84-93
from quant.contracts.constants import CVD_STRONG_SLOPE_NORM

result["cvd_confirmation"] = ""
result["cvd_confirmed"] = False
if cvd_state is not None:
    denom = max(result["avg_candle_vol"] * tick_size, 1e-9)
    result["cvd_slope_norm"] = cvd_state.slope / denom
    if cvd_state.slope >= CVD_STRONG_SLOPE_NORM * denom:
        result["cvd_confirmation"] = "LONG"
    elif cvd_state.slope <= -CVD_STRONG_SLOPE_NORM * denom:
        result["cvd_confirmation"] = "SHORT"
    elif cvd_state.has_divergence:
        div = (cvd_state.divergence_type or "").upper()
        if "BULL" in div:
            result["cvd_confirmation"] = "LONG"
        elif "BEAR" in div:
            result["cvd_confirmation"] = "SHORT"
    result["cvd_confirmed"] = bool(result["cvd_confirmation"])
else:
    result["cvd_slope_norm"] = 0.0
```

DTO: in `amt_result_to_dto` add `"cvdConfirmation": flow cvd_confirmation, "cvdSlopeNorm": ...` (thread the two values through `AMTResult` exactly as `aggression_score` already is — follow `analyzer.py:814` pattern). Context builder: `cvd_confirmation=str(amt_dto.get("cvdConfirmation") or "")`, `cvd_slope_norm=float(amt_dto.get("cvdSlopeNorm") or 0.0)`.

Gate guard (`gates_edge.py:44-51`) — keep the raw-slope conflict blocks, add normalized opposition:

```python
norm = getattr(ctx, "cvd_slope_norm", 0.0)
if ctx.agent_direction == "LONG" and norm < -CVD_KILL_NORM:
    return GateResult(3, False, f"CVD norm {norm:.2f} aggressively opposes LONG")
if ctx.agent_direction == "SHORT" and norm > CVD_KILL_NORM:
    return GateResult(3, False, f"CVD norm {norm:.2f} aggressively opposes SHORT")
```

Exit kill (`exit_checks.py:35-44`): `threshold = dto.get("cvdSlopeNorm"); if threshold is not None: use it with CVD_KILL_NORM semantics; else fall back to legacy raw slope + raw threshold` (back-compat for replayed journals).

`runtime.py:292` becomes `ExitEngine(time_stop_bars=time_stop_bars, cvd_kill_threshold=CVD_KILL_NORM)` (raw value now only used when the DTO has no norm — replay safety).

- [ ] **Step 4: Run suites**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/ tests/quant/execution/test_exits.py tests/quant/runtime/ tests/quant/test_golden_replay.py -q`
Expected: PASS (golden replay: DTO gains keys — if the golden file pins exact DTO key sets, regenerate via the documented golden-update command and note it).

- [ ] **Step 5: Commit**

```bash
git add quant/amt/orderflow/compute.py quant/amt/dto.py quant/decision/context_builder.py quant/decision/context.py quant/decision/gates_edge.py quant/execution/exit_checks.py quant/contracts/constants.py tests/quant/decision/test_evidence_gates.py
git commit -m "orderflow: directional volume-normalized CVD confirmation; kill switch on normalized slope"
```

---

### Task 7: Footprint evidence — real diagonal imbalance required at Gate 3

Audit findings: `footprint_confirmed` is only `len(agg_prints)>=2 and |delta/vol|>0.30` (`compute.py:80-82`) and Gate 3 never consumes the tick accumulator's diagonal work (`quant/amt/orderflow/footprint.py` already computes 3:1 diagonals + stacked counts). Fix: aggregate the accumulator's most recent completed candle into a frozen `FootprintEvidence`, emit via DTO, and require direction-matched confirmation on the aggressive Gate-3 paths.

**Files:**
- Create: `quant/decision/evidence.py` (frozen evidence objects; also used by Task 9)
- Modify: `quant/amt/orderflow/footprint.py` (`evidence()` method)
- Modify: `quant/amt/analyzer.py` (emit `footprintDiagonalBuy/Sell`, `footprintConfirmed` from `footprint_accumulator.evidence()`)
- Modify: `quant/amt/dto.py` (pass-through keys)
- Modify: `quant/decision/context.py` (`footprint_evidence: Any | None = None`)
- Modify: `quant/decision/context_builder.py` (build `FootprintEvidence`)
- Modify: `quant/decision/gates_edge.py:57-69` (require evidence on evidence/Triple-A paths)
- Test: `tests/quant/decision/test_evidence_gates.py` (classes `TestFootprintEvidence`, `TestGate3Footprint`)

**Interfaces:**
- Produces: `FootprintEvidence(diagonal_buy: int, diagonal_sell: int, volume: float, confirmed: bool, direction: str)` with `direction` ∈ {"BUY","SELL",""} (majority diagonal side; "" if <2 diagonals).
- Gate rule: evidence path & Triple-A path require `ctx.footprint_evidence.confirmed` AND `direction` matching `agent_direction` (LONG⇒BUY).

- [ ] **Step 1: Write the failing tests**

```python
# tests/quant/decision/test_evidence_gates.py (append)
from quant.decision.evidence import FootprintEvidence


class TestFootprintEvidence:
    def test_two_buy_diagonals_confirm_buy(self):
        e = FootprintEvidence(diagonal_buy=3, diagonal_sell=0, volume=5_000.0,
                              confirmed=True, direction="BUY")
        assert e.confirmed and e.direction == "BUY"

    def test_fewer_than_two_diagonals_never_confirms(self):
        e = FootprintEvidence(diagonal_buy=1, diagonal_sell=0, volume=5_000.0,
                              confirmed=False, direction="")
        assert not e.confirmed


class TestGate3Footprint:
    def _ctx(self, evidence):
        # minimal DecisionContext for gate_triple_a_edge; follow the pattern in
        # tests/quant/decision/test_context_builder_behavior.py for required fields
        ...
    def test_triple_a_path_blocked_without_footprint(self):
        ctx = self._ctx(evidence=None)
        r = gate_triple_a_edge(ctx)
        assert not r.passed and "footprint" in r.reason.lower()

    def test_triple_a_path_blocked_when_diagonals_oppose(self):
        ctx = self._ctx(evidence=FootprintEvidence(0, 3, 4_000.0, True, "SELL"))
        ctx = replace(ctx, agent_direction="LONG")
        r = gate_triple_a_edge(ctx)
        assert not r.passed
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_evidence_gates.py -q`
Expected: FAIL — `quant.decision.evidence` missing; gate passes without footprint.

- [ ] **Step 3: Implement**

```python
# quant/decision/evidence.py
"""Frozen evidence objects handed from analyzer -> context -> gates.
Built ONCE per bar; gates consume, never re-derive (single source of truth)."""
from __future__ import annotations
from dataclasses import dataclass


@dataclass(frozen=True)
class FootprintEvidence:
    diagonal_buy: int = 0
    diagonal_sell: int = 0
    volume: float = 0.0
    confirmed: bool = False
    direction: str = ""   # "BUY" | "SELL" | ""


@dataclass(frozen=True)
class ReclaimEvidence:   # consumed by Task 9
    probed_outside: bool = False
    failed_acceptance: bool = False
    back_inside: bool = False
    lvn_retested: bool = False
    flow_confirms: bool = False

    @property
    def complete(self) -> bool:
        return all((self.probed_outside, self.failed_acceptance,
                    self.back_inside, self.lvn_retested, self.flow_confirms))
```

`footprint.py` — inside `TickFootprintAccumulator`:

```python
def evidence(self) -> dict:
    """Diagonal-imbalance evidence from the most recent COMPLETED candle."""
    if not self._completed:
        return {"diagonal_buy": 0, "diagonal_sell": 0, "volume": 0.0,
                "confirmed": False, "direction": ""}
    candle = self._completed[max(self._completed.keys())]
    buy = sum(1 for lv in candle.levels if lv.ask >= 3 * lv.bid and lv.ask > 0)
    sell = sum(1 for lv in candle.levels if lv.bid >= 3 * lv.ask and lv.bid > 0)
    vol = float(sum(lv.bid + lv.ask for lv in candle.levels))
    direction = "BUY" if buy >= 2 and buy > sell else "SELL" if sell >= 2 and sell > buy else ""
    return {"diagonal_buy": buy, "diagonal_sell": sell, "volume": vol,
            "confirmed": direction != "", "direction": direction}
```

Analyzer: where the DTO is assembled (same block that emits `stackedImbalance*`), add:

```python
fp = footprint_accumulator.evidence() if footprint_accumulator is not None else {}
```
and thread `fp` into the result/DTO keys `footprintDiagonalBuy`, `footprintDiagonalSell`, `footprintConfirmed`, `footprintDirection`.

Context builder: construct `FootprintEvidence(**{...})` from those DTO keys (missing keys ⇒ all-zero evidence, still frozen) and set `footprint_evidence=`. Context field: `footprint_evidence: Any | None = None`.

Gate 3 (`gates_edge.py`), at the top of `_check_setup_paths`:

```python
fp = getattr(ctx, "footprint_evidence", None)
need = ("LONG", "BUY") if ctx.agent_direction == "LONG" else ("SHORT", "SELL")
fp_ok = fp is not None and fp.confirmed and fp.direction == need[1]
```
Then: the `ev.is_complete()` path and the `phase == "AGGRESSION"` path require `fp_ok` (return `GateResult(3, False, "No directional footprint confirmation (need stacked 3:1 diagonals)")` when absent). The LVN/Initiative/Squeeze/Second-Drive paths are location-triggered, not aggressive pulses — leave them unchanged (audit scopes the requirement to aggressive entries).

- [ ] **Step 4: Run suites**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/ tests/quant/amt/orderflow/ backend/tests/unit/domain/test_footprint_analyzer.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add quant/decision/evidence.py quant/amt/orderflow/footprint.py quant/amt/analyzer.py quant/amt/dto.py quant/decision/context.py quant/decision/context_builder.py quant/decision/gates_edge.py tests/quant/decision/test_evidence_gates.py
git commit -m "gates: Gate-3 aggressive entries require direction-matched tick-footprint diagonal evidence"
```

---

### Task 8: Triple-A machine records per-phase truth — no inference from the final pulse

Audit findings: `TripleAMachine` jumps WAITING→AGGRESSION on an absorption pulse (`quant/amt/triple_a.py:85-96`) and `context_builder.py:185-196` then marks absorption+accumulation+aggression all True. Correction: keep the fast pulse path (it is gated by Task 7's footprint requirement), but `SetupEvidence` must reflect **observed** phases only — a pulse proves aggression, not the walked sequence.

**Files:**
- Modify: `quant/amt/triple_a.py` (snapshot fields `absorption_at`, `accumulation_at`, `aggression_at`; `update(..., bar_time: str = "")`)
- Modify: `quant/amt/analyzer.py` (pass `current.time`; DTO keys `tripleAAbsorptionAt`, `tripleAAccumulationAt`, `tripleAAggressionAt`)
- Modify: `quant/amt/dto.py` (pass-through)
- Modify: `quant/decision/context_builder.py:185-199` (map timestamps → evidence flags)
- Test: `tests/quant/decision/test_evidence_gates.py` (class `TestTripleATimestamps`)

**Interfaces:**
- Produces: `TripleASnapshot(..., absorption_at: str = "", accumulation_at: str = "", aggression_at: str = "")`; `update(*, close, high, low, absorption_side, vwap=0.0, cvd_slope=0.0, bar_time: str = "")`.
- Rule: pulse path sets ONLY `aggression_at`; walked path sets each timestamp as its phase is entered. Evidence flags = `bool(<phase>_at)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/quant/decision/test_evidence_gates.py (append)
from quant.amt.triple_a import TripleAMachine


class TestTripleATimestamps:
    def test_pulse_records_aggression_only(self):
        m = TripleAMachine()
        s = m.update(close=101, high=101, low=99, absorption_side="SELL_ABSORBED",
                     bar_time="2026-09-07T10:00:00+05:30")
        assert s.phase == "AGGRESSION" and s.aggression_at.endswith("10:00:00")
        assert s.absorption_at == "" and s.accumulation_at == ""

    def test_walked_path_records_each_phase(self):
        m = TripleAMachine()
        m.update(close=100, high=101, low=99, absorption_side="ABSORB",
                 bar_time="2026-09-07T10:00:00+05:30")   # WAITING -> ABSORBING
        m.update(close=100, high=101, low=99, absorption_side="",
                 bar_time="2026-09-07T10:05:00+05:30")   # ACCUMULATING after _ACCUM_BARS
        s = m.update(close=103, high=103, low=100, absorption_side="",
                     vwap=100.5, cvd_slope=1.0,
                     bar_time="2026-09-07T10:10:00+05:30")  # breakout -> AGGRESSION
        assert s.absorption_at and s.accumulation_at and s.aggression_at
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_evidence_gates.py::TestTripleATimestamps -q`
Expected: FAIL — snapshot lacks the timestamp fields.

- [ ] **Step 3: Implement**

`triple_a.py`: add the three fields (default `""`) to `TripleASnapshot`, track `self._absorption_at/_accumulation_at/_aggression_at` in `__init__/reset`, set `aggression_at = bar_time` on both pulse branches (lines 85-96), set `absorption_at` when WAITING→ABSORBING occurs via the unconfirmed path, `accumulation_at` at ABSORBING→ACCUMULATING (`analyzer` passes `bar_time=current.time` at its `_triple_a.update(...)` call site), `aggression_at` in the ACCUMULATING breakout branches. `analyzer.py` DTO emits the three keys from `self._triple_a.snapshot()`.

`context_builder.py:185-196` becomes:

```python
if triple_phase == "AGGRESSION" and (triple_signal in ("LONG", "SHORT") or agent_direction in ("LONG", "SHORT")):
    direction = triple_signal or agent_direction
    accepted = bool(amt_dto.get("acceptanceAbove") if direction == "LONG"
                    else amt_dto.get("acceptanceBelow"))
    if accepted:
        # Timestamps are TRUTH: a detector pulse proves aggression only.
        return SetupEvidence(
            setup_type="TRIPLE_A", direction=direction,
            absorption=bool(amt_dto.get("tripleAAbsorptionAt")),
            accumulation=bool(amt_dto.get("tripleAAccumulationAt")),
            aggression=bool(amt_dto.get("tripleAAggressionAt")),
            acceptance=True, cvd_agrees=cvd_agrees,
        )
```

`setup_state.is_complete()` already requires all three flags (`setup_state.py:59`) — with truthful flags, a bare pulse can no longer fabricate complete evidence; the fast pulse entry survives through Gate 3's direct `phase == "AGGRESSION"` path (now footprint-gated by Task 7).

- [ ] **Step 4: Run suites**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/ tests/quant/amt/ backend/tests/unit/domain/test_amt_aggressive_registry.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add quant/amt/triple_a.py quant/amt/analyzer.py quant/amt/dto.py quant/decision/context_builder.py tests/quant/decision/test_evidence_gates.py
git commit -m "triple-a: per-phase timestamps; SetupEvidence reflects observed phases, pulses prove aggression only"
```

---

### Task 9: VA fade requires the full reclaim sequence + reversion permission

Audit findings: `detect_va_fade()` enters while price is still outside VA (`quant/decision/va_fade.py:58,71`), and the fallback path in `decision_service.py:106-126` never checks `ctx.allow_reversion` (the Gate-1 check applies only when `setup_evidence` exists, `gates_session_position.py:18-19`). Correction per audit: probe → failed acceptance → close back inside VA → LVN retest → flow confirmation.

**Files:**
- Modify: `quant/decision/va_fade.py` (rewrite around `ReclaimEvidence`)
- Modify: `quant/decision/context.py` (`reclaim_evidence: Any | None = None`, `nearest_lvn: float = 0.0`)
- Modify: `quant/decision/context_builder.py` (build `ReclaimEvidence` from DTO keys; `nearest_lvn`)
- Modify: `quant/amt/analyzer.py` (emit `reclaimBackInside`, `rejectionAtHigh/Low` already exist — reuse; `nearestLvn`)
- Modify: `quant/decision/decision_service.py:106-126` (`allow_reversion` enforcement)
- Test: `tests/quant/decision/test_va_fade_reclaim.py`

**Interfaces:**
- Produces: `detect_va_fade(ctx) -> VAFadeSignal | None` — returns None unless `ctx.reclaim_evidence.complete` and `ctx.allow_reversion` are true. Direction: probe side that FAILED (below VAL ⇒ LONG fade; above VAH ⇒ SHORT fade).
- Analyzer emits: `reclaimBackInside: bool` (prev close outside VA AND current close inside), `nearestLvn: float` (nearest LVN to current close from the session LVN list).

- [ ] **Step 1: Write the failing tests**

```python
# tests/quant/decision/test_va_fade_reclaim.py
from dataclasses import replace
from quant.decision.context import DecisionContext
from quant.decision.evidence import ReclaimEvidence
from quant.decision.va_fade import detect_va_fade
from quant.bars import Bar


def _ctx(**kw):
    base = dict(
        bar=Bar(time="2026-09-07T10:30:00+05:30", open=94.5, high=95.0,
                low=93.8, close=94.5, volume=1000.0, vwap=94.4, buy_volume=600.0, delta=200.0),
        poc=95.0, vah=99.0, val=91.0, tick_size=0.05, cvd_slope=1.0,
        allow_reversion=True,
        reclaim_evidence=ReclaimEvidence(probed_outside=True, failed_acceptance=True,
                                         back_inside=True, lvn_retested=True,
                                         flow_confirms=True),
        nearest_lvn=94.4,
    )
    base.update(kw)
    return DecisionContext(**base)


def test_full_reclaim_sequence_fires_long_fade():
    sig = detect_va_fade(_ctx())
    assert sig and sig.direction == "LONG" and sig.tp == 95.0


def test_entry_outside_va_is_refused(self_and_everything=False):
    bar = replace(_ctx().bar, close=90.5)   # still below VAL — no reclaim
    assert detect_va_fade(_ctx(bar=bar)) is None


def test_missing_lvn_retest_blocks():
    ev = ReclaimEvidence(probed_outside=True, failed_acceptance=True,
                         back_inside=True, lvn_retested=False, flow_confirms=True)
    assert detect_va_fade(_ctx(reclaim_evidence=ev)) is None


def test_cvd_opposing_flow_blocks():
    ev = ReclaimEvidence(probed_outside=True, failed_acceptance=True,
                         back_inside=True, lvn_retested=True, flow_confirms=False)
    assert detect_va_fade(_ctx(reclaim_evidence=ev, cvd_slope=-1.0)) is None


def test_reversion_phase_permission_blocks_even_with_full_evidence():
    assert detect_va_fade(_ctx(allow_reversion=False)) is None
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_va_fade_reclaim.py -q`
Expected: FAIL — current implementation fires on `close < val and cvd > 0` (no evidence object).

- [ ] **Step 3: Implement**

`va_fade.py` — full rewrite of the decision core (keep `VAFadeSignal` and stop/target math):

```python
def detect_va_fade(ctx: DecisionContext) -> VAFadeSignal | None:
    """Mean-reversion fade back to POC — only after a CONFIRMED reclaim:
    outside probe -> failed acceptance -> close back inside VA -> LVN retest
    -> matching order flow. Nothing else (audit 2026-09-07 #9/#10)."""
    if not ctx or not ctx.bar or not ctx.allow_reversion:
        return None
    ev = getattr(ctx, "reclaim_evidence", None)
    if ev is None or not ev.complete:
        return None
    poc, val, vah, step = ctx.poc, ctx.val, ctx.vah, ctx.tick_size
    if not (poc and val and vah and step):
        return None
    close = float(ctx.bar.close)
    if not (val <= close <= vah):
        return None  # must trade INSIDE the reclaimed value area
    # Preserve the existing stop/target construction below this guard;
    # replace its direction source with `ev.side` as described next.
```

Direction must not live on ctx privates — carry it on the evidence: add `side: str = ""` to `ReclaimEvidence` (`"BELOW"` probed below VAL / `"ABOVE"` probed above VAH; set by context_builder from `prevClose`/`rejectionAt*`), and use `direction = "LONG" if ev.side == "BELOW" else "SHORT"`. Keep the existing SL/TP construction (probe extreme ± tick, target POC, RR math) verbatim from the current implementation.

`context_builder.py` builds the evidence per bar:

```python
from quant.decision.evidence import ReclaimEvidence
prev_close = float(amt_dto.get("prevClose") or 0.0)
probed_below = bool(amt_dto.get("rejectionAtLow")) or (0 < prev_close < float(amt_dto.get("valueAreaLow") or 0.0))
probed_above = bool(amt_dto.get("rejectionAtHigh")) or (0 < prev_close > float(amt_dto.get("valueAreaHigh") or 0.0))
back_inside = bool(amt_dto.get("reclaimBackInside"))
nearest_lvn = float(amt_dto.get("nearestLvn") or 0.0)
flow = str(amt_dto.get("cvdConfirmation") or "")
reclaim = ReclaimEvidence(
    probed_outside=probed_below or probed_above,
    failed_acceptance=bool(probed_below or probed_above),
    side="BELOW" if probed_below else ("ABOVE" if probed_above else ""),
    back_inside=back_inside,
    lvn_retested=nearest_lvn > 0 and abs(close_px - nearest_lvn) <= 3.0 * tick_size,
    flow_confirms=(probed_below and flow == "LONG") or (probed_above and flow == "SHORT"),
)
```

(`prevClose`/`reclaimBackInside`/`nearestLvn` are emitted by the analyzer — `data[-2].close` is already in scope where `compute_value_area` runs; nearestLvn = `min(lvns, key=|lvn-current.close|)` guarded for empty lists.)

`decision_service.py:106-111` — enforce permission before detection:

```python
if not ctx.allow_reversion:
    return QuantDecision(False, None, "NO_EDGE", "", tuple(results),
                         blocked + ("Reversion not permitted this phase",))
fade = detect_va_fade(ctx)
```

- [ ] **Step 4: Run suites**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/ tests/quant/test_audit_regressions.py -q`
Expected: PASS. Tests pinning the old outside-VA entry are updated to the reclaim spec (list in commit body).

- [ ] **Step 5: Commit**

```bash
git add quant/decision/va_fade.py quant/decision/context.py quant/decision/context_builder.py quant/decision/decision_service.py quant/amt/analyzer.py tests/quant/decision/test_va_fade_reclaim.py
git commit -m "va-fade: full reclaim sequence (probe->rejection->reclaim->LVN retest->flow) + allow_reversion enforced in fallback"
```

---

### Task 10: GreekProvider port — fresh chain delta reaches option translation; honest rejects

Audit findings: `context_builder.py:398-402` reads `amt_dto["optionGreekDelta"]`, a key **nothing emits** (verified by grep), so every option entry dies at `selector.py:398-403` ("explicit option Greek delta is required"). Additionally `runtime.py:916-922` mislabels that failure as `OPPOSING_TYPE`.

**Files:**
- Create: `quant/contracts/ports/greeks.py`, `quant/amt/session/greeks.py`
- Modify: `quant/amt/session/scanner.py` (`last_result(symbol)` cache with timestamp)
- Modify: `quant/amt/session/selector.py:375-403` (raise `MissingGreekDeltaError` instead of returning None)
- Modify: `quant/runtime.py:900-925` (provider lookup; catch and label `MISSING_GREEK_DELTA`)
- Modify: `quant/multi_engine.py` + `backend/app/main.py` (construct/wire one provider per coordinator)
- Delete: the dead `optionGreekDelta` read in `context_builder.py:395-402` (`ctx.option_delta` default stays None; provider is the source)
- Test: `tests/quant/execution/test_option_gate.py` (class `TestGreekWiring`)

**Interfaces:**
- Produces: `GreekProvider.delta(symbol: str) -> float | None` (Protocol); `ScannerGreekProvider(scanner, max_age_sec=120.0)`; `MissingGreekDeltaError(RuntimeError)` with `symbol` attr.
- Runtime rule: `delta = provider.delta(symbol)`; `None` ⇒ translate raises ⇒ decision reason `MISSING_GREEK_DELTA` (fail-closed, honest label).

- [ ] **Step 1: Write the failing tests**

```python
# tests/quant/execution/test_option_gate.py (file created; Greek classes first)
import time
import pytest
from quant.amt.session.greeks import ScannerGreekProvider
from quant.amt.session.selector import MissingGreekDeltaError, OptionSelector
from quant.decision.signal_builder import Signal


class FakeScanner:
    def __init__(self):
        self._last = {}
        self._ts = {}
    def publish(self, symbol, delta):
        self._last[symbol] = delta
        self._ts[symbol] = time.time()
    def last_greek(self, symbol):
        if symbol not in self._last:
            return None
        return {"delta": self._last[symbol], "ts": self._ts[symbol]}


class TestGreekWiring:
    def test_fresh_delta_passes_through(self):
        s = FakeScanner(); s.publish("NIFTY 8 SEP 23850 CALL", 0.42)
        p = ScannerGreekProvider(s)
        assert p.delta("NIFTY 8 SEP 23850 CALL") == 0.42

    def test_stale_delta_is_none_fail_closed(self):
        s = FakeScanner(); s.publish("X", 0.42)
        p = ScannerGreekProvider(s, max_age_sec=1.0)
        s._ts["X"] = time.time() - 3600
        assert p.delta("X") is None

    def test_unknown_symbol_is_none(self):
        assert ScannerGreekProvider(FakeScanner()).delta("Y") is None

    def test_translate_raises_on_missing_delta(self):
        sig = Signal(type="LONG", reason="t", entry=24_000.0, sl=23_980.0,
                     tp=24_050.0, rr=2.5, symbol="NIFTY", timestamp="t")
        with pytest.raises(MissingGreekDeltaError):
            OptionSelector().translate_underlying_signal_to_option(
                signal=sig, option_symbol="NIFTY 8 SEP 23850 CALL",
                option_ltp=150.0, delta=None)
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/test_option_gate.py -q`
Expected: FAIL — modules/exception missing; `translate` currently returns None.

- [ ] **Step 3: Implement**

```python
# quant/contracts/ports/greeks.py
"""The ONE source of option Greeks for execution (audit 2026-09-07 #8).
Implementations must return None when the quote is missing/stale — never a
guess. Consumers treat None as fail-closed."""
from typing import Protocol, runtime_checkable


@runtime_checkable
class GreekProvider(Protocol):
    def delta(self, symbol: str) -> float | None: ...
```

```python
# quant/amt/session/greeks.py
from quant.contracts.ports.greeks import GreekProvider  # re-export for DI typing
import time


class ScannerGreekProvider:
    """Binds chain deltas from OptionScannerService to symbol + quote time."""

    def __init__(self, scanner, max_age_sec: float = 120.0) -> None:
        self._scanner = scanner
        self._max_age = float(max_age_sec)

    def delta(self, symbol: str) -> float | None:
        g = self._scanner.last_greek(symbol)
        if not g:
            return None
        if time.time() - g["ts"] > self._max_age:
            return None
        d = g["delta"]
        if d is None:
            return None
        d = float(d)
        return d if 0.0 < abs(d) <= 1.0 else None
```

`scanner.py`: add `self._last_greek: dict[str, dict] = {}` in `__init__`; wherever a `ScanResult` is produced per contract, record `self._last_greek[result.symbol] = {"delta": result.delta, "ts": time.time()}`; expose `last_greek(symbol)` returning the dict or None.

`selector.py:398-403`:

```python
class MissingGreekDeltaError(RuntimeError):
    def __init__(self, symbol: str) -> None:
        super().__init__(f"{symbol}: no fresh chain Greek delta — option entry fail-closed")
        self.symbol = symbol

# inside translate_underlying_signal_to_option:
if delta is None or not math.isfinite(float(delta)) or not 0.0 < abs(float(delta)) <= 1.0:
    raise MissingGreekDeltaError(option_symbol)
```

`runtime.py:900-925`:

```python
delta = None
if self._greek_provider is not None:
    delta = self._greek_provider.delta(self.symbol)
if delta is None:
    delta = getattr(ctx, "option_delta", None)
try:
    opt_signal = selector.translate_underlying_signal_to_option(
        signal=decision.signal, option_symbol=self.symbol,
        option_ltp=opt_ltp, delta=delta, tick_size=self._tick_size)
except MissingGreekDeltaError:
    decision = _dc_replace(decision, approved=False, signal=None,
                           reason="MISSING_GREEK_DELTA",
                           block_reasons=(f"No fresh chain Greek delta for {self.symbol} "
                                          f"(quote age > max) — fail-closed",))
else:
    if opt_signal is None:
        decision = _dc_replace(decision, approved=False, signal=None,
                               reason="OPPOSING_TYPE",
                               block_reasons=("Signal direction opposes option contract type",))
    else:
        decision = _dc_replace(decision, signal=opt_signal)
```

`QuantEngine.__init__(..., greek_provider=None)` → `self._greek_provider`; `_spawn_engine` forwards `greek_provider=self._greek_provider` from coordinator config; `backend/app/main.py` constructs `ScannerGreekProvider(scanner)` next to where it builds `_gex_by_root` and passes it into the coordinator config (`"greek_provider": provider`). Delete `context_builder.py:395-402` dead key read (comment included) — `option_delta` keeps its default `None`.

- [ ] **Step 4: Run suites**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/test_option_gate.py tests/quant/decision/test_option_signal_translation.py tests/quant/test_adversarial_regression.py backend/tests/unit/domain/test_option_scanner.py -q`
Expected: PASS (translation tests that fed `delta=0.5` directly are unaffected; none relied on the None-rejection return).

- [ ] **Step 5: Commit**

```bash
git add quant/contracts/ports/greeks.py quant/amt/session/greeks.py quant/amt/session/scanner.py quant/amt/session/selector.py quant/runtime.py quant/multi_engine.py backend/app/main.py quant/decision/context_builder.py tests/quant/execution/test_option_gate.py
git commit -m "options: GreekProvider port from scanner chain — fresh-delta fail-closed translation, honest MISSING_GREEK_DELTA reject; delete dead optionGreekDelta key"
```

---

### Task 11: One option admission gate — liquidity, IV/theta viability, GEX pin

Audit findings: `OptionSelector.validate_option()`/`check_theta()` are called only by tests — never on the live path; GEX is display-only (`multi_engine.py:1444-1445`); the zero-DTE pin scenario has no defense. One gate, reusing the existing selector logic (no duplication), enforced before translation.

**Files:**
- Create: `quant/execution/option_gate.py`
- Modify: `quant/runtime.py` (call gate pre-translation; build quote from provider + ctx)
- Modify: `quant/contracts/constants.py` (`MAX_GAMMA_PIN_DISTANCE_PCT = 0.0025`)
- Test: `tests/quant/execution/test_option_gate.py` (class `TestOptionAdmission`)

**Interfaces:**
- Produces: `validate_option_entry(*, quote: ScanResult | None, selector_cfg: OptionSelectorConfig | None, spot: float, gamma_pin_strike: float, zero_flip_level: float, expected_hold_minutes: int = 30, target_premium_move: float) -> OptionAdmission(allowed: bool, reasons: tuple[str, ...])`.
- Gate rules (fail-closed): missing quote ⇒ reject; `validate_option` fail ⇒ reject; `check_theta` not viable ⇒ reject; `dte == 0` AND (`|spot - gamma_pin_strike|/spot <= MAX_GAMMA_PIN_DISTANCE_PCT` OR spot beyond `zero_flip_level` in the adverse direction) ⇒ reject.

- [ ] **Step 1: Write the failing tests**

```python
# tests/quant/execution/test_option_gate.py (append)
from types import SimpleNamespace
from quant.execution.option_gate import validate_option_entry


def _quote(**kw):
    base = dict(symbol="NIFTY 8 SEP 23850 CALL", delta=0.42, iv=0.12,
                theta=-45.0, bid_ask_spread=1.2, oi=250_000, volume=80_000,
                ltp=150.0, expiry="2026-09-08", num_lots=1, lot_size=75)
    base.update(kw)
    return SimpleNamespace(**base)


class TestOptionAdmission:
    def test_healthy_quote_is_admitted(self):
        a = validate_option_entry(quote=_quote(), selector_cfg=None, spot=23_860.0,
                                  gamma_pin_strike=0.0, zero_flip_level=0.0,
                                  target_premium_move=12.0)
        assert a.allowed and not a.reasons

    def test_missing_quote_is_rejected_fail_closed(self):
        a = validate_option_entry(quote=None, selector_cfg=None, spot=23_860.0,
                                  gamma_pin_strike=0.0, zero_flip_level=0.0,
                                  target_premium_move=12.0)
        assert not a.allowed and "quote" in a.reasons[0].lower()

    def test_theta_heavy_quote_is_rejected(self):
        a = validate_option_entry(quote=_quote(theta=-400.0), selector_cfg=None,
                                  spot=23_860.0, gamma_pin_strike=0.0,
                                  zero_flip_level=0.0, target_premium_move=4.0)
        assert not a.allowed and any("theta" in r.lower() for r in a.reasons)

    def test_zero_dte_pin_zone_is_rejected(self):
        a = validate_option_entry(quote=_quote(expiry="2026-09-07"), selector_cfg=None,
                                  spot=23_850.0, gamma_pin_strike=23_850.0,
                                  zero_flip_level=23_850.0, target_premium_move=12.0)
        assert not a.allowed and any("pin" in r.lower() for r in a.reasons)
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/test_option_gate.py::TestOptionAdmission -q`
Expected: FAIL — module missing.

- [ ] **Step 3: Implement**

```python
# quant/execution/option_gate.py
"""The ONE admission gate for option entries (audit 2026-09-07 #15/#16).

Reuses OptionSelector.validate_option / check_theta — no second liquidity or
theta implementation. Adds what those lack: quote existence, GEX pin /
zero-flip defense on zero-DTE. Fail-closed on every missing input.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from types import SimpleNamespace

from quant.contracts.constants import MAX_GAMMA_PIN_DISTANCE_PCT
from quant.contracts.timezones import today_ist
from quant.amt.session.selector import OptionSelector, OptionSelectorConfig


@dataclass(frozen=True)
class OptionAdmission:
    allowed: bool
    reasons: tuple[str, ...] = ()


def validate_option_entry(*, quote, selector_cfg: OptionSelectorConfig | None,
                          spot: float, gamma_pin_strike: float,
                          zero_flip_level: float, expected_hold_minutes: int = 30,
                          target_premium_move: float) -> OptionAdmission:
    reasons: list[str] = []
    if quote is None:
        return OptionAdmission(False, ("No scanner quote for contract — fail-closed",))
    if spot <= 0 or quote.ltp <= 0:
        return OptionAdmission(False, ("No valid spot/premium quote — fail-closed",))

    cfg = selector_cfg or OptionSelectorConfig()
    sel = OptionSelector(cfg)
    ok, why = sel.validate_option(quote)
    if not ok:
        reasons.append(why)

    dte = (date.fromisoformat(str(quote.expiry)) - today_ist()).days
    if dte == 0 and gamma_pin_strike > 0 and \
            abs(spot - gamma_pin_strike) / spot <= MAX_GAMMA_PIN_DISTANCE_PCT:
        reasons.append(
            f"Zero-DTE gamma pin: spot {spot:.0f} within "
            f"{MAX_GAMMA_PIN_DISTANCE_PCT:.2%} of pin {gamma_pin_strike:.0f}")
    if dte == 0 and zero_flip_level > 0 and spot < zero_flip_level:
        reasons.append(
            f"Zero-DTE below gamma flip {zero_flip_level:.0f} — dealer-negative regime")

    theta = sel.check_theta(quote, expected_hold_minutes, target_premium_move)
    if not theta.viable:
        reasons.append(
            f"Theta ratio {theta.theta_ratio:.2f} exceeds max "
            f"{cfg.max_theta_ratio:.2f} (cost {theta.holding_cost} vs profit {theta.expected_profit})")

    return OptionAdmission(allowed=not reasons, reasons=tuple(reasons))
```

`constants.py`: `MAX_GAMMA_PIN_DISTANCE_PCT = _get("max_gamma_pin_distance_pct", 0.0025)`.

`runtime.py` — before the translation block (after `decision.approved`):

```python
admission = None
if self._underlying_gateway is not None:   # option contract with futures feed
    from quant.execution.option_gate import validate_option_entry
    gex = getattr(self._amt_engine, "_gex", None)
    quote = self._greek_provider.quote(self.symbol) if self._greek_provider else None
    spot = self._underlying_ltp()          # existing helper for futures LTP
    admission = validate_option_entry(
        quote=quote, selector_cfg=self._option_selector_cfg,
        spot=spot,
        gamma_pin_strike=float(getattr(gex, "gamma_pin_strike", 0.0) or 0.0),
        zero_flip_level=float(getattr(gex, "zero_flip_level", 0.0) or 0.0),
        expected_hold_minutes=int(time_stop_minutes),
        target_premium_move=max(self._tick_size * 20, opt_ltp * 0.08))
    if not admission.allowed:
        decision = _dc_replace(decision, approved=False, signal=None,
                               reason="OPTION_ADMISSIBILITY",
                               block_reasons=admission.reasons)
if admission is not None and admission.allowed:
    # execute the existing translation block here, unchanged apart from
    # consuming the provider-supplied fresh delta.
```

(`ScannerGreekProvider.quote(symbol)` returns the cached `ScanResult`-shaped quote or None — one more accessor beside `last_greek`; `OptionSelectorConfig` comes from coordinator config key `option_selector_cfg` defaulting to `OptionSelectorConfig()`. GEX field names verified against `quant/amt/profile/gamma.py:66-71`: `zero_flip_level`, `gamma_pin_strike`.)

- [ ] **Step 4: Run suites**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/test_option_gate.py tests/quant/runtime/ tests/quant/test_certification.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add quant/execution/option_gate.py quant/runtime.py quant/contracts/constants.py tests/quant/execution/test_option_gate.py
git commit -m "options: single admission gate — liquidity+DTE via selector, theta viability, zero-DTE gamma-pin/zero-flip defense"
```

---

### Task 12: Cost-accurate paper fills — one factory, simulator always wired

Audit findings: the paper path injects plain `PaperOMS` with no simulator (`quant/runtime.py:282`, `multi_engine.py:1446-1457`) — fills at signal price, gross P&L, zero STT/brokerage/GST/slippage, even though `quant/execution/trade_costs.py` + `paper_simulator.py` are complete and tested. Fix: one factory; the coordinator cannot construct a costless paper OMS.

**Files:**
- Create: `quant/execution/oms_factory.py`
- Modify: `quant/multi_engine.py:1446+` (paper branch uses factory)
- Modify: `backend/app/config_models/loader.py` (surface `cost_profile` from `base.yaml:510-516` into coordinator config)
- Test: `tests/quant/execution/test_oms_costs.py`

**Interfaces:**
- Produces: `make_paper_oms(*, contract: ContractRef, cost_profile: dict) -> PaperOMS` (raises `ValueError` when `cost_profile` is missing/empty — no costless paper fills in production code paths).
- Consumes: `PaperExecutionSimulator(fill_mode, slippage_bps)`, `PaperOMS(lot_size, simulator=, contract=)`.

- [ ] **Step 1: Write the failing test**

```python
# tests/quant/execution/test_oms_costs.py
import pytest
from quant.contracts.contracts import ContractRef
from quant.decision.signal_builder import Signal
from quant.execution.oms_factory import make_paper_oms


def _contract():
    return ContractRef(symbol="NIFTY 8 SEP 23850 CALL", exchange="NFO",
                       expiry="2026-09-08", lot_size=75, tick_size=0.05)


def _signal(entry=150.0):
    return Signal(type="LONG", reason="t", entry=entry, sl=145.0, tp=160.0,
                  rr=2.0, symbol=_contract().symbol, timestamp="2026-09-07T10:00:00+05:30")


def test_factory_refuses_missing_cost_profile():
    with pytest.raises(ValueError):
        make_paper_oms(contract=_contract(), cost_profile=None)


def test_round_trip_pnl_is_net_of_costs():
    oms = make_paper_oms(contract=_contract(), cost_profile={
        "slippage_bps": 10, "stt_pct": 0.000625, "exchange_fee_pct": 0.000495,
        "brokerage_per_order": 20.0, "gst_on_brokerage_pct": 0.18,
        "sebi_charges_pct": 0.000001})
    pos = oms.submit(_signal(), quantity=75)
    fill = oms.close(pos, price=155.0, time="t2", reason="TP")
    gross = (155.0 - 150.0) * 75
    assert fill.pnl < gross, "paper P&L must be net of round-trip costs"
    assert oms.last_fill is not None and oms.last_fill.costs.total > 0
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/test_oms_costs.py -q`
Expected: FAIL — `oms_factory` missing.

- [ ] **Step 3: Implement**

```python
# quant/execution/oms_factory.py
"""The ONE constructor for cost-accurate paper OMS instances.

Audit 2026-09-07 #14: the coordinator injected bare PaperOMS (no simulator),
so paper fills ignored STT/exchange/brokerage/GST/slippage. Production code
paths must use this factory — a missing cost profile is a startup error,
not a silent gross-P&L mode.
"""
from __future__ import annotations

from quant.contracts.contracts import ContractRef
from quant.execution.oms import PaperOMS
from quant.execution.paper_simulator import PaperExecutionSimulator

_REQUIRED_COST_KEYS = ("slippage_bps", "stt_pct", "exchange_fee_pct",
                       "brokerage_per_order", "gst_on_brokerage_pct",
                       "sebi_charges_pct")


def make_paper_oms(*, contract: ContractRef, cost_profile: dict | None) -> PaperOMS:
    if not cost_profile or any(k not in cost_profile for k in _REQUIRED_COST_KEYS):
        missing = [k for k in _REQUIRED_COST_KEYS if not cost_profile or k not in cost_profile]
        raise ValueError(
            f"cost_profile missing keys {missing} — refusing costless paper fills "
            "(audit 2026-09-07 #14)")
    simulator = PaperExecutionSimulator(
        # Normal paper uses executable bid/ask semantics. `instant_mid` is
        # permitted only by explicit unit-test/replay configuration.
        fill_mode=str(cost_profile.get("fill_mode", "bid_ask")),
        slippage_bps=float(cost_profile["slippage_bps"]),
    )
    return PaperOMS(lot_size=float(contract.lot_size),
                    simulator=simulator, contract=contract)
```

If `PaperExecutionSimulator` needs the remaining cost keys passed through (verify at `quant/execution/paper_simulator.py:37-45` vs `trade_costs.py:30-57` defaults), extend its constructor to accept them explicitly in this task and have the factory forward all six keys — one authority, no hidden defaults divergence.

`multi_engine.py` paper branch (the `else` of `live_oms_enabled`):

```python
else:
    from quant.execution.oms_factory import make_paper_oms
    contract = self._contract_for(symbol)   # build ContractRef via DEFAULT_REGISTRY.resolve(symbol): exchange/expiry/lot/tick (expiry from selector when option)
    engine._oms = make_paper_oms(contract=contract,
                                 cost_profile=self.config.get("cost_profile"))
```

`loader.py`: `"cost_profile": merged.get("strategy", {}).get("cost_profile")` into coordinator config (key exists at `base.yaml:510-516`).

- [ ] **Step 4: Run suites**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/ tests/quant/test_certification.py tests/system/ -q`
Expected: PASS. Suites constructing bare `PaperOMS()` directly keep working (direct construction remains legal for unit tests — the factory is the coordinator's path, asserted by `test_factory_refuses_missing_cost_profile`).

- [ ] **Step 5: Commit**

```bash
git add quant/execution/oms_factory.py quant/multi_engine.py backend/app/config_models/loader.py tests/quant/execution/test_oms_costs.py
git commit -m "paper: cost-accurate fills — make_paper_oms factory wires simulator+cost_profile, refuses costless paper OMS"
```

---

### Task 13: LiveOMS partial close — lot-snapped quantity, filled-qty P&L

Audit findings: `LiveOMS.close_partial()` truncates with `int(closed_size)` and books P&L on the *requested* size (`quant/execution/live_oms.py:215-260`): a 50% exit of a 65-unit NIFTY lot yields 32 units (invalid), and a partial broker fill misreports P&L.

**Files:**
- Modify: `quant/execution/live_oms.py:203-290`
- Test: `tests/quant/execution/test_oms_conformance.py` (extend the OD suite: classes `TestPartialLotSafety`)

**Interfaces:** unchanged signature `close_partial(position, fraction, price, time, reason) -> (Fill, Position)`. New behavior:
- `close_lots = min(held_lots, floor(held_lots * fraction))`; `qty = close_lots * lot_size`.
- `close_lots < 1` ⇒ zero-fill no-op (position returned untouched, reason `PARTIAL_DUST`).
- P&L: `(fill_price - open_price) * filled_qty_signed` where `filled_qty_signed` comes from `_fill.filled_qty` (broker truth), never the requested size.

- [ ] **Step 1: Write the failing tests**

```python
# tests/quant/execution/test_oms_conformance.py (append; reuse suite's broker stub)
class TestPartialLotSafety:
    def test_fraction_below_one_lot_is_a_noop(self, live_oms_65lot):
        pos = _open(live_oms_65lot, size=65)         # 1 lot of 65
        fill, remaining = live_oms_65lot.close_partial(pos, 0.5, price=101.0,
                                                       time="t", reason="TP1")
        assert fill.pnl == 0.0 and remaining.size == pos.size
        assert fill.reason == "PARTIAL_DUST"

    def test_pnl_uses_broker_filled_quantity(self, live_oms_65lot, partial_fill_32):
        # broker fills 32 of requested 32 (2 lots of 16 impossible -> stub returns filled_qty=32)
        pos = _open(live_oms_65lot, size=130)        # 2 lots
        fill, remaining = live_oms_65lot.close_partial(pos, 0.5, price=101.0,
                                                       time="t", reason="TP1")
        assert fill.position.size == 65.0
        assert fill.pnl == pytest.approx((fill.close_price - pos.open_price) * 65.0)

    def test_never_closes_more_than_held(self, live_oms_65lot):
        pos = _open(live_oms_65lot, size=65)
        fill, remaining = live_oms_65lot.close_partial(pos, 0.9, price=101.0,
                                                       time="t", reason="TP1")
        assert remaining.size == pos.size  # floor(1*0.9)=0 lots -> noop
```

- [ ] **Step 2: Run to verify failure**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/test_oms_conformance.py -q -k TestPartialLotSafety`
Expected: FAIL — current code books 32 units P&L on the 65-lot case.

- [ ] **Step 3: Implement**

```python
# live_oms.py — replace lines 215-220 and 260
held_lots = int(round(abs(position.size) / self._lot_size)) if self._lot_size > 0 else 0
close_lots = int(held_lots * fraction)          # floor — never exceed held
qty = close_lots * self._lot_size
if close_lots < 1:
    logger.warning("LiveOMS.close_partial: %.0f%% of %d units < 1 lot — noop",
                   fraction * 100, abs(position.size))
    return (Fill(position=Position(order=position.order,
                open_price=position.open_price, open_time=position.open_time,
                size=0.0, realized_pnl=0.0, pyramid_level=position.pyramid_level,
                is_pyramid=position.is_pyramid),
                close_price=price, close_time=time, reason="PARTIAL_DUST", pnl=0.0),
            position)
# ... broker close_position(...) unchanged ...
signed_filled = filled_qty if long else -filled_qty
partial_pnl = (fill_price - position.open_price) * signed_filled
# fill_position.size = signed_filled ; remaining.size = position.size - signed_filled
```

(`filled_qty` already exists at line 258 via `broker_position_to_fill`; only the P&L/size lines change. `snap_to_lot` is intentionally NOT used here — flooring lots is the safe direction; `snap_to_lot` rounds.)

- [ ] **Step 4: Run suites**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/test_oms_conformance.py tests/quant/test_partial_fold_reconcile.py tests/quant/runtime/ -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add quant/execution/live_oms.py tests/quant/execution/test_oms_conformance.py
git commit -m "live: partial close snaps to whole lots (floor), no-ops on dust, P&L from broker filled_qty"
```

---

### Task 14: One metrics surface + honest reconciliation status

Audit findings: `/metrics/summary` reads `ticks_processed_total` — a counter no production code increments (`backend/app/api/routers/observability.py:24`, `backend/app/core/metrics.py:200`) — while `quant/execution/coordinator_metrics.py` already provides the live, authoritative activity snapshot; paper-mode reconciliation reports `restored=db_positions` with no broker check (`backend/app/domain/ops/startup_reconciliation.py:87-93`), producing the observed misleading `db=2 broker=0 restored=2`.

**Files:**
- Modify: `backend/app/api/routers/observability.py:18-35` (summary from `CoordinatorMetricsProvider`)
- Modify: `backend/app/main.py` (inject provider via a `set_activity_provider()` — same DI pattern as `metrics.py:set_trackers`)
- Modify: `backend/app/core/metrics.py:200` (delete the dead counter)
- Modify: `backend/app/domain/ops/startup_reconciliation.py` (`broker_checked: bool` on the result)
- Modify: `backend/app/api/routers/health.py` (readiness + `/health` expose `position_mismatch`)
- Test: `backend/tests/unit/test_metrics_truth.py`, `backend/tests/unit/domain/test_reconciliation_truth.py`

**Interfaces:**
- Produces: `observability.set_activity_provider(provider: CoordinatorMetricsProvider)`; summary payload gains `engines` (per-engine heartbeat + `data_age_seconds`) and `ticks_processed` from the provider.
- Produces: `ReconciliationResult(..., broker_checked: bool)`; `/health` includes `"reconciliation": {"broker_checked": bool, "status": "OK" | "PAPER_TOLERATED"}`.

- [ ] **Step 1: Write the failing tests**

```python
# backend/tests/unit/test_metrics_truth.py
def test_summary_reflects_engine_activity(fake_coordinator_with_engine):
    from app.api.routers import observability
    from quant.execution.coordinator_metrics import CoordinatorMetricsProvider
    observability.set_activity_provider(CoordinatorMetricsProvider(fake_coordinator_with_engine))
    import asyncio
    summary = asyncio.run(observability.metrics_summary())
    assert summary["ticks_processed"] >= 1
    assert summary["engines"], "per-engine heartbeats must be exposed"
    eng = next(iter(summary["engines"].values()))
    assert "data_age_seconds" in eng and "seed_status" in eng


def test_dead_counter_is_gone():
    from app.core.metrics import metrics
    assert "ticks_processed_total" not in metrics._metrics
```

```python
# backend/tests/unit/domain/test_reconciliation_truth.py
def test_paper_mode_reports_broker_unchecked(paper_mode, db_two_positions):
    svc = StartupReconciliation(storage=db_two_positions, broker=DeadBroker(), policy=ReconcilePolicy.QUARANTINE)
    result = svc.run()
    assert result.restored == 2
    assert result.broker_checked is False
    assert result.status == "PAPER_TOLERATED"

def test_live_mode_refuses_on_mismatch(live_mode, db_two_positions, empty_broker):
    svc = StartupReconciliation(storage=db_two_positions, broker=empty_broker, policy=ReconcilePolicy.QUARANTINE)
    with pytest.raises(ReconciliationError):
        svc.run()
```

- [ ] **Step 2: Run to verify failure**

Run: `cd backend && PYTHONPATH=..:. ../.venv/bin/python -m pytest tests/unit/test_metrics_truth.py tests/unit/domain/test_reconciliation_truth.py -q`
Expected: FAIL — `set_activity_provider` missing; result lacks `broker_checked`.

- [ ] **Step 3: Implement**

`observability.py`: module-level `_activity = None` + `set_activity_provider(p)`; `/summary` becomes:

```python
payload = {
    "signals_generated": ...,
    "errors_total": ...,
    "pipeline_duration_avg": ...,
    "startup": startup_snapshot(),
    "crash_summary": crash_summary(),
    "startup_unresolved_symbols": unresolved_count(),
}
if _activity is not None:
    snap = _activity.snapshot()
    payload["ticks_processed"] = snap.get("ticks_processed", 0)
    payload["engines"] = snap.get("engines", {})
else:
    payload["ticks_processed"] = 0
return payload
```

`main.py` — after coordinator start: `observability_router` import already exists; add `from app.api.routers import observability` … `observability.set_activity_provider(CoordinatorMetricsProvider(coordinator))`. Delete `metrics.counter("ticks_processed_total", ...)` at `core/metrics.py:200`.

`startup_reconciliation.py`: extend the frozen/`dataclass` `ReconciliationResult` with `broker_checked: bool = False` and `status: str = "OK"`; the non-live short-circuit (lines 87-93) sets `broker_checked=False, status="PAPER_TOLERATED"`; live path sets `broker_checked=True` (mismatch handling unchanged — already refuses). `health.py` `/health` + `/health/ready` include the reconciliation status from the stored startup result; readiness stays `ready` in paper (tolerated) but now states why, and in live remains refused on mismatch.

- [ ] **Step 4: Run suites**

Run: `cd backend && PYTHONPATH=..:. ../.venv/bin/python -m pytest tests/unit/ tests/integration/test_api_endpoints.py -q`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/app/api/routers/observability.py backend/app/main.py backend/app/core/metrics.py backend/app/domain/ops/startup_reconciliation.py backend/app/api/routers/health.py backend/tests/unit/test_metrics_truth.py backend/tests/unit/domain/test_reconciliation_truth.py
git commit -m "observability: one live metrics surface (CoordinatorMetricsProvider); reconciliation exposes broker_checked/PAPER_TOLERATED"
```

---

### Task 15: Certification battery — gap day, pin day, chop day

Audit conclusion: fail live-readiness until "implemented and replay-certified". The repo already has the harness (`make parity` → `tests/quant/test_golden_*.py` + `tests/quant/certification/run_battery`). This task adds the three audited stress scenarios as deterministic replay tests and wires the gate into acceptance.

**Files:**
- Create: `tests/quant/certification/test_production_readiness.py`
- Modify: `backend/scripts/acceptance_gate.py` (require the new battery marker)
- Test: the file itself (marked `certification`)

**Interfaces:**
- Consumes: `QuantEngine` + `PaperOMS` via the existing certification fixtures (see `tests/quant/test_certification.py:220-240` and `runtime_audit/e2e/test_phase8_e2e.py` for engine-boot patterns; synthetic bars via `tests/helpers/synthetic.py`).
- Scenario helpers: `_boot_engine(symbol, lot_size)`, `_feed(eng, bars)`, `_approved_decisions(eng)`.

- [ ] **Step 1: Write the three scenario tests**

```python
# tests/quant/certification/test_production_readiness.py
"""Replay certification for the 2026-09-07 audit scenarios.
Each test boots a real QuantEngine + cost-accurate PaperOMS and replays a
synthetic day. Green = the audit's fail-closed defenses hold end-to-end."""
import pytest

pytestmark = [pytest.mark.certification]

from tests.quant.certification.fixtures import (  # shared boot helpers
    boot_paper_engine, feed_bars, gap_day_bars, pin_day_bars, chop_day_bars)


def test_gap_day_no_entries_before_acceptance_and_portfolio_cap_holds():
    eng = boot_paper_engine("NIFTY 8 SEP 23850 CALL")
    feed_bars(eng, gap_day_bars(open_gap_pct=1.2))   # overnight gap through prior VA
    approved = [r for r in eng.cert_records if r["decision"].approved]
    first = approved[0] if approved else None
    if first is not None:
        # any approval must be after the first acceptance flag, never bar 1-3
        assert first["bar_index"] > 3
    # portfolio authority capped what risk was booked
    assert eng._portfolio_risk._open_risk <= eng._portfolio_risk._max_open_risk


def test_pin_day_zero_dte_entries_blocked_near_gamma_pin():
    eng = boot_paper_engine("NIFTY 8 SEP 23850 CALL", gex_pin=23_850.0, spot=23_851.0)
    feed_bars(eng, pin_day_bars(center=23_850.0))
    blocked = [r for r in eng.cert_records
               if r["decision"].reason in ("OPTION_ADMISSIBILITY", "MISSING_GREEK_DELTA")]
    assert blocked, "pin-day entries must be refused by the option gate"


def test_chop_day_va_fade_requires_full_reclaim():
    eng = boot_paper_engine("NIFTY 8 SEP 23850 CALL")
    feed_bars(eng, chop_day_bars(center=23_850.0, va_width=40.0))
    fades = [r for r in eng.cert_records if r["decision"].model_label == "VA_Fade"]
    for r in fades:
        assert r["context"]["reclaim_complete"] is True
    # and every fill was cost-adjusted
    if eng._oms.last_fill is not None:
        assert eng._oms.last_fill.costs.total > 0
```

(The fixture module `tests/quant/certification/fixtures.py` is created in this task with the boot/feed helpers plus the three synthetic-day generators, following the existing patterns in `tests/helpers/synthetic.py` and `tests/quant/certification/__init__.py`.)

- [ ] **Step 2: Run the battery**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/certification/test_production_readiness.py -q`
Expected: PASS after scenarios exercise Tasks 1-14. A red test here means an earlier task's gate is bypassable — fix the gate, never loosen the scenario.

- [ ] **Step 3: Wire into acceptance + full gates**

`backend/scripts/acceptance_gate.py`: add `-m certification` suite to the required list alongside the existing phases. Then run the complete release gate:

```bash
make lint
make test-ci
make parity
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/certification/ -q
cd backend && PYTHONPATH=..:. ../.venv/bin/python scripts/acceptance_gate.py
```

Expected: all green.

- [ ] **Step 4: Commit**

```bash
git add tests/quant/certification/test_production_readiness.py tests/quant/certification/fixtures.py backend/scripts/acceptance_gate.py
git commit -m "cert: replay battery for gap/pin/chop days — live-option approval now gated on green certification"
```

---

## Post-completion checklist (all must be true)

1. `grep -rn "optionGreekDelta" quant/` → no hits (dead key deleted).
2. `grep -rn "0.95" backend/config/base.yaml` → no hits in risk section.
3. `grep -rn "_update_session_vwap\|session_open=data\[0\]" quant/` → analyzer no longer self-detects rollover.
4. `grep -rn "max_portfolio_risk_pct: float = 0.95" quant/` → no hits (limits required).
5. Paper runtime log shows net-of-cost fills (`"slippage"|"stt"|"brokerage"` in fill events).
6. `/metrics/summary` shows non-zero `ticks_processed` + per-engine `data_age_seconds` while feed is live.
7. Option entries rejected only with honest reasons: `MISSING_GREEK_DELTA` / `OPTION_ADMISSIBILITY` / `OPPOSING_TYPE`.
8. `make lint && make test-ci && make parity` + certification battery green.
9. Live options remain disabled (`live_oms_enabled=false`) until sign-off on #8 and a paper week with the new gates.

## Self-Review

- **Spec coverage:** every audited finding maps to a task — #1/#2→T3/T4, #3→T5, #4→T8, #5→T7, #6→T6, #7→T8, #8→T9, #9/#10→T9, #8(dead key)/relabel→T10, #15/#16/GEX→T11, #14→T12, #17→T13, #11/#12→T1, #13→T2, #18(drawdown)→T1, #19(CVD scale)→T6, #20(metrics)→T14, #21(readiness)→T14, structural-stop fallbacks (audit #22, Med/High) are partially covered by Task 9's LVN retest requirement; a dedicated structural-stop audit is deferred (documented, not silently dropped). #23 observability→T14.
- **Placeholder scan:** no unresolved TODO/TBD work remains. Code excerpts intentionally omit unchanged bodies only where the surrounding text names the exact existing implementation to preserve; implementers must not treat those elisions as permission to invent a weaker seam or skip the stated invariant.
- **Type consistency:** `PortfolioLimits` (T1) consumed in T1 only; `ExecutionFailureBreaker` (T2) consumed in runtime/multi_engine; `FootprintEvidence`/`ReclaimEvidence` (T7) consumed in T9; `GreekProvider`/`MissingGreekDeltaError` (T10) consumed in T11; `OptionAdmission` (T11) consumed by T15 assertions.
