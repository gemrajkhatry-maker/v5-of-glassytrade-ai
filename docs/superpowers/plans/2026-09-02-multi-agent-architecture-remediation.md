# Multi-Agent Architecture Remediation Plan

**Date:** 2026-09-02
**Repository:** GlassyTrade AI
**Branch at planning time:** `feat/value-area-reversion-signals`
**Status:** Execution plan; no implementation changes

> **For agentic workers:** REQUIRED SUB-SKILL: `superpowers:subagent-driven-development` for every task. Use `superpowers:executing-plans` for the coordinator when applying this document. The repository does not contain an installed `ponytail` skill; in this plan, **Ponytail** means the repository's existing discipline of marking deliberate ceilings and deferred behavior with a concise `# ponytail:` comment.

## 1. Objective

Make the live trading path safe, restartable, observable, and architecturally convergent without attempting a risky all-at-once rewrite.

The target architecture is:

```text
market feed -> canonical event stream -> deterministic strategy
           -> single RiskGate -> durable OMS -> broker adapter
           -> fills/order events -> folded state -> API/WS projections
```

Backtest, replay, paper, and live modes must share strategy, risk, state transitions, and wire projections. Only the feed, clock, OMS implementation, and broker adapter may vary by mode.

## 2. Current Assessment

The repository has useful foundations, but they are not yet the runtime authority:

- `quant/event_store.py`, `state_machine.py`, `transitions.py`, and `state.py` provide event-store and projection primitives, but restart authority and durable order recovery are incomplete.
- Mutable runtime state, per-engine state, SQLite persistence, JSONL journals, and the event store can all represent positions or trades.
- Mode is read from more than one environment/configuration source.
- Risk and sizing are configured and enforced in multiple layers.
- Live order quantity can be discarded before reaching the broker adapter.
- Broker failures can terminate an engine and leave a reservation behind.
- Reconciliation does not consistently normalize signed short quantities or partial order states.
- WebSocket contracts are hand-maintained in multiple producers and in TypeScript.
- Frontend components re-derive trading decisions, PnL, session phases, and market structure.
- The focused EventStore suite currently has known failures; those failures are a gate, not noise.

This plan supersedes neither `2026-08-29-architecture-review-fixes.md` nor `2026-09-01-event-sourced-architecture.md`; it sequences and narrows them into executable agent lanes.

## 3. Non-Negotiable Rules

1. **No live deployment during this program.** A canary requires explicit human approval after all gates pass.
2. **One fresh failing test before every behavior fix.** Capture the current failure, then implement the minimum change.
3. **One authoritative runtime mode.** Validate it once before dependency construction; downstream code receives the immutable value.
4. **One sizing authority.** The engine/RiskGate computes quantity and lot size; adapters validate and execute the supplied values, never resize.
5. **Every submitted order is durable and state-machined.** Unknown broker outcomes require reconciliation, never blind retry.
6. **Every broker failure unwinds reservations and is non-fatal to the symbol engine.**
7. **Decision logic uses bar/tick timestamps, not wall-clock fallbacks.**
8. **`quant/` stays independent of `backend/`, FastAPI, frontend, and broker SDKs.**
9. **No new dependency unless an existing repository capability cannot meet the requirement.**
10. **Every deliberate limit, approximation, or deferred migration carries a nearby `# ponytail:` comment explaining the ceiling and upgrade condition.**
11. **Do not touch the pre-existing untracked files** `docs/superpowers/plans/2026-09-01-event-sourced-architecture.md` and `stop.sh`.
12. **Never use broad staging.** Agents stage only files they own and changed.

## 4. Team Model

Use one coordinator plus five implementation agents. Agents work in separate worktrees or isolated branches and submit small commits or patches to the coordinator. The coordinator owns integration, conflict resolution, full-suite gates, and release decisions.

