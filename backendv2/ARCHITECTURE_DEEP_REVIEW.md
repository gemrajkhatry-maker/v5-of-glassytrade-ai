# Architecture Review — GlassyTrade AI v5 BackendV2
## Principal Engineer / Staff+ Assessment

**Reviewer**: Staff+ Architecture Review  
**Scope**: `backendv2/app/` — 285 source files, ~40,000 LOC, 166 test files  
**Methodology**: Static analysis, import-graph tracing, layer violation detection, duplication detection, flow tracing, god-class identification  
**Date**: 2026-05-10

---

# 1. Executive Summary

## Overall Grade: C+ (Acceptable for a startup, but with material structural debt)

BackendV2 demonstrates **genuine architectural intent** — hexagonal architecture with ports/adapters, event-driven decoupling, clean layering, and domain isolation. However, **execution drift has accumulated significantly**: the codebase exhibits material shotgun surgery, feature scattering, god classes, layer violations, and duplication that will materially slow developer velocity and increase operational risk as the system scales.

### The Good
- **Domain isolation is real**: Zero imports from `domain/` to `infrastructure/`, `api/`, or `application/`. This is textbook clean architecture and the project's strongest architectural asset.
- **Port/Adapter pattern is consistently applied**: `IBroker`, `IMarketData`, `ILLMInference`, `IStorage`, `INotification`, `IProbabilityInference` are well-defined and implemented by concrete adapters.
- **Event-driven architecture reduces coupling**: `EventBus` decouples handlers; domain events are immutable.
- **Test coverage is respectable**: 2,269 tests passing, covering critical paths.

### The Bad
- **Signal lifecycle touches 81 files** (28.6% of codebase). Changing signal confidence thresholds requires edits across 7+ files in 4 layers.
- **VWAP computation is scattered across 48 files** — multiple services re-derive VWAP instead of passing a canonical object downstream.
- **Risk management is split across 3 packages**: `domain/risk/`, `domain/trading/`, `runtime/pipeline/`. Changing a daily loss limit requires edits in 4+ files.
- **7 god classes exceed 500 lines**, with `LLMEntryHandler` at 1,072 lines handling LLM orchestration, prompt building, JSON parsing, error recovery, MCX filtering, session phase logic, and safety nets.

### The Ugly
- **Layer violations exist**: `domain/exit/service/exit_engine.py` imports from `runtime/pipeline/events.py`. `application/handlers/` import from `runtime/pipeline/events.py` and `infrastructure/messaging/event_bus.py`.
- **Global singletons**: `get_cost_tracker()` uses module-level mutable state with double-checked locking. `MLXInferenceAdapter` stores class-level mutable cloud-throttling state.
- **Duplicate class names**: `InitialBalanceEngine`, `PartitionExitManager`, `AlertManager`, `EventStore` each have 2+ implementations in different directories.
- **A single tick flows through 25+ files** before becoming a position. This is not decoupled; it is distributed.

### Bottom Line
The codebase is **functionally complete** but **architecturally fragile**. The original hexagonal design has drifted toward a distributed monolith where business logic is scattered across runtime pipelines, application handlers, domain services, and infrastructure adapters. **Without structural consolidation, adding new trading strategies, exchanges, or signal types will require shotgun surgery across 20+ files.**

---

# 2. Architectural Risk Assessment

## 2.1 Risk Matrix

| Risk Category | Severity | Likelihood | Impact | Mitigation Urgency |
|---------------|----------|------------|--------|-------------------|
| Shotgun surgery on signal lifecycle | **Critical** | **High** | Every new signal type or confidence change requires 7+ file edits | Immediate |
| God class maintenance burden | **High** | **High** | `LLMEntryHandler` (1,072L), `SessionRuntime` (761L), `MLXInferenceAdapter` (788L) are single points of failure | Immediate |
| Layer violations (domain→runtime, app→infra) | **High** | **Medium** | Violations erode clean architecture guarantees; testing becomes harder | High |
| Duplicate VWAP computation (48 files) | **High** | **High** | Band changes require edits across signal generation, gate evaluation, LLM safety nets, feature computation, and serialization | High |
| Risk logic fragmentation (3 packages) | **Medium** | **High** | Daily loss limits, position sizing, and circuit breakers are split across `domain/risk/`, `domain/trading/`, `domain/exit/`, `runtime/pipeline/risk.py` | High |
| Global singleton mutable state | **Medium** | **Medium** | `get_cost_tracker()`, `MLXInferenceAdapter` class-level state make parallel sessions and testing unreliable | Medium |
| Duplicate event hierarchies | **Medium** | **Medium** | `runtime/pipeline/events.py` and `domain/shared/event/` define parallel event taxonomies; adding a field requires 4+ edits | Medium |
| Config access scattered in domain services | **Medium** | **High** | 21 files read config directly; domain services should not know about config files | Medium |
| Test coverage gaps on large modules | **Low** | **High** | Exit engine, exit rules, risk manager lack dedicated tests; god classes are under-tested relative to their size | Medium |
| Duplicate class names (IBEngine, EventStore, etc.) | **Low** | **Medium** | Developer confusion, import ambiguity, potential runtime bugs from wrong import | Low |

## 2.2 Scalability Risks

1. **Symbol scaling**: Per-symbol state dictionaries in `RiskEvaluation`, `GateEvaluation`, `OrderFlowPipeline` grow unbounded. Adding 100 symbols will cause memory pressure.
2. **Pipeline stage scaling**: `SessionRuntime` manually wires ~15 pipeline stages. Adding a new stage requires editing `session.py`. There is no plugin architecture.
3. **Exchange scaling**: Exchange-specific logic (NSE phases, MCX commodity filtering) is hardcoded in handlers. Adding a new exchange requires edits across `llm_entry_handler.py`, `session_phase_gate.py`, and `bootstrap/infrastructure.py`.
4. **Model scaling**: LLM inference has 3 parallel prompt-building paths. Adding a new model provider requires edits in `prompt_builder.py`, `llm_entry_handler.py`, and adapter files.
5. **Strategy scaling**: Trading strategies (breakout scalp, AAA, mean reversion) are scattered across `domain/services/`, `domain/amt/`, and `runtime/pipeline/`. Adding a new strategy requires understanding and editing 10+ files.

---

# 3. Shotgun Surgery Findings

## 3.1 Signal Lifecycle — 81 Files Touched

**Root Cause**: Signal is not a single canonical object passed through a pipeline. Instead, signal generation, validation, grading, gating, risk evaluation, position creation, and event emission each re-interpret signal data from their own event/handler context.

**Dependency Chain**:
```
Tick → CandlePipeline → SignalGeneration → GateEvaluation → RiskEvaluation → PositionLifecycle → ExecutionPipeline → EventPersistence
         ↑___________↑______________↑______________↑________________↑_________________↑_________________↑
              7 separate files, each re-computes or re-interprets signal data
```

**Files requiring change for "add signal confidence threshold"**:
1. `runtime/pipeline/signal.py` — generation logic
2. `runtime/pipeline/gates.py` — gate rejection thresholds  
3. `domain/amt/service/entry_gates.py` — domain gate logic
4. `domain/fabio_ai/services/entry_gates/grading.py` — AI grading
5. `application/handlers/evaluate_entry_handler.py` — command handler
6. `application/handlers/llm_entry_handler.py` — LLM safety nets
7. `infrastructure/serialization/schemas.py` — validation schema
8. `domain/shared/event/signal.py` — domain event
9. `runtime/pipeline/events.py` — runtime event

**Coupling Source**: No canonical `Signal` value object that carries all signal metadata (confidence, grade, session phase, VWAP bias, aggression score) through the pipeline. Each stage extracts fields from raw `amt_result` dictionaries.

**Maintenance Impact**: Adding a new signal field requires 9+ file edits. Removing a field risks silent failures in stages that still reference it.

**Scaling Risk**: As signal sophistication grows (momentum confirmation, divergence checks, footprint alignment), the number of files touched per change grows linearly.

**Fix**: Create a single canonical `TradingSignal` value object in `domain/trading/model/value_objects.py` with all signal metadata. Every pipeline stage receives and returns `TradingSignal`. Stages extract what they need; no stage re-derives signal data from raw inputs.

---

## 3.2 VWAP Computation — 48 Files Touched

