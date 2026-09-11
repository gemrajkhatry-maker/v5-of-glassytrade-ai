# Codebase Audit: Duplication, Code Smells & Architectural Issues Review

> **Audit Execution Date:** 2026-09-11  
> **Source Repository:** `/Users/apple/Documents/v5-of-glassytrade-ai`  
> **Diagnostic Tools:** `graphify` Knowledge Graph (15,223 nodes, 34,414 edges, 557 communities), AST parsers, Architectural Fitness Functions  
> **Scope:** Full-stack codebase — Quant Core (`quant/`), Backend Shell (`backend/app/`), Broker Adapters (`brokers/`), Shared Domain (`shared/`), and Dashboard UI (`frontend/`)

---

## Executive Summary

An exhaustive analysis of the codebase reveals a robust core trading engine with clean domain isolation (enforced by automated architecture fitness tests) and a mathematically sound Auction Market Theory (AMT) event-sourcing pipeline. 

However, as the codebase evolved through multiple iterations (v1 through v5), **structural duplication, monolithic god classes, layer boundary bleeds, and dead scaffolding** have accumulated. This review documents every concrete finding with file-and-line evidence, assesses its severity, and provides an actionable remediation plan.

### Summary Scorecard

| Category | Severity | Findings Count | Primary Risk |
|:---|:---:|:---:|:---|
| **1. Domain Entity Duplication** | HIGH | 6 core models duplicated | Drift across domain vs. broker representations; mapping overhead |
| **2. Logic & Algorithm Duplication** | MEDIUM | 6 duplicated subsystems | Divergent lot-sizing, underlying symbol parsing, and PnL math |
| **3. God Classes & Monolithic Files** | HIGH | 6 classes >1,000 LOC | High cognitive load, thread contention, low unit testability |
| **4. Architectural Layering & Bleed** | MEDIUM | 5 layer boundary leaks | Broker/API layers directly reaching into quant domain internals |
| **5. Code Smells & Dead Scaffolding** | MEDIUM | 9 silent `except: pass`, 1,300+ unreferenced symbols | Swallowed broker errors, phantom services (`TradeJournal`) |
| **6. Number System & Precision Parity** | LOW-MEDIUM | Dual `float` vs. `Decimal` | Float rounding vs. broker Decimal representation |

---

## 1. Domain Entity & Data Model Duplication

The system defines duplicate data classes for fundamental trading concepts across different packages. While some separation between broker-agnostic domain entities and broker-specific transfer objects is legitimate, multiple internal models share identical names and overlapping responsibilities without clear architectural justification.

```
┌──────────────────────────────────────────────────────────────────────────────────┐
│                             ENTITY DUPLICATION MATRIX                           │
├───────────────┬──────────────────────────────────────────────────────────────────┤
│ Entity        │ Confirmed Definitions in Codebase                                │
├───────────────┼──────────────────────────────────────────────────────────────────┤
│ Position      │ 1. quant/execution/order.py:L15       (Engine Position Aggregate)│
│               │ 2. quant/contracts/entities.py:L149    (Broker-Agnostic Entity)  │
│               │ 3. shared/entities/models.py:L254      (Legacy Shared Entity)    │
├───────────────┼──────────────────────────────────────────────────────────────────┤
│ Signal        │ 1. quant/decision/signal_builder.py:L54(Engine Decision Signal)  │
│               │ 2. quant/contracts/entities.py:L73     (Broker Wire Signal)      │
├───────────────┼──────────────────────────────────────────────────────────────────┤
│ Order         │ 1. quant/execution/order.py:L9        (Execution Order Model)    │
│               │ 2. shared/entities/models.py:L133      (Shared Models Order)     │
├───────────────┼──────────────────────────────────────────────────────────────────┤
│ OHLC / Bar    │ 1. quant/bars.py:L11                  (Bar: Float Candle)        │
│               │ 2. quant/contracts/value_objects.py:L19(OHLC: Decimal Candle)    │
│               │ 3. brokers/broker/dhan/domain/value_objects.py:L460 (Dhan OHLC)  │
├───────────────┼──────────────────────────────────────────────────────────────────┤
│ Tick          │ 1. quant/brokers/gateway.py:L10       (Quant Ingestion Tick)     │
│               │ 2. shared/entities/models.py:L120      (Shared Protocol Tick)    │
├───────────────┼──────────────────────────────────────────────────────────────────┤
│ MarketDepth   │ 1. brokers/broker/dhan/domain/value_objects.py:L397 (Dhan Depth) │
│               │ 2. shared/entities/models.py:L239      (Shared Market Depth)     │
└───────────────┴──────────────────────────────────────────────────────────────────┘
```

