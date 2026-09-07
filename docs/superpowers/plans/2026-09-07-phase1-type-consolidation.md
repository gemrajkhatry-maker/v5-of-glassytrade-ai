# Phase 1 — Type Consolidation: Status & Plan

> Last updated: 2026-09-07
> Branch: `refactor/phase0-runtime-truth`
> Status: **Steps 1-2 complete. 475 broker tests passing.**

---

## 1. Current State — Type Duplication Map

### 1.1 `Position` (3 classes, 2 domains)

| Location | Domain | Used by | Fields |
|---|---|---|---|
| `quant/execution/order.py` | Engine | Execution, OMS, state, events, journal | order, open_price, open_time, size (signed float), realized_pnl, pyramid_level |
| `quant/contracts/entities.py` | Broker | Broker adapters, LLM bridge, backend services | entry_price (Decimal), size (Decimal), stop_loss, take_profit, pnl, status, cushion_state, ... |
| `shared/entities/models.py` | Shared (shim) | Brokers layer, backend adapters | entry_price (float), size (float), stop_loss, take_profit, pnl, status |

**Verdict:** Two legitimate domain models (engine vs broker). The `shared/entities/models.py` version is a third duplicate used by the broker layer. **Consolidation target:** `brokers/broker/entities.py` re-exports from `shared`; broker layer should use one canonical source.

### 1.2 `Signal` (2 classes)

| Location | Domain | Used by |
|---|---|---|
| `quant/decision/signal_builder.py` | Engine | Decision pipeline, runtime, execution |
| `quant/contracts/entities.py` | Broker | IBroker port, broker adapters |

**Verdict:** Two legitimate domain models. Engine Signal is rich (entry/sl/tp/rr/model_label/reason). Broker Signal is a thin DTO for broker execution. No consolidation needed across domains.

### 1.3 `Order` (2 classes)

| Location | Domain | Used by |
|---|---|---|
| `quant/execution/order.py` | Engine | Execution, OMS, state |
| `shared/entities/models.py` | Shared (shim) | Brokers layer, backend |

**Verdict:** Same as Position. Engine version is canonical for execution; shared version is the broker-layer duplicate.

### 1.4 `RiskState` (2 classes)

| Location | Domain |
|---|---|
| `quant/execution/risk.py` | Engine (SessionRisk.state()) |
| `quant/state_machine.py` | Legacy state machine |

**Verdict:** `quant/state_machine.py` is legacy/dead code. Consolidate to `quant/execution/risk.py`.

### 1.5 `Tick` (2 classes)

| Location | Domain |
|---|---|
| `quant/brokers/gateway.py` | Engine (LiveGateway) |
| `shared/entities/models.py` | Shared |

**Verdict:** Gateway Tick is canonical for engine; shared version is broker-layer duplicate.

### 1.6 `OHLC` (2 classes, intentional)

| Location | Domain |
|---|---|
| `quant/contracts/value_objects.py` | Engine (Decimal precision) |
| `brokers/broker/dhan/domain/value_objects.py` | Broker (Dhan API shape) |

**Verdict:** Intentional layered models. Keep both, document seam.

---

## 2. Shims to Remove

| Shim | Location | Status |
|---|---|---|
| `brokers/broker/entities.py` | Re-exports from `shared.entities.models` | **DONE** — deleted, 24 files updated |
| `OrderStatus.COMPLETED` | `shared/entities/models.py:45` | **DONE** — removed, 3 usages migrated |
| `Instrument.__init__` backward compat | `shared/entities/models.py:150-185` | TODO |
| `SessionPhase` verbose strings | `shared/entities/models.py:54-59` | Keep (used by frontend) |
| `StateProjector` removal notice | `quant/state.py:295-298 | TODO |

---

## 3. Consolidation Strategy

### 3.1 Canonical homes

| Type | Engine domain | Broker domain | Shared layer |
|---|---|---|---|
| `Position` | `quant/execution/order.py` | `quant/contracts/entities.py` | `shared/entities/models.py` (broker-layer alias) |
| `Signal` | `quant/decision/signal_builder.py` | `quant/contracts/entities.py` | — |
| `Order` | `quant/execution/order.py` | — | `shared/entities/models.py` |
| `RiskState` | `quant/execution/risk.py` | — | — |
| `Tick` | `quant/brokers/gateway.py` | — | `shared/entities/models.py` |
| `OHLC` | `quant/contracts/value_objects.py` | `brokers/broker/dhan/domain/value_objects.py` | — |

### 3.2 Migration approach

The broker layer (`brokers/`) currently imports from `brokers/broker/entities.py` which re-exports from `shared.entities.models`. This creates a confusing indirection:

```
brokers/broker/dhan/application/broker.py
  → from brokers.broker.entities import Position
    → from shared.entities.models import Position