**Root Cause**: VWAP is computed in multiple places, and bands are re-derived from raw `amt_result` fields instead of being passed as a canonical object.

**Dependency Chain**:
```
Tick → VWAPService.compute() → amt_result.vwap, vwap_upper_1, vwap_lower_1, vwap_upper_2, vwap_lower_2
         ↓
    [48 files extract these 5 fields individually and re-compute or re-interpret]
```

**Files requiring change for "change VWAP band from 2σ to 3σ"**:
1. `domain/amt/service/vwap_service.py` — computation logic
2. `domain/amt/service/volume_profile.py` — alternate computation
3. `runtime/pipeline/signal.py` — signal entry/SL/TP derived from bands
4. `runtime/pipeline/gates.py` — gate evaluation references VWAP
5. `runtime/pipeline/features.py` — feature vector includes VWAP metrics
6. `domain/amt/service/amt_analyzer.py` — analyzer references bands
7. `domain/fabio_ai/services/entry_gates/signal_builder.py` — signal builder uses bands
8. `domain/fabio_ai/services/entry_gates/three_align.py` — alignment checks
9. `domain/fabio_ai/services/entry_gates/grading.py` — grading uses VWAP bias
10. `application/handlers/llm_entry_handler.py` — `_apply_safety_nets()` checks `vwap_upper_2`
11. `infrastructure/serialization/schemas.py` — schema validation
12. `application/handlers/trade_lifecycle_handler.py` — trailing stop references VWAP

**Coupling Source**: VWAP bands are stored as 5 separate float fields in `amt_result`. Consumers extract and interpret them individually. No `VWAPProfile` object encapsulates the computation and interpretation.

**Fix**: Create `VWAPProfile` value object with `price, bands: list[VWAPBand], bias: str`. Pass it through the pipeline. Consumers query `profile.is_price_above(2)` instead of `price > amt_result.vwap_upper_2`.

---

## 3.3 Risk Management — 63 Files Touched

**Root Cause**: Risk is not a unified domain. Daily drawdown, position sizing, circuit breakers, and kill switches are split across `domain/risk/`, `domain/trading/`, `domain/exit/`, and `runtime/pipeline/risk.py`.

**Dependency Chain**:
```
Tick → RiskEvaluation (runtime) → checks drawdown, position limits
         ↓
    domain/trading/service/risk_manager.py → portfolio-level risk
         ↓
    domain/risk/service/circuit_breakers.py → circuit breakers
         ↓
    domain/exit/service/position_sizer.py → position sizing
         ↓
    domain/exit/service/partition_exit_manager.py → exit risk
         ↓
    runtime/pipeline/gates.py → gate evaluation also does risk-like checks
```

**Files requiring change for "change daily loss limit from 2% to 3%"**:
1. `domain/risk/service/circuit_breakers.py` — breaker threshold
2. `domain/trading/service/risk_manager.py` — daily drawdown check
3. `runtime/pipeline/risk.py` — runtime risk evaluation
4. `domain/exit/service/loss_tracker.py` — loss tracking
5. `application/handlers/trade_lifecycle_handler.py` — handler references limits
6. `infrastructure/config/settings.py` — config value
7. `bootstrap/infrastructure.py` — config propagation

**Fix**: Create a single `RiskPolicy` domain service in `domain/risk/service/risk_policy.py` that owns all risk thresholds. All other modules import `RiskPolicy` and query it. Thresholds are injected at bootstrap; no hardcoded percentages outside `RiskPolicy`.

---

## 3.4 LLM Prompt Building — 49 Files Touched

**Root Cause**: Three parallel prompt-building paths exist with no shared abstraction. Each path constructs its own JSON/markdown context independently.

**Dependency Chain**:
```
Signal → prompt_builder.py (structured)
     → llm_entry_handler.py:_build_market_data_ai() (JSON context)
     → llm_rationale_service.py (rationale-specific)
     → llm_overseer_handler.py (overseer-specific)
```

**Files requiring change for "add OI/PCR to LLM context"**:
1. `domain/fabio_ai/services/prompt_builder.py` — add OI section
2. `application/handlers/llm_entry_handler.py` — pass OI data
3. `application/handlers/llm_overseer_handler.py` — pass OI data
4. `application/handlers/llm_rationale_service.py` — pass OI data
5. `domain/amt/service/narrative_builder.py` — narrative includes OI
6. `infrastructure/serialization/schemas.py` — schema for OI

**Fix**: Create `LLMContextBuilder` in `domain/fabio_ai/services/` with methods `build_entry_context()`, `build_overseer_context()`, `build_rationale_context()`. Each method delegates to shared `MarketContext`, `PositionContext`, `RiskContext` sub-builders. Adding a new data field requires one edit to the relevant sub-builder.

---

## 3.5 Tick-to-Position Flow — 25+ Files

**Root Cause**: The tick processing pipeline is a distributed pipeline with no central contract. Each stage extracts what it needs from the previous stage's output.

**Full Flow**:
```
1. runtime/feeds/live.py          → receives raw tick
2. runtime/feeds/dhan_feed.py     → feed adapter
3. runtime/orchestrator/session.py → run_once() / _process_tick()
4. runtime/pipeline/sequencer.py   → sequence tick
5. runtime/pipeline/normalizer.py  → normalize
6. runtime/pipeline/candle_builder.py → build candles
7. runtime/pipeline/orderflow.py   → orderflow metrics
8. runtime/pipeline/microstructure.py → microstructure
9. runtime/pipeline/market_structure.py → market structure
10. runtime/pipeline/features.py  → feature vector
11. runtime/pipeline/signal.py    → signal generation
12. runtime/pipeline/gates.py     → gate evaluation
13. runtime/pipeline/risk.py      → risk check
14. runtime/pipeline/position.py  → position open
15. runtime/pipeline/execution.py → order submission
16. runtime/pipeline/broker_sync.py → sync fills
17. runtime/pipeline/persistence.py → persist events
18. application/handlers/update_tick_handler.py → app-layer tick handler
19. application/handlers/amt_handler.py → AMT processing
20. application/handlers/evaluate_entry_handler.py → entry evaluation
21. application/handlers/llm_entry_handler.py → LLM gating
22. application/event_subscribers.py → event subscribers
23. infrastructure/messaging/event_bus.py → event bus
24. infrastructure/adapters/dhan_adapter.py → broker adapter
25. infrastructure/serialization/schemas.py → serialization
```

**Fix**: Introduce a `TickContext` value object that accumulates computed state as it flows through the pipeline. Each stage reads from and writes to `TickContext`. No stage re-computes what a previous stage already computed.

---

# 4. Structural Inconsistencies

## 4.1 Duplicate Directory Patterns

| Pattern | Locations | Issue |
|---------|-----------|-------|
| `domain/services/` and `domain/amt/service/` | Both contain trading logic | `domain/services/` has `initial_balance_engine.py`, `vwap_tracker.py`, `ib_breakout_scalp.py` — all AMT-related. These should be in `domain/amt/service/`. |
| `domain/fabio_ai/services/` and `domain/amt/service/` | Both have `session_context.py` | Same concept, two implementations. `domain/amt/service/session_context.py` and `domain/fabio_ai/services/session_context.py`. |
| `app/core/` and `app/domain/trading/` | Both have `event_store.py` | `core/event_store.py` is in-memory list store. `domain/trading/event_store.py` is an ABC with JSON serialization. |
| `app/application/di/` and `app/bootstrap/` | Both have `container.py` | `application/di/container.py` is the DI container. `bootstrap/container.py` is bootstrap-specific DI. Two DI systems. |
| `app/application/event_bus.py` and `app/infrastructure/messaging/event_bus.py` | Both expose EventBus | Application layer re-exports infrastructure event bus, creating a module-level alias that hides the dependency. |

## 4.2 Mixed Responsibilities Within Files

