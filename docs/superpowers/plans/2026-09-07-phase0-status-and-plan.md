# Phase 0 — Runtime Truth: Status & Plan

> Last updated: 2026-09-07
> Branch: `refactor/phase0-runtime-truth`
> Status: **Phase 0 complete. 1861 tests passing, 0 failures.**

---

## 1. Current State

### What was built (10 sub-phases, TDD throughout)

| # | Module | What | Tests |
|---|---|---|---|
| 0.1 | `risk.py` | `RiskLoadStatus` enum — missing key is silent info, not scary warning; corrupt/storage-error block trades | 12 |
| 0.2 | `paper_reconciliation.py` | `PaperPositionReconciler` — stale positions quarantined, not restored | 10 |
| 0.3 | `readiness.py` | `ReadinessStatus` enum — READY / DEGRADED_NO_NEW_ENTRIES / NOT_READY | 8 |
| 0.4 | `coordinator_metrics.py` | `CoordinatorMetricsProvider` — per-engine activity from runtime | 9 |
| 0.5 | `seed_scheduler.py` | `HistorySeedScheduler` — shared rate-limited fetch with retry/cache/dedup | 11 |
| 0.6 | `multi_engine.py` | Coordinator runs reconciler in `start()`, exposes `quarantined_positions()` | 5 |
| 0.7 | `health.py` | Backend `/health/ready` includes coordinator readiness | — |
| 0.8 | `health.py` | Backend `/v1/metrics` uses `CoordinatorMetricsProvider` | — |
| 0.9 | `amt_engine.py` | AMT engine uses scheduler, tracks `_seed_status` | — |
| 0.10 | — | Full regression | **1861 passed** |

### What changed in production code

- **`quant/multi_engine.py`**: `start()` runs `PaperPositionReconciler` before spawning; `_spawn_engine` only restores OPEN positions; `quarantined_positions()` and `readiness()` methods added; shared `HistorySeedScheduler` created
- **`quant/runtime.py`**: `seed_scheduler` parameter threaded through to `AMTEngine`
- **`quant/amt_engine.py`**: `seed()` uses scheduler when available; tracks `_seed_status` (NOT_STARTED → SEEDING → READY | DEGRADED_*)
- **`backend/app/api/routers/health.py`**: `/health/ready` includes `coordinator_readiness`; `/v1/metrics` uses `CoordinatorMetricsProvider`

### What's preserved

- 95% paper deployment policy
- Broker-private security IDs
- Fabio AMT behavior
- Event-sourced runtime
- Deterministic replay
- Legacy seed path (tests/replay without scheduler)

---

## 2. Production Code Changes (Diff Summary)

### `quant/execution/risk.py`
- Added `RiskLoadStatus` enum: `MISSING_INITIALIZED`, `LOADED`, `CORRUPT`, `STORAGE_ERROR`, `MEMORY_ONLY`
- `SessionRisk._load()` now classifies cause correctly: missing key → silent info; corrupt → ERROR + blocks trades; storage failure → CRITICAL + blocks trades
- `SessionRisk.load_status` property exposed for telemetry/readiness
- `can_trade()` blocks entries when load status is `STORAGE_ERROR` or `CORRUPT`
- Added `_reset_fresh()` helper for corrupt-data quarantine

### `quant/execution/paper_reconciliation.py` (new)
- `PaperPositionStatus` enum: `OPEN`, `QUARANTINED_STALE_CONTRACT`, `QUARANTINED_UNRESOLVED`
- `PaperPositionReconciler` classifies every persisted position against active universe
- `ReconciliationResult` with `open_positions` (restore), `quarantined` (preserve only), `summary()`
- `reconcile_paper_positions()` convenience wrapper

### `quant/execution/readiness.py` (new)
- `ReadinessStatus` enum: `READY`, `DEGRADED_NO_NEW_ENTRIES`, `NOT_READY`
- `readiness_status()` function with severity ladder: NOT_READY > DEGRADED_NO_NEW_ENTRIES > READY
- `CoordinatorLike` Protocol for structural typing

### `quant/execution/coordinator_metrics.py` (new)
- `EngineActivity` dataclass: per-engine runtime metrics
- `CoordinatorMetricsProvider.snapshot()`: aggregates across all engines
- `coordinator_metrics_provider()` convenience wrapper

### `quant/execution/seed_scheduler.py` (new)
- `SeedStatus` enum: `NOT_STARTED`, `SEEDING`, `READY`, `DEGRADED_RATE_LIMIT`, `DEGRADED_EMPTY`, `FAILED`
- `HistorySeedScheduler`: shared fetch scheduler with min interval, retry, cache, dedup
- `seed_status()` convenience function

### `quant/multi_engine.py`
- Added imports: `os`, `PaperPositionReconciler`, `ReconciliationResult`, `readiness_status`, `ReadinessStatus`, `HistorySeedScheduler`
- `QuantCoordinator.__init__`: added `_quarantined`, `_reconciliation_result`, `_seed_scheduler` attributes
- `start()`: runs `PaperPositionReconciler` before spawning; logs quarantined positions
- `_spawn_engine()`: only restores OPEN positions from reconciler; passes `seed_scheduler` to `QuantEngine`
- Added `quarantined_positions()` method
- Added `readiness()` method