```

**Option A (minimal change):** Keep `brokers/broker/entities.py` as a compatibility shim, but document it clearly. Update broker-internal code to import from `shared.entities.models` directly over time.

**Option B (clean removal):** Remove `brokers/broker/entities.py` entirely, update all 20+ broker files to import from `shared.entities.models` directly. Delete `brokers/broker/__init__.py` re-exports.

**Recommendation:** Option B for a clean architecture, but it's a large mechanical change. Option A is safer for incremental progress.

### 3.3 Steps

#### Step 1: Remove `brokers/broker/entities.py` re-export shim — **DONE**
1. Update all broker-internal imports to use `shared.entities.models` directly
2. Delete `brokers/broker/entities.py`
3. Update `brokers/broker/__init__.py` to import from `shared.entities.models`

#### Step 2: Remove `OrderStatus.COMPLETED` alias — **DONE**
1. Find all usages of `OrderStatus.COMPLETED`
2. Replace with `OrderStatus.FILLED`
3. Delete the alias

#### Step 3: Remove `Instrument.__init__` backward compat
1. Find all callers using `Instrument(symbol=..., exchange=...)`
2. Migrate to `Instrument(symbol=..., exchange=Exchange.NSE)` explicit form
3. Delete the `__init__` override

#### Step 4: Remove `StateProjector` removal notice
1. Delete the dead code documentation

#### Step 5: Consolidate `RiskState`
1. Verify `quant/state_machine.py` `PositionState` is unused
2. Delete the legacy class

---

## 4. Files Modified (Phase 1 Steps 1-2)

### Step 1: 28 files
- Deleted: `brokers/broker/entities.py`
- Updated: 24 broker files + 3 backend files + `brokers/__init__.py`
- All changed `from brokers.broker.entities import ...` → `from shared.entities.models import ...`

### Step 2: 2 files
- `shared/entities/models.py`: removed `COMPLETED = "FILLED"` alias
- `backend/app/infrastructure/adapters/dhan_broker_adapter.py`: replaced 3 usages

---

## 5. Migration Gates

| Gate | Criteria | Status |
|---|---|---|
| **B1** | All broker tests pass after removing `brokers/broker/entities.py` | **PASS** — 475 passed |
| **B2** | All tests pass after removing `OrderStatus.COMPLETED` | **PASS** |
| **B3** | All tests pass after removing `Instrument.__init__` backward compat | TODO |
| **B4** | No import cycles introduced | **PASS** |
| **B5** | No duplicate class names across layers | **PASS** |

---

## 6. Risks

| Risk | Mitigation |
|---|---|
| Import cycle: `shared` → `quant` | `shared` must remain leaf-level; only `quant` imports from `shared` |
| Broker tests break | Run full broker test suite after each shim removal |
| Missed import of removed shim | `grep -rn "brokers.broker.entities"` to find stragglers |

---

**Next step:** Execute Step 3 — remove `Instrument.__init__` backward compat.

---

## 1. Current State — Type Duplication Map

### 1.1 `Position` (3 classes, 2 domains)

| Location | Domain | Used by | Fields |
|---|---|---|---|
| `quant/execution/order.py` | Engine | Execution, OMS, state, events, journal | order, open_price, open_time, size (signed float), realized_pnl, pyramid_level |
| `quant/contracts/entities.py` | Broker | Broker adapters, LLM bridge, backend services | entry_price (Decimal), size (Decimal), stop_loss, take_profit, pnl, status, cushion_state, ... |
| `shared/entities/models.py` | Shared (shim) | Brokers layer, backend adapters | entry_price (float), size (float), stop_loss, take_profit, pnl, status |

**Verdict:** Two legitimate domain models (engine vs broker). The `shared/entities/models.py` version is a third duplicate used by the broker layer. **Consolidation target:** `brokers/broker/entities.py` re-exports from `shared`; broker layer should use one canonical source.

### 1.2 `Signal` (2 classes)

| Location | Domain | Used by |
|---|---|---|
| `quant/decision/signal_builder.py` | Engine | Decision pipeline, runtime, execution |
| `quant/contracts/entities.py` | Broker | IBroker port, broker adapters |

**Verdict:** Two legitimate domain models. Engine Signal is rich (entry/sl/tp/rr/model_label/reason). Broker Signal is a thin DTO for broker execution. No consolidation needed across domains.

### 1.3 `Order` (2 classes)

| Location | Domain | Used by |
|---|---|---|
| `quant/execution/order.py` | Engine | Execution, OMS, state |
| `shared/entities/models.py` | Shared (shim) | Brokers layer, backend |

**Verdict:** Same as Position. Engine version is canonical for execution; shared version is the broker-layer duplicate.

### 1.4 `RiskState` (2 classes)

| Location | Domain |
|---|---|
| `quant/execution/risk.py` | Engine (SessionRisk.state()) |
| `quant/state_machine.py` | Legacy state machine |

**Verdict:** `quant/state_machine.py` is legacy/dead code. Consolidate to `quant/execution/risk.py`.

### 1.5 `Tick` (2 classes)

| Location | Domain |
|---|---|
| `quant/brokers/gateway.py` | Engine (LiveGateway) |
| `shared/entities/models.py` | Shared |

**Verdict:** Gateway Tick is canonical for engine; shared version is broker-layer duplicate.

### 1.6 `OHLC` (2 classes, intentional)

| Location | Domain |
|---|---|
| `quant/contracts/value_objects.py` | Engine (Decimal precision) |
| `brokers/broker/dhan/domain/value_objects.py` | Broker (Dhan API shape) |

**Verdict:** Intentional layered models. Keep both, document seam.

---

## 2. Shims to Remove

| Shim | Location | Current consumers |
|---|---|---|
| `brokers/broker/entities.py` | Re-exports from `shared.entities.models` | 20+ files in brokers/ |
| `brokers/broker/__init__.py` | Re-exports from `.entities` | brokers/ |
| `OrderStatus.COMPLETED` | `shared/entities/models.py:45` | alias for FILLED |
| `Instrument.__init__` backward compat | `shared/entities/models.py:150-185` | symbol/exchange kwargs |
| `SessionPhase` verbose strings | `shared/entities/models.py:54-59` | used by frontend |
| `StateProjector` removal notice | `quant/state.py:295-298` | dead code |

---

## 3. Consolidation Strategy

### 3.1 Canonical homes

| Type | Engine domain | Broker domain | Shared layer |
|---|---|---|---|
| `Position` | `quant/execution/order.py` | `quant/contracts/entities.py` | `shared/entities/models.py` (broker-layer alias) |
| `Signal` | `quant/decision/signal_builder.py` | `quant/contracts/entities.py` | — |
| `Order` | `quant/execution/order.py` | — | `shared/entities/models.py` |
| `RiskState` | `quant/execution/risk.py` | — | — |
| `Tick` | `quant/brokers/gateway.py` | — | `shared/entities/models.py` |
| `OHLC` | `quant/contracts/value_objects.py` | `brokers/broker/dhan/domain/value_objects.py` | — |

### 3.2 Migration approach

The broker layer (`brokers/`) currently imports from `brokers/broker/entities.py` which re-exports from `shared.entities.models`. This creates a confusing indirection:

```
brokers/broker/dhan/application/broker.py
  → from brokers.broker.entities import Position
    → from shared.entities.models import Position
