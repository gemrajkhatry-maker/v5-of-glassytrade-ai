# Pre-Deployment Refactor Execution Plan

**Branch:** `refactor/predeploy-system-hardening`

**Purpose:** coordinate a parallel, dependency-aware refactoring program that removes dead paths, consolidates duplicated ownership, hardens the real-money execution boundary, and proves the system safe enough for staged live-shadow validation.

**Status:** execution started. P0, the broker quantity-authority lane, and the verified-zero-caller AMT deletion lane are complete. No commit, push, deployment, or production-order change is authorized by this document.

## Execution handoff — current branch

Completed on this branch:

```text
P0 baseline: 81 characterization tests passed (one intentional crash-thread warning)
Broker quantity lane: 60 focused tests passed
Combined safety/regression lane: 141 tests passed
Verified dead-code lane: 677 AMT/runtime/state tests passed, 2 pre-existing skips
Zero production references remain for deleted one-minute/RL observation paths
```

Production changes completed:

```text
backend/app/infrastructure/adapters/dhan_broker_adapter.py
  removed portfolio-based fallback sizing
  requires finite positive integer metadata["order_quantity"]
  rejects before broker.place_order when quantity is absent/invalid

quant/amt/analyzer.py
  removed unused RL observation builder and import

Deleted:
  quant/amt/session/one_min_bar.py
  quant/amt/models/observation.py
  quant/amt/models/__init__.py
  tests/quant/amt/session/test_one_min_bar.py
```

Integration gate completed before the next shared-file lane:

```text
Full quant suite: 1722 passed, 11 pre-existing skips, 1 intentional crash-thread warning
Backend infrastructure suite: 149 passed, 1 pre-existing skip
Frontend suite: 273 passed across 29 files
Frontend production build: passed (Vite chunk-size warning only)
```

The deleted AMT/RL path and broker quantity-authority change are behaviorally green. The intentional lifecycle thread warning and frontend React/canvas warnings remain pre-existing test-environment findings.

B1 configuration/risk lane completed:

```text
backend/tests/unit/test_live_risk_precedence.py and config architecture suites: 24 passed
backend/tests/unit: 681 passed, 18 skipped, 1 dependency deprecation warning
live loader now rejects missing mandatory risk fields
live.yaml explicitly declares absolute_ceiling_pct
validator rejects non-finite/non-positive risk values and invalid live cap relationships
```

B2 order identity/price/quantity completed as a narrow boundary hardening slice:

```text
Engine Signal now owns one stable signal_id for its lifecycle
broker_mapper preserves signal_id and records engine_signal_id metadata
LiveOMS rejects non-numeric, non-finite, and non-positive quantities before broker execution
mapper/OMS regression: 66 passed
backend Dhan adapter regression remains green
```

B2 remainder completed:

Durable signal identity (restart-safe):

```text
signal_id is now DERIVED from decision content via uuid5
(quant/contracts/entities.derive_signal_id; applied in both Signal
dataclasses through __post_init__ — explicit signal_id= still wins).
Replaying the same approved decision after a crash re-derives the SAME
id, so broker-side correlationId dedup survives process restarts.
compare=False retained — replay determinism parity stays exact.
New suite: tests/quant/execution/test_signal_identity.py (9 tests:
stability across reconstruction, content sensitivity, explicit-id
precedence, mapper preservation).
```

Payload boundary suite (backend/tests/unit/infrastructure/test_dhan_payload_boundary.py):

```text
Adapter decision -> DhanConverter.from_order_request for every emitted
order type: default collared LIMIT entry (price present, no trigger,
correlationId == signal_id), explicit MARKET (no price field), SL
(triggerPrice + price), SLM (triggerPrice only), collared close LIMIT,
naked close MARKET, no-reference-price close MARKET; correlationId
capped at 36 chars in all cases.
Cross-checked against DhanHQ v2 docs: payload orderType correctly uses
the v2 vocabulary STOP_LOSS / STOP_LOSS_MARKET (SL / SLM were v1).
```

Reservation lifecycle: verified already covered
(test_audit_regressions.test_entry_oms_failure_unwinds_risk_and_keeps_engine_alive,
test_portfolio_risk_guard fractional release, tick-partial adoption) —
no gap found; LiveOMS.submit raises on broker rejection so the engine
unwind path is exercised.

Regression evidence:

```text
Full quant suite: 1742 passed, 11 pre-existing skips
Backend unit suite: 688 passed, 18 skipped
mapper/OMS/adapter/payload/identity combined: 227 passed
```

B2 is now COMPLETE. Runtime, ledger, and trace files remain protected.

B7 passive hot-path observability completed (uncommitted on this branch):

```text
quant/hotpath.py: HotPathSubscriber bus subscriber (priority +200) maps
  BarClosed/DecisionProduced/PositionOpened/PositionClosed/PositionReduced
  onto trace phases and records the event correlation_id per record; emit
  is guarded (JSONL failure cannot stop trading), try_emit for non-bus call
  sites; ring overflow counted and exposed via tracer.dropped
quant/runtime.py: engine subscribes the subscriber in __init__ and no longer
  owns the phase field-extraction mapping (_hotpath_event deleted); tick
  call sites route through try_emit
quant/multi_engine.py: snapshot call-site routes through try_emit
tests/quant/test_hotpath_trace.py: 8 tests — original 4 plus trace-on==trace-
off event parity (deletion gate), correlation-id presence, ring-overflow
  visibility, and trace-failure engine isolation
```

Verified under heavy machine load (load avg >100): hot-path suite 8 passed;
test_events 4 passed; broker mapper/live OMS/positive-approval 31 passed;
full determinism suite 4 passed. Remaining before B7 deletion gate closes:
repeat the broader runtime/golden regressions when the machine is idle.

B7 deletion gate closed on idle machine (full quant suite: 1730 passed, 2 failed):

The 2 failures were tests/quant/test_fast_determinism_parity.py — B2's
signal_id (fresh uuid4 per Signal construction, default equality) leaked
volatile identity into event equality, breaking the suite's documented
"identity-free equality" contract. Fixed by marking signal_id compare=False
on both Signal dataclasses (quant/contracts/entities.py,
quant/decision/signal_builder.py), matching the established
Event.correlation_id / Order._id identity pattern. All real consumers
(mapper preservation, broker dedup) compare the string directly and are
unaffected. Re-verified: parity+mapper/OMS 31 passed; determinism, golden
replay, hot-path trace, Dhan adapter 54 passed. B2 durable uuid5 identity
across restart remains open (live dedup semantics change — do not bundle).

## Working-tree protection

The branch was created from the current checkout with these existing uncommitted hot-path trace changes preserved:

```text
quant/runtime.py
quant/multi_engine.py
quant/hotpath.py
tests/quant/test_hotpath_trace.py
```

These files are protected baseline work. Agents must not overwrite, reset, stash, or broadly reformat them. Any agent needing one of these files must declare an explicit integration handoff and provide a narrow patch.

## Operating rules for the agent team

Each agent works from a child branch or isolated worktree based on this branch. Agents may edit only their owned files. They must not stage or commit another agent's files. A lane is mergeable only when its acceptance tests pass and its output contract is written in the lane handoff.

The integration agent merges child branches in dependency order. If two lanes need the same file, the file has one owner; other lanes submit a patch request or an interface change, not direct edits. Deletions happen only at deletion gates. No compatibility shim is retained without a named active caller and a deletion date.

Every lane handoff contains:

```text
scope completed
files changed
files intentionally untouched
new or changed invariants
tests run and exact results
remaining risks
next lane dependency
```

No lane may declare success because the unit tests pass if the production caller graph still contains a duplicate or an unhandled failure path.

# Dependency graph

