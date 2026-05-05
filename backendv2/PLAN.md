# BackendV2 → Zero Parity Implementation Plan

> **Goal**: Transform backendv2 from a clean-architecture skeleton into a truly
> event-driven, production-grade trading backend that achieves functional parity
> with `backend` — while being faster, more extensible, more maintainable, and
> having a dramatically smaller blast radius than the original.
>
> **Non-goals**: Reinventing the domain model. The existing backend's domain
> logic is battle-tested. We port it, we don't rewrite it from scratch.

---

## Design Principles (Immutable)

1. **Event-sourced core** — Every state mutation originates from a domain event.
   No service directly mutates another service's state. Events are the sole
   integration mechanism.

2. **Single writer, many readers** — Per-symbol state has exactly one writer
   (the session event loop). All other components are read-only observers or
   event subscribers. This eliminates an entire class of race conditions.

3. **Blast radius containment** — Each symbol's session is an isolated
   aggregate. A crash in one symbol's processing never affects another. A
   handler failure is caught and logged; it never propagates to the event loop.

4. **Zero duplication** — Domain models, events, and DTOs are defined once.
   TypeScript types are generated, not hand-maintained. Serialization schemas
   are the single source of truth.

5. **Testability by construction** — Pure functions for domain logic. Mockable
   ports for infrastructure. Event replay for integration tests. Every handler
   is independently testable.

6. **Separation of concerns at every layer**:
   - **Domain**: What is true (models, value objects, domain services)
   - **Application**: What happens (event handlers, command orchestration)
   - **Infrastructure**: How it's stored/sent (adapters, serialization, I/O)
   - **API**: How it's exposed (FastAPI routers, SSE, WebSocket)

---

## Target Architecture