| Role | Skill assignment | Responsibility | May modify |
|---|---|---|---|
| Coordinator / reviewer | `superpowers:executing-plans`, `superpowers:subagent-driven-development` | Baseline, dependency gates, integration, review, parity evidence | Tests, docs, integration glue only when explicitly assigned |
| Agent S: safety and risk | `superpowers:subagent-driven-development` + Ponytail safety discipline | Mode, risk propagation, sizing, reservation unwind, emergency halt | `quant/execution/`, selected `quant/runtime.py`, `quant/multi_engine.py`, mode/config tests |
| Agent P: persistence and reconciliation | `superpowers:subagent-driven-development` + Ponytail recovery discipline | Durable orders, event-store restart semantics, fills, signed reconciliation | `quant/event_store.py`, `quant/state_machine.py`, `quant/transitions.py`, persistence/reconciliation modules and tests |
| Agent B: broker reliability | `superpowers:subagent-driven-development` + Ponytail failure-boundary discipline | Retry semantics, idempotency, exact quantity, feed-drop observability | `brokers/`, broker adapters, broker tests |
| Agent C: contracts and backend shell | `superpowers:subagent-driven-development` + Ponytail compatibility discipline | Canonical WS producer, startup health, snapshot performance, API contract tests | `backend/app/api/`, `backend/app/main.py`, `quant/ws_contract.py`, `quant/ws_adapter.py`, backend tests |
| Agent F: frontend and parity | `superpowers:subagent-driven-development` + Ponytail UI-boundary discipline | Render-only frontend, generated/validated contract, replay/live evidence | `frontend/`, frontend tests, contract fixtures |

### Worktree policy

Recommended worktrees:

```text
../glassytrade-remediation-safety
../glassytrade-remediation-persistence
../glassytrade-remediation-broker
../glassytrade-remediation-contracts
../glassytrade-remediation-frontend
```

If the client cannot create worktrees, use branches and strict file ownership. No agent rebases or resets another agent's branch. The coordinator integrates in dependency order.

## 5. Complexity and Risk Model

Effort estimates are engineering complexity, not calendar promises.

| Rating | Meaning | Required evidence |
|---|---|---|
| S | 0.5–1 day, local behavior | Focused unit test and lint/typecheck |
| M | 1–3 days, one subsystem | Focused suite, failure-path test, integration check |
| L | 3–7 days, cross-module contract | Golden trace, restart or e2e test, full relevant suite |
| XL | 1–3 weeks, architecture migration | Design checkpoint, shadow mode, replay parity, rollback plan |

Risk is rated separately: **R1** low behavior risk, **R2** moderate, **R3** live-path/high regression risk, **R4** potentially capital-threatening.

## 6. Dependency Gates

No lane may advance past a gate until the coordinator records the evidence in the plan or an attached issue.

### Gate G0: Baseline and known failures

Coordinator records:

- `git status --short --branch` and the base commit.
- Focused EventStore failures, full quant/backend/broker/frontend test counts, and lint/typecheck status.
- Existing skipped tests and known environment limitations.
- A list of files changed by each agent; unrelated worktree changes remain untouched.

**Exit:** baseline is reproducible and all pre-existing failures are classified.

### Gate G1: Live safety

Required before any architecture migration:

- One validated runtime mode.
- Configured risk reaches every `SessionRisk` and `PortfolioRiskAuthority` instance.
- Exact engine quantity and lot size reach the broker.
- Broker rejection/timeout cannot kill the engine or leak reservations.
- Emergency halt is lock-serialized and idempotent.
- Signed short reconciliation works.
- Unsafe or ambiguous config fails closed.

**Exit:** safety regression suite passes and a paper end-to-end order trace proves reservation, submit, fill/reject, and release behavior.

### Gate G2: Durable state and restart

- Orders and fills have durable lifecycle records.
- Unknown submission outcomes are recoverable by broker status lookup.
- Event log integrity is verified on load.
- Restart folds the same position/order/risk state from durable data.
- Reconciliation compares identity, signed quantity, side, average price, and order state.

**Exit:** kill/restart simulation passes for filled, partially filled, rejected, cancelled, and unknown orders.

### Gate G3: Contract and presentation

- One backend WS producer and one canonical schema.
- Versioned envelopes and explicit delta semantics.
- Frontend consumes backend values without reimplementing trading decisions or PnL.
- Real fixtures, not phantom payloads, drive frontend tests.

