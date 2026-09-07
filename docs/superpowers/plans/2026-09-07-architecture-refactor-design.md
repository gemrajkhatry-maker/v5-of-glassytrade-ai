# Architecture Refactoring Audit & Design Plan

## Executive Summary

This audit covered the production paper-trading runtime path **leaf-by-leaf** across
`quant/`, `backend/app/`, `brokers/`, and `shared/`. The earlier "paper-ready" verdict was
overstated: the recent commits added **optional helpers**, not adopted workflows. The running
application is healthy, but the architecture has god modules, duplicated types, compatibility
shims, shotgun-surgery coupling, and a readiness contract that lies.

**Current state:** 523 production Python files, ~61,000 lines. The paper runtime works, but it is
not safe to evolve or operate confidently.

**Recommendation:** A staged design-level refactor with explicit adoption gates, not more
patches.

---

## 1. Audit Methodology

- Read every production module on the paper runtime path, not just diffs.
- Traced actual runtime behavior via the live application (`/api/health`, `/api/health/ready`,
  `/api/system/config`, `/api/v1/metrics`, WebSocket snapshots, SQLite state).
- Distinguished **implemented helpers** from **adopted workflows**.
- Classified findings by severity and refactor leverage.

---

## 2. Verified Runtime State

### Healthy

| Component | Evidence |
|---|---|
| Process health | Backend `:8090`, frontend `:5191`, both responding |
| Mode | `environment=paper`, `broker_mode=paper`, `tradingMode=paper` |
| Live data | WebSocket snapshots receive ticks, LTP, OI, AMT profile |
| Engines | 12 active, 0 crashed, 0 stale |
| Decisions | Conservative `NO_EDGE` with correct gate ordering |
| No live orders | `LiveOMS` not instantiated |

### Degraded

| Component | Evidence |
|---|---|
| Readiness | Reports `ready` with 2 stale DB positions restored but not in active universe |
| Metrics | `/api/v1/metrics` reports 0 ticks despite live WebSocket flow |
| Risk state | Every engine logs `failed to load persisted state — starting fresh` |
| History seed | `DH-3001` rate limits during startup, no global scheduler |
| Paper positions | 2 stale positions (`NIFTY 1 SEP 24050 CALL`, `MIDCPNIFTY 29 SEP 14700 PUT`) restored but not managed |

---

## 3. God Modules

### 3.1 `quant/runtime.py` — 1,591 lines

**Responsibilities owned:**
- Tick ingestion loop
- Bar aggregation orchestration
- AMT engine lifecycle (underlying + option)
- Decision gating and context building
- Order submission and portfolio-risk reservation
- Position management (entry, exit, pyramid, partials)
- Tick-level and bar-level exit evaluation
- Thesis-flip evaluation
- Event emission and event-store reconciliation
- Session-risk initialization
- Advisor wiring
- Live quote caching

**Problem:** One class owns the entire per-symbol runtime. Changing exit logic requires
understanding tick loop, AMT seeding, option translation, and portfolio risk simultaneously.

**Refactor seam:** Extract `TickPipeline`, `EntryOrchestrator`, `ExitOrchestrator`,
`PositionLifecycleManager`, and `RuntimeDependencies`.

### 3.2 `quant/multi_engine.py` — 1,470 lines

**Responsibilities owned:**
- Symbol scanning and contract resolution
- Engine spawning and thread-pool management
- Gateway lifecycle (underlying + option)
- History seeding coordination
- Position restoration on restart
- EOD watchdog and symbol rotation
- Intraday broker reconciliation
- Portfolio-risk authority sharing
- Journal attachment

**Problem:** Coordinator knows too much about engine internals and broker reconciliation.

**Refactor seam:** Extract `EngineFactory`, `StartupReconciliation`, `SymbolRotationPolicy`,
and `CoordinatorState`.

### 3.3 `quant/amt/analyzer.py` — 1,066 lines

**Responsibilities owned:**
- Volume profile construction
- POC/VAH/VAL computation
- LVN/HVN detection
- CVD tracking
- Profile shape classification
- Session context
- Acceptance/rejection
- Break detection
- Displacement detection
- Aggression scoring
- Drive tracking
- Opening classification
- VWAP bands
- Prior-session persistence

**Problem:** One class owns the entire AMT analysis pipeline. The extracted modules
(`compute.py`, `volume_profile.py`, `vwap.py`, etc.) exist but the analyzer still
orchestrates everything.