| File | Responsibilities | Grade |
|------|-----------------|-------|
| `llm_entry_handler.py` (1,072L) | LLM inference orchestration, worker thread management, per-symbol queueing, prompt building, response parsing, normalization, persistence, session phase logic, MCX filtering, safety nets | **F** |
| `agent_pipeline.py` (906L) | RegimeAgent, DirectionAgent, TimingAgent, SizingAgent, Kelly formula, regime hysteresis, CVD slope checks | **F** |
| `mlx_inference_adapter.py` (788L) | MLX model loading, VLM detection, cloud fallback inference, GPU locking, response extraction, token cost tracking, singleton management | **F** |
| `session.py` (761L) | Pipeline stage wiring, session lifecycle, threading locks, metrics, symbol history, AAA evaluation, phase gating | **D** |
| `schemas.py` (632L) | OHLC, AMT, signals, positions, chat messages, volume profiles, aggressive prints, footprint data — 20+ DTOs | **D** |
| `dhan_adapter.py` (514L) | Market data fetch, order book, streaming, option chain, lot sizes, retry logic, caching | **D** |
| `database.py` (422L) | SQLite storage, 10+ tables, CRUD, migration helpers, tick batching | **D** |
| `trade_lifecycle_handler.py` (367L) | Entry evaluation, exit checking, breakeven, trailing, partial TP, position updates, event publishing | **C** |

## 4.3 Naming Inconsistencies

| Inconsistency | Examples |
|---------------|----------|
| `service/` vs `services/` | `domain/amt/service/` (singular) vs `domain/fabio_ai/services/` (plural) |
| `handler/` vs `handlers/` | `application/handlers/` (plural) — consistent, but `application/handler/` would be singular |
| `model/` vs `models/` | `domain/trading/model/` (singular) vs `domain/trading/model/entities.py` uses plural class names |
| Port file naming | `broker.py`, `market_data.py`, `llm_inference.py` (consistent) but `notifications.py` (plural) |
| Event file naming | `signal.py`, `position.py`, `market.py` (singular) but `risk.py` (singular) |

## 4.4 Inconsistent Abstraction Levels

- `runtime/pipeline/events.py` defines both low-level dataclasses (`Tick`, `OHLC`) and high-level domain events (`Signal`, `PositionEvent`, `ExitDecision`) in the same file.
- `domain/shared/event/` has parallel event taxonomy with `DomainEvent` base class, but runtime pipeline does not use it.
- `domain/exit/service/exit_engine.py` contains `ExitEngine`, `TrailEngine`, `PartitionExitManager`, and `TradeManagerConfig` — 4 abstractions at different levels in one file.

---

# 5. Dependency Graph Analysis

## 5.1 Layer Dependency Matrix

```
              domain  application  runtime  infrastructure  api  core  shared  bootstrap
domain           ✓         ✗         ✗            ✗          ✗    ✗      ✓         ✗
application      ✓         ✓         ✓            ✓          ✗    ✗      ✓         ✗
runtime          ✓         ✗         ✓            ✓          ✗    ✗      ✓         ✗
infrastructure   ✓         ✗         ✗            ✓          ✗    ✓      ✓         ✗
api              ✓         ✓         ✓            ✓          ✓    ✓      ✓         ✗
core             ✗         ✗         ✗            ✗          ✗    ✓      ✗         ✗
shared           ✗         ✗         ✗            ✗          ✗    ✗      ✓         ✗
bootstrap        ✓         ✓         ✓            ✓          ✓    ✓      ✓         ✓
```

**✓ = allowed, ✗ = violation**

**Critical violations**:
1. `application → runtime`: `llm_entry_handler.py` imports `Signal` from `runtime/pipeline/events`
2. `application → infrastructure`: 5 handlers import `EventBus` from `infrastructure/messaging/event_bus`
3. `runtime → infrastructure`: `persistence.py` imports `SQLiteStorageAdapter` directly
4. `domain → runtime`: `exit_engine.py` imports `ExitDecision` from `runtime/pipeline/events`

## 5.2 Circular Dependency Risk

No hard import cycles detected between major layers. However:
- `dhan_adapter.py` locally imports `OptionScannerService` inside a method (runtime cycle avoidance, but inverted dependency)
- `application/di/container.py` and `bootstrap/container.py` are two DI containers that may cross-reference

## 5.3 Dependency Hot-Spots

| Module | In-Degree | Out-Degree | Risk |
|--------|-----------|------------|------|
| `runtime/pipeline/events.py` | 12 | 0 | Central event schema; every change ripples |
| `domain/shared/port/market_data.py` | 8 | 0 | Port with 8 methods; 4 adapters implement it |
| `domain/trading/model/value_objects.py` | 25+ | 0 | Core value objects; imported everywhere |
| `infrastructure/serialization/schemas.py` | 15+ | 0 | DTOs imported by routers, handlers, and runtime |
| `runtime/orchestrator/session.py` | 3 | 15 | Orchestrator imports 15 pipeline stages |
| `application/handlers/llm_entry_handler.py` | 2 | 12 | Handler imports 12 different modules |

## 5.4 Framework Coupling

| Framework | Leaked Into | Severity |
|-----------|-------------|----------|
| FastAPI | `bootstrap/lifespan.py` (acceptable) | Low |
| Pydantic | `domain/fabio_ai/services/response_parser.py` (domain layer!) | **High** |
| SQLAlchemy | None | Clean |
| httpx | None in domain; used in infrastructure adapters | Clean |
| gymnasium | `domain/ai/rl/valentini_env.py` | Acceptable (isolated subdomain) |
| numpy | `domain/ai/rl/valentini_env.py`, `domain/probability/features.py` | Acceptable |

---

# 6. Duplication Analysis

## 6.1 Exact Duplication

| Duplicate | Location 1 | Location 2 | Lines |
|-----------|-----------|-----------|-------|
| `_extract_json_candidate` | `mlx_inference_adapter.py:712` | `gguf_inference_adapter.py:130` | ~15 lines |
| `wait_until_ready` polling loop | `mlx_inference_adapter.py:758` | `gguf_inference_adapter.py:149` | ~10 lines |
| `ENTRY_JSON_RUNTIME_REMINDER` | `mlx_inference_adapter.py:37` | `gguf_inference_adapter.py:16` | ~5 lines |
| `_deep_merge` recursive dict merge | `config_adapter.py:21` | `settings.py:166` | ~15 lines |
| `_read_yaml` / `_read_yaml_file` | `config_adapter.py:34` | `settings.py:154` | ~8 lines |
| `resolve_environment()` | `config_adapter.py:52` | `settings.py:145` | ~10 lines |
| `_to_domain_signal` | `position.py:272` | `risk.py:437` | ~20 lines |
| `_serialize_position` | `position.py:293` | `risk.py:455` | ~15 lines |
| `_deserialize_position` | `position.py:319` | `risk.py:474` | ~20 lines |
| Broker retry loop (`_post_create_order` / `_get_fill`) | `mcx_broker.py:179` | `mcx_broker.py:198` | ~15 lines each |
| EMA volume calculation inline loops | `mlx_compute.py:68` | `confirmation_bundle.py:48,110` | ~5 lines each |

## 6.2 Semantic Duplication

| Concept | Implementations | Issue |
|---------|-----------------|-------|
| ATR calculation | `mlx_compute.py:98`, `confirmation_bundle.py:145` | Same math, different interfaces |
| VWAP + bands | `volume_profile.py:125`, `vwap_service.py:64`, `market_data_utils.py:5` | Three separate computations |
| Position sizing | `entry_gates.py:8`, `gate_runner.py:46`, `position_sizer.py:101` | Three separate sizing logics |
| Session phase | `runtime/pipeline/gates.py`, `llm_entry_handler.py`, `session_phase_gate.py` | Three separate phase computations |
| Initial balance | `domain/services/initial_balance_engine.py`, `domain/amt/service/initial_balance_engine.py` | Two separate implementations |
| Event store | `core/event_store.py`, `domain/trading/event_store.py` | Two separate implementations |

## 6.3 Structural Duplication

| Pattern | Locations | Count |
|---------|-----------|-------|
| Pipeline stage `warmup()` / `teardown()` / `reset()` | 19 pipeline stage files | 19 |
| Safe float cast `try/except (TypeError, ValueError)` | 8 pipeline files | 15+ |
| EventBus handler exception swallowing | `event_bus.py`, `alert_manager.py`, `application/handlers/*` | 10+ |
| `check_spread_blowout` | Only in `exit_rules.py` | 1 (good pattern, needs extension) |

## 6.4 Configuration Duplication