**Exit:** contract tests, frontend tests, and a live/replay snapshot comparison pass.

### Gate G4: Release readiness

- `make test-ci`, `make lint`, `make test-arch`, and `make parity` pass or have explicitly approved, classified exceptions.
- No unbounded retry, market-order fallback, or unauthenticated operator route remains in the release path.
- Observability shows order lifecycle, risk decisions, reconciliation, feed drops, and engine health.
- Human signs off on paper soak and limited canary criteria.

## 7. Execution Waves

### Wave 0 — Baseline and contract freeze

**Owner:** Coordinator. **Complexity:** M. **Risk:** R1.

- [ ] Run G0 commands and record outputs.
- [ ] Capture golden traces for entry decisions, exits, order mapping, and WS snapshots.
- [ ] Identify current EventStore test failures and decide whether each is an implementation defect or stale expectation.
- [ ] Create a change ledger with owner, files, test command, and rollback point.
- [ ] Define the minimum canonical objects for this wave: mode, risk parameters, order identity, signed quantity, event envelope.

**Deliverable:** baseline report and frozen fixture set.

### Wave 1 — Parallel safety lanes

Agents S, P, and B may start in parallel after G0. Their integration order is S → P → B because persistence needs the corrected order/risk contract, while broker behavior can be implemented against explicit interfaces.

#### S1. Single validated runtime mode

**Owner:** Agent S. **Complexity:** L. **Risk:** R4.

- [ ] Add a single mode resolver with explicit precedence and conflict rejection.
- [ ] Resolve mode once in composition; inject it into scanner, reconciliation, testing routes, OMS, and emergency controls.
- [ ] Disable synthetic tick injection and unsafe testing routes in live mode.
- [ ] Add tests for every environment combination, including conflicting live/paper values.
- [ ] Add a fail-closed startup test.

#### S2. Risk configuration and portfolio ceiling

**Owner:** Agent S. **Complexity:** L. **Risk:** R4.

- [ ] Add a failing test proving configured `risk_per_trade_pct`, daily loss, consecutive-loss, trade-count, and portfolio caps reach runtime authorities.
- [ ] Replace permissive `0.95` defaults with validated config-derived values.
- [ ] Ensure `PortfolioRiskAuthority` is constructed once at coordinator scope and shared by engines.
- [ ] Make invalid or missing live risk values fail startup.
- [ ] Mark any temporary derivation with `# ponytail:` and an explicit tuning/validation condition.

#### S3. Exact quantity and non-fatal order failure

**Owner:** Agent S. **Complexity:** L. **Risk:** R4.

- [ ] Carry engine quantity and lot size through signal, OMS, mapping, and adapter.
- [ ] Delete adapter-side portfolio re-sizing; adapter only validates and translates.
- [ ] Test non-lot quantities, options, partial quantities, and zero/negative quantities.
- [ ] Wrap submit failures; emit typed failure state/event; release reservations exactly once.
- [ ] Prove a failed order does not mark the symbol engine crashed.

#### S4. Emergency close and signed reconciliation wiring

**Owner:** Agent S with Agent P review. **Complexity:** M. **Risk:** R4.

- [ ] Route emergency close through the same lock-serialized, pyramid-aware path as normal force close.
- [ ] Add idempotency tests proving repeated halt requests create at most one logical close.
- [ ] Normalize broker short quantities to signed domain quantities at the boundary.
- [ ] Test restart with long, short, flat, partial, and multiple-add-on positions.

**Wave 1 S exit:** all S tests pass and G1 safety evidence is accepted.

#### P1. EventStore correctness and durable restart authority

**Owner:** Agent P. **Complexity:** XL. **Risk:** R4.

- [ ] Fix the currently failing EventStore tests first; preserve checksum-chain and ordering invariants.
- [ ] Define whether the event log is authoritative for runtime state. If it is not yet authoritative, document the transitional read path and block claims of full event sourcing.
- [ ] Make append, load, verify, and fold semantics explicit for empty logs, corrupted records, duplicate sequence numbers, and unknown event types.
- [ ] Persist the event log or durable event records; do not treat an in-memory store as restart recovery.
- [ ] Add crash simulation at each order lifecycle boundary.
- [ ] Prove replay from a clean process produces the same state and projections.
- [ ] Keep a compatibility importer for existing JSONL/SQLite data only if required; mark it `# ponytail:` with deletion criteria.