**Refactor seam:** The analyzer should be a **facade** over focused analyzers, not the
implementation.

---

## 4. Duplicated Types

| Type | Locations | Status |
|---|---|---|
| `Position` | `quant/contracts/entities.py`, `quant/execution/order.py`, `shared/entities/models.py` | **True duplication** — engine vs broker vs shared |
| `Signal` | `quant/contracts/entities.py`, `quant/decision/signal_builder.py` | **True duplication** — broker-facing vs engine-facing |
| `Order` | `quant/execution/order.py`, `shared/entities/models.py` | **True duplication** |
| `OHLC` | `quant/contracts/value_objects.py`, `brokers/broker/dhan/domain/value_objects.py` | **Layered models** — intentional per spec §8 |
| `RiskState` | `quant/state_machine.py`, `quant/execution/risk.py` | **True duplication** |
| `Tick` | `quant/brokers/gateway.py`, `shared/entities/models.py` | **True duplication** |
| `DepthLevel` | `brokers/broker/dhan/domain/value_objects.py`, `shared/entities/models.py` | **Re-export shim** |

**Refactor plan:**
- `Position`, `Signal`, `Order`, `RiskState`, `Tick` → single canonical home per layer.
- `OHLC` → keep layered, but document the seam explicitly.
- `DepthLevel` → remove the broker re-export; import from `shared`.

---

## 5. Compatibility Shims

| Shim | Location | Purpose | Safe to remove? |
|---|---|---|---|
| `brokers/broker/entities.py` | Re-exports from `shared.entities.models` | Backward compat for broker tests | **Yes** — after updating imports |
| `OrderSide.LONG/SHORT` | `shared/entities/models.py:29-30` | Alias for `BUY/SELL` | **No** — used by LLM bridge |
| `OrderStatus.COMPLETED` | `shared/entities/models.py:45` | Alias for `FILLED` | **Yes** — normalize to `FILLED` |
| `Instrument.__init__` backward compat | `shared/entities/models.py:150-185` | `symbol`/`exchange` kwargs | **Yes** — migrate callers |
| `SessionPhase` verbose strings | `shared/entities/models.py:54-59` | Human-readable phase names | **No** — used by frontend |
| `legacy_formats` in exit reasons | `quant/contracts/entities.py:274` | Old exit reason strings | **Yes** — after journal migration |
| `StateProjector` removal notice | `quant/state.py:295-298` | Dead code documentation | **Yes** — delete |
| `sync_boundary` star import | `backend/app/core/async_boundary.py:7` | Re-export | **Review** |

---

## 6. Shotgun Surgery

Changes that require touching many files:

### 6.1 Risk-state changes
Touch: `risk.py`, `runtime.py`, `position_manager.py`, `oms.py`, `live_oms.py`,
`multi_engine.py`, `session_levels.py`, `health.py`

**Root cause:** Risk state is not a single value object with a clear owner.

### 6.2 Exit-reason changes
Touch: `entities.py`, `transitions.py`, `position_manager.py`, `oms.py`, `live_oms.py`,
`journal.py`, `schemas.py`

**Root cause:** Exit reason is a string, not a typed enum.

### 6.3 Position lifecycle changes
Touch: `position_manager.py`, `oms.py`, `live_oms.py`, `transitions.py`, `runtime.py`,
`event_store.py`, `journal.py`

**Root cause:** Position lifecycle is distributed across OMS, PositionManager, and runtime.

---

## 7. Unadopted Helpers

Recent commits added helpers that are **not wired into the production path**:

| Helper | File | Status |
|---|---|---|
| `PaperExecutionSimulator` | `quant/execution/paper_simulator.py` | Optional in `PaperOMS`; not default |
| `PaperContractResolver` | `quant/execution/paper_contracts.py` | Optional in `PaperOMS`; not default |
| `ContractRef` | `quant/contracts/contracts.py` | Used by resolver only |
| `compute_fill_costs` | `quant/execution/trade_costs.py` | Used by simulator only |
| `capital_deployment_pct` | `quant/execution/risk.py` | Wired but untested in live path |

**Implication:** The "paper-ready" verdict was based on unit tests of helpers, not on the
actual runtime behavior. The production path still uses the legacy instant-fill `PaperOMS`
unless a simulator is explicitly injected.

---

## 8. Design-Level Refactor Plan