```
backendv2/
├── app/
│   ├── domain/                          # Pure business logic — zero framework deps
│   │   ├── shared/                      # Cross-cutting domain primitives
│   │   │   ├── event/
│   │   │   │   ├── __init__.py          # Re-exports all events
│   │   │   │   ├── base.py              # DomainEvent base class
│   │   │   │   ├── market.py            # TickReceived, OrderBookSnapshot
│   │   │   │   ├── analysis.py          # AMTAnalyzed, AIAnalysisCompleted
│   │   │   │   ├── signal.py            # SignalGenerated, SignalValidated
│   │   │   │   ├── order.py             # OrderPlaced, OrderCancelled, FillReceived
│   │   │   │   ├── position.py          # PositionOpened, PositionClosed, PositionChanged
│   │   │   │   └── risk.py              # RiskCheckFailed, DailyLossLimitReached
│   │   │   └── port/                    # Domain-defined interfaces (ports)
│   │   │       ├── __init__.py
│   │   │       ├── broker.py            # IBroker port
│   │   │       ├── market_data.py       # IMarketData port
│   │   │       ├── storage.py           # IStorage, IKeyValueStorage ports
│   │   │       ├── llm_inference.py     # ILLMInference port
│   │   │       ├── notifications.py     # INotification port
│   │   │       └── probability.py       # IProbabilityInference port
│   │   │
│   │   ├── trading/                     # Trading domain
│   │   │   ├── model/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── entities.py          # Position, Signal (with full lifecycle)
│   │   │   │   ├── aggregates.py        # Portfolio (with slippage, commission, scale-in)
│   │   │   │   ├── enums.py             # Side, SignalType, Source, MarketState, etc.
│   │   │   │   ├── value_objects.py     # OHLC, OrderBook, AMTResult, VolumeProfileLevel
│   │   │   │   └── cvd.py               # CVD models
│   │   │   ├── event_store.py           # Abstract EventStore + AuditTrailVerifier
│   │   │   └── service/
│   │   │       ├── risk_manager.py      # RiskManager (daily drawdown, kill switch)
│   │   │       ├── signal_validator.py  # Signal validation domain service
│   │   │       └── trade_aggregate.py   # Trade aggregate adapter
│   │   │
│   │   ├── amt/                         # AMT analysis domain
│   │   │   ├── model/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── amt_models.py        # VolumeProfile, Absorption, TripleAResult, etc.
│   │   │   │   └── phase_results.py     # InitialBalanceResult, AcceptanceResult, etc.
│   │   │   └── service/
│   │   │       ├── __init__.py
│   │   │       ├── amt_analyzer.py      # Main orchestrator (thin, delegates)
│   │   │       ├── volume_profile.py    # Volume profile construction (CME Two-Row)
│   │   │       ├── lvn_detector.py      # LVN/HVN detection (percentile-based)
│   │   │       ├── cvd_tracker.py       # CVD tracking (slope, divergence, z-score)
│   │   │       ├── aggression_scorer.py # Multi-signal additive scoring (7-component)
│   │   │       ├── acceptance_rejection.py # Acceptance/Rejection engine
│   │   │       ├── market_state_engine.py  # BALANCED/IMBALANCED classification
│   │   │       ├── profile_classifier.py  # Profile shape, POC migration
│   │   │       ├── orderflow_detectors.py # BigTrade, Bubble, OFI, Absorption
│   │   │       ├── initial_balance_engine.py # IB analysis
│   │   │       ├── break_detector.py    # IB break detection
│   │   │       ├── displacement_detector.py # Displacement detection
│   │   │       ├── drive_tracker.py     # Momentum tracking
│   │   │       ├── session_context.py   # Gap analysis, OBI, session info
│   │   │       ├── opening_classifier.py # Opening type classification
│   │   │       ├── mtf_analyzer.py      # Multi-timeframe AMT
│   │   │       ├── market_structure_classifier.py # Market structure
│   │   │       ├── gap_analyzer.py      # Gap analysis
│   │   │       ├── oi_analyzer.py       # Open interest analysis
│   │   │       ├── footprint_analyzer.py # Footprint analysis
│   │   │       ├── vwap_service.py      # VWAP calculation
│   │   │       ├── signal_generator.py  # Signal generation (Fabio spec gating)
│   │   │       └── signal_pipeline.py   # Signal pipeline coordination
│   │   │
│   │   ├── exit/                        # Trade management domain
│   │   │   ├── model/
│   │   │   │   ├── __init__.py
│   │   │   │   └── exit_models.py       # ExitSignal, PartitionState, etc.
│   │   │   └── service/
│   │   │       ├── __init__.py
│   │   │       ├── exit_engine.py       # Main exit orchestrator
│   │   │       ├── exit_rules.py        # Pure exit rule functions
│   │   │       ├── trail_engine.py      # ATR/VWAP/CVD trailing stops
│   │   │       ├── partition_exit_manager.py # P1/P2/P3 partition exits
│   │   │       ├── pyramid_manager.py   # Structured add-on management
│   │   │       ├── scale_manager.py     # Scale-in management (40/30/30)
│   │   │       ├── position_sizer.py    # Fixed fractional sizing
│   │   │       ├── structural_stop_engine.py # Structural SL placement
│   │   │       └── loss_tracker.py      # Daily loss tracking, circuit breakers
│   │   │
│   │   ├── ai/                          # AI/ML domain
│   │   │   ├── model/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── observation.py       # AMTObservation
│   │   │   │   └── predictions.py       # Prediction models
│   │   │   ├── service/
│   │   │   │   ├── __init__.py
│   │   │   │   ├── generative_ai_service.py # LLM integration
│   │   │   │   ├── prompt_builder.py    # Prompt construction
│   │   │   │   ├── response_parser.py   # LLM response parsing
│   │   │   │   ├── llm_rationale_service.py # Rationale generation
│   │   │   │   ├── rule_based_rationale.py  # Rule-based rationale
│   │   │   │   └── mlx_compute.py       # Apple Silicon GPU compute
│   │   │   └── rl/                      # Reinforcement learning
│   │   │       ├── __init__.py
│   │   │       ├── valentini_env.py     # Valentini trading environment
│   │   │       ├── reward_shaper.py     # Reward shaping
│   │   │       ├── trainer.py           # RL training
│   │   │       └── data_loader.py       # RL data loading
│   │   │
│   │   └── risk/                        # Risk domain
│   │       ├── model/
│   │       │   ├── __init__.py
│   │       │   └── risk_assessment.py   # RiskAssessment value object
│   │       └── service/
│   │           ├── __init__.py
│   │           ├── risk_sizing_engine.py    # Risk-based position sizing
│   │           ├── risk_tier_engine.py      # Risk tier management
│   │           ├── circuit_breaker.py       # Domain circuit breaker
│   │           ├── flash_crash_protector.py # Flash crash protection
│   │           └── self_healing.py          # Self-healing / recovery
│   │
│   ├── application/                     # Application layer — orchestration only
│   │   ├── command/                     # Input DTOs (immutable)
│   │   │   ├── __init__.py
│   │   │   └── trading_commands.py      # UpdateTick, EvaluateEntry, CheckExit, etc.
│   │   │
│   │   ├── handler/                     # Event handlers (subscribe → react)
│   │   │   ├── __init__.py
│   │   │   ├── update_tick_handler.py   # TickReceived → AMT analysis
│   │   │   ├── evaluate_entry_handler.py # AMTAnalyzed → Signal evaluation
│   │   │   ├── check_exit_handler.py    # TickReceived → Exit evaluation
│   │   │   ├── llm_entry_handler.py     # LLM-based entry decisions
│   │   │   ├── llm_overseer_handler.py  # LLM overseer validation
│   │   │   ├── llm_decision_processor.py # LLM decision processing
│   │   │   ├── llm_worker.py            # Threaded LLM worker
│   │   │   ├── rl_handler.py            # RL status/train/evaluate
│   │   │   ├── trade_lifecycle_handler.py # Position lifecycle management
│   │   │   ├── post_trade_analyst.py    # Post-trade analysis
│   │   │   └── pre_candle_advisor.py    # Pre-candle advisory
│   │   │
│   │   ├── service/                     # Application services (thin orchestration)
│   │   │   ├── __init__.py
│   │   │   ├── session_orchestrator.py  # Per-symbol event loop (THE core)
│   │   │   ├── session_state_manager.py # Per-symbol state management
│   │   │   ├── session_cache.py         # Cached analysis data
│   │   │   ├── session_risk_coordinator.py # Per-symbol risk coordination
│   │   │   ├── session_phase_manager.py # Session phase management
│   │   │   ├── session_event_logger.py  # Session event logging
│   │   │   ├── session_event_router.py  # Session event routing
│   │   │   ├── amt_service.py           # AMT analysis orchestration
│   │   │   ├── entry_coordinator.py     # Entry coordination
│   │   │   ├── exit_coordinator.py      # Exit coordination
│   │   │   ├── signal_coordinator.py    # Signal coordination
│   │   │   ├── signal_tracking_service.py # Signal tracking
│   │   │   ├── state_broadcaster.py     # State broadcasting to frontend
│   │   │   ├── state_snapshot_builder.py # State snapshot construction
│   │   │   ├── tick_processor.py        # Tick processing pipeline
│   │   │   ├── stream_manager.py        # Stream management
│   │   │   ├── watchdog_manager.py      # Watchdog management
│   │   │   ├── engine_lifecycle.py      # Engine lifecycle management
│   │   │   ├── experiment_context.py    # Experiment context
│   │   │   ├── forward_test_logger.py   # Forward test logging
│   │   │   └── trading_session.py       # Thin facade over orchestrator
│   │   │
│   │   ├── di/                          # Dependency injection
│   │   │   ├── __init__.py
│   │   │   ├── composition_root.py      # DI container setup
│   │   │   └── container.py             # DI container
│   │   │
│   │   └── event_bus.py                 # Application event bus (in-memory + async)
│   │
│   ├── infrastructure/                  # Infrastructure layer — adapters
│   │   ├── adapter/                     # External system adapters
│   │   │   ├── __init__.py
│   │   │   ├── dhan_adapter.py          # Dhan broker adapter
│   │   │   ├── mcx_broker.py            # MCX broker adapter
│   │   │   ├── paper_broker.py          # Paper trading broker
│   │   │   ├── delta_profile_adapter.py # Delta profile adapter
│   │   │   ├── npoc_adapter.py          # NPOC adapter
│   │   │   ├── null_notification_adapter.py # Null notification adapter
│   │   │   ├── gguf_inference_adapter.py # GGUF LLM inference
│   │   │   ├── mlx_inference_adapter.py # MLX LLM inference
│   │   │   └── lgbm_probability_adapter.py # LGBM probability inference
│   │   │
│   │   ├── storage/                     # Storage implementations
│   │   │   ├── __init__.py
│   │   │   ├── database.py              # SQLite storage (IStorage impl)
│   │   │   ├── postgresql_adapter.py    # PostgreSQL storage
│   │   │   └── redis_cache.py           # Redis cache
│   │   │
│   │   ├── config/                      # Configuration adapters
│   │   │   ├── __init__.py
│   │   │   ├── config_adapter.py        # Config adapter
│   │   │   └── settings.py              # Settings management
│   │   │
│   │   ├── serialization/               # Serialization
│   │   │   ├── __init__.py
│   │   │   └── schemas.py               # Pydantic DTOs (single source of truth)
│   │   │
│   │   ├── strategy/                    # Exchange strategies
│   │   │   ├── __init__.py
│   │   │   ├── nse_strategy.py          # NSE exchange strategy
│   │   │   └── mcx_strategy.py          # MCX exchange strategy
│   │   │
│   │   ├── alert/                       # Alert system
│   │   │   ├── __init__.py
│   │   │   └── alert_manager.py         # Alert management
│   │   │
│   │   └── metrics.py                   # Infrastructure metrics
│   │
│   ├── api/                             # API layer
│   │   ├── __init__.py
│   │   ├── main.py                      # FastAPI application entry point
│   │   ├── dependencies.py              # FastAPI dependency injection
│   │   ├── router/                      # API routers
│   │   │   ├── __init__.py
│   │   │   ├── health.py                # Health check endpoints
│   │   │   ├── trading.py               # Trading endpoints
│   │   │   ├── market.py                # Market data endpoints
│   │   │   ├── ai.py                    # AI endpoints
│   │   │   ├── rl.py                    # RL endpoints
│   │   │   ├── alerts.py                # Alert endpoints
│   │   │   ├── analysis.py              # Analysis endpoints
│   │   │   ├── metrics.py               # Metrics endpoints
│   │   │   └── observability.py         # Observability endpoints
│   │   └── sse/                         # Server-sent events
│   │       ├── __init__.py
│   │       └── gameloop.py              # SSE game loop
│   │
│   └── core/                            # Cross-cutting infrastructure
│       ├── __init__.py
│       ├── logging.py                   # Logging setup
│       ├── correlation.py               # Correlation ID tracking
│       └── metrics.py                   # Metrics collection
│
├── tests/
│   ├── conftest.py                      # Shared fixtures
│   ├── unit/
│   │   ├── domain/                      # Domain unit tests
│   │   │   ├── trading/                 # Trading domain tests
│   │   │   ├── amt/                     # AMT domain tests
│   │   │   ├── exit/                    # Exit domain tests
│   │   │   ├── ai/                      # AI domain tests
│   │   │   └── risk/                    # Risk domain tests
│   │   ├── application/                 # Application layer tests
│   │   ├── infrastructure/              # Infrastructure tests
│   │   └── api/                         # API tests
│   ├── integration/                     # Integration tests
│   │   ├── test_event_flow.py           # Event flow integration
│   │   ├── test_tick_to_execution.py    # Full tick → execution pipeline
│   │   ├── test_risk_integration.py     # Risk management integration
│   │   └── test_session_recovery.py     # Session recovery integration
│   └── e2e/                             # End-to-end tests
│       ├── test_valentini_scalper.py    # Valentini scalper E2E
│       └── test_triple_a_validation.py  # Triple-A validation E2E
│
├── config/                              # Configuration files
│   ├── base.yaml                        # Base configuration
│   ├── environments/
│   │   ├── development.yaml
│   │   ├── paper.yaml
│   │   └── live.yaml
│   ├── strategies/
│   │   ├── nse_options.yaml
│   │   └── mcx_options.yaml
│   ├── feature_flags.yaml
│   └── instruments.json
│
└── scripts/                             # Operational scripts
    ├── generate_types.py                # Generate TypeScript from Pydantic
    ├── run_backtest.py                  # Backtest runner
    └── parallel_test.py                 # Parallel comparison test
```