```text
                         ┌──────────────────────────┐
                         │ P0 BASELINE / FREEZE     │
                         │ characterization + graph│
                         └─────────────┬────────────┘
                                       │
       ┌───────────────────┬───────────┼────────────┬───────────────────┐
       │                   │           │            │                   │
       ▼                   ▼           ▼            ▼                   ▼
┌────────────┐     ┌────────────┐ ┌───────────┐ ┌────────────┐ ┌────────────┐
│A MONEY     │     │A LEDGER   │ │A DOMAIN   │ │A STATE     │ │A FRONTEND  │
│boundary    │     │failure    │ │contracts  │ │runtime     │ │authority   │
│audit       │     │audit      │ │audit      │ │audit       │ │audit       │
└─────┬──────┘     └─────┬──────┘ └─────┬─────┘ └─────┬──────┘ └─────┬──────┘
      │                  │             │             │                │
      └──────────┬───────┴──────┬──────┴──────┬──────┴────────────────┘
                 ▼              ▼             ▼
          ┌────────────┐ ┌────────────┐ ┌──────────────┐
          │P1 MONEY    │ │P2 ORDER    │ │P3 CONTRACT   │
          │config +    │ │LEDGER +    │ │OWNERSHIP +   │
          │quantity    │ │idempotency │ │session model │
          └─────┬──────┘ └─────┬──────┘ └──────┬───────┘
                │              │               │
                └──────┬───────┴───────┬───────┘
                       ▼               ▼
                ┌────────────┐  ┌──────────────┐
                │G1 MONEY    │  │P4 STATE      │
                │SAFETY GATE │  │PROJECTION    │
                └─────┬──────┘  └──────┬───────┘
                      │                │
                      ▼                ▼
               ┌────────────┐  ┌──────────────┐
               │P5 EXECUTION│  │P6 WS/BACKEND │
               │CONSOLIDATE │  │CONTRACT      │
               └─────┬──────┘  └──────┬───────┘
                     └─────────┬──────┘
                               ▼
                        ┌──────────────┐
                        │P7 DELETE     │
                        │dead/duplicate│
                        │paths         │
                        └──────┬───────┘
                               ▼
                        ┌──────────────┐
                        │G2 FULL TEST  │
                        │AND DELETION  │
                        │GATE          │
                        └──────┬───────┘
                               ▼
                        ┌──────────────┐
                        │P8 LIVE SHADOW│
                        └──────┬───────┘
                               ▼
                        ┌──────────────┐
                        │P9 ONE-LOT    │
                        │CANARY        │
                        └──────────────┘
```

# File ownership map

The following files have exclusive owners during the program.

| Owner lane | Exclusive files |
|---|---|
| Integration/Gatekeeper | `quant/runtime.py`, `quant/multi_engine.py`, `quant/events.py`, `quant/event_store.py`, `quant/state.py`, `quant/transitions.py`, `quant/state_machine.py` |
| Money boundary | `quant/execution/risk.py`, `quant/execution/lots.py`, `quant/execution/order.py`, `quant/execution/broker_mapper.py`, `quant/execution/oms.py`, `quant/execution/live_oms.py`, `quant/execution/portfolio_risk.py`, `quant/execution/trade_costs.py` |
| Broker/order ledger | `backend/app/infrastructure/adapters/dhan_broker_adapter.py`, `backend/app/infrastructure/adapters/dhan_order_feed.py`, `backend/app/infrastructure/storage/database.py`, broker order-service files |
| Config | `backend/app/config.py`, `backend/app/config_models/*`, `backend/app/application/di/*`, `config/*` |
| AMT/domain contracts | `quant/bars.py`, `quant/aggregator.py`, `quant/amt_engine.py`, `quant/contracts/*`, `quant/amt/*` |
| Decision | `quant/decision/*`, `quant/strategies/*` |
| Backend transport | `backend/app/api/websocket/gameloop.py`, `backend/app/infrastructure/serialization/schemas.py`, `quant/ws_adapter.py`, `quant/ws_contract.py` |
| Frontend | `frontend/types.ts`, `frontend/hooks/useServerTradingSystem.ts`, `frontend/components/*`, `frontend/utils/*`, `frontend/stores/*` |
| Observability | `quant/hotpath.py`, `backend/app/core/*`, `backend/app/domain/ops/*`, `backend/app/api/routers/health.py` |
| Tests | Each lane owns tests corresponding to its production files; integration tests are owned by Integration/Gatekeeper. |

No two agents edit an exclusive file concurrently.

# P0 — Baseline, freeze, and active graph

**Execution:** sequential. Nothing else starts until P0 is complete.

## P0.1 Feature freeze

**Owner:** Integration/Gatekeeper

**Inspect:**

```text
frontend/components/chart/HARSIManager.ts
frontend/components/ChartScene.tsx
quant/amt/market/half_trend.py
quant/decision/*
```

**Output:** classify every current feature as `decision-critical`, `risk-critical`, `transport-critical`, or `display-only`.

**Acceptance criteria:**

```text
no unclassified feature remains
HARSI has an explicit display-only or quant-owned decision status
HalfTrend has one decision owner
```

## P0.2 Behavioral baseline

**Owner:** Integration/Gatekeeper

**Run:**