| Config Key | Defined In | Also In |
|------------|-----------|---------|
| `OPTION_CHAIN_CACHE_TTL_SEC` | `dhan_adapter.py` | Should be in `settings.py` |
| `GLASSYTRADE_ENV` | `config_adapter.py`, `settings.py` | Two resolution functions |
| Risk thresholds | `circuit_breakers.py`, `risk_manager.py`, `exit_engine.py` | Hardcoded in 3+ files |
| VWAP band multipliers | `vwap_service.py`, `volume_profile.py` | Hardcoded σ values |

---

# 7. High-Risk Modules and Hotspots

## 7.1 God Classes (>500 lines or >20 methods)

| File | Lines | Methods | Primary Class | Risk |
|------|-------|---------|---------------|------|
| `application/handlers/llm_entry_handler.py` | 1,072 | 41 | `LLMEntryHandler` | **Critical** — Single point of failure for all LLM-driven entries |
| `domain/probability/agent_pipeline.py` | 906 | 31 | `RegimeAgent`, `DirectionAgent`, `TimingAgent`, `SizingAgent` | **High** — 4 agents in one file; changing one risks breaking others |
| `infrastructure/adapters/mlx_inference_adapter.py` | 788 | 25 | `MLXInferenceAdapter` | **High** — Singleton with class-level mutable state; cloud throttling |
| `runtime/orchestrator/session.py` | 761 | 25 | `SessionRuntime` | **High** — Orchestrates 15 stages; manual wiring; no plugin architecture |
| `infrastructure/adapters/dhan_adapter.py` | 514 | 26 | `DhanAdapter` | **High** — Broker + market data + streaming + option chain + lot sizes |
| `runtime/pipeline/risk.py` | 503 | 20 | `RiskEvaluation` | **Medium** — Per-symbol state grows unbounded |
| `infrastructure/storage/database.py` | 422 | 31 | `SQLiteStorageAdapter` | **High** — 10+ tables in one class; no repository pattern |
| `runtime/pipeline/position.py` | 347 | 20 | `PositionLifecycle` | **Medium** — Position open/close/modify in one class |
| `runtime/pipeline/market_structure.py` | 344 | 18 | `MarketStructureAnalysis` | **Medium** — Swing detection + structure classification |
| `application/handlers/trade_lifecycle_handler.py` | 367 | 18 | `TradeLifecycleHandler` | **Medium** — Entry + exit + breakeven + trailing in one handler |

## 7.2 Change-Risk Hotspots

| Module | Change Frequency | Blast Radius | Risk Score |
|--------|-----------------|--------------|------------|
| `runtime/pipeline/events.py` | High (new events added often) | 12+ consumers | **Critical** |
| `domain/trading/model/value_objects.py` | Medium | 25+ consumers | **High** |
| `infrastructure/serialization/schemas.py` | High | 15+ consumers | **High** |
| `runtime/orchestrator/session.py` | High (new stages added) | 15 pipeline stages | **High** |
| `application/handlers/llm_entry_handler.py` | High (LLM tuning) | All LLM-driven entries | **High** |
| `domain/amt/service/vwap_service.py` | Medium | 48 consumers | **High** |
| `domain/risk/service/circuit_breakers.py` | Low | 4 consumers | Medium |

## 7.3 Fragile Modules

| Module | Fragility Reason |
|--------|-----------------|
| `runtime/pipeline/gates.py` (386L) | Combines OI analysis, aggression scoring, thesis validation, drive decay, and session phase gating. Changing one gate risks breaking others. |
| `domain/services/ib_breakout_scalp.py` (329L) | Strategy logic tightly coupled to IB engine, VWAP tracker, and session context. Not reusable for other strategies. |
| `infrastructure/adapters/infrastructure_adapters.py` (224L) | Defines shadow ports (`IBroker`, `IMarketData`) that duplicate domain ports. Risk of divergence. |
| `core/cost_tracker.py` (241L) | Global singleton with mixed concerns (LLM tokens, API calls, trade costs). Hard to test, hard to reason about. |

---

# 8. Recommended Target Architecture

## 8.1 Guiding Principles

1. **Canonical Objects**: Every domain concept has a single canonical value object. No stage re-derives what a previous stage computed.
2. **Unified Risk**: All risk logic lives in `domain/risk/`. No risk checks in `runtime/`, `application/`, or `exit/`.
3. **Pipeline Contracts**: Pipeline stages communicate through immutable `TickContext` and `TradingSignal` objects. Stages are pure functions.
4. **Handler Slimming**: Handlers are thin orchestrators. Business logic lives in domain services.
5. **Plugin Architecture**: New pipeline stages, strategies, and exchanges are registered via plugins, not hardcoded in `session.py`.
6. **No Global State**: All state is instance-level and injected. No module-level mutable globals.
7. **One Event Taxonomy**: `domain/shared/event/` is the single source of truth. `runtime/pipeline/events.py` is deleted.

## 8.2 Target Layer Diagram

```
┌─────────────────────────────────────────────────────────────┐
│                         API Layer                            │
│  routers/  websocket/  dependencies/                         │
│  → FastAPI-only, no business logic                           │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                    Application Layer                         │
│  handlers/  commands/  services/  contracts/                 │
│  → Thin orchestrators, delegate to domain                    │
│  → No imports from runtime/ or infrastructure/               │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                     Runtime Layer                            │
│  pipeline/  feeds/  orchestrator/                            │
│  → Pure pipeline stages, no business logic                   │
│  → Stages communicate via TickContext / TradingSignal        │
│  → Orchestrator uses PipelineBuilder (plugin registry)       │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                      Domain Layer                            │
│  trading/  amt/  risk/  exit/  fabio_ai/  probability/       │
│  → All business logic, no framework imports                  │
│  → Unified risk policy, canonical value objects              │
│  → Port definitions in shared/port/                          │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                   Infrastructure Layer                       │
│  adapters/  storage/  serialization/  config/  messaging/    │
│  → Implements domain ports                                   │
│  → No business logic                                         │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                    Shared / Core Layer                       │
│  shared/  core/                                              │
│  → Utilities, tracing, metrics                               │
│  → No business logic, no framework coupling                  │
└─────────────────────────────────────────────────────────────┘
                              │
┌─────────────────────────────────────────────────────────────┐
│                     Bootstrap Layer                          │
│  bootstrap/                                                  │
│  → DI container, settings, exchange resolution               │
│  → Imports from all layers (composition root)                │
└─────────────────────────────────────────────────────────────┘
```

## 8.3 Key Architectural Changes

### A. Canonical Value Objects

Create `domain/trading/model/canonical_objects.py`:
```python
@dataclass(frozen=True)
class TickContext:
    tick: Tick
    candle: OHLC | None = None
    vwap_profile: VWAPProfile | None = None
    market_structure: MarketStructure | None = None
    signal: TradingSignal | None = None
    # ... accumulates state as it flows through pipeline

@dataclass(frozen=True)
class TradingSignal:
    direction: SignalDirection
    confidence: ConfidenceLevel
    grade: int
    aggression_score: float
    session_phase: SessionPhase
    vwap_bias: VWAPBias
    # ... all signal metadata in one object

@dataclass(frozen=True)
class VWAPProfile:
    price: float
    bands: tuple[VWAPBand, ...]  # 1σ, 2σ, 3σ
    bias: VWAPBias
    
    def is_price_above(self, sigma: int) -> bool: ...
    def is_price_below(self, sigma: int) -> bool: ...
```

### B. Unified Risk Policy

Create `domain/risk/service/risk_policy.py`:
```python
@dataclass(frozen=True)
class RiskPolicy:
    max_daily_loss_pct: float
    max_consecutive_losses: int
    max_concurrent_positions: int
    max_portfolio_notional_pct: float
    max_per_symbol_notional_pct: float
    spread_blowout_threshold: float
    
    def evaluate(self, portfolio: Portfolio) -> RiskResult: ...
```

All risk checks delegate to `RiskPolicy`. No hardcoded thresholds outside this file.

### C. Plugin Architecture for Pipeline Stages

Create `runtime/pipeline/registry.py`:
```python
class PipelineStageRegistry:
    def register(self, name: str, stage: PipelineStage) -> None: ...
    def build_pipeline(self, config: PipelineConfig) -> list[PipelineStage]: ...
```

`SessionRuntime` receives a `PipelineStageRegistry` at construction. New stages are registered in `bootstrap/container.py`, not in `session.py`.

### D. Unified Event Taxonomy