#### P2. Durable order and fill lifecycle

**Owner:** Agent P. **Complexity:** XL. **Risk:** R4.

- [ ] Introduce durable order records and fill records using existing persistence conventions where possible.
- [ ] Enforce legal transitions: `CREATED → SUBMITTED → ACKED/PARTIAL → FILLED/CANCELLED/REJECTED`; unknown outcomes remain recoverable.
- [ ] Make fill application idempotent by broker order id plus fill id or deterministic fallback.
- [ ] Rebuild positions and reservations from durable order/fill events on restart.
- [ ] Test partial fills followed by cancellation, late fills, duplicate updates, and broker status lookup.

#### B1. Broker retry and idempotency safety

**Owner:** Agent B. **Complexity:** M. **Risk:** R4.

- [ ] Add a failing test showing a network failure after broker-side acceptance causes no automatic order POST retry.
- [ ] Make retry policy HTTP-method-aware and surface an `OrderStateUnknown` result for non-idempotent ambiguity.
- [ ] Add stable idempotency keys to entry, close, fallback-close, and retry paths.
- [ ] Derive keys from logical order/position identity, not wall-clock or a new UUID per retry.
- [ ] Remove dead retry configuration or wire it to the tested policy.

#### B2. Feed and adapter observability

**Owner:** Agent B. **Complexity:** M. **Risk:** R3.

- [ ] Count dropped WebSocket messages monotonically.
- [ ] Log first and periodic drops without logging every packet.
- [ ] Expose feed-drop health data to the backend health surface.
- [ ] Add adapter conformance tests for exact quantity, order status mapping, rejection, timeout, and unknown state.
- [ ] Confirm there is only one broker/rate-limiter instance per runtime.

**Wave 1 integration:** coordinator merges S, then P, then B; runs G1 and G2 together. Any mismatch between event-derived state and SQLite state blocks the next wave.

### Wave 2 — Backend shell and wire contracts

Agents C and F start after G1. C lands the backend producer and schema boundary before F removes frontend fallbacks.

#### C1. Startup health and lifecycle truth

**Owner:** Agent C. **Complexity:** M. **Risk:** R3.

- [ ] Replace unconditional `"ok"` checks for strategy runtime and close contract with real probes.
- [ ] Ensure readiness is degraded when coordinator startup fails or close capability is absent.
- [ ] Make startup reconciliation failure visible and fail closed in live mode.
- [ ] Add health tests for missing, failed, stale, and partially initialized components.

#### C2. Canonical versioned WS contract

**Owner:** Agent C. **Complexity:** L. **Risk:** R3.

- [ ] Select one canonical producer, making `view_state_to_ws` construct the validated envelope.
- [ ] Define explicit versioned snapshot/event envelopes and delta semantics.
- [ ] Validate in test/development send paths and fail loudly on schema drift.
- [ ] Remove post-serialization mutation and ad-hoc duplicate envelope producers.
- [ ] Add contract fixtures for full AMT, depth objects, orders, positions, risk, and replay snapshots.
- [ ] Keep code generation as a separate task if introducing it would delay safety; mark manual compatibility as `# ponytail:`.

#### C3. Event-loop and snapshot performance

**Owner:** Agent C. **Complexity:** M. **Risk:** R2.

- [ ] Move CPU-bound snapshot/delta work off the asyncio event loop.
- [ ] Add a bounded benchmark for multiple symbols and repeated cycles.
- [ ] Diff nested high-volume structures at useful granularity.
- [ ] Preserve message ordering and backpressure behavior.

#### F1. Render-only frontend boundary

**Owner:** Agent F. **Complexity:** XL. **Risk:** R3.