```text
.venv/bin/python -m pytest tests/quant/test_golden_replay.py tests/quant/test_determinism.py tests/quant/runtime/test_positive_approval.py tests/quant/runtime/test_events.py tests/quant/test_state_machine.py tests/quant/test_transitions.py tests/quant/test_ws_contract_parity.py tests/quant/test_reconciliation_service_matrix.py tests/quant/test_double_close_guard.py tests/quant/test_lifecycle_races.py tests/quant/test_emergency_halt.py tests/quant/test_eod_square_off.py -q
```

Also run the frontend test/build commands from `frontend/package.json` using the repository's existing package manager.

**Record:**

```text
pass/fail result
known failures
approved decision count
position open/close count
partial-fill count
WS snapshot digest
trace-off event digest
```

**Acceptance criteria:** baseline results are stored in the handoff and failures are classified as pre-existing, introduced, or environment-only.

## P0.3 Active module and import graph

**Owner:** Architecture/Graph agent

**Inspect:** `quant/`, `backend/app/`, `brokers/`, `shared/`, and `frontend/` source files only.

**Output:** active, conditional, and zero-caller inventories. Include DI construction, dynamic imports, serialization readers, and production entry points.

**Known candidates to verify:**

```text
quant/amt/session/one_min_bar.py
quant/amt/models/observation.py
quant/execution/exit_rules.py
quant/strategy.py
backend/app/application/services/trade_journal.py
backend/app/infrastructure/adapters/paper_broker.py
frontend/components/ProfileOverlayInfo.tsx
```

**Acceptance criteria:** no deletion candidate is marked dead using filename search alone.

# Parallel Audit Wave A

After P0, these audits run in parallel. They produce evidence and interface requirements; they do not delete production code.

## A1 — Money boundary audit

**Owner:** Money agent

**Inspect:**

```text
quant/decision/signal_builder.py
quant/execution/risk.py
quant/execution/lots.py
quant/execution/order.py
quant/execution/broker_mapper.py
quant/execution/oms.py
quant/execution/live_oms.py
quant/execution/portfolio_risk.py
backend/app/infrastructure/adapters/dhan_broker_adapter.py
```

**Trace:**

```text
Signal
→ quantity
→ lot snap
→ reservation
→ Order
→ broker mapper
→ Dhan payload
→ acknowledgement
→ fill
```

**Output:** exact transformation table for quantity, price, side, signal id, client order id, and broker order id.

**Acceptance criteria:** every transformation has one owner and one failure behavior.

## A2 — Ledger and failure audit

**Owner:** Ledger agent

**Inspect:**

```text
quant/events.py
quant/event_store.py
quant/persistence.py
quant/persistence_bridge.py
backend/app/infrastructure/storage/database.py
backend/app/infrastructure/adapters/dhan_order_feed.py
quant/reconciliation_service.py
backend/app/domain/ops/startup_reconciliation.py
```

**Output:** order/fill/position lifecycle matrix, including timeout, rejection, partial fill, duplicate update, restart, and reconciliation.

**Acceptance criteria:** every state transition has a durable location and an observable failure signal.

## A3 — Domain and contract audit

**Owner:** Domain agent

**Inspect:**

```text
quant/bars.py
quant/contracts/value_objects.py
quant/contracts/entities.py
quant/contracts/aggregates.py
quant/decision/signal_builder.py
quant/execution/order.py
shared/entities/models.py
brokers/broker/dhan/domain/*
```

**Output:** canonical ownership matrix for Tick, Bar, Signal, Order, Fill, Position, Trade, money, time, session, instrument, and PnL.

**Acceptance criteria:** every duplicate is classified as `canonical`, `boundary DTO`, `legacy`, or `unknown`; unknown cannot proceed to deletion.

## A4 — State and coordinator audit

**Owner:** State agent

**Inspect:**

```text
quant/runtime.py
quant/multi_engine.py
quant/state.py
quant/state_machine.py
quant/transitions.py
quant/event_store.py
quant/coordinator_view.py
quant/ws_adapter.py
```

**Output:** mutation graph showing all writes to position, risk, portfolio, engine state, event store, live quote cache, and coordinator snapshots.

**Acceptance criteria:** every mutable field has one owner and every snapshot has a consistency boundary.

## A5 — Frontend authority audit

**Owner:** Frontend agent

**Inspect:**