Delete `runtime/pipeline/events.py`. Move all events to `domain/shared/event/`:
- `TickEvent` → `domain/shared/event/market.py`
- `SignalEvent` → `domain/shared/event/signal.py`
- `PositionEvent` → `domain/shared/event/position.py`
- `ExitDecision` → `domain/shared/event/position.py`

### E. LLM Context Builder

Create `domain/fabio_ai/services/llm_context_builder.py`:
```python
class LLMContextBuilder:
    def __init__(self, market_builder: MarketContextBuilder, 
                 position_builder: PositionContextBuilder,
                 risk_builder: RiskContextBuilder): ...
    
    def build_entry_context(self, ctx: TickContext) -> str: ...
    def build_overseer_context(self, ctx: TickContext) -> str: ...
    def build_rationale_context(self, ctx: TickContext) -> str: ...
```

---

# 9. Proposed Folder/File Reorganization

## 9.1 Current Structure Problems

1. `domain/services/` and `domain/amt/service/` both contain AMT-related code
2. `runtime/pipeline/events.py` duplicates `domain/shared/event/`
3. `application/di/container.py` and `bootstrap/container.py` are two DI systems
4. `infrastructure/serialization/schemas.py` is a 632-line DTO dumping ground
5. `domain/exit/service/exit_engine.py` contains 4 abstractions
6. `core/cost_tracker.py` mixes LLM cost, API cost, and trade cost tracking

## 9.2 Proposed Structure

```
backendv2/app/
├── api/                          # HTTP/WebSocket layer (unchanged)
│   ├── routers/
│   ├── websocket/
│   └── dependencies/
│
├── application/                  # Use-case orchestration
│   ├── handlers/                 # Thin event handlers
│   ├── commands/                 # Command objects
│   ├── services/                 # App-level services (session state manager)
│   └── contracts/                # DTOs for app-layer contracts
│       ├── tick_context.py
│       └── trading_signal.py
│
├── runtime/                      # Pipeline execution
│   ├── pipeline/
│   │   ├── base.py               # PipelineStageBase ABC
│   │   ├── registry.py           # PipelineStageRegistry (plugin system)
│   │   ├── stages/               # Individual stage implementations
│   │   │   ├── candle_builder.py
│   │   │   ├── orderflow.py
│   │   │   ├── microstructure.py
│   │   │   ├── market_structure.py
│   │   │   ├── signal_generation.py
│   │   │   ├── gate_evaluation.py
│   │   │   ├── risk_evaluation.py
│   │   │   ├── position_lifecycle.py
│   │   │   ├── execution.py
│   │   │   ├── broker_sync.py
│   │   │   └── persistence.py
│   │   └── orchestrator/
│   │       └── session.py        # Slimmed to 200-300 lines
│   └── feeds/
│
├── domain/                       # Business logic
│   ├── trading/
│   │   ├── model/
│   │   │   ├── entities.py
│   │   │   ├── value_objects.py
│   │   │   ├── aggregates.py
│   │   │   └── canonical_objects.py    # NEW: TickContext, TradingSignal, VWAPProfile
│   │   ├── service/
│   │   │   └── portfolio_manager.py
│   │   └── event/
│   │       ├── base.py
│   │       ├── signal.py
│   │       ├── position.py
│   │       ├── market.py
│   │       ├── risk.py
│   │       └── order.py
│   │
│   ├── amt/
│   │   └── service/
│   │       ├── volume_profile.py
│   │       ├── vwap_service.py       # Canonical VWAP computation
│   │       ├── lvn_detector.py
│   │       ├── cvd_tracker.py
│   │       ├── market_state_engine.py
│   │       ├── break_detector.py
│   │       ├── displacement_detector.py
│   │       ├── initial_balance_engine.py
│   │       ├── acceptance_rejection.py
│   │       ├── drive_tracker.py
│   │       ├── session_context.py
│   │       ├── mtf_analyzer.py
│   │       ├── profile_classifier.py
│   │       ├── orderflow_detectors.py
│   │       ├── aggression_scorer.py
│   │       ├── signal_generator.py
│   │       └── amt_analyzer.py       # Orchestrates AMT services
│   │
│   ├── risk/
│   │   └── service/
│   │       ├── risk_policy.py        # NEW: Unified risk policy
│   │       ├── circuit_breakers.py
│   │       ├── flash_crash_protector.py
│   │       ├── risk_tier_engine.py
│   │       ├── risk_sizing_engine.py
│   │       ├── self_healing.py
│   │       ├── startup_reconciliation.py
│   │       ├── position_reconciliation.py
│   │       ├── loss_tracker.py       # MOVED from exit/
│   │       └── consecutive_loss_tracker.py
│   │
│   ├── exit/
│   │   └── service/
│   │       ├── exit_engine.py        # Slimmed: only exit evaluation
│   │       ├── exit_rules.py
│   │       ├── trail_engine.py       # Extracted from exit_engine.py
│   │       ├── partition_exit_manager.py
│   │       ├── breakeven_engine.py
│   │       ├── structural_stop_engine.py
│   │       └── position_sizer.py     # MOVED from exit/ to risk/ (see note)
│   │
│   ├── fabio_ai/
│   │   └── services/
│   │       ├── llm_context_builder.py    # NEW: Unified prompt building
│   │       ├── prompt_builder.py
│   │       ├── signal_coordinator.py
│   │       ├── amt_pipeline.py
│   │       ├── llm_contract.py
│   │       ├── llm_rationale_service.py
│   │       ├── generative_ai_service.py
│   │       ├── absorption_validator.py
│   │       ├── alert_manager.py
│   │       ├── session_context_factory.py
│   │       ├── session_risk_manager.py
│   │       ├── session_warmup.py
│   │       ├── underlying_profile_router.py
│   │       ├── vp_contract_selector.py
│   │       ├── rule_based_rationale.py
│   │       ├── response_parser.py
│   │       ├── profile_factory.py
│   │       ├── profile_selector.py
│   │       ├── gap_analyzer.py
│   │       ├── scale_manager.py
│   │       └── amt_parameters.py
│   │
│   ├── probability/
│   │   ├── agents/               # NEW: Extracted from agent_pipeline.py
│   │   │   ├── regime_agent.py
│   │   │   ├── direction_agent.py
│   │   │   ├── timing_agent.py
│   │   │   └── sizing_agent.py
│   │   ├── features.py
│   │   ├── labels.py
│   │   ├── regime_classifier.py
│   │   ├── regime_hysteresis_store.py
│   │   ├── direction_timing.py
│   │   ├── sizing.py
│   │   └── playbook.py
│   │
│   ├── shared/
│   │   ├── port/
│   │   │   ├── broker.py
│   │   │   ├── market_data.py
│   │   │   ├── llm_inference.py
│   │   │   ├── storage.py
│   │   │   ├── notification.py
│   │   │   ├── probability.py
│   │   │   ├── npoc.py
│   │   │   └── delta_profile.py
│   │   └── event/
│   │       ├── base.py
│   │       ├── signal.py
│   │       ├── position.py
│   │       ├── market.py
│   │       ├── risk.py
│   │       ├── order.py
│   │       └── analysis.py
│   │
│   └── ai/
│       └── rl/
│           ├── valentini_env.py
│           ├── trainer.py
│           ├── reward_shaper.py
│           └── data_loader.py
│
├── infrastructure/
│   ├── adapters/
│   │   ├── dhan/
│   │   │   ├── market_data.py      # Split from dhan_adapter.py
│   │   │   ├── streaming.py
│   │   │   ├── option_chain.py
│   │   │   └── lot_sizes.py
│   │   ├── mlx/
│   │   │   ├── inference.py        # Slimmed MLX adapter
│   │   │   └── base.py             # NEW: LLM adapter base class
│   │   ├── gguf/
│   │   │   └── inference.py        # Uses LLM adapter base
│   │   ├── lgbm/
│   │   │   └── probability.py
│   │   ├── paper_broker.py
│   │   ├── mcx_broker.py
│   │   ├── npoc_adapter.py
│   │   ├── delta_profile_adapter.py
│   │   ├── null_notification_adapter.py
│   │   └── telegram_adapter.py
│   │
│   ├── storage/
│   │   ├── database.py             # Slimmed to connection management
│   │   ├── repositories/           # NEW: Repository pattern
│   │   │   ├── tick_repository.py
│   │   │   ├── trade_repository.py
│   │   │   ├── position_repository.py
│   │   │   ├── session_repository.py
│   │   │   └── event_repository.py
│   │   └── adapters/
│   │       └── sqlite_adapter.py
│   │
│   ├── serialization/
│   │   ├── schemas/
│   │   │   ├── market.py
│   │   │   ├── trading.py
│   │   │   ├── amt.py
│   │   │   ├── chat.py
│   │   │   └── risk.py
│   │   └── adapters/
│   │       └── json_adapter.py
│   │
│   ├── config/
│   │   ├── settings.py             # Unified settings
│   │   └── loader.py               # NEW: Unified config loader
│   │
│   ├── messaging/
│   │   └── event_bus.py
│   │
│   ├── alerts/
│   │   └── alert_manager.py
│   │
│   └── strategies/
│       ├── nse_strategy.py
│       └── mcx_strategy.py
│
├── core/                           # Cross-cutting concerns
│   ├── circuit_breaker.py
│   ├── event_store.py
│   ├── feature_flags.py
│   ├── metrics.py                  # Merged with metrics_collector.py
│   └── tracing.py
│
├── shared/                         # Ultra-light utilities
│   ├── timezones.py
│   └── mode.py
│
└── bootstrap/                      # Composition root
    ├── container.py                # Merged with application/di/container.py
    ├── infrastructure.py
    ├── scanner.py
    └── lifespan.py
```