### Phase 0 — Stabilize runtime truth

**Goal:** Make readiness and metrics reflect reality.

#### 0.1 Risk-state load status
- Add `RiskLoadStatus` enum: `MISSING_INITIALIZED`, `LOADED`, `CORRUPT`, `STORAGE_ERROR`,
  `MEMORY_ONLY`.
- Missing current-day key → `MISSING_INITIALIZED` (info log, not warning).
- Corrupt data → `CORRUPT` (quarantine, block entries).
- Storage failure → `STORAGE_ERROR` (block entries).
- Memory-only → `MEMORY_ONLY` (tests/replay only).

#### 0.2 Stale paper-position quarantine
- After scanner topology is known, classify persisted positions:
  - `OPEN` — contract is active, restore to engine.
  - `QUARANTINED_STALE_CONTRACT` — contract not in active universe, preserve but do not
    restore.
  - `QUARANTINED_UNRESOLVED` — invalid identity, preserve but do not restore.
- Readiness reports `degraded` until quarantined positions are resolved.
- Do not delete stale rows automatically.

#### 0.3 Truthful readiness
- Readiness checks: `database`, `coordinator`, `crashed_engines`, `stale_engines`,
  `active_contracts`, `risk_state`, `paper_position_reconciliation`, `history_seed`,
  `runtime_activity`.
- Stale positions → `degraded_no_new_entries` or `not_ready`.
- Unresolved history seed → `degraded_no_new_entries`.

#### 0.4 Coordinator-backed metrics
- Add per-engine activity: `last_tick_received_at`, `last_bar_closed_at`,
  `last_amt_update_at`, `last_decision_at`, `decision_count`, `approved_count`,
  `blocked_count`, `open_position`, `seed_status`, `data_age_seconds`.
- `/api/v1/metrics` reads from coordinator or a coordinator-owned adapter.
- Remove the disconnected `MetricsCollector` singleton.

#### 0.5 Dhan history seed scheduler
- One shared request scheduler across all engines.
- Respect `DH-3001` with broker-provided retry delay.
- Cache successful seeds.
- Per-engine seed states: `NOT_STARTED`, `SEEDING`, `READY`, `DEGRADED_RATE_LIMIT`,
  `DEGRADED_EMPTY`, `FAILED`.
- Do not allow AMT entry decisions before seed is `READY` or explicitly degraded.

**Acceptance gate:** Restart paper app, verify readiness is truthful, metrics show activity,
stale positions are quarantined, no engine starts fresh with a misleading warning.

---

### Phase 1 — Type consolidation

**Goal:** One canonical home per type per layer.

#### 1.1 Canonical homes
- `Position` → `quant/contracts/entities.py` (engine layer).
- `Signal` → `quant/decision/signal_builder.py` (engine layer).
- `Order` → `quant/execution/order.py` (engine layer).
- `RiskState` → `quant/execution/risk.py` (engine layer).
- `Tick` → `quant/brokers/gateway.py` (quant layer).
- `OHLC` → keep layered: `quant/contracts/value_objects.py` (Decimal) and
  `brokers/broker/dhan/domain/value_objects.py` (Dhan API shape). Document the seam.

#### 1.2 Remove shims
- Delete `brokers/broker/entities.py` after updating imports.
- Remove `OrderStatus.COMPLETED` alias.
- Remove `Instrument.__init__` backward compat after migrating callers.
- Delete `StateProjector` removal notice.

**Acceptance gate:** All tests pass, no import cycles, no duplicate class names.

---

### Phase 2 — God module decomposition

**Goal:** Each module has one reason to change.

#### 2.1 `QuantEngine` → focused collaborators
Extract:
- `TickPipeline` — tick ingestion, bar aggregation, AMT updates.
- `EntryOrchestrator` — decision gating, context building, signal translation, submission.
- `ExitOrchestrator` — tick/bar exits, thesis-flip, pyramid.
- `RuntimeDependencies` — gateway, aggregator, AMT engine, OMS, risk, portfolio risk.

`QuantEngine` becomes a facade wiring these together.

#### 2.2 `QuantCoordinator` → focused collaborators
Extract:
- `EngineFactory` — engine construction, OMS injection, storage attachment.
- `StartupReconciliation` — position restoration, quarantine, readiness.
- `SymbolRotationPolicy` — scanning, rescan, EOD rotation.
- `CoordinatorState` — engine registry, thread pool, lifecycle locks.