---

## Phase 0: Foundation — Event-Driven Core Skeleton

**Goal**: Establish the event-driven backbone that every subsequent phase plugs into.
No business logic yet — just the plumbing.

### 0.1 — Domain Event System

**Files**:
- `app/domain/shared/event/base.py` — `DomainEvent` base class
- `app/domain/shared/event/market.py` — `TickReceived`
- `app/domain/shared/event/analysis.py` — `AMTAnalyzed`, `AIAnalysisCompleted`
- `app/domain/shared/event/signal.py` — `SignalGenerated`, `SignalValidated`
- `app/domain/shared/event/order.py` — `OrderPlaced`, `OrderCancelled`, `FillReceived`
- `app/domain/shared/event/position.py` — `PositionOpened`, `PositionClosed`, `PositionChanged`
- `app/domain/shared/event/risk.py` — `RiskCheckFailed`, `DailyLossLimitReached`
- `app/domain/shared/event/__init__.py` — re-exports

**Design decisions**:
- Every event is a frozen dataclass with `event_id`, `timestamp`, `idempotency_key`
- Factory methods (`.create()`) on each event for clean construction with auto-generated idempotency keys
- `idempotency_key` is deterministic from event content (not random UUID) — same inputs → same key
- Event registry (`EVENT_TYPES` dict) for serialization/deserialization

**Tests**: 14 test files, ~80 tests
- Each event type: construction, immutability, idempotency key determinism
- Event registry: round-trip serialization

### 0.2 — Event Bus

**Files**:
- `app/application/event_bus.py` — Application event bus

**Design decisions**:
- In-memory pub/sub with typed event channels
- Idempotency filtering (skip duplicate `event_id`)
- Error isolation: handler failure is caught and logged, never crashes the bus
- Support for both sync and async handlers
- Subscription management (subscribe/unsubscribe)
- Event history buffer (configurable, default 10,000 events) for replay

**Tests**: 1 test file, ~12 tests
- Publish/subscribe, type filtering, idempotency, error isolation, unsubscribe

### 0.3 — Event Store

**Files**:
- `app/domain/trading/event_store.py` — Abstract `EventStore` + `AuditTrailVerifier`
- `app/infrastructure/storage/event_store.py` — SQLite implementation

**Design decisions**:
- Append-only storage with idempotency enforcement
- Query by `aggregate_id`, `event_type`, `start_time`, `end_time`
- `AuditTrailVerifier` for deterministic state reconstruction
- Abstract base class; SQLite for dev, PostgreSQL for prod

**Tests**: 1 test file, ~10 tests
- Append, query, idempotency enforcement, replay, audit verification

### 0.4 — Domain Ports (Interfaces)

**Files**:
- `app/domain/shared/port/broker.py` — `IBroker`
- `app/domain/shared/port/market_data.py` — `IMarketData`
- `app/domain/shared/port/storage.py` — `IStorage`, `IKeyValueStorage`, sub-ports
- `app/domain/shared/port/llm_inference.py` — `ILLMInference`
- `app/domain/shared/port/notifications.py` — `INotification`
- `app/domain/shared/port/probability.py` — `IProbabilityInference`

**Design decisions**:
- Ports are defined in the **domain** layer, not infrastructure
- Use `Protocol` for structural typing (no inheritance required)
- Interface segregation: `ITickStorage`, `ITradeStorage`, etc. compose into `IStorage`

**Tests**: None (interfaces are tested via adapter implementations)

### 0.5 — DI Container

**Files**:
- `app/application/di/container.py` — DI container
- `app/application/di/composition_root.py` — Wiring

**Design decisions**:
- Constructor-based injection (no service locator)
- Module-level singletons for FastAPI `Depends()`
- All infrastructure adapters are registered in the composition root
- Domain services receive ports (interfaces), not concrete implementations

**Tests**: 1 test file, ~6 tests
- Container resolution, singleton lifecycle, override for testing

### Phase 0 Deliverables

- ✅ 8 event types with factory methods
- ✅ Event bus with idempotency and error isolation
- ✅ Abstract + SQLite event store
- ✅ 6 domain ports
- ✅ DI container with composition root
- ✅ ~108 tests passing

---

## Phase 1: Domain Models — Trading Core

**Goal**: Port the complete domain model from `backend` with zero simplification.

### 1.1 — Value Objects

**Files**:
- `app/domain/trading/model/value_objects.py`

**Port from**: `backend/app/domain/trading/models/value_objects.py`

**Key models**:
- `OHLC` — with `create()` factory, Decimal fields
- `OrderBook`, `OrderBookLevel`
- `VolumeProfileLevel` — with delta property
- `AggressivePrint`
- `AMTResult` — simplified direct-attribute storage (post-refactoring version)
- `StrategyStats`

**Tests**: `tests/unit/domain/trading/test_value_objects.py` — ~25 tests

### 1.2 — Entities

**Files**:
- `app/domain/trading/model/entities.py`

**Port from**: `backend/app/domain/trading/models/entities.py`

**Key models**:
- `Signal` — with `create()` factory, `is_buy`, full metadata
- `Position` — with full lifecycle: `cushion_state`, `initial_stop`, `peak_profit`, `mae`, `mfe`, `tick_count`, `partial_taken`, `runner_active`, `breakeven_set`, `atr_trail_active`, `scale_step`, `entry_lvns`, `update_pnl()`, `move_stop_to_breakeven()`, `set_partial_taken()`, `should_close()`, `close()`, `from_signal()`, `validate_cushion_transition()`, `advance_cushion_state()`

**Tests**: `tests/unit/domain/trading/test_entities.py` — ~30 tests