## 9.3 Key Moves

| From | To | Reason |
|------|-----|--------|
| `domain/services/initial_balance_engine.py` | `domain/amt/service/initial_balance_engine.py` | Consolidate AMT services |
| `domain/services/vwap_tracker.py` | `domain/amt/service/vwap_tracker.py` | Consolidate AMT services |
| `domain/services/ib_breakout_scalp.py` | `domain/amt/service/strategies/ib_breakout_scalp.py` | Strategy-specific code |
| `domain/exit/service/loss_tracker.py` | `domain/risk/service/loss_tracker.py` | Risk logic belongs in risk/ |
| `domain/exit/service/position_sizer.py` | `domain/risk/service/position_sizer.py` | Sizing is risk management |
| `runtime/pipeline/events.py` | Delete; merge into `domain/shared/event/` | Unified event taxonomy |
| `application/di/container.py` | Merge into `bootstrap/container.py` | Single DI container |
| `core/metrics_collector.py` | Merge into `core/metrics.py` | Single metrics module |
| `core/cost_tracker.py` | Split into `infrastructure/tracking/llm_cost_tracker.py`, `infrastructure/tracking/api_cost_tracker.py`, `domain/trading/service/trade_cost_calculator.py` | Separate concerns |
| `infrastructure/adapters/dhan_adapter.py` | Split into `infrastructure/adapters/dhan/` package | Separate market data, streaming, option chain |
| `infrastructure/adapters/mlx_inference_adapter.py` | Extract `infrastructure/adapters/mlx/base.py` | Shared LLM adapter base |
| `infrastructure/storage/database.py` | Extract repository classes into `infrastructure/storage/repositories/` | Repository pattern |
| `infrastructure/serialization/schemas.py` | Split into `infrastructure/serialization/schemas/` package | Domain-specific DTOs |

---

# 10. Refactoring Recommendations

## 10.1 Immediate (This Sprint)

### R1. Extract Canonical Value Objects
**Files**: `domain/trading/model/canonical_objects.py` (new)  
**Impact**: Eliminates shotgun surgery on signal and VWAP changes  
**Effort**: Medium (2-3 days)  
**Steps**:
1. Create `TradingSignal`, `VWAPProfile`, `TickContext` value objects
2. Refactor `runtime/pipeline/signal.py` to return `TradingSignal`
3. Refactor `runtime/pipeline/gates.py` to accept `TradingSignal`
4. Refactor `runtime/pipeline/risk.py` to accept `TradingSignal`
5. Refactor `application/handlers/llm_entry_handler.py` to accept `TradingSignal`
6. Update `infrastructure/serialization/schemas.py` to serialize `TradingSignal`

### R2. Split `LLMEntryHandler`
**Files**: `application/handlers/llm_entry_handler.py` → 5 files  
**Impact**: Reduces god class from 1,072L to ~200L each  
**Effort**: Medium (2-3 days)  
**New files**:
- `domain/fabio_ai/services/llm_orchestrator.py` — Worker thread management, queueing
- `domain/fabio_ai/services/llm_request_builder.py` — Prompt building, context assembly
- `domain/fabio_ai/services/llm_response_parser.py` — JSON extraction, normalization (already exists, expand)
- `domain/fabio_ai/services/session_phase_resolver.py` — NSE/MCX phase logic
- `application/handlers/llm_entry_handler.py` — Thin handler, delegates to above

### R3. Merge Duplicate `InitialBalanceEngine`
**Files**: `domain/services/initial_balance_engine.py`, `domain/amt/service/initial_balance_engine.py`  
**Impact**: Eliminates confusion, import ambiguity  
**Effort**: Low (1 day)  
**Steps**:
1. Compare implementations
2. Keep the more complete one (likely `domain/amt/service/`)
3. Update all imports
4. Delete the other

### R4. Unify Event Taxonomy
**Files**: `runtime/pipeline/events.py`, `domain/shared/event/`  
**Impact**: Adding a field to an event requires 1 edit instead of 4  
**Effort**: Medium (2 days)  
**Steps**:
1. Map all event types in `runtime/pipeline/events.py`
2. Merge into `domain/shared/event/` files
3. Update all imports
4. Delete `runtime/pipeline/events.py`

## 10.2 Short-Term (Next 2 Sprints)

### R5. Create `RiskPolicy` Unified Service
**Files**: `domain/risk/service/risk_policy.py` (new)  
**Impact**: All risk thresholds in one place  
**Effort**: Medium (2-3 days)  
**Steps**:
1. Extract all hardcoded risk thresholds from:
   - `domain/risk/service/circuit_breakers.py`
   - `domain/trading/service/risk_manager.py`
   - `runtime/pipeline/risk.py`
   - `domain/exit/service/loss_tracker.py`
2. Create `RiskPolicy` value object
3. Inject `RiskPolicy` into all risk services at bootstrap
4. Update tests

### R6. Split `SessionRuntime` with `PipelineBuilder`
**Files**: `runtime/orchestrator/session.py`, `runtime/pipeline/registry.py` (new)  
**Impact**: Adding a new pipeline stage requires 1 edit (register in container) instead of editing `session.py`  
**Effort**: Medium (3-4 days)  
**Steps**:
1. Create `PipelineStageRegistry`
2. Create `PipelineBuilder` that assembles stages from registry
3. Extract AAA evaluation into `runtime/pipeline/aaa_evaluation.py`
4. Extract phase gating into `runtime/pipeline/phase_gating.py`
5. Slim `SessionRuntime` to orchestration loop only

### R7. Extract Repository Pattern from `SQLiteStorageAdapter`
**Files**: `infrastructure/storage/repositories/` (new package)  
**Impact**: Each table has its own repository; tests can mock individual repositories  
**Effort**: Medium (3 days)  
**New files**:
- `TickRepository`
- `TradeRepository`
- `PositionRepository`
- `SessionRepository`
- `EventRepository`

### R8. Split `DhanAdapter` into Focused Adapters
**Files**: `infrastructure/adapters/dhan/` (new package)  
**Impact**: Market data, streaming, option chain are separate concerns  
**Effort**: Low (1-2 days)  
**New files**:
- `DhanMarketDataAdapter` (implements `IMarketData`)
- `DhanStreamingAdapter`
- `DhanOptionChainAdapter`

### R9. Create LLM Adapter Base Class
**Files**: `infrastructure/adapters/mlx/base.py` (new)  
**Impact**: Eliminates duplication between MLX and GGUF adapters  
**Effort**: Low (1 day)  
**Extract into base**:
- Singleton logic (`__new__`, `_init_lock`)
- `_extract_json_candidate`
- `wait_until_ready` polling loop
- `ENTRY_JSON_RUNTIME_REMINDER`

## 10.3 Medium-Term (Next Quarter)

### R10. Unify Config Loading
**Files**: `infrastructure/config/loader.py` (new), delete `config_adapter.py`  
**Impact**: Single source of truth for config  
**Effort**: Low (1 day)  