#### 2.3 `AMTAnalyzer` → facade
The analyzer delegates to focused analyzers:
- `VolumeProfileComputer`
- `VWAPTracker`
- `CVDTracker`
- `AbsorptionDetector`
- `AggressionScorer`
- `SessionContext`
- `BreakDetector`
- `DisplacementDetector`

The analyzer owns orchestration and the result DTO, not the math.

**Acceptance gate:** All existing AMT tests pass, no behavioral change, modules are
independently testable.

---

### Phase 3 — Adopt paper helpers

**Goal:** Make the new simulator the default paper path.

#### 3.1 Default simulator injection
- `QuantCoordinator._spawn_engine()` injects `PaperExecutionSimulator` and `ContractRef`
  for all paper engines.
- Legacy instant-fill path remains only for explicit opt-out (tests/replay).

#### 3.2 Cost-aware paper fills
- All paper fills go through `compute_fill_costs`.
- Net P&L feeds `SessionRisk`, `PortfolioRiskAuthority`, journal, and reports.

#### 3.3 Paper position persistence
- Persist fills and positions on every state change.
- On restart, reconstruct from the fill ledger, not just the last position row.

**Acceptance gate:** Paper trades show costs in journal, restart reconstructs exact state,
simulator is the default.

---

### Phase 4 — AMT data-quality reporting

**Goal:** Do not present inferred data as exchange-exact.

#### 4.1 Data-quality enum
```python
class DataQuality(str, Enum):
    TICK_EXACT = "TICK_EXACT"
    CANDLE_DISTRIBUTED = "CANDLE_DISTRIBUTED"
    CANDLE_GAUSSIAN = "CANDLE_GAUSSIAN"
    PRICE_DIRECTION_PROXY = "PRICE_DIRECTION_PROXY"
    UNKNOWN = "UNKNOWN"
```

#### 4.2 Attach to AMT DTO and decision evidence
- Footprint and profile carry their data quality.
- High-conviction setups require `TICK_EXACT` or explicitly configured degraded mode.
- Missing/zero aggressor volume is visible in the UI.

**Acceptance gate:** Frontend shows data quality, no high-conviction setup fires on synthetic
footprint.

---

## 9. Migration Gates

### Gate A — Runtime truth
- Restart paper app.
- Verify `/api/health/ready` is truthful.
- Verify metrics show nonzero ticks/bars.
- Verify stale positions are quarantined.
- Verify no engine starts fresh with a misleading warning.

### Gate B — Type consolidation
- All tests pass.
- No import cycles.
- No duplicate class names.

### Gate C — God module decomposition
- All existing tests pass.
- No behavioral change.
- Modules are independently testable.

### Gate D — Paper adoption
- Paper trades show costs in journal.
- Restart reconstructs exact state.
- Simulator is the default.

### Gate E — Full regression
```bash
.venv/bin/python -m pytest tests/quant -q
PYTHONPATH=backend:. .venv/bin/python -m pytest backend/tests/unit -q
.venv/bin/python -m pytest tests/system/test_paper_protocol.py -q
```

---

## 10. Risk Register

| Risk | Mitigation |
|---|---|
| Refactor breaks live paper runtime | Staged gates, full regression suite, feature flags |
| Type consolidation introduces import cycles | AST-based import graph check before commit |
| God module decomposition changes behavior | Golden-file replay tests, deterministic fixtures |
| Paper adoption changes P&L | Byte-identical golden traces before/after |
| Dhan rate limiting worsens | Global scheduler, cached seeds, degraded mode |

---

## 11. Priority

```
P0  Runtime truth (risk state, readiness, metrics, stale positions, seed scheduler)
P1  Type consolidation and shim removal
P1  God module decomposition
P2  Paper helper adoption
P2  AMT data-quality reporting
P3  Dashboard visibility for new states
```

---

## 12. What This Plan Preserves

- 95% paper capital deployment policy.
- Broker-private security IDs.
- Fabio AMT behavior.
- Event-sourced runtime.
- Deterministic replay.
- Existing test contracts.

---

## 13. What This Plan Removes

- Falsely green readiness.
- Disconnected metrics.
- Fail-open risk loading.
- Stale paper position restoration.
- God modules.
- Duplicated types.
- Unwanted compatibility shims.
- Unadopted helpers.

---

**Next step:** Approve this plan, then implement Phase 0 with TDD.