### Detailed Findings:

#### 1.1 `Position` Defined 3 Times
- [`quant/execution/order.py:L15`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/execution/order.py#L15): The live execution position model tracking `entry_price`, `quantity`, `trailing_stop`, `unrealized_pnl`, and `pyramids`.
- [`quant/contracts/entities.py:L149`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/contracts/entities.py#L149): Pydantic/dataclass domain position holding `Decimal` attributes and timestamps.
- [`shared/entities/models.py:L254`](file:///Users/apple/Documents/v5-of-glassytrade-ai/shared/entities/models.py#L254): A third position class with PnL calculation methods.
- **Risk:** Fills and order status updates must constantly map back and forth between these models (`to_position()`, `broker_position_to_fill()`). A field added to one is easily missed in the others.

#### 1.2 `Signal` Incompatibility (`quant/decision` vs `quant/contracts`)
- [`quant/decision/signal_builder.py:L54`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/decision/signal_builder.py#L54): Frozen dataclass, directional string (`LONG` / `SHORT`), native `float` pricing, explicit gate references, and model labels.
- [`quant/contracts/entities.py:L73`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/contracts/entities.py#L73): Mutable Pydantic model with `SignalType.BUY` / `SignalType.SELL`, `Decimal` price, and UUID string.
- **Risk:** Required the creation of a translation bridge ([`quant/execution/broker_mapper.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/execution/broker_mapper.py#L27)) where quantity was historically dropped during mapping (the C1 principal defect).

#### 1.3 `OHLC` Name Collision
- [`quant/contracts/value_objects.py:L19`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/contracts/value_objects.py#L19) and [`brokers/broker/dhan/domain/value_objects.py:L460`](file:///Users/apple/Documents/v5-of-glassytrade-ai/brokers/broker/dhan/domain/value_objects.py#L460) both export `OHLC`.
- **Graphify Finding:** In `graphify`, multiple domain classes in `quant/amt/analyzer.py` and `quant/amt/market/` had their semantic edges mapped to the broker's `OHLC` rather than the domain `OHLC` due to identical symbol resolution in the AST.

---

## 2. Logic & Algorithm Duplication

### 2.1 Lot Size & Snap Authority Fragmentation
Lot sizes and lot-snapping logic are scattered across four different files:
1. [`quant/execution/lots.py:L8`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/execution/lots.py#L8): `snap_to_lot(qty, lot_size)`. (Sanctioned authority).
2. [`quant/contracts/exchange_config.py:L35`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/contracts/exchange_config.py#L35): `ExchangeConfig.get_lot_size(symbol)`.
3. [`brokers/broker/market_info.py:L25`](file:///Users/apple/Documents/v5-of-glassytrade-ai/brokers/broker/market_info.py#L25): Hardcoded lot size dictionaries for NIFTY, BANKNIFTY, CRUDEOIL, etc.
4. [`brokers/broker/dhan/application/broker.py:L950-L1000`](file:///Users/apple/Documents/v5-of-glassytrade-ai/brokers/broker/dhan/application/broker.py#L950-L1000): Complex 4-step fallback resolving lot size through security ID, symbol mapper, regex, and finally `ExchangeConfig`.

### 2.2 Underlying Symbol Extraction Regexes
Extracting the root commodity or index (e.g. `CRUDEOIL` from `CRUDEOIL24SEP6200CE`) is independently re-implemented with distinct regex patterns in:
- [`backend/app/domain/ops/startup_reconciliation.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/backend/app/domain/ops/startup_reconciliation.py)
- [`brokers/broker/dhan/application/exchange_resolver.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/brokers/broker/dhan/application/exchange_resolver.py)
- [`quant/amt/session/futures_provider.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/amt/session/futures_provider.py)
- [`quant/amt/session/symbol_registry.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/amt/session/symbol_registry.py)

### 2.3 Option Instrument Classification
Determining whether a contract is an option, call, or put:
- `is_option_contract()` in [`quant/contracts/instrument_registry.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/contracts/instrument_registry.py)
- `is_call_symbol()` / `is_put_symbol()` in [`quant/contracts/vocabulary.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/contracts/vocabulary.py)
- `is_option_symbol()` in [`brokers/broker/utils/symbol.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/brokers/broker/utils/symbol.py)
- `.is_option()` method on `DhanInstrument` in [`brokers/broker/dhan/domain/instrument.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/brokers/broker/dhan/domain/instrument.py)

---

## 3. God Classes & Monolithic Modules

Multiple files exceed 1,000 lines of code, aggregating numerous unrelated concerns:

```
┌────────────────────────────────────────────────────────────────────────────────────────┐
│                        TOP 6 MONOLITHS (GOD CLASSES / MODULES)                         │
├────────────────────────────────────────────────┬────────────┬─────────────┬────────────┤
│ File Path                                      │ Total LOC  │ Code LOC    │ Graph Edges│
├────────────────────────────────────────────────┼────────────┼─────────────┼────────────┤
│ 1. quant/runtime.py                            │ 1,917 lines│ 1,519 lines │ 324 edges  │
│ 2. quant/multi_engine.py                       │ 1,912 lines│ 1,551 lines │ 158 edges  │
│ 3. frontend/components/ChartScene.tsx          │ 1,637 lines│ 1,322 lines │  45 edges  │
│ 4. backend/app/infrastructure/adapters/dhan... │ 1,135 lines│   956 lines │  98 edges  │
│ 5. quant/amt/analyzer.py                       │ 1,102 lines│   858 lines │ 198 edges  │
│ 6. backend/app/infrastructure/storage/database │ 1,097 lines│   976 lines │  74 edges  │
└────────────────────────────────────────────────┴────────────┴─────────────┴────────────┘
```

### Detailed Evaluation of Monoliths:

#### 3.1 `QuantEngine` in [`quant/runtime.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/runtime.py) (1,917 Lines)
- **Concerns Bundled:**
  1. Tick ingestion and gateway polling loop (`_run_inner`)
  2. Bar aggregation and candle interval boundaries
  3. AMTEngine execution and history seed ingestion
  4. Decision service evaluation, gate checking, and signal clamping
  5. Position management (pyramids, trailing stops, scale-outs)
  6. Exit evaluation across 6 exit reasons
  7. Risk management checks and session halt transitions
  8. OMS order submission and execution response processing
  9. Event bus emission (`_emit`) and EventStore appending
  10. Depth cache, quote cache, and WebSocket view-state serialization
- **Impact:** Testing any single concern requires initializing a massive harness. Hard to reason about concurrent state mutations.

#### 3.2 `QuantCoordinator` in [`quant/multi_engine.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/multi_engine.py) (1,912 Lines)
- **Concerns Bundled:**
  1. Contract universe persistence and file IO
  2. Thread pool lifecycle (`ThreadPoolExecutor`) and run task tracking
  3. Dynamic strike rotation and strike migration logic
  4. Cross-engine portfolio risk monitoring (`PortfolioRiskAuthority`)
  5. Multiplexed market feed subscription orchestration
  6. Rate-limited history seeding coordination (`HistorySeedScheduler`)
  7. Intraday EOD square-off daemon thread
  8. WebSocket viewer snapshot aggregation (`snapshot()`)
- **Impact:** High lock contention between `_lifecycle_lock` and engine threads during symbol rotation.

#### 3.3 `ChartScene.tsx` in [`frontend/components/ChartScene.tsx`](file:///Users/apple/Documents/v5-of-glassytrade-ai/frontend/components/ChartScene.tsx) (1,637 Lines)
- **Concerns Bundled:**
  1. Raw HTML5 Canvas rendering context management
  2. Candlestick coordinate math and scaling transforms
  3. Volume Profile horizontal histogram binning and drawing
  4. Session VWAP and Standard Deviation band projection
  5. Trade execution marker plotting and entry/exit line connectors
  6. Real-time cursor crosshair and floating price tag calculation
  7. DOM event listeners (wheel zoom, mouse drag pan, pinch gestures)
- **Impact:** Any modification to chart visual styling risks breaking canvas coordinate calculations.

#### 3.4 `AMTAnalyzer` in [`quant/amt/analyzer.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/amt/analyzer.py) (1,102 Lines)
- While designed as a facade, `analyze()` acts as a procedural pipeline running over 15 sub-calculations in a single pass with hundreds of intermediate variables.

---

## 4. Architectural Layering & Boundary Bleeds

Clean Architecture dictates that inner layers (Domain/Quant) must not know about outer layers (Adapters/Transport), and outer layers should interact with domain internals only through well-defined ports.

```
       ┌────────────────────────────────────────────────────────┐
       │             OUTER: Adapters & Transports               │
       │    backend/app/api/          brokers/broker/dhan/      │
       └───────────────────────────┬────────────────────────────┘
                                   │
             LEAK 1: broker.py ───┐│ LEAK 2: market.py imports
             imports ExchangeCfg  ││ HalfTrend detector directly
                                  ▼▼
       ┌────────────────────────────────────────────────────────┐
       │             INNER: Quant Core Domain                   │
       │    quant/contracts/          quant/amt/                │
       └────────────────────────────────────────────────────────┘
```

### Confirmed Layer Leaks:

1. **Broker Adapter Importing Domain Configuration Directly**:
   - In [`brokers/broker/dhan/application/broker.py:L995`](file:///Users/apple/Documents/v5-of-glassytrade-ai/brokers/broker/dhan/application/broker.py#L995):
     ```python
     from quant.contracts.exchange_config import ExchangeConfig
     ```
   - *Violation:* The broker adapter (infrastructure) is directly importing quant core domain configuration to resolve lot sizes, rather than relying on injected configuration or broker-provided specifications.

2. **REST API Routers Importing Quant Internal Indicators Directly**:
   - In [`backend/app/api/routers/market.py:L44`](file:///Users/apple/Documents/v5-of-glassytrade-ai/backend/app/api/routers/market.py#L44):
     ```python
     from quant.amt.market.half_trend import compute_half_trend_series
     ```
   - *Violation:* The web router bypasses the application service layer and directly imports a specific mathematical indicator from deep within `quant/amt/market/`.

3. **Analysis Router Directly Instantiating Analyzers**:
   - In [`backend/app/application/services/analysis_service.py:L5-L6`](file:///Users/apple/Documents/v5-of-glassytrade-ai/backend/app/application/services/analysis_service.py#L5-L6):
     ```python
     from quant.amt.analyzer import AMTAnalyzer
     from quant.amt.orderflow.footprint import FootprintAnalyzer
     ```
   - *Violation:* Application service creates ad-hoc unmanaged instances of domain analyzers to service one-off REST analysis requests outside the `QuantCoordinator` execution brain.

4. **Health Router Reaching into Feature Extraction**:
   - In [`backend/app/api/routers/health.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/backend/app/api/routers/health.py): Directly imports `quant.probability.features`.

---

## 5. Code Smells & Dead Scaffolding

### 5.1 Silent Exception Swallowing (`except: pass`)
Graphify and AST checks identified **9 occurrences** of unlogged `except: pass` blocks in production broker code:

| File Location | Context | Risk |
|:---|:---|:---|
| [`brokers/broker/dhan/application/broker.py:L373`](file:///Users/apple/Documents/v5-of-glassytrade-ai/brokers/broker/dhan/application/broker.py#L373) | `__del__` destructor cleanup | Leaked background threads during interpreter shutdown |
| [`brokers/broker/dhan/application/broker.py:L959`](file:///Users/apple/Documents/v5-of-glassytrade-ai/brokers/broker/dhan/application/broker.py#L959) | `get_lot_size` symbol resolution | Swallows network/mapper errors during lot resolution |
| [`brokers/broker/dhan/application/broker.py:L1000`](file:///Users/apple/Documents/v5-of-glassytrade-ai/brokers/broker/dhan/application/broker.py#L1000) | `ExchangeConfig` fallback | Masks invalid exchange metadata |
| [`brokers/broker/dhan/application/services/streaming_service.py:L102,121,135,143`](file:///Users/apple/Documents/v5-of-glassytrade-ai/brokers/broker/dhan/application/services/streaming_service.py#L102) | WebSocket subscription retries | Silently ignores dropped subscription packets |
| [`brokers/broker/dhan/infrastructure/symbol_mapper.py:L512,565`](file:///Users/apple/Documents/v5-of-glassytrade-ai/brokers/broker/dhan/infrastructure/symbol_mapper.py#L512) | Parsing security ID master list | Corrupted CSV rows silently skipped without telemetry |

### 5.2 Phantom Service: `TradeJournal`
- [`backend/app/application/services/trade_journal.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/backend/app/application/services/trade_journal.py) (1,031 lines) implements a full journal with `log_signal()`, `log_entry()`, `log_exit()`.
- **Graphify Discovery:** There are **zero production writers** calling `log_signal()` or `log_entry()` from `QuantEngine` or `QuantCoordinator`.
- Real production persistence is performed directly by `quant/persistence.py` (`Journal` JSONL file) and `SQLiteStorageAdapter` (`database.py`).
- The entire 1,031 lines of `trade_journal.py` serve historical queries from `/api/journal` over empty or manually populated data structures.

### 5.3 Dead Narrative Predicates in `quant/llm/narrative.py`
- Contains **40 uncalled functions** (e.g. `_pos_take_profit_pred`, `_pos_long_vwap_exhaustion_pred`, `_pos_long_exhaustion_build`).
- These represent a deprecated, rule-based text generation scaffold that was superseded by the dynamic LLM advisor and TimesFM agents.

---

## 6. Number System & Precision Parity

The codebase operates with dual precision models:
1. **The Fast Quant Core (`quant/`)**:
   - Uses native 64-bit IEEE 754 `float` for prices, volumes, indicators, and delta math (`quant/bars.py`, `quant/amt/`, `quant/runtime.py`).
   - *Rationale:* Essential for sub-millisecond calculation speeds, NumPy/SciPy integration, and TimesFM vector forecasting.
2. **The Wire & Accounting Layer (`quant/contracts/entities.py`, `shared/money.py`)**:
   - Uses Python `Decimal` for financial monetary values, broker order requests, and PnL accounting.
- **Code Smell:** Forces constant translation wrappers across the boundary:
  - `_to_decimal()` and `_to_float()` are invoked on every order submission and fill ingestion.
  - Risk of floating-point comparison issues (e.g. `6200.000000000001 != 6200.00`) when checking price stops or limit targets unless snapped via `round()` or `snap_to_tick()`.

---

## 7. Actionable Refactoring Roadmap

To address these findings without destabilizing the certified trading core, execute the following 4-phase refactoring plan:

### Phase 1: Clean Up Dead Code & Swallowed Exceptions (Low Risk)
- [ ] **Remove or deprecate `quant/llm/narrative.py` dead predicates:** Delete the 40 unused rule functions.
- [ ] **Fix 9 silent `except: pass` occurrences:** Replace with `logger.debug()` or `logger.warning()` containing proper exception context (`exc_info=True`).
- [ ] **Decommission or re-wire `TradeJournal`:** Either connect `TradeJournal` to `EventStore` events via an event listener, or delete the dead writer methods in `trade_journal.py` and unify journal queries with SQLite.

### Phase 2: Unify Domain Entities & SSoT (Medium Risk)
- [ ] **Consolidate `Position` & `Order` Models:**
  - Standardize on `quant/execution/order.py:Position` for active engine state.
  - Deprecate `shared/entities/models.py:Position` and `Order`.
- [ ] **Merge `Signal` Models:**
  - Allow `quant/decision/signal_builder.py:Signal` to serve as the unified signal object across both the engine and broker adapters.
- [ ] **Unify Underlying Regex Extraction:**
  - Promote `quant/contracts/vocabulary.py:extract_underlying()` as the single authoritative function; remove local regex copies in `startup_reconciliation.py`, `futures_provider.py`, and `exchange_resolver.py`.

### Phase 3: De-Monolith God Classes (Architectural Refactor)
- [ ] **Decompose `QuantEngine` (`quant/runtime.py`):**
  - Extract tick ingestion and bar aggregation into an `IngestionCoordinator`.
  - Extract order lifecycle and fill processing into a dedicated `ExecutionHandler`.
  - Retain `QuantEngine` strictly as the state-machine orchestrator.
- [ ] **Split `frontend/components/ChartScene.tsx`:**
  - Separate raw Canvas lifecycle from rendering layers:
    - `CandleRenderer.ts`
    - `VolumeProfileRenderer.ts`
    - `VWAPRenderer.ts`
    - `InteractionController.ts` (crosshair, zoom, pan).

### Phase 4: Enforce Strict Port Inversion (Fitness Hardening)
- [ ] **Invert Broker ExchangeConfig Dependency:**
  - Remove `from quant.contracts.exchange_config import ExchangeConfig` from `brokers/broker/dhan/application/broker.py`.
  - Pass exchange lot size metadata into `DhanBroker` via its configuration constructor.
- [ ] **Route Router Indicators through Use-Case Services:**
  - Route `/market/halftrend` and `/analysis` through `TradingQueryService` rather than directly importing `quant/amt/` modules into FastAPI routers.

---
*Report compiled via static code inspection and knowledge graph queries from `graphify`.*