```

**Option A (minimal change):** Keep `brokers/broker/entities.py` as a compatibility shim, but document it clearly. Update broker-internal code to import from `shared.entities.models` directly over time.

**Option B (clean removal):** Remove `brokers/broker/entities.py` entirely, update all 20+ broker files to import from `shared.entities.models` directly. Delete `brokers/broker/__init__.py` re-exports.

**Recommendation:** Option B for a clean architecture, but it's a large mechanical change. Option A is safer for incremental progress.

### 3.3 Steps

#### Step 1: Remove `brokers/broker/entities.py` re-export shim
1. Update all broker-internal imports to use `shared.entities.models` directly
2. Delete `brokers/broker/entities.py`
3. Update `brokers/broker/__init__.py` to import from `shared.entities.models`

#### Step 2: Remove `OrderStatus.COMPLETED` alias
1. Find all usages of `OrderStatus.COMPLETED`
2. Replace with `OrderStatus.FILLED`
3. Delete the alias

#### Step 3: Remove `Instrument.__init__` backward compat
1. Find all callers using `Instrument(symbol=..., exchange=...)`
2. Migrate to `Instrument(symbol=..., exchange=Exchange.NSE)` explicit form
3. Delete the `__init__` override

#### Step 4: Remove `StateProjector` removal notice
1. Delete the dead code documentation

#### Step 5: Consolidate `RiskState`
1. Verify `quant/state_machine.py` `PositionState` is unused
2. Delete the legacy class

---

## 4. Files to Modify

### High confidence (safe mechanical changes)
| File | Change |
|---|---|
| `brokers/broker/__init__.py` | Update import source |
| `brokers/broker/dhan/application/broker.py` | Update import source |
| `brokers/broker/dhan/application/converters.py` | Update import source |
| `brokers/broker/dhan/application/order_converter.py` | Update import source |
| `brokers/broker/dhan/application/portfolio_converter.py` | Update import source |
| `brokers/broker/dhan/application/quote_converter.py` | Update import source |
| `brokers/broker/dhan/application/services/*.py` | Update import source |
| `brokers/broker/dhan/tests/*.py` | Update import source |

### Medium confidence (need to verify callers)
| File | Change |
|---|---|
| `shared/entities/models.py` | Remove `OrderStatus.COMPLETED`, `Instrument.__init__` backward compat |
| `quant/state_machine.py` | Delete legacy `PositionState` |

---

## 5. Migration Gates

| Gate | Criteria |
|---|---|
| **B1** | All broker tests pass after removing `brokers/broker/entities.py` |
| **B2** | All tests pass after removing `OrderStatus.COMPLETED` |
| **B3** | All tests pass after removing `Instrument.__init__` backward compat |
| **B4** | No import cycles introduced |
| **B5** | No duplicate class names across layers |

---

## 6. Risks

| Risk | Mitigation |
|---|---|
| Import cycle: `shared` → `quant` | `shared` must remain leaf-level; only `quant` imports from `shared` |
| Broker tests break | Run full broker test suite after each shim removal |
| Missed import of removed shim | `grep -rn "brokers.broker.entities"` to find stragglers |

---

**Next step:** Execute Step 1 — remove `brokers/broker/entities.py` shim.