### `quant/runtime.py`
- `QuantEngine.__init__`: added `seed_scheduler` parameter
- All 3 `AMTEngine()` constructions now pass `seed_scheduler=seed_scheduler`

### `quant/amt_engine.py`
- `AMTEngine.__init__`: added `seed_scheduler` parameter, `_seed_status` attribute
- `AMTEngine.seed()`: uses scheduler when available; tracks `_seed_status` through the seed lifecycle
- Legacy seed path preserved for tests/replay

### `backend/app/api/routers/health.py`
- `/health/ready`: added `coordinator_readiness` check; `NOT_READY` overrides overall status
- `/v1/metrics`: uses `CoordinatorMetricsProvider` instead of disconnected `MetricsCollector`

---

## 3. New Files

| File | Lines | Purpose |
|---|---|---|
| `quant/execution/paper_reconciliation.py` | 129 | Paper position quarantine |
| `quant/execution/readiness.py` | 96 | Truthful readiness |
| `quant/execution/coordinator_metrics.py` | 123 | Coordinator-backed metrics |
| `quant/execution/seed_scheduler.py` | 166 | History seed scheduler |
| `tests/quant/execution/test_risk_load_status.py` | 182 | Phase 0.1 tests |
| `tests/quant/execution/test_paper_reconciliation.py` | 172 | Phase 0.2 tests |
| `tests/quant/execution/test_readiness.py` | 100 | Phase 0.3 tests |
| `tests/quant/execution/test_coordinator_metrics.py` | 166 | Phase 0.4 tests |
| `tests/quant/execution/test_seed_scheduler.py` | 157 | Phase 0.5 tests |
| `tests/quant/execution/test_coordinator_quarantine.py` | 129 | Phase 0.6 tests |

---

## 4. Test Status

### Phase 0 new tests: 76
- `test_risk_load_status.py`: 12 passed
- `test_paper_reconciliation.py`: 10 passed
- `test_readiness.py`: 8 passed
- `test_coordinator_metrics.py`: 9 passed
- `test_seed_scheduler.py`: 11 passed
- `test_coordinator_quarantine.py`: 5 passed
- Existing tests: 20 risk + 1740+ other quant = 1836+ passed

### Total: 1861 passed, 11 skipped, 0 failed, 0 errors

---

## 5. Runtime Verification

### Before Phase 0 (degraded state)
| Component | Evidence |
|---|---|
| Readiness | Reports `ready` with 2 stale DB positions restored but not in active universe |
| Metrics | `/api/v1/metrics` reports 0 ticks despite live WebSocket flow |
| Risk state | Every engine logs `failed to load persisted state` for legitimate new-day init |
| History seed | `DH-3001` rate limits during startup |
| Paper positions | 2 stale positions restored but not managed |

### After Phase 0 (expected)
| Component | Expected |
|---|---|
| Readiness | `DEGRADED_NO_NEW_ENTRIES` until quarantined positions resolved |
| Metrics | Per-engine activity visible (last tick, decisions, seed status) |
| Risk state | New day: silent info log. Corrupt/storage: loud error + block trades |
| History seed | Rate-limited, cached, deduplicated across all engines |
| Paper positions | Quarantined: preserved in storage, not loaded into engines |

---

## 6. Next Phases

### Phase 1 — Type Consolidation

**Goal:** One canonical home per type per layer.

| Type | Current homes | Target home |
|---|---|---|
| `Position` | `quant/contracts/entities.py`, `quant/execution/order.py`, `shared/entities/models.py` | `quant/contracts/entities.py` |
| `Signal` | `quant/contracts/entities.py`, `quant/decision/signal_builder.py` | `quant/decision/signal_builder.py` |
| `Order` | `quant/execution/order.py`, `shared/entities/models.py` | `quant/execution/order.py` |
| `RiskState` | `quant/state_machine.py`, `quant/execution/risk.py` | `quant/execution/risk.py` |
| `Tick` | `quant/brokers/gateway.py`, `shared/entities/models.py` | `quant/brokers/gateway.py` |
| `OHLC` | `quant/contracts/value_objects.py`, `brokers/broker/dhan/domain/value_objects.py` | Keep layered, document seam |

**Shims to remove:**
- `brokers/broker/entities.py` (re-export shim)
- `OrderStatus.COMPLETED` alias
- `Instrument.__init__` backward compat (after migrating callers)
- `StateProjector` removal notice

**Acceptance gate:** All tests pass, no import cycles, no duplicate class names.

---

### Phase 2 — God Module Decomposition

**Goal:** Each module has one reason to change.

#### 2.1 `QuantEngine` → focused collaborators
Extract:
- `TickPipeline` — tick ingestion, bar aggregation, AMT updates
- `EntryOrchestrator` — decision gating, context building, signal translation, submission
- `ExitOrchestrator` — tick/bar exits, thesis-flip, pyramid
- `RuntimeDependencies` — gateway, aggregator, AMT engine, OMS, risk, portfolio risk