### 1.3 — Aggregates

**Files**:
- `app/domain/trading/model/aggregates.py`

**Port from**: `backend/app/domain/trading/models/aggregates.py`

**Key models**:
- `Portfolio` — with `PortfolioConfig`, slippage model, commission model, tiered risk by confidence, `process_tick()`, `open_position()`, `close_position()`, `partial_close_position()`, `add_to_position()`, `recover_position()`, `has_straddle_conflict()`, `get_open_positions_summary()`

**Tests**: `tests/unit/domain/trading/test_aggregates.py` — ~35 tests

### 1.4 — Enums

**Files**:
- `app/domain/trading/model/enums.py`

**Port from**: `backend/app/domain/trading/models/enums.py`

**Key enums**: `Side`, `SignalType`, `Source`, `MarketState`, `MarketStructureState`, `SetupType`, `PositionStatus`, `Sentiment`, `TrendDirection`, `CushionState`, `MessageRole`, `MarketStateCodec`, `ProfileShapeCodec`

**Tests**: `tests/unit/domain/trading/test_enums.py` — ~15 tests

### Phase 1 Deliverables

- ✅ Complete domain model (value objects, entities, aggregates, enums)
- ✅ `Position` with full lifecycle management
- ✅ `Portfolio` with slippage, commission, scale-in, straddle prevention
- ✅ ~105 tests passing

---

## Phase 2: AMT Analysis Pipeline

**Goal**: Port the complete 6-stage AMT pipeline. This is the heart of the system.
Each stage is an independent, testable domain service.

### 2.1 — AMT Models

**Files**:
- `app/domain/amt/model/amt_models.py` — VolumeProfile, Absorption, TripleAResult, Signal, CVD models
- `app/domain/amt/model/phase_results.py` — InitialBalanceResult, AcceptanceResult, BreakResult, POCMigrationResult

**Tests**: `tests/unit/domain/amt/test_amt_models.py` — ~15 tests

### 2.2 — Volume Profile

**Files**:
- `app/domain/amt/service/volume_profile.py`

**Port from**: `backend/app/domain/services/volume_profile.py`

**Key functions**:
- `create_profile()` — CME Two-Row Pairs, delta profile buckets
- `calculate_vwap()` — with standard deviation bands

**Tests**: `tests/unit/domain/amt/test_volume_profile.py` — ~20 tests

### 2.3 — LVN/HVN Detection

**Files**:
- `app/domain/amt/service/lvn_detector.py`

**Port from**: `backend/app/domain/services/lvn_detector.py`

**Key functions**:
- `LVNLevel`, `HVNLevel` dataclasses
- `_smooth_array()` — centered moving average
- `_percentile()` — linear interpolation percentile
- `detect_lvn_hvn()` — percentile-based with clustering
- `LVNPersistenceTracker` — cross-bar tracking

**Tests**: `tests/unit/domain/amt/test_lvn_detector.py` — ~25 tests

### 2.4 — CVD Tracker

**Files**:
- `app/domain/amt/service/cvd_tracker.py`

**Port from**: `backend/app/domain/fabio_ai/services/cvd_tracker.py`

**Key features**:
- `CVDState` — value, slope, has_divergence, divergence_type, z_score
- `CVDTracker` — 500-point history, linear regression slope, divergence detection, session boundary auto-reset, sign persistence filter

**Tests**: `tests/unit/domain/amt/test_cvd_tracker.py` — ~15 tests

### 2.5 — Aggression Scorer

**Files**:
- `app/domain/amt/service/aggression_scorer.py`

**Port from**: `backend/app/domain/fabio_ai/services/aggression_scorer.py`

**Key features**:
- 7-component additive scoring (max 4.5): footprint, CVD, big trade, absorption, OFI, confluence, volume bubble
- `AggressionResult` — score, confirmed, pyramid_eligible, confidence, breakdown
- `PersistentAggressionScorer` — with persistence bars

**Tests**: `tests/unit/domain/amt/test_aggression_scorer.py` — ~20 tests

### 2.6 — Acceptance/Rejection Engine

**Files**:
- `app/domain/amt/service/acceptance_rejection.py`

**Port from**: `backend/app/domain/services/acceptance_rejection.py`

**Key features**:
- `AcceptanceRejectionEngine` — time accumulation, velocity, wick analysis, liquidity sweep
- `ARResult` — accepted_above/below, rejected_at_high/low, liquidity_sweep

**Tests**: `tests/unit/domain/amt/test_acceptance_rejection.py` — ~15 tests

### 2.7 — Market State Engine

**Files**:
- `app/domain/amt/service/market_state_engine.py`

**Port from**: `backend/app/domain/fabio_ai/services/market_state_engine.py`

**Key features**:
- `detect_market_state()` — BALANCED/IMBALANCED with zone sub-classification
- `MarketStateResult` — state, zone, confidence, trigger, displacement, acceptance, balance_ratio, extreme_deviation
- `log_state_transition()`

**Tests**: `tests/unit/domain/amt/test_market_state_engine.py` — ~15 tests

### 2.8 — Profile Classifier

**Files**:
- `app/domain/amt/service/profile_classifier.py`

**Port from**: `backend/app/domain/fabio_ai/services/profile_classifier.py`

**Key features**:
- `classify_shape()` — P/b/D/B classification
- `POCMigrationTracker` — POC migration monitoring

**Tests**: `tests/unit/domain/amt/test_profile_classifier.py` — ~12 tests

### 2.9 — Order Flow Detectors

**Files**:
- `app/domain/amt/service/orderflow_detectors.py`

**Port from**: `backend/app/domain/fabio_ai/services/orderflow_detectors.py`

**Key features**:
- `BigTradeDetector` — large trade detection
- `BubbleDetector` — volume bubble detection
- `OFICalculator` — Order Flow Imbalance
- `AbsorptionDetector` — professional absorption detection

**Tests**: `tests/unit/domain/amt/test_orderflow_detectors.py` — ~18 tests

### 2.10 — Remaining AMT Services

**Files**:
- `app/domain/amt/service/initial_balance_engine.py` — IB analysis
- `app/domain/amt/service/break_detector.py` — IB break detection
- `app/domain/amt/service/displacement_detector.py` — Displacement detection
- `app/domain/amt/service/drive_tracker.py` — Momentum tracking
- `app/domain/amt/service/session_context.py` — Gap analysis, OBI, session info
- `app/domain/amt/service/opening_classifier.py` — Opening type classification
- `app/domain/amt/service/mtf_analyzer.py` — Multi-timeframe AMT
- `app/domain/amt/service/market_structure_classifier.py` — Market structure
- `app/domain/amt/service/gap_analyzer.py` — Gap analysis
- `app/domain/amt/service/oi_analyzer.py` — OI analysis
- `app/domain/amt/service/footprint_analyzer.py` — Footprint analysis
- `app/domain/amt/service/vwap_service.py` — VWAP calculation
- `app/domain/amt/service/signal_generator.py` — Signal generation (Fabio spec)
- `app/domain/amt/service/signal_pipeline.py` — Signal pipeline coordination

**Tests**: ~12 test files, ~120 tests

### 2.11 — AMT Orchestrator

**Files**:
- `app/domain/amt/service/amt_analyzer.py` — Thin orchestrator that delegates to all AMT services