- [ ] Inventory all frontend-derived verdicts, gates, PnL, R-multiple, session phases, breakout/retest zones, and client prices.
- [ ] Replace each with backend fields or remove it when no longer required by the product.
- [ ] Use canonical backend LTP and session overlays, including MCX-specific phases.
- [ ] Maintain one WS-driven store and remove duplicate candle caches.
- [ ] Fix unstable memoization and the chart comparator's implicit tick-bus coupling with regression tests.
- [ ] Keep UI formatting logic, but ban trading decisions and financial calculations from presentation code.

#### F2. Contract typing

**Owner:** Agent F with C review. **Complexity:** L. **Risk:** R3.

- [ ] Consume the canonical backend contract in TypeScript.
- [ ] Generate types if the existing toolchain supports it without a new dependency; otherwise add a checked fixture/type assertion and ledger codegen as the next task.
- [ ] Delete phantom fields and dead event handlers only after fixture coverage proves they are unused.
- [ ] Add compile-time and runtime tests for full and delta messages.

**Wave 2 exit:** G3 passes, including a real backend fixture rendered by the frontend and no client-side decision/PnL drift in the audited surfaces.

### Wave 3 — Convergence and decomposition

This wave is intentionally sequential. It has high technical depth but lower immediate money risk because behavior must already be protected by G1–G3.

#### D1. Canonical domain model migration

**Owner:** Coordinator with a dedicated follow-up agent. **Complexity:** XL. **Risk:** R3.

- [ ] Choose canonical `Bar`, `Tick`, `Signal`, `Order`, `Fill`, `Position`, `Trade`, `RiskParams`, and session types.
- [ ] Add explicit anti-corruption mappings at broker and presentation boundaries.
- [ ] Remove duplicate models one cluster at a time: order/position/signal, then candle/tick, then VWAP/session/time.
- [ ] Keep Decimal at money boundaries and convert only at explicitly tested transport edges.
- [ ] Use import checks to enforce inward dependency direction.
- [ ] Preserve golden traces after each cluster.

#### D2. Break import cycles and enforce boundaries

**Owner:** Coordinator. **Complexity:** M. **Risk:** R2.

- [ ] Remove `contracts → execution → decision → contracts` imports.
- [ ] Replace cross-layer concrete imports with domain types, protocols, or boundary mappers.
- [ ] Add an import-linter or equivalent test using existing repository tooling.
- [ ] Verify `quant` remains importable without backend initialization.

#### D3. Decompose coordinator and engine

**Owner:** Coordinator plus one sequential agent. **Complexity:** XL. **Risk:** R3.

- [ ] Extract lifecycle, scanner, EOD, health, and reconciliation responsibilities from `QuantCoordinator`.
- [ ] Keep `QuantEngine` as a small event-loop orchestrator; extract decision, exit, event-sourcing, and session lifecycle services only where existing seams already exist.
- [ ] Do not change strategy thresholds during decomposition.
- [ ] Require golden replay equality after each extraction.

#### D4. Delete dead paths

**Owner:** Coordinator during touched-file cleanup. **Complexity:** M. **Risk:** R2.

- [ ] Remove dead `exit_rules.py` portions, unused constants, unused signal sizing, orphaned events, dead strategy seam, stale AI value objects, and phantom frontend surfaces.
- [ ] Retire or wire `TradeJournal` and `PaperBrokerAdapter`; do not leave parallel persistence/execution paths undocumented.
- [ ] Delete only after repository-wide references and tests prove absence.

### Wave 4 — Replay parity, observability, and release

#### O1. Tick-grade journal and live/replay parity

**Owner:** Agent P with F and C support. **Complexity:** XL. **Risk:** R3.

- [ ] Journal raw ticks, depth, bars, decisions, orders, fills, and relevant configuration version.
- [ ] Replay through the same engine and injected clock.
- [ ] Compare recorded live decisions and order intents, not only two fresh replay engines.
- [ ] Report the first divergent event with symbol, timestamp, sequence, input hash, and state hash.
- [ ] Include final forming-bar and zero-volume edge cases explicitly.

#### O2. Operational metrics and alerting

**Owner:** Agent B/C. **Complexity:** L. **Risk:** R2.