### R11. Extract `TickContext` Pipeline Pattern
**Files**: All `runtime/pipeline/*.py` files  
**Impact**: Pipeline stages are pure functions; no hidden state  
**Effort**: High (1 week)  

### R12. Extract `LLMContextBuilder`
**Files**: `domain/fabio_ai/services/llm_context_builder.py` (new)  
**Impact**: Adding a new data field to LLM context requires 1 edit  
**Effort**: Medium (3 days)  

### R13. Split `AgentPipeline` into Individual Agents
**Files**: `domain/probability/agents/` (new package)  
**Impact**: Each agent is independently testable and replaceable  
**Effort**: Medium (2-3 days)  

### R14. Remove Global Singletons
**Files**: `core/cost_tracker.py`, `infrastructure/config/config_adapter.py`, `api/routers/rl.py`  
**Impact**: Parallel sessions and testing become reliable  
**Effort**: Medium (2-3 days)  

### R15. Add Per-Symbol State Pruning
**Files**: `runtime/pipeline/risk.py`, `runtime/pipeline/gates.py`, `runtime/pipeline/orderflow.py`  
**Impact**: Memory does not grow unbounded with symbol count  
**Effort**: Low (1 day)  

## 10.4 Long-Term (Next 2 Quarters)

### R16. Strategy Plugin Architecture
**Files**: `domain/amt/service/strategies/` (new package)  
**Impact**: New strategies are plugins, not code changes  
**Effort**: High (2 weeks)  

### R17. Exchange Plugin Architecture
**Files**: `infrastructure/exchanges/` (new package)  
**Impact**: New exchanges are plugins, not code changes  
**Effort**: High (2 weeks)  

### R18. Replace Pydantic in Domain
**Files**: `domain/fabio_ai/services/response_parser.py`  
**Impact**: Domain is framework-agnostic  
**Effort**: Low (1 day)  

---

# 11. Engineering Standards Proposal

## 11.1 Layer Dependency Rules

```python
# ENFORCED VIA IMPORT LINTING (e.g., import-linter, or custom pre-commit hook)

# ALLOWED IMPORTS:
domain/           → shared/                        # Shared kernel only
domain/           → (nothing else)
application/      → domain/, shared/               # Business logic + shared
application/      → application/contracts/         # App-layer DTOs
runtime/          → domain/, shared/               # Business logic + shared
runtime/          → application/contracts/         # TickContext, TradingSignal
infrastructure/   → domain/, shared/, core/        # Ports + shared + core
api/              → application/, infrastructure/, runtime/, domain/, shared/
bootstrap/        → ALL                            # Composition root

# FORBIDDEN IMPORTS:
domain/           → application/, runtime/, infrastructure/, api/
application/      → infrastructure/, runtime/
runtime/          → infrastructure/
core/             → domain/, application/, runtime/, infrastructure/, api/
```

## 11.2 File Size Limits

| Type | Max Lines | Max Methods | Rationale |
|------|-----------|-------------|-----------|
| Handler | 150 | 8 | Handlers are thin orchestrators |
| Domain service | 250 | 12 | Single responsibility |
| Adapter | 300 | 15 | Port implementation only |
| Pipeline stage | 200 | 10 | Pure transformation |
| Repository | 150 | 8 | CRUD only |
| Router | 100 | 6 | HTTP routing only |
| Schema/DTO | 100 | N/A | Data transfer only |

## 11.3 Naming Conventions

| Layer | Directory | File | Class | Function |
|-------|-----------|------|-------|----------|
| Domain | `domain/<domain>/service/` | `snake_case.py` | `PascalCase` (noun) | `verb_noun()` |
| Application | `application/handlers/` | `snake_case_handler.py` | `PascalCaseHandler` | `handle_verb()` |
| Runtime | `runtime/pipeline/stages/` | `snake_case.py` | `PascalCase` | `process()` |
| Infrastructure | `infrastructure/adapters/` | `snake_case_adapter.py` | `PascalCaseAdapter` | `fetch_verb()` |
| API | `api/routers/` | `snake_case.py` | N/A (functions) | `get_/post_()` |

## 11.4 Configuration Rules