```text
frontend/components/ChartScene.tsx
frontend/components/AIAnalysisPanel.tsx
frontend/components/ai/*
frontend/hooks/useServerTradingSystem.ts
frontend/utils/*
frontend/types.ts
```

**Output:** list of frontend calculations that affect display versus trading interpretation.

**Acceptance criteria:** every frontend-derived value is classified as visual-only or server-authoritative.

## A6 — Observability and trace audit

**Owner:** Observability agent

**Inspect:**

```text
quant/hotpath.py
quant/runtime.py
quant/multi_engine.py
quant/events.py
backend/app/core/*
backend/app/domain/ops/*
backend/app/api/routers/health.py
```

**Output:** required trace phases, correlation identifiers, health signals, sink behavior, and thread-affinity rules.

**Acceptance criteria:** trace can be made passive without losing tick ingress, gate, fill, or WS egress evidence.

# Gate G0 — Audit convergence

**Owner:** Integration/Gatekeeper

G0 is passed only when all A-lane handoffs agree on:

```text
active production path
canonical owner of each safety-critical concept
delete candidates
required interface changes
file conflicts
required tests
```

If two agents disagree about whether a module is active, the module remains and the disagreement becomes a blocking investigation task.

# Parallel Implementation Wave B

Wave B starts only after G0. The lanes below can work in parallel because their file ownership is separated.

## B1 — Configuration and risk wiring

**Depends on:** A1, A3.

**Owner:** Config agent

**Files:**

```text
backend/app/config_models/loader.py
backend/app/config_models/validator.py
backend/app/config_models/settings_adapter.py
backend/app/application/di/composition_root.py
backend/app/application/di/container.py
backend/app/config.py
config/base.yaml
config/environments/live.yaml
config/strategies/*.yaml
```

**Work:** make `SystemConfig` the only source for risk, capital, lot/tick policy, session, and order settings. Pass effective values explicitly to the engine.

**Acceptance criteria:**

```text
live.yaml risk_per_trade_pct reaches SessionRisk
missing safety config blocks boot
invalid ranges block boot
boot output exposes effective non-secret risk configuration
```

**Tests:** `tests/quant/test_risk_config_propagation.py`, `tests/quant/test_risk_engine_wiring.py`, new live-composition boot test.

**Deletion gate:** remove safety-sensitive runtime defaults only after the boot test passes in paper and live configuration modes.

## B2 — Quantity, price, and order identity

**Depends on:** A1.

**Owner:** Money agent

**Files:**

```text
quant/execution/risk.py
quant/execution/lots.py
quant/execution/order.py
quant/execution/broker_mapper.py
quant/execution/live_oms.py
quant/execution/oms.py
quant/execution/portfolio_risk.py
backend/app/infrastructure/adapters/dhan_broker_adapter.py
```

**Work:**

```text
finalize quantity once
validate lot alignment once
preserve quantity through mapper
create deterministic client_order_id
separate structural, execution, and broker price
reserve and release risk explicitly
```

**Acceptance criteria:**

```text
engine quantity == broker payload quantity
engine lot size == broker lot validation
retry reuses client order id
broker adapter never re-sizes
zero-size orders never reach OMS
```

**Tests:** new order-boundary property suite, OMS conformance suite, timeout/retry tests, lot-size tests, price-policy tests.

**Deletion gate:** delete `SignalBuilder.size()` and `_resolve_quantity()` only after the property suite and all broker adapter tests pass.

## B3 — Durable order and fill ledger

**Depends on:** A2, B2.

**Owner:** Ledger agent

**Files:**

```text
quant/execution/order.py
quant/events.py
quant/event_store.py
quant/persistence.py
quant/persistence_bridge.py
backend/app/infrastructure/storage/database.py
backend/app/infrastructure/adapters/dhan_order_feed.py
backend/app/infrastructure/serialization/schemas.py
```

**Work:** add durable order intent, state transitions, broker identifiers, cumulative fills, and restart restoration.

**Acceptance criteria:**

```text
intent persists before broker submit
UNKNOWN is durable after ambiguous response
partial fills are cumulative and idempotent
position quantity derives from fills
restart restores long and short positions
```

**Tests:** crash-window tests, partial-fill tests, duplicate-update tests, restart tests, database failure tests.

**Deletion gate:** no direct in-memory-only live order path remains.

## B4 — Session and instrument ownership