**Design decisions**:
- This file is a **pipeline coordinator**, not a god-object
- Each stage is a pure function or stateless service
- Pipeline stages: Profile → Market State → Setup → Session Context → MTF → Order Flow
- Output: `AMTResult` value object

**Tests**: `tests/unit/domain/amt/test_amt_analyzer.py` — ~15 integration tests

### Phase 2 Deliverables

- ✅ 20+ AMT domain services, each independently testable
- ✅ Complete 6-stage AMT pipeline
- ✅ ~285 tests passing

---

## Phase 3: Trade Management (Exit Domain)

**Goal**: Port the complete trade management system — exits, pyramiding, position sizing, stops.

### 3.1 — Exit Models

**Files**:
- `app/domain/exit/model/exit_models.py` — ExitSignal, PartitionState, PyramidSignal, StructuralStop

**Tests**: ~8 tests

### 3.2 — Exit Rules (Pure Functions)

**Files**:
- `app/domain/exit/service/exit_rules.py`

**Port from**: `backend/app/domain/fabio_ai/services/exit_rules.py`

**Key features**:
- `TIME_STOP_TABLE` — session-aware time stops
- `ExitReason` constants
- `check_spread_blowout()`, `check_time_stop_with_price()`, `is_valid_rr()`, `update_excursions()`
- `classify_exit()` — Fabio exit classification

**Tests**: `tests/unit/domain/exit/test_exit_rules.py` — ~20 tests

### 3.3 — Trail Engine

**Files**:
- `app/domain/exit/service/trail_engine.py`

**Port from**: `backend/app/domain/fabio_ai/services/trail_engine.py`

**Key features**:
- ATR trailing stop (activation at R-multiple, step percentage)
- VWAP trail
- CVD breakeven
- Imbalance trail
- Tick-size rounding

**Tests**: `tests/unit/domain/exit/test_trail_engine.py` — ~18 tests

### 3.4 — Partition Exit Manager

**Files**:
- `app/domain/exit/service/partition_exit_manager.py`

**Port from**: `backend/app/domain/fabio_ai/services/partition_exit_manager.py`

**Key features**:
- P1 (30% at 1R), P2 (40% at 2R), P3 (30% trail)
- Counter-aggression detection
- Break-even logic
- Trail formula: `SL = current - (remaining_to_target × 0.40)`

**Tests**: `tests/unit/domain/exit/test_partition_exit_manager.py` — ~15 tests

### 3.5 — Pyramid Manager

**Files**:
- `app/domain/exit/service/pyramid_manager.py`

**Port from**: `backend/app/domain/fabio_ai/services/pyramid_manager.py`

**Key features**:
- Max 2 adds (3 total entries)
- Add sizes: Add 1 = 100%, Add 2 = 50% of base
- Aggression ≥ 3.0 required
- Unified stop management

**Tests**: `tests/unit/domain/exit/test_pyramid_manager.py` — ~10 tests

### 3.6 — Scale Manager

**Files**:
- `app/domain/exit/service/scale_manager.py`

**Port from**: `backend/app/domain/fabio_ai/services/scale_manager.py`

**Key features**:
- 40/30/30 scale-in management

**Tests**: `tests/unit/domain/exit/test_scale_manager.py` — ~8 tests

### 3.7 — Position Sizer

**Files**:
- `app/domain/exit/service/position_sizer.py`

**Port from**: `backend/app/domain/fabio_ai/services/position_sizer.py`

**Key features**:
- Fixed fractional sizing (0.5% risk per trade)
- Hard ceiling: 1.0% per trade
- `PositionSize` result with lots, risk_amount, risk_pct, validity

**Tests**: `tests/unit/domain/exit/test_position_sizer.py` — ~12 tests

### 3.8 — Structural Stop Engine

**Files**:
- `app/domain/exit/service/structural_stop_engine.py`

**Port from**: `backend/app/domain/fabio_ai/services/structural_stop_engine.py`

**Key features**:
- SL placement at structural invalidation levels (LVN, VA boundary, IB extreme, probe extreme)
- ATR multiplier cap
- `StopReason` enum, `StructuralStop` result

**Tests**: `tests/unit/domain/exit/test_structural_stop_engine.py` — ~15 tests

### 3.9 — Loss Tracker

**Files**:
- `app/domain/exit/service/loss_tracker.py`

**Port from**: `backend/app/domain/fabio_ai/services/loss_tracker.py`

**Key features**:
- Daily loss tracking
- Circuit breakers
- Cooldown management
- `IKeyValueStorage` persistence

**Tests**: `tests/unit/domain/exit/test_loss_tracker.py` — ~10 tests

### 3.10 — Exit Engine (Orchestrator)

**Files**:
- `app/domain/exit/service/exit_engine.py`

**Port from**: `backend/app/domain/fabio_ai/services/exit_engine.py`

**Design decisions**:
- Stateless — receives `Position` object, returns `ExitDecision`
- Delegates to: exit_rules, trail_engine, partition_exit_manager, pyramid_manager, scale_manager, loss_tracker
- LLM was trained on entry only; trade management is **rule-based and deterministic**

**Tests**: `tests/unit/domain/exit/test_exit_engine.py` — ~15 integration tests

### Phase 3 Deliverables

- ✅ 10 exit domain services
- ✅ Complete trade management: exits, pyramiding, scaling, stops
- ✅ ~131 tests passing

---

## Phase 4: Risk Domain

**Goal**: Port the complete risk management system.

### 4.1 — Risk Manager

**Files**:
- `app/domain/trading/service/risk_manager.py`

**Port from**: `backend/app/domain/trading/services/risk_manager.py`

**Key features**:
- `DailyRiskState` — trade_date, starting/peak/current equity, realized_pnl, consecutive_losses, halt state
- `RiskManager` — MAX_DAILY_DRAWDOWN_PCT (2%), MAX_CONSECUTIVE_LOSSES (3), MAX_CONCURRENT_POSITIONS (5), MAX_PORTFOLIO_NOTIONAL_PCT (60%), MAX_PER_SYMBOL_NOTIONAL_PCT (20%)
- Drift detection — rolling win rate vs baseline
- Kill switch integration

**Tests**: `tests/unit/domain/trading/test_risk_manager.py` — ~20 tests

### 4.2 — Risk Sizing Engine

**Files**:
- `app/domain/risk/service/risk_sizing_engine.py`

**Port from**: `backend/app/domain/services/risk_sizing_engine.py`

**Tests**: ~10 tests

### 4.3 — Circuit Breakers

**Files**:
- `app/domain/risk/service/circuit_breaker.py`

**Port from**: `backend/app/domain/services/circuit_breakers.py`

**Tests**: ~10 tests

### 4.4 — Flash Crash Protector

**Files**:
- `app/domain/risk/service/flash_crash_protector.py`

**Port from**: `backend/app/domain/services/flash_crash_protector.py`

**Tests**: ~8 tests

### 4.5 — Self-Healing

**Files**:
- `app/domain/risk/service/self_healing.py`

**Port from**: `backend/app/domain/services/self_healing.py`

**Key features**:
- `OrderRejectionHandler` — handles broker order rejections
- `DBFallbackBuffer` — buffers events when DB is unavailable

**Tests**: ~8 tests

### 4.6 — Position Reconciliation

**Files**:
- `app/domain/trading/service/position_reconciliation.py`

**Port from**: `backend/app/domain/services/position_reconciliation.py`

**Tests**: ~8 tests