- [ ] Emit metrics for order latency, unknown broker state, rejection rate, reservation leakage, reconciliation mismatches, engine crashes, stale feeds, and dropped packets.
- [ ] Make alert dispatch asynchronous and awaited by its owning task; prevent exceptions from disappearing in fire-and-forget callbacks.
- [ ] Add operator-facing health details without exposing secrets.

#### O3. Paper soak and limited canary gate

**Owner:** Coordinator and human operator. **Complexity:** L. **Risk:** R4.

- [ ] Run a multi-session paper soak with the same strategy and risk configuration intended for live.
- [ ] Compare paper event/fill behavior with broker adapter conformance results.
- [ ] Rehearse startup, SIGTERM, network loss, broker timeout, partial fill, and restart.
- [ ] Obtain explicit human approval before any live canary; use a documented position-size ceiling and immediate abort criteria.

## 8. Agent Task Protocol

Every implementation task follows this sequence:

1. Read the current code and identify all callers.
2. Write a minimal failing test for the concrete defect.
3. Run only that test and record the failure.
4. Implement the smallest coherent fix.
5. Add or update `# ponytail:` only when preserving a known limitation or deliberate ceiling.
6. Run focused tests, then the lane suite.
7. Check imports, diff size, and owned-file boundaries.
8. Report changed files, tests, residual risks, and rollback commit to the coordinator.

A task that exceeds its estimate by more than one complexity level pauses for a design checkpoint. Do not hide a migration behind a compatibility layer without documenting its authority and deletion condition.

## 9. Required Test Matrix

| Area | Minimum gate |
|---|---|
| Event store | focused EventStore suite, corruption/ordering/restart tests |
| Risk and OMS | `tests/quant/execution`, rejection/timeout/reservation tests, exact quantity tests |
| Reconciliation | long/short/partial/duplicate/unknown order cases |
| Broker | `brokers` suite, no retry after accepted POST, idempotency conformance |
| Backend | `backend/tests`, startup health, WS delta, event-loop benchmark |
| Frontend | `cd frontend && npm test`, typecheck, real contract fixtures |
| Architecture | `make test-arch`, import boundary checks |
| Certification | `make parity`, replay-x2 and recorded live-vs-replay parity |
| Full CI | `make test-ci && make lint` |

A green test result does not waive a known skipped test. Each skip must have an owner, reason, and removal condition recorded by the coordinator.

## 10. Rollback and Stop Criteria

Stop integration immediately if any of the following occurs:

- A live-mode configuration can construct a paper/live mixed graph.
- Quantity at the broker differs from the RiskGate quantity.
- An order can be submitted without a durable logical id.
- An unknown broker outcome triggers a blind retry.
- Restart produces a different signed position or risk reservation.
- Emergency halt can issue duplicate logical closes.
- A reconciliation mismatch is silently ignored.
- Replay diverges without a first-divergence diagnostic.
- Any agent modifies files outside its ownership without coordinator approval.

Rollback to the last gate-passing commit, preserving failing tests and diagnostic artifacts. Never reset or discard unrelated user changes.

## 11. Definition Of Done

The program is complete only when:

- G1–G4 have recorded evidence.
- The event log or a clearly documented durable state authority owns restart reconstruction.
- One mode, one risk configuration, one sizing path, one signed position model, and one order lifecycle are active in production composition.
- Paper/live adapters differ only at explicit ports.
- Broker failures are recoverable and observable.
- WS schema is versioned and tested; frontend is a projection.
- Replay uses the same engine and proves parity against recorded live decisions on tick-grade data.
- Full CI and certification commands pass, with no unowned exceptions.
- A human has approved the paper soak and any subsequent live canary.

## 12. Recommended Immediate Sequence

1. Coordinator completes Wave 0 baseline.
2. Agents S, P, and B implement failing tests in parallel.
3. Integrate S and establish G1 before enabling persistence migration.
4. Integrate P and establish G2; broker unknown-state behavior is required for both.
5. Integrate B and rerun the combined money-path suite.
6. Agents C and F execute Wave 2 after the durable order/state contracts are stable.
7. Defer model deletion and god-class decomposition until replay/golden traces are green.
8. Run Wave 4 parity and paper soak before any live canary.