**Depends on:** A3.

**Owner:** Domain agent

**Files:**

```text
quant/amt/session/context.py
quant/session_gates.py
quant/contracts/timezones.py
quant/contracts/market_calendar.py
quant/contracts/exchange_config.py
quant/contracts/instrument_registry.py
quant/amt/session/symbol_registry.py
quant/amt/session/futures_provider.py
quant/amt/session/selector.py
frontend/utils/profileInfo.ts
frontend/components/ChartScene.tsx
```

**Work:** consolidate session and instrument metadata. Make underlying analysis symbol and option execution symbol explicit.

**Acceptance criteria:**

```text
NSE and MCX use correct independent schedules
all backend session gates use one SessionInfo
lot/tick values come from one registry
frontend contains no session authority
unknown instruments fail closed
```

**Deletion gate:** remove frontend exchange-hour constants and duplicate MCX symbol sets only after cross-exchange tests pass.

## B5 — Event-derived state and snapshot consistency

**Depends on:** A4, B3.

**Owner:** State agent

**Files:**

```text
quant/state_machine.py
quant/transitions.py
quant/event_store.py
quant/state.py
quant/runtime.py
quant/multi_engine.py
quant/coordinator_view.py
quant/ws_adapter.py
```

**Work:** remove coordinator reach-through, make state fold authoritative, expose explicit read models, add state/quote sequence metadata, and convert fold failures into degraded health.

**Acceptance criteria:**

```text
fold(events) == live EngineState
coordinator does not access engine private risk/position/OMS state
snapshot identifies state and quote sequence
fold failure blocks new entries and is visible
```

**Deletion gate:** remove direct private-field reads and fallback-to-normal-state behavior only after state-fold and degraded-snapshot tests pass.

## B6 — Contract-driven backend/frontend boundary

**Depends on:** A5, B4, B5.

**Owner:** Transport agent

**Files:**

```text
quant/ws_contract.py
quant/ws_adapter.py
backend/app/infrastructure/serialization/schemas.py
backend/app/api/websocket/gameloop.py
frontend/types.ts
frontend/hooks/useServerTradingSystem.ts
frontend/components/ChartScene.tsx
```

**Work:** make one canonical WS contract, generate or mechanically validate frontend types, and validate delta base sequences.

**Acceptance criteria:**

```text
field names and nullability match
full and delta snapshots have explicit versions
unknown fields are intentional
missing required fields fail decoding
frontend cannot display a normal state from a degraded snapshot
```

**Deletion gate:** remove phantom fields and compatibility types only after frontend tests use the canonical contract.

## B7 — Passive hot-path observability

**Depends on:** A6, B5.

**Owner:** Observability agent

**Files:**

```text
quant/hotpath.py
quant/runtime.py
quant/multi_engine.py
quant/events.py
backend/app/api/websocket/gameloop.py
backend/app/core/metrics.py
backend/app/domain/ops/*
backend/app/api/routers/health.py
```

**Work:** move event tracing to an EventBus subscriber, tick tracing to an observer, snapshot tracing to WS egress, and writes to an off-thread sink.

**Acceptance criteria:**

```text
runtime does not contain trace implementation logic
trace records decision/order/fill correlation ids
trace writer failure does not stop trading
ring overflow is visible
trace is bounded per symbol
```

**Deletion gate:** remove current inline trace hooks only after passive-subscriber tests and trace-on/off parity tests pass.

# Gate G1 — Money safety gate

G1 is mandatory before execution consolidation or live-shadow work.

Required passing tests:

```text
engine quantity == broker payload quantity
lot multiple validation
risk config propagation
idempotent retry
ambiguous submit handling
partial fill handling
duplicate fill idempotency
reservation release
broker rejection does not kill engine
normal close and emergency close race
long and short restart restoration
```

Required evidence:

```text
one captured order intent
one submitted order
one acknowledged order
one partial fill
one completed fill
one rejected order
one UNKNOWN order reconciled
```

If G1 fails, all work after G1 is paused except documentation and test preparation.

# Wave C — Sequential execution consolidation

These tasks are sequential because they change shared runtime semantics.

## C1 — Consolidate OMS contract

**Depends on:** G1, B3.

Merge PaperOMS and LiveOMS behind one lifecycle contract. Paper and live may differ in fill source, never in order state semantics.

**Files:**