### Phase 4 Deliverables

- ✅ 6 risk domain services
- ✅ Complete risk management: drawdown, circuit breakers, self-healing
- ✅ ~64 tests passing

---

## Phase 5: Application Layer — Event-Driven Orchestration

**Goal**: Build the application services that wire domain services together via events.
This is where the event-driven architecture becomes real.

### 5.1 — Session Orchestrator (THE Core)

**Files**:
- `app/application/service/session_orchestrator.py`

**Port from**: `backend/app/application/services/trading_session.py` (decomposed)

**Design decisions**:
- **Single writer**: The orchestrator is the only component that mutates `SessionState`
- **Event-driven**: Reacts to `TickReceived`, publishes `AMTAnalyzed`, `SignalGenerated`, etc.
- **Per-symbol isolation**: Each symbol has its own `SessionState` + `SessionCache`
- **Blast radius containment**: Handler failures are caught; the event loop continues

**Event flow**:
```
TickReceived
  → update candle buffer
  → run AMT analysis (AMTService)
  → publish AMTAnalyzed
  → check session phase (SessionPhaseManager)
  → evaluate entry (EntryCoordinator + LLMEntryHandler)
  → publish SignalGenerated
  → validate signal (SignalValidator)
  → publish SignalValidated
  → execute signal (BrokerAdapter + Portfolio)
  → publish PositionOpened
  → check exits (ExitCoordinator + ExitEngine)
  → publish PositionClosed
  → build state snapshot (StateSnapshotBuilder)
  → broadcast to frontend (StateBroadcaster)
```

**Tests**: `tests/unit/application/test_session_orchestrator.py` — ~20 tests

### 5.2 — Session State Manager

**Files**:
- `app/application/service/session_state_manager.py`

**Port from**: `backend/app/application/services/session_state_manager.py`

**Key features**:
- Per-symbol `SessionState` with `SessionCache`
- Thread-safe with `RLock`
- Playbook guard management
- Session eviction (idle timeout)
- LLM throttling state

**Tests**: `tests/unit/application/test_session_state_manager.py` — ~15 tests

### 5.3 — Session Cache

**Files**:
- `app/application/service/session_cache.py`

**Port from**: `backend/app/application/services/session_cache.py`

**Key features**:
- AMT analysis caching
- Footprint data caching
- Candle buffer management (MAX_CANDLES_PER_SYMBOL = 2000)

**Tests**: `tests/unit/application/test_session_cache.py` — ~12 tests

### 5.4 — Session Risk Coordinator

**Files**:
- `app/application/service/session_risk_coordinator.py`

**Port from**: `backend/app/application/services/session_risk_coordinator.py`

**Key features**:
- Per-symbol `RiskManager` instances
- `SystemRiskState` aggregation
- Risk tier engine integration

**Tests**: `tests/unit/application/test_session_risk_coordinator.py` — ~12 tests

### 5.5 — Session Phase Manager

**Files**:
- `app/application/service/session_phase_manager.py`

**Port from**: `backend/app/application/services/session_phase_manager.py`

**Key features**:
- Session phase detection (MORNING/AFTERNOON)
- Halt/resume trading
- Initial balance tracking

**Tests**: `tests/unit/application/test_session_phase_manager.py` — ~10 tests

### 5.6 — Entry Coordinator

**Files**:
- `app/application/service/entry_coordinator.py`

**Port from**: `backend/app/application/services/entry_coordinator.py`

**Key features**:
- Signal gating (gate pipeline)
- Position sizing integration
- Risk check before entry

**Tests**: `tests/unit/application/test_entry_coordinator.py` — ~12 tests

### 5.7 — Exit Coordinator

**Files**:
- `app/application/service/exit_coordinator.py`

**Port from**: `backend/app/application/services/exit_coordinator.py`

**Key features**:
- Delegates to `ExitEngine`
- Manages partition state
- Coordinates trailing stops

**Tests**: `tests/unit/application/test_exit_coordinator.py` — ~10 tests

### 5.8 — Signal Coordinator

**Files**:
- `app/application/service/signal_coordinator.py`

**Port from**: `backend/app/application/services/signal_coordinator.py`

**Tests**: ~10 tests

### 5.9 — State Snapshot Builder

**Files**:
- `app/application/service/state_snapshot_builder.py`

**Port from**: `backend/app/application/services/state_snapshot_builder.py`

**Key features**:
- Builds the state dict for the React dashboard
- Computes `cumulative_deltas` (CVD) — backend single source of truth
- Includes portfolio, AMT, AI analysis, risk state, stats by source

**Tests**: `tests/unit/application/test_state_snapshot_builder.py` — ~12 tests

### 5.10 — State Broadcaster

**Files**:
- `app/application/service/state_broadcaster.py`

**Port from**: `backend/app/application/services/state_broadcaster.py`

**Key features**:
- Publishes state snapshots to SSE clients
- Delta compression (only send changed fields)
- Generation counter for frontend versioning

**Tests**: `tests/unit/application/test_state_broadcaster.py` — ~10 tests

### 5.11 — Tick Processor

**Files**:
- `app/application/service/tick_processor.py`

**Port from**: `backend/app/application/services/tick_processor.py`

**Tests**: ~8 tests

### 5.12 — Stream Manager

**Files**:
- `app/application/service/stream_manager.py`

**Port from**: `backend/app/application/services/stream_manager.py`

**Tests**: ~8 tests

### 5.13 — Watchdog Manager

**Files**:
- `app/application/service/watchdog_manager.py`

**Port from**: `backend/app/application/services/watchdog_manager.py`

**Tests**: ~6 tests

### 5.14 — Engine Lifecycle

**Files**:
- `app/application/service/engine_lifecycle.py`

**Port from**: `backend/app/application/services/engine_lifecycle.py`

**Key features**:
- Startup: load open positions, initialize sessions
- Shutdown: persist state, close connections
- Health monitoring

**Tests**: ~8 tests

### 5.15 — AMT Service

**Files**:
- `app/application/service/amt_service.py`

**Port from**: `backend/app/application/services/amt_service.py`

**Key features**:
- Thin wrapper around `amt_analyzer` domain service
- Publishes `AMTAnalyzed` event

**Tests**: ~8 tests

### 5.16 — LLM Entry Handler

**Files**:
- `app/application/handler/llm_entry_handler.py`

**Port from**: `backend/app/application/handlers/llm_entry_handler.py`

**Key features**:
- Builds LLM context from session state
- Calls `ILLMInference` port
- Processes LLM responses into `AgentDecision`
- Throttling and consistency guards

**Tests**: `tests/unit/application/test_llm_entry_handler.py` — ~12 tests

### 5.17 — LLM Overseer Handler

**Files**:
- `app/application/handler/llm_overseer_handler.py`

**Port from**: `backend/app/application/handlers/llm_overseer_handler.py`

**Tests**: ~10 tests

### 5.18 — Trade Lifecycle Handler

**Files**:
- `app/application/handler/trade_lifecycle_handler.py`

**Port from**: `backend/app/application/handlers/trade_lifecycle_handler.py`

**Key features**:
- Checks exits on every tick
- Manages partition exits
- Coordinates with `ExitEngine`

**Tests**: `tests/unit/application/test_trade_lifecycle_handler.py` — ~12 tests

### 5.19 — RL Handler

**Files**:
- `app/application/handler/rl_handler.py`