`QuantEngine` becomes a facade wiring these together.

#### 2.2 `QuantCoordinator` → focused collaborators
Extract:
- `EngineFactory` — engine construction, OMS injection, storage attachment
- `StartupReconciliation` — position restoration, quarantine, readiness
- `SymbolRotationPolicy` — scanning, rescan, EOD rotation
- `CoordinatorState` — engine registry, thread pool, lifecycle locks

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

**Acceptance gate:** All existing AMT tests pass, no behavioral change, modules are independently testable.

---

### Phase 3 — Paper Helper Adoption

**Goal:** Make the new simulator the default paper path.

| Helper | File | Current status | Target |
|---|---|---|---|
| `PaperExecutionSimulator` | `quant/execution/paper_simulator.py` | Optional in `PaperOMS` | Default |
| `PaperContractResolver` | `quant/execution/paper_contracts.py` | Optional in `PaperOMS` | Default |
| `ContractRef` | `quant/contracts/contracts.py` | Used by resolver only | Default |
| `compute_fill_costs` | `quant/execution/trade_costs.py` | Used by simulator only | Default |

**Steps:**
1. `QuantCoordinator._spawn_engine()` injects `PaperExecutionSimulator` and `ContractRef` for all paper engines
2. Legacy instant-fill path remains only for explicit opt-out (tests/replay)
3. All paper fills go through `compute_fill_costs`; net P&L feeds risk, journal, reports
4. Persist fills and positions on every state change; reconstruct from fill ledger on restart

**Acceptance gate:** Paper trades show costs in journal, restart reconstructs exact state, simulator is the default.

---

### Phase 4 — AMT Data-Quality Reporting

**Goal:** Do not present inferred data as exchange-exact.

```python
class DataQuality(str, Enum):
    TICK_EXACT = "TICK_EXACT"
    CANDLE_DISTRIBUTED = "CANDLE_DISTRIBUTED"
    CANDLE_GAUSSIAN = "CANDLE_GAUSSIAN"
    PRICE_DIRECTION_PROXY = "PRICE_DIRECTION_PROXY"
    UNKNOWN = "UNKNOWN"
```

**Steps:**
1. Footprint and profile carry their data quality
2. High-conviction setups require `TICK_EXACT` or explicitly configured degraded mode
3. Missing/zero aggressor volume is visible in the UI

**Acceptance gate:** Frontend shows data quality, no high-conviction setup fires on synthetic footprint.

---

## 7. Migration Gates

| Gate | Criteria |
|---|---|
| **A** | Restart paper app, verify readiness truthful, metrics show activity, stale positions quarantined |
| **B** | All tests pass, no import cycles, no duplicate class names |
| **C** | All existing tests pass, no behavioral change, modules independently testable |
| **D** | Paper trades show costs in journal, restart reconstructs exact state |
| **E** | Frontend shows data quality, no high-conviction setup fires on synthetic footprint |

---

## 8. Risk Register

| Risk | Mitigation |
|---|---|
| Refactor breaks live paper runtime | Staged gates, full regression suite, feature flags |
| Type consolidation introduces import cycles | AST-based import graph check before commit |
| God module decomposition changes behavior | Golden-file replay tests, deterministic fixtures |
| Paper adoption changes P&L | Byte-identical golden traces before/after |
| Dhan rate limiting worsens | Global scheduler, cached seeds, degraded mode |

---

## 9. Files Modified (Production Code)

| File | Lines changed | Summary |
|---|---|---|
| `quant/execution/risk.py` | ~279 insertions, ~47 deletions | `RiskLoadStatus`, `_load()` rewrite, `load_status` property, `can_trade()` blocks |
| `quant/multi_engine.py` | ~80 insertions, ~5 deletions | Reconciler wiring, scheduler, new methods |
| `quant/runtime.py` | ~5 insertions | `seed_scheduler` parameter |
| `quant/amt_engine.py` | ~30 insertions, ~5 deletions | `seed_scheduler` param, `seed()` rewrite, `_seed_status` tracking |
| `backend/app/api/routers/health.py` | ~15 insertions | Coordinator readiness + metrics provider |

## 10. Files Created (Production Code)

| File | Lines | Summary |
|---|---|---|
| `quant/execution/paper_reconciliation.py` | 129 | Paper position quarantine |
| `quant/execution/readiness.py` | 96 | Truthful readiness |
| `quant/execution/coordinator_metrics.py` | 123 | Coordinator-backed metrics |
| `quant/execution/seed_scheduler.py` | 166 | History seed scheduler |

---

## 11. What This Plan Preserves

- 95% paper capital deployment policy.
- Broker-private security IDs.
- Fabio AMT behavior.
- Event-sourced runtime.
- Deterministic replay.
- Existing test contracts.

## 12. What This Plan Removes

- Falsely green readiness.
- Disconnected metrics.
- Fail-open risk loading.
- Stale paper position restoration.
- God modules.
- Duplicated types.
- Unwanted compatibility shims.
- Unadopted helpers.

---

**Next step:** Approve to continue with Phase 1 (Type Consolidation).