```text
quant/execution/ports.py
quant/execution/oms.py
quant/execution/live_oms.py
backend/app/infrastructure/adapters/paper_broker.py
backend/app/application/di/composition_root.py
```

**Deletion gate:** delete `PaperBrokerAdapter` only after paper boot and full OMS contract tests prove it has no active caller.

## C2 — Consolidate exit implementation

**Depends on:** C1.

Move used functions from `quant/execution/exit_rules.py` into the active `ExitEngine`, remove the import from `quant/contracts/entities.py`, then delete the legacy module.

**Files:**

```text
quant/execution/exits.py
quant/execution/exit_checks.py
quant/execution/exit_signal.py
quant/execution/exit_rules.py
quant/position_manager.py
quant/contracts/entities.py
```

**Deletion gate:** repository call graph clean; exit golden, EOD, emergency halt, thesis-flip, pyramid, and partial-close tests pass.

## C3 — One close coordinator

**Depends on:** C2, B3, B5.

Route normal exit, partial target, EOD, SIGTERM, emergency halt, and thesis flip through one idempotent close operation.

**Deletion gate:** no direct `_oms.close()` remains outside the close coordinator.

## C4 — Canonical type migration

**Depends on:** B3, B4, C1.

Migrate in order:

```text
Tick/Bar → SignalIntent → Order/Fill → Position → Trade/Portfolio
```

Do not delete old types until each production caller is migrated.

**Deletion gate:** replay digest, broker adapter tests, restart tests, and WS serialization tests remain unchanged.

# Wave D — Authority removal and dead-code deletion

## D1 — Remove frontend trading logic

**Depends on:** B6, C4.

Delete or replace:

```text
frontend/utils/threeA.ts verdict behavior
client-side PnL authority
client midpoint LTP
ChartScene session clock
duplicate IB breakout/retest detection
local risk-state decisions
```

Retain only visual transformation helpers.

**Deletion gate:** frontend tests prove components render server values and contain no trading verdict calculations.

## D2 — Remove verified dead AMT modules

**Depends on:** P0.3, C4.

Delete:

```text
quant/amt/session/one_min_bar.py
quant/amt/models/observation.py
AMTAnalyzer.compute_observation()
```

**Deletion gate:** zero production callers, no dynamic import, no persisted-data dependency, AMT/replay suites pass.

## D3 — Remove obsolete strategy seam

**Depends on:** P0.3, C4.

Choose one explicit outcome:

```text
supported strategy extension → retain one tested StrategyPort
unsupported extension → delete quant/strategy.py and unused injection path
```

**Deletion gate:** no production caller relies on dynamic strategy injection.

## D4 — Remove empty journal path

**Depends on:** B3.

Either make the journal read the durable ledger or delete the empty surface:

```text
backend/app/application/services/trade_journal.py
backend/app/api/routers/journal.py
frontend/components/JournalPage.tsx
```

**Deletion gate:** no endpoint returns an always-empty production store.

## D5 — Remove duplicate types and constants

**Depends on:** C4, B4, B6.

Delete or merge:

```text
duplicate Signal model
duplicate Position model
duplicate Order model
FloatOHLC/OHLC conversion chain
frontend MCX sets
frontend session constants
duplicate lot snapping
duplicate sizing
phantom WS fields
```

**Deletion gate:** import graph, type-check, golden replay, broker adapter, state-fold, and frontend contract tests pass.

# Gate G2 — Full integration and deletion gate

G2 is a clean-tree gate. It must run after all deletion work.

## Backend and quant

```text
.venv/bin/python -m pytest tests/quant -q
.venv/bin/python -m pytest backend/tests -q
```

Run the repository's configured type, lint, and import-boundary checks. Existing baseline failures must be separated from failures introduced by this program.

## Frontend

Run the package-manager commands declared in `frontend/package.json` for:

```text
unit tests
build
typecheck
```

## Required invariants

```text
trace OFF digest == trace ON digest
fold(events) == live state
engine quantity == broker payload quantity
short restart == correct signed short position
one close request == one broker close order
unknown order never blindly duplicates
frontend verdict == server verdict
NSE clock != MCX clock
```

## Deletion approval

The integration agent writes a deletion manifest containing:

```text
deleted file
last active caller
replacement owner
tests proving replacement
```

No deletion is considered complete without that manifest.

# P8 — Live-shadow validation