1. **No hardcoded values in domain/**. All thresholds, limits, and parameters are injected via constructor.
2. **Config is read at bootstrap only**. Domain services receive config objects, not config files.
3. **Environment variables are resolved in `bootstrap/` or `infrastructure/config/` only**.
4. **Feature flags are read in `application/` or `bootstrap/` only**.

## 11.5 Testing Standards

1. **Every domain service has a dedicated test file**.
2. **Handlers are tested via integration tests**, not unit tests (they are thin orchestrators).
3. **Adapters are tested with contract tests** against the port interface.
4. **Pipeline stages are tested in isolation** with mock `TickContext` inputs.
5. **God classes (>300 lines) must have >80% coverage**.

## 11.6 Event Standards

1. **Single event taxonomy**: `domain/shared/event/` is the only place events are defined.
2. **Events are immutable dataclasses** (frozen=True).
3. **Event names are past tense**: `SignalGenerated`, `PositionOpened`, `ExitTriggered`.
4. **Events carry full context**: No consumer should need to query state to handle an event.

## 11.7 Error Handling Standards

1. **Domain errors are exceptions**: `RiskViolation`, `GateRejection`, `BrokerError`.
2. **Application errors are Result types**: `Result[T, Error]`.
3. **Infrastructure errors are retried with backoff**: Exponential backoff, max 3 retries.
4. **No bare `except:` clauses**. Always catch specific exceptions.

## 11.8 State Management Standards

1. **No global mutable state**. All state is instance-level.
2. **State is owned by one module**. No shared mutable state between modules.
3. **Per-symbol state is pruned**. Evict symbols inactive for >24h.
4. **State changes are events**. Every state mutation emits an event.

---

# 12. Migration Roadmap

## Phase 1: Foundation (Weeks 1-2) — Quick Wins

| Task | Effort | Files |
|------|--------|-------|
| R3: Merge duplicate `InitialBalanceEngine` | 1 day | 2 files |
| R4: Unify event taxonomy | 2 days | 10 files |
| R9: Create LLM adapter base class | 1 day | 3 files |
| R10: Unify config loading | 1 day | 2 files |
| R15: Add per-symbol state pruning | 1 day | 3 files |
| Add import-linter pre-commit hook | 1 day | CI config |

**Total**: ~6 days, ~20 files  
**Risk**: Low — mechanical changes with clear before/after  
**Tests**: Run full suite after each change; expect 0 regressions

## Phase 2: Canonical Objects (Weeks 3-4) — Medium Risk

| Task | Effort | Files |
|------|--------|-------|
| R1: Extract `TradingSignal`, `VWAPProfile` | 3 days | 15 files |
| R5: Create `RiskPolicy` unified service | 3 days | 8 files |
| R8: Split `DhanAdapter` | 2 days | 4 files |
| R2: Split `LLMEntryHandler` (part 1: extract prompt builder) | 2 days | 3 files |

**Total**: ~10 days, ~30 files  
**Risk**: Medium — touches runtime pipeline and application handlers  
**Tests**: Add integration tests for tick-to-position flow before starting  
**Rollback**: Git revert; changes are additive (new files) with deprecation of old

## Phase 3: Structural Refactor (Weeks 5-7) — High Risk

| Task | Effort | Files |
|------|--------|-------|
| R6: Split `SessionRuntime` with `PipelineBuilder` | 4 days | 5 files |
| R7: Extract repository pattern | 3 days | 6 files |
| R2: Split `LLMEntryHandler` (part 2: extract orchestrator) | 2 days | 2 files |
| R12: Extract `LLMContextBuilder` | 3 days | 8 files |
| R13: Split `AgentPipeline` | 3 days | 5 files |

**Total**: ~15 days, ~26 files  
**Risk**: High — changes orchestration logic  
**Tests**: Full integration test suite must pass; add e2e tests for trading flow  
**Rollback**: Feature flags for new pipeline builder; can fallback to old `SessionRuntime`

## Phase 4: Cleanup (Weeks 8-9) — Low Risk

| Task | Effort | Files |
|------|--------|-------|
| R14: Remove global singletons | 3 days | 5 files |
| R11: Extract `TickContext` pipeline pattern | 5 days | 20 files |
| R18: Replace Pydantic in domain | 1 day | 1 file |
| File reorganization (move files to new locations) | 2 days | 30 files |

**Total**: ~11 days, ~56 files  
**Risk**: Low-Medium — mechanical moves, but many files  
**Tests**: Full suite; add tests for any new modules  
**Rollback**: Git revert

## Phase 5: Architecture Plugins (Weeks 10-12) — High Risk

| Task | Effort | Files |
|------|--------|-------|
| R16: Strategy plugin architecture | 10 days | 10 files |
| R17: Exchange plugin architecture | 10 days | 8 files |

**Total**: ~20 days, ~18 files  
**Risk**: High — architectural changes  
**Tests**: Extensive integration and e2e tests  
**Rollback**: Feature flags; maintain old hardcoded paths as fallback

---

# 13. Technical Debt Prioritization Matrix

## 13.1 Matrix

| # | Debt Item | Severity | Effort | Frequency of Change | Impact if Unfixed | Priority |
|---|-----------|----------|--------|---------------------|-------------------|----------|
| 1 | Signal lifecycle in 81 files | Critical | Medium | Very High | Every signal change requires 7+ edits | **P0** |
| 2 | `LLMEntryHandler` god class (1,072L) | Critical | Medium | High | Single point of failure; hard to test | **P0** |
| 3 | Layer violations (domain→runtime, app→infra) | High | Low | Medium | Erodes clean architecture; tests become fragile | **P0** |
| 4 | VWAP scattered in 48 files | High | Medium | Medium | Band changes require 12+ edits | **P1** |
| 5 | Risk fragmented in 3 packages | High | Medium | Low-Medium | Threshold changes require 4+ edits | **P1** |
| 6 | Duplicate event hierarchies | High | Medium | Medium | Adding event fields requires 4+ edits | **P1** |
| 7 | `SessionRuntime` god class (761L) | High | Medium | High | Adding pipeline stages requires editing orchestrator | **P1** |
| 8 | Global singletons | Medium | Low | Low | Parallel sessions unreliable | **P2** |
| 9 | Duplicate `InitialBalanceEngine` | Medium | Low | Low | Import confusion | **P2** |
| 10 | `DhanAdapter` god class (514L) | Medium | Low | Low | Hard to test; mixed concerns | **P2** |
| 11 | Config access in domain services | Medium | Low | Medium | Domain should not know about config files | **P2** |
| 12 | `schemas.py` dumping ground (632L) | Medium | Medium | High | Adding DTOs increases file size | **P2** |
| 13 | Duplicate config loading | Low | Low | Low | Maintenance overhead | **P3** |
| 14 | Duplicate LLM adapter code | Low | Low | Low | Maintenance overhead | **P3** |
| 15 | Pydantic in domain | Low | Low | Low | Framework coupling | **P3** |

## 13.2 Prioritization Rationale

**P0 (Do Now)**: Items that block developer velocity on the most frequent changes (signal lifecycle, LLM handler, layer violations). These have high severity and medium effort — the ROI is immediate.

**P1 (Next Sprint)**: Items that cause shotgun surgery on moderately frequent changes (VWAP, risk, events, pipeline orchestration). These have high severity but require more careful refactoring.

**P2 (Next Quarter)**: Items that are architectural smells but do not block daily work (singletons, duplicate classes, god adapters, config access). These are important for long-term health but not urgent.

**P3 (Backlog)**: Items that are low-severity cleanup (duplicate config, pydantic in domain). These can be addressed opportunistically.

---

# 14. Long-Term Scalability Recommendations

## 14.1 Symbol Scaling

**Current Risk**: Per-symbol state dictionaries in `RiskEvaluation`, `GateEvaluation`, `OrderFlowPipeline` grow unbounded.

**Recommendation**:
- Add TTL-based eviction to all per-symbol state (evict after 24h of inactivity)
- Use LRU cache with max 500 symbols per pipeline stage
- For >500 symbols, shard by symbol across multiple `SessionRuntime` instances

## 14.2 Exchange Scaling

**Current Risk**: Exchange-specific logic (NSE phases, MCX commodity filtering) is hardcoded in handlers.

**Recommendation**:
- Create `Exchange` port with methods: `get_phases()`, `is_commodity()`, `get_session_times()`
- Implement `NSEExchange`, `MCXExchange`, `BSEExchange`
- Register exchange in bootstrap; handlers query exchange port

## 14.3 Strategy Scaling

**Current Risk**: Strategies are scattered across `domain/services/`, `domain/amt/`, and `runtime/pipeline/`.

**Recommendation**:
- Create `Strategy` port with `evaluate(context: TickContext) -> Signal | None`
- Implement `IBreakoutStrategy`, `AAAStrategy`, `MeanReversionStrategy`
- Register strategies in plugin registry
- `SessionRuntime` iterates over registered strategies

## 14.4 Model Scaling

**Current Risk**: LLM inference has 3 parallel prompt-building paths.

**Recommendation**:
- Create `ModelProvider` port with `infer(prompt: str, temperature: float) -> str`
- Implement `MLXProvider`, `GGUFProvider`, `OpenRouterProvider`
- Use `LLMContextBuilder` for all prompt construction
- Add model A/B testing framework

## 14.5 Team Scaling

**Current Risk**: 285 source files with inconsistent naming, mixed responsibilities, and no clear ownership boundaries.

**Recommendation**:
- Assign module ownership to teams: AMT team, Risk team, LLM team, Infrastructure team
- Enforce CODEOWNERS file
- Require architecture review for changes to `runtime/`, `domain/`, and `bootstrap/`
- Use import-linter in CI to prevent layer violations

## 14.6 Operational Scaling

**Current Risk**: No clear operational boundaries. A failure in `LLMEntryHandler` can block all entries.

**Recommendation**:
- Add circuit breakers per pipeline stage
- Add per-symbol circuit breakers
- Add health checks for each adapter
- Add metrics emission per pipeline stage (latency, drops, errors)
- Add distributed tracing for tick-to-position flow

## 14.7 Data Scaling

**Current Risk**: SQLite is single-node. Tick data grows unbounded.

**Recommendation**:
- Move tick storage to time-series database (InfluxDB, TimescaleDB)
- Add tick data retention policy (keep 7 days raw, 30 days aggregated)
- Use write-ahead logging for SQLite to reduce lock contention
- Consider sharding by symbol for tick data

---

# Appendix A: Metrics

| Metric | Current | Target |
|--------|---------|--------|
| God classes (>500L) | 7 | 0 |
| God classes (>300L) | 17 | <5 |
| Files per signal change | 9 | 2 |
| Files per VWAP change | 12 | 2 |
| Files per risk threshold change | 7 | 2 |
| Files per event field change | 4 | 1 |
| Layer violations | 4 | 0 |
| Global singletons | 4 | 0 |
| Duplicate class names | 5 | 0 |
| Test coverage (by file) | ~58% | >80% |
| Test coverage (by line) | ~70% | >85% |
| Pipeline stage wiring | Hardcoded in session.py | Plugin registry |
| Config access points | 21 | 5 (bootstrap only) |

# Appendix B: Files Requiring Immediate Attention

| Priority | File | Issue | Action |
|----------|------|-------|--------|
| P0 | `application/handlers/llm_entry_handler.py` | 1,072L god class | Split into 5 files |
| P0 | `runtime/orchestrator/session.py` | 761L, hardcodes 15 stages | Extract PipelineBuilder |
| P0 | `domain/exit/service/exit_engine.py` | Imports runtime events | Move ExitDecision to domain |
| P0 | `application/handlers/llm_entry_handler.py` | Imports runtime Signal | Move Signal to domain |
| P1 | `domain/amt/service/vwap_service.py` | 48 consumers re-derive bands | Create VWAPProfile value object |
| P1 | `runtime/pipeline/events.py` | Duplicates domain events | Merge into domain/shared/event/ |
| P1 | `infrastructure/adapters/dhan_adapter.py` | 514L god adapter | Split into 3 adapters |
| P1 | `infrastructure/serialization/schemas.py` | 632L DTO dumping ground | Split by domain |
| P2 | `core/cost_tracker.py` | Global singleton, mixed concerns | Split and inject |
| P2 | `infrastructure/storage/database.py` | 422L, 10+ tables | Extract repositories |

---

*End of Architecture Review*