**Port from**: `backend/app/application/handlers/rl_handler.py`

**Tests**: ~8 tests

### 5.20 — Post-Trade Analyst

**Files**:
- `app/application/handler/post_trade_analyst.py`

**Port from**: `backend/app/application/handlers/post_trade_analyst.py`

**Tests**: ~8 tests

### Phase 5 Deliverables

- ✅ 20 application services/handlers
- ✅ Complete event-driven orchestration
- ✅ ~227 tests passing

---

## Phase 6: Infrastructure — Adapters & Storage

**Goal**: Port all infrastructure adapters. These are the only files that depend on
external libraries (httpx, asyncpg, sqlite3, etc.).

### 6.1 — Storage

**Files**:
- `app/infrastructure/storage/database.py` — SQLite `IStorage` implementation
- `app/infrastructure/storage/postgresql_adapter.py` — PostgreSQL (already exists, enhance)
- `app/infrastructure/storage/redis_cache.py` — Redis cache (already exists, enhance)

**Port from**: `backend/app/infrastructure/storage/database.py`

**Key features**:
- Full `IStorage` implementation: ticks, trades, LLM decisions, performance snapshots, session profiles, position events
- Batched tick writes (flush every 50 ticks or 5 seconds)
- Thread-safe with persistent connection + lock

**Tests**: `tests/unit/infrastructure/test_database.py` — ~20 tests

### 6.2 — Broker Adapters

**Files**:
- `app/infrastructure/adapter/dhan_adapter.py` — Enhance existing
- `app/infrastructure/adapter/mcx_broker.py` — Port from `backend`
- `app/infrastructure/adapter/paper_broker.py` — Port from `backend`

**Tests**: ~25 tests

### 6.3 — Market Data Adapters

**Files**:
- `app/infrastructure/adapter/market_data_adapter.py` — `IMarketData` implementation

**Tests**: ~10 tests

### 6.4 — LLM Inference Adapters

**Files**:
- `app/infrastructure/adapter/mlx_inference_adapter.py` — MLX (Apple Silicon)
- `app/infrastructure/adapter/gguf_inference_adapter.py` — GGUF inference
- `app/infrastructure/adapter/lgbm_probability_adapter.py` — LGBM probability

**Tests**: ~15 tests

### 6.5 — Serialization (Pydantic Schemas)

**Files**:
- `app/infrastructure/serialization/schemas.py`

**Port from**: `backend/app/infrastructure/serialization/schemas.py`

**Key schemas**: `AMTResultDTO`, `FootprintDTO`, `SignalDTO`, `PositionDTO`, `PortfolioDTO`, `OHLCDataDTO`

**Tests**: `tests/unit/infrastructure/test_schemas.py` — ~15 tests

### 6.6 — Configuration

**Files**:
- `app/infrastructure/config/config_adapter.py`
- `app/infrastructure/config/settings.py`
- `config/base.yaml`, `config/environments/*.yaml`, `config/strategies/*.yaml`

**Port from**: `backend/config/`, `backend/app/config.py`, `backend/app/config_models/`

**Tests**: ~10 tests

### 6.7 — Exchange Strategies

**Files**:
- `app/infrastructure/strategy/nse_strategy.py`
- `app/infrastructure/strategy/mcx_strategy.py`

**Port from**: `backend/app/infrastructure/strategies/`

**Tests**: ~10 tests

### 6.8 — Notifications

**Files**:
- `app/infrastructure/adapter/null_notification_adapter.py`
- `app/infrastructure/alert/alert_manager.py` — Enhance existing

**Tests**: ~8 tests

### Phase 6 Deliverables

- ✅ 15+ infrastructure adapters
- ✅ Full storage, broker, market data, LLM, serialization coverage
- ✅ ~113 tests passing

---

## Phase 7: API Layer

**Goal**: Port all API routers and the FastAPI application.

### 7.1 — API Routers

**Files**:
- `app/api/router/health.py` — `/healthz`, `/readyz`, `/system/risk-state`
- `app/api/router/trading.py` — `/api/trading/start`, `/stop`, `/state/{symbol}`
- `app/api/router/market.py` — `/api/market/data/{symbol}`, `/quotes`
- `app/api/router/ai.py` — `/api/ai/analyze/{symbol}`, `/decision/{symbol}`
- `app/api/router/rl.py` — `/api/rl/status`, `/train`, `/evaluate`
- `app/api/router/alerts.py` — `/api/alerts/active`, `/history`
- `app/api/router/analysis.py` — `/api/analysis/amt/{symbol}`, `/profile/{symbol}`
- `app/api/router/metrics.py` — `/api/metrics/prometheus`, `/custom`
- `app/api/router/observability.py` — `/api/obs/traces`, `/logs`

**Port from**: `backend/app/api/routers/`

**Tests**: `tests/unit/api/` — ~30 tests

### 7.2 — SSE / Game Loop

**Files**:
- `app/api/sse/gameloop.py`

**Port from**: `backend/app/api/websocket/gameloop.py`

**Key features**:
- Bidirectional communication
- State snapshot broadcasting
- Real-time P&L updates
- Delta compression

**Tests**: ~8 tests

### 7.3 — FastAPI Application

**Files**:
- `app/api/main.py` — Enhance existing
- `app/api/dependencies.py` — Port from `backend`

**Key features**:
- CORS middleware
- Correlation ID middleware
- Lifespan management (startup/shutdown)
- DI integration

**Tests**: ~6 tests

### Phase 7 Deliverables

- ✅ 9 API routers
- ✅ SSE streaming
- ✅ Full FastAPI application
- ✅ ~44 tests passing

---

## Phase 8: AI/ML Domain

**Goal**: Port the AI/ML subsystem — LLM integration, RL training, probability models.

### 8.1 — Generative AI Service

**Files**:
- `app/domain/ai/service/generative_ai_service.py`

**Port from**: `backend/app/domain/fabio_ai/services/generative_ai_service.py`

**Tests**: ~10 tests

### 8.2 — Prompt Builder

**Files**:
- `app/domain/ai/service/prompt_builder.py`

**Port from**: `backend/app/domain/fabio_ai/services/prompt_builder.py`

**Tests**: ~10 tests

### 8.3 — Response Parser

**Files**:
- `app/domain/ai/service/response_parser.py`

**Port from**: `backend/app/domain/fabio_ai/services/response_parser.py`

**Tests**: ~8 tests

### 8.4 — LLM Rationale Service

**Files**:
- `app/domain/ai/service/llm_rationale_service.py`

**Port from**: `backend/app/domain/fabio_ai/services/llm_rationale_service.py`

**Tests**: ~8 tests

### 8.5 — Rule-Based Rationale

**Files**:
- `app/domain/ai/service/rule_based_rationale.py`

**Port from**: `backend/app/domain/fabio_ai/services/rule_based_rationale.py`

**Tests**: ~8 tests

### 8.6 — MLX Compute

**Files**:
- `app/domain/ai/service/mlx_compute.py`

**Port from**: `backend/app/domain/fabio_ai/services/mlx_compute.py`

**Tests**: ~6 tests

### 8.7 — RL System

**Files**:
- `app/domain/ai/rl/valentini_env.py`
- `app/domain/ai/rl/reward_shaper.py`
- `app/domain/ai/rl/trainer.py`
- `app/domain/ai/rl/data_loader.py`

**Port from**: `backend/app/domain/fabio_ai/rl/`