**Depends on:** G2.

Run real Dhan market data with PaperOMS and full tracing. Do not enable real order submission.

```text
real packet
→ real symbol map
→ real canonical Tick
→ real Bar
→ real AMT
→ real gates
→ real risk sizing
→ PaperOMS
→ durable ledger
→ reconciliation
→ WS snapshot
→ hot-path trace
```

Record raw ticks and depth at the feed boundary. Compare the live-shadow session with offline replay.

Required events:

```text
disconnect/reconnect
order-update feed interruption
process restart
partial fill simulation
session boundary
NSE session
MCX evening session
expiry session
```

**Exit condition:** no unexplained phase gaps, reservation leaks, duplicate orders, position sign mismatches, or live/replay decision differences.

# P9 — One-lot canary

**Depends on:** P8 and explicit human approval.

Restrictions:

```text
one symbol
one lot
one account
manual enablement
full trace enabled
intraday reconciliation enabled
hard daily-loss halt
automatic global kill switch
```

The canary may expand only after the following are observed in production-like conditions:

```text
order intent visible before submit
broker id visible after acknowledgement
fill visible and durable
position equals broker
close confirmed by reconciliation
restart restores correctly
SIGTERM produces no unexpected position
```

# Parallelism schedule

```text
Day/Window 0:
  P0.1, P0.2, P0.3 sequential

After P0:
  A1 money audit       || A2 ledger audit       || A3 domain audit
  || A4 state audit    || A5 frontend audit     || A6 observability audit

After G0:
  B1 config            || B2 money boundary     || B3 ledger
  || B4 session         || B5 state              || B6 transport
  || B7 trace

After G1:
  C1 OMS
    → C2 exits
      → C3 close coordinator
        → C4 canonical types

After C4:
  D1 frontend cleanup  || D2 AMT deletion       || D3 strategy deletion
  || D4 journal decision || D5 duplicate cleanup

After G2:
  P8 live shadow → P9 one-lot canary
```

The apparent parallelism in Wave B is safe only because the file ownership map is enforced. `runtime.py`, `events.py`, `state.py`, and `multi_engine.py` remain integration-owned shared files.

# Agent launch prompts

These prompts can be assigned to isolated agents.

## Architecture/Graph agent

> Build the active production call graph for quant, backend, brokers, shared, and frontend. Classify every module as active, conditional, or zero-caller. Do not delete code. Produce exact callers, DI construction paths, dynamic imports, and deletion evidence.

## Money agent

> Trace Signal → quantity → lot snap → reservation → Order → broker payload → acknowledgement → fill. Make quantity and deterministic order identity explicit. Add property tests for exact quantity preservation, idempotent retry, timeout, rejection, and partial fills. Do not edit runtime.py or multi_engine.py.

## Ledger agent

> Design and implement the durable order/fill lifecycle and reconciliation state machine. Cover crash windows, UNKNOWN orders, duplicate broker updates, partial fills, signed positions, and restart. Do not change frontend or session logic.

## Domain agent

> Produce the canonical ownership model for Tick, Bar, Signal, Order, Fill, Position, Session, Instrument, money, and PnL. Consolidate session/instrument ownership without deleting types until the caller graph and migration tests are complete.

## State agent

> Make EngineState event-derived, remove coordinator private-field reach-through, and add explicit snapshot consistency metadata and degraded-state behavior. Own runtime/state/multi_engine integration changes through narrow patches only.

## Transport/frontend agent

> Make the WS contract canonical and remove frontend trading authority. Preserve visual-only transformations, delete local verdict/PnL/session logic only after snapshot fixtures provide server values. Run frontend tests and build.

## Observability agent

> Move hot-path tracing to passive EventBus/observer boundaries, add correlation ids and off-thread writing, and prove trace-on/trace-off behavioral parity. Trace actual WS egress, not only snapshot composition.

## Deletion agent

> After G2 prerequisites are complete, execute only deletion-manifest entries with zero active callers and passing replacement tests. Do not preserve dead paths for compatibility.

# Final release gate

The refactor is not deployable merely because all tests are green. Release requires:

```text
G1 money safety passed
G2 clean integration/deletion passed
live-shadow replay parity passed
intraday reconciliation passed
failure health states visible
frontend is read-only
one-lot canary approved
```

Until all gates pass, the runtime remains paper/shadow-only.