**Tests**: ~15 tests

### 8.8 — Agent Pipeline

**Files**:
- `app/domain/ai/service/agent_pipeline.py` (from `backend/app/domain/probability/agent_pipeline.py`)

**Tests**: ~10 tests

### Phase 8 Deliverables

- ✅ 8 AI/ML domain services
- ✅ LLM integration, RL training, probability models
- ✅ ~75 tests passing

---

## Phase 9: Integration & E2E Tests

**Goal**: Verify the complete system works end-to-end.

### 9.1 — Integration Tests

**Files**:
- `tests/integration/test_event_flow.py` — Complete TickReceived → PositionClosed flow
- `tests/integration/test_tick_to_execution.py` — Full tick → signal → execution pipeline
- `tests/integration/test_risk_integration.py` — Risk management integration
- `tests/integration/test_session_recovery.py` — Session recovery after crash
- `tests/integration/test_dual_engine_sync.py` — Dual engine synchronization
- `tests/integration/test_gate_pipeline_entry_signal_chain.py` — Gate pipeline chain
- `tests/integration/test_failure_scenarios.py` — Failure scenario handling

**Target**: ~40 integration tests

### 9.2 — E2E Tests

**Files**:
- `tests/e2e/test_valentini_scalper.py` — Valentini scalper E2E (enhance existing)
- `tests/e2e/test_triple_a_validation.py` — Triple-A validation (enhance existing)

**Target**: ~10 E2E tests

### Phase 9 Deliverables

- ✅ 6 integration test files
- ✅ 2 E2E test files
- ✅ ~50 tests passing

---

## Phase 10: TypeScript Type Generation

**Goal**: Eliminate manual type duplication between Python and TypeScript.

### 10.1 — Type Generator

**Files**:
- `scripts/generate_types.py` — Enhance existing

**Design decisions**:
- Generates `frontend/types_generated.ts` from Pydantic DTOs
- Run via `npm run generate-types`
- Covers all DTOs: `AMTAnalysis`, `OHLCData`, `OrderBook`, `TradePosition`, `Portfolio`, etc.

**Tests**: ~5 tests (verify generated output matches expected)

### Phase 10 Deliverables

- ✅ Automated TypeScript type generation
- ✅ Zero manual type duplication
- ✅ ~5 tests passing

---

## Summary: Test Count Targets

| Phase | Test Files | Tests | Cumulative |
|-------|-----------|-------|------------|
| 0 — Foundation | 8 | ~108 | 108 |
| 1 — Domain Models | 5 | ~105 | 213 |
| 2 — AMT Pipeline | 20 | ~285 | 498 |
| 3 — Trade Management | 12 | ~131 | 629 |
| 4 — Risk Domain | 7 | ~64 | 693 |
| 5 — Application | 22 | ~227 | 920 |
| 6 — Infrastructure | 10 | ~113 | 1,033 |
| 7 — API | 5 | ~44 | 1,077 |
| 8 — AI/ML | 9 | ~75 | 1,152 |
| 9 — Integration/E2E | 8 | ~50 | 1,202 |
| 10 — Type Generation | 1 | ~5 | 1,207 |
| **Total** | **107** | **~1,207** | **~1,207** |

---

## Key Architectural Decisions

### ADR-1: Event-Sourced Core

**Decision**: Every state mutation originates from a domain event. No service
directly mutates another service's state.

**Rationale**: Eliminates an entire class of bugs (hidden state mutations, race
conditions). Makes the system auditable (event log is the audit trail). Enables
replay for debugging and testing.

**Consequences**: Slightly more code (event classes, handlers). Significantly
easier to reason about. Full audit trail for free.

### ADR-2: Single Writer Per Symbol

**Decision**: Each symbol's `SessionState` has exactly one writer — the session
event loop. All other components are read-only observers or event subscribers.

**Rationale**: Eliminates race conditions without locks. The existing backend
uses `threading.RLock` in many places; the event-driven approach makes this
unnecessary.

**Consequences**: Requires async event processing. Handlers must be fast (or
run in background threads).

### ADR-3: Blast Radius Containment

**Decision**: Each symbol's session is an isolated aggregate. Handler failures
are caught and logged; they never propagate to the event loop.

**Rationale**: A crash in one symbol's LLM processing should never affect
another symbol's trading.

**Consequences**: Requires careful error handling in every handler. Requires
per-symbol health monitoring.

### ADR-4: Ports Defined in Domain Layer

**Decision**: All ports (interfaces) are defined in `app/domain/shared/port/`.
Infrastructure adapters implement these ports.

**Rationale**: Dependency inversion. The domain layer has zero dependencies
on infrastructure. You can swap SQLite for PostgreSQL without touching domain code.

**Consequences**: More files. Cleaner architecture. Easier testing.

### ADR-5: No Service Locator

**Decision**: Constructor-based dependency injection only. No `ServiceGraph`,
no global state (except immutable configuration).

**Rationale**: Explicit dependencies. Easier testing. No hidden coupling.

**Consequences**: More verbose constructors. DI container required. Worth it.

### ADR-6: Immutable Domain Events

**Decision**: All events are frozen dataclasses. Events are never modified after
creation.

**Rationale**: Thread safety. Deterministic replay. Audit trail integrity.

**Consequences**: Events must contain all data needed at creation time. Cannot
add fields later.

### ADR-7: Idempotent Events

**Decision**: Events have deterministic `idempotency_key` derived from content.
Duplicate events are silently dropped.

**Rationale**: Network retries, reconnections, and replay can cause duplicate
events. The system must be idempotent.

**Consequences**: Requires careful idempotency key design. Storage overhead for
deduplication set.

### ADR-8: Pure Functions for Domain Logic

**Decision**: Domain services are pure functions (no side effects). They receive
input, return output, and don't mutate anything.

**Rationale**: Easy to test. Easy to reason about. No hidden state.

**Consequences**: State must be passed explicitly. Some services need to be
wrapped in stateful adapters (e.g., `CVDTracker` maintains history).

---

## Migration Strategy

### Parallel Run

1. Deploy backendv2 alongside existing backend
2. Feed identical market data to both systems
3. Compare outputs (signals, positions, P&L) in real-time
4. Log discrepancies for analysis
5. Gradually shift traffic from old to new

### Rollback Plan

- Keep old backend running until backendv2 has 7 days of clean parallel operation
- Feature flags control which backend handles live trading
- Instant rollback via feature flag toggle

### Risk Mitigation

- Each phase is independently testable and deployable
- Phase 0-4 can run in "shadow mode" (process events, don't trade)
- Phase 5+ requires shadow mode validation before live trading
- Every event is logged; full replay capability for post-mortem

---

## File Count Estimate

| Layer | Existing backend | Target backendv2 |
|-------|-----------------|------------------|
| Domain models | ~30 | ~30 |
| Domain services | ~120 | ~120 |
| Application services | ~25 | ~25 |
| Infrastructure adapters | ~15 | ~15 |
| API layer | ~12 | ~12 |
| Config/scripts | ~15 | ~15 |
| **Total source files** | **~217** | **~217** |
| **Test files** | **176** | **107** |
| **Tests** | **2,061** | **~1,207** |

Note: backendv2 has fewer test files but comparable coverage because:
- Pure functions are easier to test (fewer mocks needed)
- Event-driven architecture enables better integration tests
- Each handler is independently testable
