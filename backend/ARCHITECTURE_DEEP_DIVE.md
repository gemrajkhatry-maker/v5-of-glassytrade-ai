# Backend Trading System — Complete Architecture & How-It-Works Guide

> **Scope**: Every component, every flow, every protocol. From network bytes to high-level trading abstractions.

---

## Table of Contents

1. [System Overview](#1-system-overview)
2. [Clean Architecture Layers](#2-clean-architecture-layers)
3. [Component Interaction Map](#3-component-interaction-map)
4. [How Tick Processing Works](#4-how-tick-processing-works)
5. [How AMT Analysis Works](#5-how-amt-analysis-works)
6. [How the Probability Agent Pipeline Works](#6-how-the-probability-agent-pipeline-works)
7. [How LLM Entry Works](#7-how-llm-entry-works)
8. [How LLM Overseer Works](#8-how-llm-overseer-works)
9. [How Trade Lifecycle & Exits Work](#9-how-trade-lifecycle--exits-work)
10. [How Event Sourcing Works](#10-how-event-sourcing-works)
11. [How Streaming & Reconnection Work](#11-how-streaming--reconnection-work)
12. [How Persistence Works](#12-how-persistence-works)
13. [How Risk Management Works](#13-how-risk-management-works)
14. [How Options Selection Works](#14-how-options-selection-works)
15. [How WebSocket Frontend Updates Work](#15-how-websocket-frontend-updates-work)
16. [How Crash Recovery Works](#16-how-crash-recovery-works)
17. [How Observability Works](#17-how-observability-works)
18. [How RL Training Works](#18-how-rl-training-works)
19. [Complete Flow Diagrams](#19-complete-flow-diagrams)
20. [Exchange Support Matrix](#20-exchange-support-matrix)
21. [Performance Characteristics](#21-performance-characteristics)
22. [Configuration & Feature Flags](#22-configuration--feature-flags)
23. [API Layer](#23-api-layer-backendappapi)
24. [Pipeline Layer](#24-pipeline-layer-backendapppipeline)
25. [Fabio AI Strategy Engine](#25-fabio-ai-strategy-engine)
26. [Fabio AI Models](#26-fabio-ai-models)
27. [Trading Value Objects & Aggregates](#27-trading-value-objects--aggregates)
28. [Serialization Layer](#28-serialization-layer-backendappinfrastructureserializationschemaspy)
29. [Configuration Models](#29-configuration-models)
30. [Domain Services Catalog](#30-domain-services-catalog)
31. [Fabio AI Services Catalog](#31-fabio-ai-services-catalog)
32. [Design Patterns Summary](#32-design-patterns-summary)
33. [Known Limitations & Technical Debt](#33-known-limitations--technical-debt)
23. [API Layer](#23-api-layer-backendappapi)
24. [Pipeline Layer](#24-pipeline-layer-backendapppipeline)
25. [Fabio AI Strategy Engine](#25-fabio-ai-strategy-engine)
26. [Fabio AI Models](#26-fabio-ai-models)
27. [Trading Value Objects & Aggregates](#27-trading-value-objects--aggregates)
28. [Serialization Layer](#28-serialization-layer-backendappinfrastructureserializationschemaspy)
29. [Configuration Models](#29-configuration-models)
30. [Domain Services Catalog](#30-domain-services-catalog)
31. [Fabio AI Services Catalog](#31-fabio-ai-services-catalog)
32. [Design Patterns Summary](#32-design-patterns-summary)
33. [Known Limitations & Technical Debt](#33-known-limitations--technical-debt)

---

## 1. System Overview

The backend is a **Python-based low-latency algorithmic options trading system** for Indian derivatives markets (NSE NIFTY/BANKNIFTY/FINNIFTY options and MCX commodity options). It implements **Fabio Valentini's Auction Market Theory (AMT)** methodology combined with LLM-powered trade decisions, first-passage probability models, and reinforcement learning.

### Architectural Style

**Domain-Driven Design (DDD) + Hexagonal Architecture + Event-Driven + Pipeline Processing**

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              USAGE LAYER                                            │
│                                                                                     │
│   ┌──────────────────────┐    ┌──────────────────────┐    ┌──────────────────────┐  │
│   │    TradingEngine     │    │   TradingSession     │    │   PortfolioCoord.    │  │
│   │  (engine.py:852L)    │    │  (trading_session.py)│    │   (cross-symbol)     │  │
│   │                      │    │                      │    │                      │  │
│   │  Root orchestrator   │    │  Per-symbol state    │    │  5-rule filtering    │  │
│   │  Tick loop + streams │    │  Handler delegation  │    │  Notional limits     │  │
│   └──────────┬───────────┘    └──────────┬───────────┘    └──────────┬───────────┘  │
│              │                           │                           │              │
│              └───────────────────────────┼───────────────────────────┘              │
│                                          │                                          │
│                                          ▼                                          │
│  ┌─────────────────────────────────────────────────────────────────────────────┐    │
│  │                        IBrokerPort Interface                                │    │
│  │                     (Abstract Broker Contract)                              │    │
│  │                                                                             │    │
│  │  Market Data:  fetch_history(), get_ltp(), stream_full(), scan_candidates() │    │
│  │  Streaming:    stream_full(), stream_depth()                                │    │
│  │  Orders:       execute_order(), cancel_order()                              │    │
│  │  Options:      get_option_chain()                                           │    │
│  └──────────────────────────────────────────┬──────────────────────────────────┘    │
│                                             │                                       │
│                    ┌────────────────────────┼────────────────────────┐              │
│                    ▼                        ▼                        ▼              │
│  ┌───────────────────────┐  ┌───────────────────────┐  ┌───────────────────────┐   │
│  │     PaperBroker       │  │      DhanBroker       │  │   Future Brokers      │   │
│  │  (paper_broker.py)    │  │ (dhan_adapter.py)     │  │   (Zerodha, Upstox)   │   │
│  │                       │  │                       │  │                       │   │
│  │  Realistic Indian     │  │  WebSocket + REST     │  │   Pluggable via       │   │
│  │  market cost model    │  │  Polling fallback     │  │   IBrokerPort         │   │
│  │  Testing & dev        │  │  Production-ready     │  │   interface           │   │
│  └───────────────────────┘  └───────────┬───────────┘  └───────────────────────┘   │
│                                         │                                           │
└─────────────────────────────────────────┼───────────────────────────────────────────┘
                                          │
                     ┌────────────────────┼────────────────────┐
                     ▼                    ▼                    ▼
   ┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐
   │   Application Layer │  │    Domain Layer     │  │ Infrastructure Layer│
   │                     │  │                     │  │                     │
   │  Handlers: AMT,     │  │  AMTAnalyzer        │  │  SQLiteStorage      │
   │  LLM Entry,         │  │  EntryGate          │  │  AsyncPersistence   │
   │  Overseer,          │  │  TradeManager       │  │  InMemoryEventBus   │
   │  Lifecycle, RL      │  │  SignalCoordinator  │  │  MLX/LLM Inference  │
   │  Services: Session, │  │  RiskManager        │  │  LightGBM           │
   │  Risk, Journal      │  │  AgentPipeline       │  │  Telegram           │
   └─────────────────────┘  └─────────────────────┘  └─────────────────────┘
```

---

## 2. Clean Architecture Layers

### Layer 1: Domain Layer — Pure Business Logic

**Location**: `backend/app/domain/`

**Purpose**: Broker-agnostic business rules, entities, value objects, and error types. Zero external dependencies. All monetary values use `Decimal` for precision.

#### Domain Models (`domain/trading/models/`)

**Value Objects**:
```
OHLC
├── open, high, low, close: Decimal
├── volume: Decimal
├── delta: Decimal              # Cumulative buy-sell volume delta
├── vwap: Decimal               # Volume-weighted average price
├── taker_buy_volume: Decimal
└── timestamp: datetime

AMTResult (150+ fields)
├── market_state: MarketState   # BALANCED / IMBALANCED / PROBING / NO_TRADE
├── poc, vah, val: Decimal      # Point of Control, Value Area High/Low
├── lvns, hvns: List[Decimal]   # Low/High Volume Nodes
├── aggression: float           # Sigma-based aggression score
├── cvd_slope: float            # Cumulative Volume Delta slope
├── profile_shape: str          # P-shape / b-shape / D-shape / B-shape
├── balance_ratio: float        # 0.0-1.0
├── displacement_leg: Leg       # Displacement analysis
├── market_structure: MarketStructureState  # 5-state classifier
├── ib_levels: IBLevels         # Initial Balance levels
├── npoc_levels: List[Decimal]  # Naked POC levels
└── ... and 130+ more fields
```

**Entities**:
```
Signal
├── type: SignalType            # BUY / SELL
├── side: Side                  # LONG / SHORT
├── price: Decimal
├── stop_loss: Decimal
├── take_profit: Decimal
├── setup: SetupType            # TREND_MODEL / MEAN_REVERSION / PREDICTION_ENTRY / RL_ENTRY
├── source: Source              # AMT / PREDICTION / RL / LLM / AGENT
└── factory: create()

Position (mutable lifecycle)
├── id: str
├── symbol: str
├── side: Side
├── entry_price: Decimal
├── stop_loss: Decimal
├── take_profit: Decimal
├── quantity: int
├── unrealized_pnl: Decimal
├── realized_pnl: Decimal
└── methods: update_pnl(), move_stop_to_breakeven(), should_close(), close(), from_signal()
```

**Enums**:
```
MarketState: NO_TRADE, BALANCED, IMBALANCED, PROBING
MarketStructureState: BALANCE, IMBALANCE, TRANSITION, EXPANSION, CHOP
Side: LONG, SHORT
SignalType: BUY, SELL
Source: AMT, PREDICTION, RL, LLM, AGENT
SetupType: TREND_MODEL, MEAN_REVERSION, PREDICTION_ENTRY, RL_ENTRY
```

**Aggregate Roots**:
```
Portfolio
├── balance: Decimal
├── positions: Dict[str, Position]
├── trade_history: List[TradeRecord]
├── equity: Decimal             # balance + unrealized PnL
├── methods:
│   ├── process_tick()          # Update all positions with new price
│   ├── open_position()         # Add new position (with duplicate source check)
│   ├── add_to_position()       # Scale-in (Fabio 40/30/30)
│   ├── partial_close_position()
│   ├── close_position()
│   └── get_stats()             # Win rate, profit factor, Sharpe, max drawdown
└── Features:
    ├── Tiered risk by confidence (STANDARD/REDUCED/ELEVATED)
    ├── Slippage + commission modeling
    ├── Lot snapping
    └── Fabio 40/30/30 scale-in plan

Trade (DDD aggregate)
├── EntrySignal (immutable)
├── Fill[] (append-only)        # Source of truth for position state
├── Position (derived from fills)
├── TradeEvent[] (audit trail)
└── methods: open(), add_fill(), close(), cancel(), get_position(), realized_pnl()
```

#### Ports/Interfaces (`domain/ports/`)

All 11 ports define abstract boundaries between the domain and infrastructure layers:

| Port | File | Responsibility |
|------|------|----------------|
| **BrokerPort** | `broker.py` | Order execution. Methods: `execute_order()`, `cancel_order()` |
| **MarketDataPort** | `market_data.py` | Market data retrieval. Methods: `fetch_history()`, `get_ltp()`, `stream_full()`, `scan_candidates()`, `get_option_chain()` |
| **LLMInferencePort** | `llm_inference.py` | LLM inference abstraction. Methods: `predict()`, `is_ready()`, `wait_until_ready()`, `validate()` |
| **ProbabilityInferencePort** | `probability_inference.py` | First-passage probability model (LightGBM). Returns `ProbabilityEstimate` (p_long_target, p_short_target, expected MFE) |
| **StoragePort** | `storage.py` | Persistent storage with Interface Segregation: `TickStoragePort`, `TradeStoragePort`, `DecisionStoragePort`, `OpenPositionStoragePort`, `PositionEventStoragePort` |
| **EventBusPort** | `event_bus.py` | Publish/subscribe event dispatch. Methods: `subscribe()`, `publish()` |
| **NotificationPort** | `notifications.py` | Operational alerts. Methods: `send()`, `send_sync()` |
| **DeltaProfilePort** | `delta_profile.py` | Delta-colored volume profile computation. Returns `DeltaProfile` with buy/sell delta per price level |
| **NPOCPort** | `npoc.py` | Naked POC tracking -- unfilled previous session POCs as magnets/secondary targets |
| **ExchangeStrategy** | `exchange_strategy.py` | Exchange-specific behavior abstraction (NSE vs MCX). Encapsulates thresholds, session times, EIA windows, LLM prompts |

#### Error Hierarchy

```
DomainError (base)
├── RiskValidationError
├── SignalValidationError
├── PositionError
│   ├── PositionNotFoundError
│   ├── DuplicatePositionError
│   └── InvalidPositionStateError
├── CircuitBreakerError
│   ├── DailyLossLimitReached
│   ├── ConsecutiveLossLimitReached
│   └── MaxPositionsExceeded
└── MarketStateError
    ├── NoTradeZoneError
    └── SessionNotOpenError
```

### Layer 2: Application Layer — Use Case Orchestration

**Location**: `backend/app/application/`

**Purpose**: Orchestrates domain logic into use cases without containing domain business rules itself. Knows nothing about HTTP/WebSocket.

#### Entry Point -- TradingEngine (`engine.py`, 852 lines)

The root orchestrator -- a standalone, asyncio-based trading engine that runs independently of any frontend WebSocket connections.

**Lifecycle**:
- `start()` -- called from FastAPI lifespan; seeds history, recovers open positions from DB, starts streaming tasks
- `stop()` -- graceful shutdown of all async tasks
- `_tick_loop_forever()` -- infinite retry loop that calls `_tick_loop()` and reconnects on disconnect

**Tick Processing Pipeline (per tick)**:
1. Demux incoming packet by symbol
2. Circuit breaker check
3. Aggregate tick into OHLC candle via `CandleAggregator`
4. Throttle to max once per 500ms per symbol
5. Dual feed: aggregate underlying futures for AMT analysis (options -> futures mapping)
6. Call `session_service.process_tick()` -- the main use case handler
7. Build range bars for visualization
8. Update `_latest_states` dict and notify WebSocket viewers via generation counter

**Key Responsibilities**:
- Mid-trade crash recovery (`_recover_open_positions()`)
- Historical data seeding (`_seed_history()`) -- fetches 500 candles per symbol on startup
- Viewer notification system -- generation counter + `asyncio.Condition` for push-based WebSocket updates
- Per-symbol circuit breaker (`PerEntityCircuitBreaker`)
- Underlying futures provider for AMT analysis on options

#### Delegated Modules

| Module | File | Lines | Responsibility |
|--------|------|-------|----------------|
| `StreamManager` | `stream_manager.py` | 303 | Market data streaming with exponential backoff reconnection, dual-stream mode, polling fallback |
| `CandleAggregator` | `candle_aggregator.py` | 322 | Tick-to-OHLCV aggregation, VWAP, delta, footprint accumulator, tick validation |
| `RangeBarBuilder` | `range_bar_builder.py` | 574 | Price-movement-based bars, volume profile, VWAP, delta, Triple-A pattern detection |
| `WatchdogManager` | `watchdog_manager.py` | 197 | SL/TP watchdog (1s), stale stream watchdog, GC loop (30min) |

#### Handlers (`application/handlers/`)

| Handler | File | Lines | Responsibility |
|---------|------|-------|----------------|
| `AMTHandler` | `amt_handler.py` | 180 | AMT analysis on every tick, incremental volume profiles, footprint generation |
| `LLMEntryHandler` | `llm_entry_handler.py` | 1030 | LLM-based entry decisions, per-symbol worker queues, gate checking, fallback chains |
| `LLMOverseerHandler` | `llm_overseer_handler.py` | 520 | Active position management every 3s (HOLD/TIGHTEN_SL/PARTIAL_EXIT/FULL_EXIT/ADD) |
| `TradeLifecycleHandler` | `trade_lifecycle_handler.py` | 364 | Deterministic exit engine: spread blowout, CVD kill, VWAP trail, partition exits |
| `EntryGateCoordinator` | `entry_gate_coordinator.py` | 234 | Multi-layered entry gate checking (7 gate types) |
| `SignalConstructor` | `signal_constructor.py` | 255 | Builds trade signals from LLM decisions with thesis and conviction |
| `PositionSizer` | `position_sizer.py` | 231 | Risk-based, Kelly, and volatility-adjusted sizing |
| `PreCandleAdvisor` | `pre_candle_advisor.py` | 190 | Non-blocking advisory for React dashboard (T-60s before bar close) |
| `PostTradeAnalyst` | `post_trade_analyst.py` | 262 | Post-trade LLM analysis on position close |
| `RLHandler` | `rl_handler.py` | 54 | Optional RL training status wrapper |

#### Application Services (`application/services/`)

| Service | File | Responsibility |
|---------|------|----------------|
| `TradingSessionService` | `trading_session.py` | **Main use case orchestrator** (~1400 lines). Coordinates entire event-driven trading pipeline per symbol |
| `SessionStateManager` | `session_state_manager.py` | Per-symbol session state management, creation, eviction, day boundary detection |
| `EntryCoordinator` | `entry_coordinator.py` | Signal execution pipeline (8 steps: validate -> dedup -> risk -> option select -> execute -> register -> publish -> persist) |
| `ExitCoordinator` | `exit_coordinator.py` | Exit callback handling: partial exits, stop-outs, position closed lifecycle |
| `SessionRiskCoordinator` | `session_risk_coordinator.py` | Session-level risk management, emergency kill switch, risk state persistence |
| `SessionEventLogger` | `session_event_logger.py` | Event logging facade: position events, trade journal, forward test logs |
| `StateSnapshotBuilder` | `state_snapshot_builder.py` | Pure DTO formatting for React dashboard |
| `PortfolioCoordinator` | `portfolio_coordinator.py` | Cross-symbol signal filtering (5 rules: max positions, notional caps, daily loss, correlation guard) |
| `SignalTrackingService` | `signal_tracking_service.py` | Signal generation decision tracking, gate block analysis, statistics |
| `PositionEventSourcing` | `position_event_sourcing.py` | Complete audit trail for position lifecycle (13 event types) |
| `PositionRecoveryService` | `position_recovery_service.py` | Unified position recovery from storage on startup |
| `TradeJournal` | `trade_journal.py` | Comprehensive JSONL logging with promotion assessment and run comparison |
| `ForwardTestLogger` | `forward_test_logger.py` | CSV-based forward testing logs |
| `BacktestEngine` | `backtest_engine.py` | Simple backtesting with Sharpe, max drawdown, win rate, profit factor |
| `DailyReporter` | `daily_reporter.py` | Background task sending daily PnL summary at 15:35 IST via Telegram |

### Layer 3: Infrastructure Layer -- External System Adapters

**Location**: `backend/app/infrastructure/`

**Purpose**: Implement ports with concrete external system integrations.

```
infrastructure/
├── adapters/
│   ├── dhan_adapter.py              -> Dhan market data (WebSocket + REST polling)
│   ├── dhan_broker_adapter.py       -> Dhan order execution (not yet activated)
│   ├── paper_broker.py              -> Simulated trading with Indian market costs
│   ├── mlx_inference_adapter.py     -> Apple Silicon MLX LLM inference
│   ├── lgbm_probability_adapter.py  -> LightGBM first-passage probability
│   ├── telegram_adapter.py          -> Telegram notifications
│   ├── delta_profile_adapter.py     -> Delta-colored volume profile computation
│   ├── data_generator.py            -> Deterministic synthetic OHLCV generator
│   └── null_notification_adapter.py -> No-op notification (default)
├── storage/
│   └── database.py                  -> Raw SQLite3 with WAL mode, tick batching
├── strategies/
│   ├── nse_strategy.py              -> NSE-specific thresholds and session times
│   └── mcx_strategy.py              -> MCX-specific thresholds, EIA windows
├── serialization/
│   └── schemas.py                   -> Pydantic DTOs with camelCase aliasing
├── async_event_bus.py               -> Async pub/sub with concurrent handlers
├── async_persistence.py             -> Dual-queue background storage writes
├── event_bus.py                     -> Sync pub/sub (deterministic)
├── metrics.py                       -> Singleton metrics collector
├── observability.py                 -> Centralized structured logging with tracing
├── mlx_gpu_lock.py                  -> Metal GPU serialization lock
├── model_tracing.py                 -> Inference records + feature drift detection
└── trade_reconstruction.py          -> Trade lifecycle reconstruction from JSONL
```

---

## 3. Component Interaction Map

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                                    CLIENT CODE                                      │
│                                                                                     │
│   FastAPI routers -> WebSocket game loop -> read-only state viewer                  │
│   REST endpoints -> health, market, analysis, trading, ai, rl, metrics              │
└──────────────────────────────────┬──────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              TRADING ENGINE (engine.py)                             │
│                                                                                     │
│   1. Demux incoming tick by symbol                                                  │
│   2. Per-symbol circuit breaker check                                               │
│   3. Aggregate tick -> OHLC candle (CandleAggregator)                               │
│   4. Throttle to 500ms per symbol                                                   │
│   5. Route to underlying futures for AMT analysis                                   │
│   6. Call TradingSessionService.process_tick()                                      │
│   7. Build range bars (RangeBarBuilder)                                             │
│   8. Update _latest_states + notify WS viewers (generation counter)                 │
│                                                                                     │
│   Threading Model:                                                                  │
│   - Main asyncio event loop for streaming                                           │
│   - Background tasks: tick_loop, SL watchdog, stale stream watchdog, GC             │
│   - ThreadPoolExecutor for LLM inference (per-symbol worker threads)                │
└──────┬──────────┬──────────┬──────────┬──────────┬──────────────────────────────────┘
       │          │          │          │          │
       ▼          ▼          ▼          ▼          ▼
┌──────────┐┌──────────┐┌──────────┐┌──────────┐┌──────────┐
│  AMT     ││  LLM     ││  Trade   ││  LLM     ││  RL      │
│  Handler ││  Entry   ││  Life    ││  Over    ││  Handler │
│          ││  Handler ││  cycle   ││  seer    ││          │
└────┬─────┘└────┬─────┘└────┬─────┘└────┬─────┘└────┬─────┘
     │           │           │           │           │
     └───────────┴───────────┴───────────┴───────────┘
                                 │
                    TradingSessionService.process_tick()
                    ├── SessionStateManager
                    ├── EntryCoordinator / ExitCoordinator
                    ├── SessionRiskCoordinator
                    ├── SessionEventLogger
                    ├── PortfolioCoordinator
                    └── StateSnapshotBuilder
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                             DOMAIN SERVICES & PORTS                                 │
│                                                                                     │
│   ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐                   │
│   │  AMTAnalyzer    │  │  EntryGate      │  │  TradeManager   │                   │
│   │  (AMT analysis) │  │  (3-align + 12) │  │  (exit logic)   │                   │
│   └────────┬────────┘  └────────┬────────┘  └────────┬────────┘                   │
│            │                    │                    │                             │
│   ┌────────┴────────┐  ┌────────┴────────┐  ┌────────┴────────┐                   │
│   │ SignalCoord.    │  │ RiskManager     │  │ AgentPipeline   │                   │
│   │ (conviction)    │  │ (circuit break) │  │ (<1ms cascade)  │                   │
│   └─────────────────┘  └─────────────────┘  └─────────────────┘                   │
└─────────────────────────────────────────────────────────────────────────────────────┘
                                 │
                                 ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                             INFRASTRUCTURE ADAPTERS                                 │
│                                                                                     │
│   ┌─────────────────┐  ┌─────────────────┐  ┌─────────────────┐                   │
│   │  Dhan Adapter   │  │  Paper Broker   │  │  MLX Inference  │                   │
│   │  (market data)  │  │  (simulation)   │  │  (Apple Silicon)│                   │
│   └────────┬────────┘  └────────┬────────┘  └────────┬────────┘                   │
│            │                    │                    │                             │
│   ┌────────┴────────┐  ┌────────┴────────┐  ┌────────┴────────┐                   │
│   │  LightGBM       │  │  SQLite Storage │  │  Telegram       │                   │
│   │  (probability)  │  │  (persistence)  │  │  (alerts)       │                   │
│   └─────────────────┘  └─────────────────┘  └─────────────────┘                   │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

---

## 4. How Tick Processing Works

### 4.1 Tick Reception & Validation

**File**: `backend/app/application/engine.py`

```
Dhan WebSocket Stream
    │
    ▼
TradingEngine._tick_loop()
    │
    ├── Demux: extract symbol from packet
    ├── Validate tick:
    │   ├── NaN check -> reject
    │   ├── Inf check -> reject
    │   ├── Negative values -> reject
    │   └── high < low -> reject
    ├── Per-symbol circuit breaker check
    │   └── If OPEN -> skip this symbol
    ├── OI tracking (change detection)
    └── Footprint accumulation (TickFootprintAccumulator)
```

### 4.2 Candle Aggregation

**File**: `backend/app/application/candle_aggregator.py` (322 lines)

```
Raw Ticks (streaming)
    │
    ▼
CandleAggregator.add_tick(tick)
    │
    ├── Check if tick belongs to current candle (by timestamp)
    ├── If new candle:
    │   ├── Emit previous candle (is_new_candle=True)
    │   └── Start new candle
    ├── Update OHLC:
    │   ├── high = max(high, tick.ltp)
    │   ├── low = min(low, tick.ltp)
    │   ├── close = tick.ltp
    │   └── volume += tick.volume
    ├── Update VWAP:
    │   └── cumulative_typical_price += tick.ltp * tick.volume
    ├── Update delta:
    │   ├── If taker_buy_volume available: delta += taker_buy - taker_sell
    │   └── If not: approximate from candle body ratio
    │       └── delta ≈ (close - open) / (high - low) * volume
    ├── Lee-Ready delta classification (optional)
    └── Return (candle, is_new_candle)
```

**Tick Validation**:
- NaN, Inf, negative values rejected
- Contextual spike caps for session resets
- High < low -> swap or reject

### 4.3 Session Processing

**File**: `backend/app/application/services/trading_session.py` (~1400 lines)

```
TradingSessionService.process_tick(symbol, tick, candle, portfolio)
    │
    ├── 1. Get or create session state for symbol
    │   └── Double-checked locking for thread safety
    │
    ├── 2. Drain pending signals from LLM worker thread
    │   └── Process cross-thread signals from LLMEntryHandler
    │
    ├── 3. Update candle data store
    │   ├── Append new candle
    │   ├── Persist closed candles to DB
    │   └── Enforce MAX_CANDLES cap (2000)
    │
    ├── 4. Process portfolio tick
    │   ├── Update all open positions with new price
    │   ├── Check SL/TP boundaries
    │   └── Record closed positions
    │
    ├── 5. Handle closed positions
    │   ├── Record session phase for pattern learning
    │   ├── Exit coordinator callbacks
    │   └── Trade persistence
    │
    └── 6. _on_tick() -- Main analysis pipeline
        │
        ├── Session phase check (force exit all at Phase 5: 15:15 IST)
        │
        ├── AMT analysis + footprint generation
        │   ├── Incremental volume profile update
        │   ├── AMTAnalyzer.analyze() -> AMTResult
        │   └── FootprintAnalyzer.generate() -> FootprintDTO
        │
        ├── Initial Balance engine update
        │
        ├── IB Breakout Scalp evaluation (Phase 4)
        │
        ├── 1-min bar engine update
        │
        ├── Pre-candle advisory fire (T-60s, debounced)
        │
        ├── Micro-agent pipeline (probability engine)
        │   └── RegimeAgent -> DirectionAgent -> TimingAgent -> SizingAgent
        │
        ├── Trade lifecycle exit checks
        │   └── Spread blowout, CVD kill, VWAP trail, SL/TP/Trail/Time
        │
        ├── Overseer trigger (every 3s)
        │   └── LLM position management
        │
        ├── UNIFIED ENTRY PATH
        │   ├── Agent decision -> pending decision
        │   ├── Gate pipeline (Three-Align + 12 gates)
        │   ├── Signal construction
        │   └── Execution via EntryCoordinator
        │
        └── LLM trigger for UI display
            └── Non-blocking LLM entry analysis
```

### 4.4 Throttling

```
Per-symbol throttle: max once per 500ms
    │
    ├── If last processing < 500ms ago -> skip
    └── Ensures AMT analysis doesn't overwhelm on high-frequency ticks
```

---

## 5. How AMT Analysis Works

### 5.1 Volume Profile Computation

**File**: `backend/app/domain/fabio_ai/services/amt_analyzer.py`

```
Candle Data (N candles, configurable lookback)
    │
    ▼
IncrementalVolumeProfile
    │
    ├── Initialize 200 price buckets spanning candle range
    ├── For each candle:
    │   ├── Map candle's price range to buckets
    │   ├── Distribute volume across buckets (proportional to overlap)
    │   ├── Track buy volume and sell volume separately
    │   └── Update cumulative statistics
    │
    ├── Compute:
    │   ├── POC (Point of Control) = bucket with highest volume
    │   ├── VAH (Value Area High) = upper 70% volume boundary
    │   ├── VAL (Value Area Low) = lower 70% volume boundary
    │   ├── LVNs (Low Volume Nodes) = local volume minima
    │   └── HVNs (High Volume Nodes) = local volume maxima
    │
    └── Day boundary detection:
        └── Force full VP rebuild on new trading day
```

### 5.2 Market State Detection

```
Volume Profile + Price Action
    │
    ▼
MarketStateEngine.detect_market_state()
    │
    ├── Balance Ratio = value area volume / total volume
    │   └── > 0.70 -> BALANCED (NSE) / > 0.55 -> BALANCED (MCX)
    │
    ├── Value Area Width = (VAH - VAL) / POC
    │   └── Narrow -> BALANCED, Wide -> IMBALANCED
    │
    ├── POC Migration = current POC vs prior session POC
    │   └── Significant shift -> IMBALANCED
    │
    └── Result: BALANCED / IMBALANCED / PROBING / NO_TRADE
```

### 5.3 Aggression Detection

```
Candle Data + Volume Profile
    │
    ▼
AggressionScorer.score()
    │
    ├── Volume impulse = current volume / average volume
    │   └── > 2.0 sigma -> aggressive
    │
    ├── Delta pressure = |delta| / total volume
    │   └── High delta + high volume -> directional aggression
    │
    ├── Spread tightness = (ask - bid) / mid
    │   └── Tight spread + high volume -> institutional activity
    │
    ├── Persistence = consecutive aggressive candles
    │   └── Sustained aggression -> higher conviction
    │
    └── Composite aggression score (sigma-based)
```

### 5.4 Footprint Analysis

```
Tick-level Data
    │
    ▼
TickFootprintAccumulator
    │
    ├── Accumulate ticks into price levels within candle
    ├── Track bid/ask volume at each price level
    ├── Detect:
    │   ├── Stacked imbalances (consecutive price levels with bid/ask imbalance)
    │   ├── Volume bubbles (unusually high volume at specific price)
    │   ├── Absorption (high volume without price movement)
    │   └── Exhaustion (low volume at extremes)
    │
    └── Generate FootprintDTO for visualization
```

---

## 6. How the Probability Agent Pipeline Works

**File**: `backend/app/domain/probability/agent_pipeline.py` (746 lines)

An ultra-fast micro-agent cascade (<1ms total latency) replacing slow LLM inference for entry timing decisions.

### 6.1 Agent 1: RegimeAgent (~0.05ms)

```
Market Data Features
    │
    ▼
RegimeAgent.classify()
    │
    ├── Rule-based classification (no ML model needed)
    ├── TRENDING: Strong directional movement, sustained CVD slope
    ├── BALANCED: Price oscillating around POC, low aggression
    ├── VOLATILE: Wide ranges, high volume, erratic movement
    └── DEAD: Low volume, no directional conviction
        └── QUANT ENGINE GATE: blocks LLM when DEAD
```

### 6.2 Agent 2: DirectionAgent (~0.1ms)

```
42-Feature Vector + LightGBM Model
    │
    ▼
DirectionAgent.predict()
    │
    ├── Feature extraction:
    │   ├── Group A: Price Microstructure (12 features)
    │   ├── Group B: Order Flow (8 features)
    │   ├── Group C: Volume Profile Structure (6 features)
    │   ├── Group D: Order Book (6 features)
    │   ├── Group E: Temporal (4 features)
    │   └── Group F: Options-Specific (6 features)
    │
    ├── LightGBM inference:
    │   ├── fp_long.txt -> P(long target hit before stop)
    │   └── fp_short.txt -> P(short target hit before stop)
    │
    ├── Optional Platt scaling (LogisticRegression calibrators)
    │
    └── Returns: ProbabilityEstimate
        ├── p_long_target
        ├── p_short_target
        └── expected_mfe (from MFE quantile models)
```

### 6.3 Agent 3: TimingAgent (~0.1ms)

```
Regime + Direction + Market Context
    │
    ▼
TimingAgent.decide()
    │
    ├── Delta gates: check delta divergence against price
    ├── CVD contradiction checks: CVD vs price direction
    ├── Three-align gate sync: market state + location + aggression
    ├── 12-gate pipeline sync: full AMT gate validation
    │
    └── Returns: ENTER_NOW / WAIT / SKIP
```

### 6.4 Agent 4: SizingAgent (~0.01ms)

```
Probability + Risk Parameters
    │
    ▼
SizingAgent.calculate()
    │
    ├── Half-Kelly formula: f* = (p*b - q) / b
    │   └── p = win probability, q = 1-p, b = win/loss ratio
    ├── Conservative cap (configurable, default 25% of Kelly)
    ├── Risk tier adjustment (STANDARD/REDUCED/ELEVATED)
    └── Returns: position size as fraction of capital
```

### 6.5 Feature Schema (42 Features)

| Group | Features | Examples |
|-------|----------|----------|
| **A: Price Microstructure** (12) | dist_to_poc, dist_to_vah, dist_to_val, candle_body_ratio, upper_wick_ratio, lower_wick_ratio, range_expansion, vwap_distance, ib_position, opening_relation, price_vs_session_high, price_vs_session_low |
| **B: Order Flow** (8) | delta, delta_ratio, cvd, cvd_slope, cvd_divergence, taker_buy_ratio, aggressive_buy_ratio, aggressive_sell_ratio |
| **C: Volume Profile** (6) | poc_distance_norm, vah_distance_norm, val_distance_norm, profile_shape_score, balance_ratio, lvn_proximity |
| **D: Order Book** (6) | bid_ask_spread, top_bid_qty, top_ask_qty, bid_imbalance, depth_imbalance, spread_normalized |
| **E: Temporal** (4) | session_minute, minutes_to_expiry, candles_since_open, time_since_last_aggression |
| **F: Options-Specific** (6) | moneyness, dte, iv_percent, pcr, oi_change, volume_oi_ratio |

---

## 7. How LLM Entry Works

**File**: `backend/app/application/handlers/llm_entry_handler.py` (1030 lines)

### 7.1 Precondition Checks

```
process_tick() -> LLMEntryHandler.should_run()
    │
    ├── Throttle: last LLM run < cooldown -> skip
    ├── LLM running flag -> skip (prevent concurrent runs)
    ├── Regime check: DEAD regime -> skip
    ├── Open position check: already in position -> skip (unless ADD)
    ├── Session phase: Phase 5 (close) -> skip
    └── All checks pass -> queue LLM request
```

### 7.2 Worker Thread Architecture

```
LLM Request Queue (bounded, max 10 per symbol)
    │
    ▼
_llm_worker_loop() [dedicated background thread]
    │
    ├── Dequeue request
    ├── Build session context:
    │   ├── AMT state (POC, VAH, VAL, LVNs, market state)
    │   ├── Footprint data (volume bubbles, stacked imbalances)
    │   ├── Episodic memory (today's trades)
    │   ├── Session phase
    │   └── Profile shape
    │
    ├── Gate checking (EntryGateCoordinator):
    │   ├── Three-Align gate
    │   ├── Momentum fade gate
    │   ├── Gate Pipeline (12 gates)
    │   ├── CVD hard gate
    │   ├── Profile shape gate
    │   └── VWAP bias check
    │
    ├── QUANT ENGINE GATE:
    │   └── If regime DEAD or engine says FLAT -> block LLM
    │
    ├── Build LLM prompt:
    │   ├── System prompt (Fabio playbook instructions)
    │   ├── Market context (AMT result, footprint, order book)
    │   └── Decision request (entry signal parameters)
    │
    ├── LLM inference (MLXInferenceAdapter):
    │   ├── GPU lock acquisition (MLX_GPU_LOCK)
    │   ├── ChatML prompt with JSON forcing
    │   ├── Output extraction (balanced JSON)
    │   └── Rambling prevention (repetition detection, char limit)
    │
    ├── Parse LLM response -> AgentDecision
    │
    ├── Signal construction (SignalConstructor):
    │   ├── build_entry_signal()
    │   ├── Enrich with trade thesis
    │   ├── Conviction multiplier calculation
    │   └── Signal validation (R:R >= 1.0)
    │
    ├── Cross-thread signal delivery:
    │   └── session._pending_signal.append(signal)
    │       └── Processed on next tick in main thread
    │
    └── Fallback chain:
        ├── Timeout -> quant signal
        ├── LLM error -> quant signal
        └── Extreme volatility -> quant signal
```

### 7.3 Safety Nets

| Safety Net | Behavior |
|------------|----------|
| Buy-only mode | Enforced when configured (blocks SHORT signals) |
| VWAP extreme | Warns on counter-VWAP entries |
| Volatility bypass | Allows entries during extreme volatility when gates would block |
| Queue bounded | Max 10 pending requests per symbol prevents storm |
| Timeout | 12-second timeout for LLM inference |

---

## 8. How LLM Overseer Works

**File**: `backend/app/application/handlers/llm_overseer_handler.py` (520 lines)

### 8.1 Overseer Cycle

```
process_tick() -> LLMOverseerHandler.should_run()
    │
    ├── Cooldown: last overseer run < 3s -> skip
    ├── Running flag -> skip
    ├── No open positions -> skip
    └── All checks pass -> queue overseer request
```

### 8.2 Worker Thread

```
_llm_worker_loop() [dedicated background thread]
    │
    ├── Dequeue request
    ├── Build overseer context:
    │   ├── Open position details (entry, SL, TP, PnL)
    │   ├── Current market state (AMT result)
    │   ├── Footprint data
    │   └── Recent price action
    │
    ├── LLM inference (Overseer prompt mode):
    │   └── Decision: HOLD / TIGHTEN_SL / PARTIAL_EXIT / FULL_EXIT / ADD
    │
    ├── Probability engine integration:
    │   └── If adverse probability > 80% -> override LLM HOLD -> FULL_EXIT
    │
    ├── Execute decision:
    │   ├── HOLD -> no action
    │   ├── TIGHTEN_SL -> move stop loss tighter
    │   ├── PARTIAL_EXIT -> close 50% of position
    │   ├── FULL_EXIT -> close entire position
    │   └── ADD -> pyramid add (rate-limited)
    │       ├── 2-minute cooldown
    │       ├── Max 2 adds per position
    │       └── Risk tier gate
    │
    └── Reset overseer running flag
```

---

## 9. How Trade Lifecycle & Exits Work

### 9.1 TradeLifecycleHandler

**File**: `backend/app/application/handlers/trade_lifecycle_handler.py` (364 lines)

```
process_tick() -> TradeLifecycleHandler.check_exits(portfolio, price, ...)
    │
    ├── 1. Spread blowout check
    │   └── If bid-ask > 3% of premium -> exit immediately
    │
    ├── 2. Scale-in check (Fabio Rule 4: 40/30/30)
    │   └── If conditions met -> add to position
    │
    ├── 3. CVD kill signal
    │   └── If CVD diverges against position (3-tick grace period) -> exit
    │
    ├── 4. CVD breakeven
    │   └── If CVD confirms direction -> move SL to entry
    │
    ├── 5. VWAP trail
    │   └── At 1.5R profit -> trail SL to VWAP bands
    │
    ├── 6. Imbalance tighten
    │   └── If stacked imbalances oppose position -> tighten SL
    │
    ├── 7. Partition Exit Manager (P1/P2/P3)
    │   ├── P1: Partial exit at first target
    │   ├── P2: Partial exit at second target
    │   ├── P3: Final exit
    │   ├── Breakeven trigger
    │   └── Counter-aggression exit
    │
    ├── 8. TradeManager.check_position()
    │   ├── Standard SL hit -> STOP_LOSS
    │   ├── Standard TP hit -> TAKE_PROFIT
    │   ├── Trailing stop hit -> TRAILING_STOP
    │   └── Max hold time exceeded -> TIME_STOP
    │
    └── 9. Position consistency reconciliation
        └── Ensure Portfolio and TradeManager state match
```

### 9.2 TradeManager Exit Reasons

**File**: `backend/app/domain/fabio_ai/services/trade_manager.py`

| Exit Reason | Trigger |
|-------------|---------|
| `STOP_LOSS` | Hard stop hit (0.5% default) |
| `TAKE_PROFIT` | Target reached (1.5% default) |
| `TRAILING_STOP` | Trail triggered (20% behind peak) |
| `TIME_STOP` | Max hold time exceeded (30 min default) |
| `PARTIAL_TAKE_PROFIT` | Partial at 50% of TP |
| `SCRATCH` | Small profit/loss exit |
| `OVERSEER_EXIT` | LLM decided to exit |
| `SPREAD_BLOWOUT` | Bid-ask spread too wide (>3%) |
| `CVD_KILL` | CVD divergence against position |
| `PHASE5_FORCED` | Session end forced exit |

### 9.3 TradeManager Configuration

```python
TradeManagerConfig:
    stop_loss_pct: 0.005          # 0.5% hard stop
    take_profit_pct: 0.015        # 1.5% take profit
    trail_step_pct: 0.20          # Trail 20% behind peak
    max_hold_seconds: 1800        # 30 min time stop
    partial_tp_pct: 0.50          # Partial at 50% of TP
    runner_close_pct: 0.75        # Close 75% at target
    breakeven_at_1r: True         # Move SL to entry at 1R
    cvd_breakeven: True           # CVD-confirmed breakeven
```

---

## 10. How Event Sourcing Works

### 10.1 Domain Events

**File**: `backend/app/domain/trading/events.py`

13 immutable frozen dataclasses forming an event-sourced architecture:

| Event | Purpose |
|-------|---------|
| `TickReceived` | Foundational market data event |
| `AIAnalysisCompleted` | LLM/generative AI analysis finished |
| `SignalGenerated` | Trade signal created |
| `SignalValidated` | Signal passed risk checks |
| `OrderPlaced` | Order submitted to broker |
| `OrderCancelled` | Order cancelled |
| `FillReceived` | **Source of truth** for position state |
| `PositionChanged` | Derived position state change |
| `PositionOpened` | New position opened |
| `PositionClosed` | Position closed (with reason, PnL, hold time) |
| `RiskCheckFailed` | Risk check rejected a signal |
| `DailyLossLimitReached` | Daily loss limit triggered |

### 10.2 Event Store

**File**: `backend/app/domain/trading/event_store.py`

```
EventStore
    │
    ├── append(event) -- append-only with idempotency detection
    │   └── Check event_id not already stored
    │
    ├── get_events(aggregate_id) -- replay events for aggregate
    │
    └── ReplayEngine
        └── Deterministic state reconstruction from events
```

### 10.3 Event Bus

**Sync Event Bus** (`event_bus.py`):
- In-memory pub/sub with `threading.Lock`-protected handler registry
- Handlers invoked synchronously in registration order (deterministic)
- Handler exceptions caught and logged; other handlers still execute

**Async Event Bus** (`async_event_bus.py`):
- Async version using `asyncio.Lock`
- Supports both async and sync handlers (auto-detected)
- Async handlers run concurrently via `asyncio.gather`
- Sync handlers run sequentially
- Tracks event count and error count metrics

---

## 11. How Streaming & Reconnection Work

### 11.1 StreamManager

**File**: `backend/app/application/stream_manager.py` (303 lines)

```
StreamManager.stream_with_reconnect()
    │
    ├── Connect to Dhan WebSocket
    │   └── stream_full() for NSE/MCX
    │
    ├── Dual-stream mode for NSE:
    │   ├── Full feed (ticker + quote)
    │   └── Depth 20 feed (order book)
    │   └── Merged into single packet stream
    │
    ├── Polling fallback for MCX options:
    │   ├── If WS returns no data -> switch to REST polling
    │   ├── Poll every 3-5 seconds
    │   └── Convert REST response to tick format
    │
    ├── Staleness detection:
    │   ├── If no data for > 10 seconds -> stale
    │   └── Trigger reconnect or switch to polling
    │
    └── Exponential backoff reconnection:
        ├── Attempt 1: 1s delay
        ├── Attempt 2: 2s delay
        ├── Attempt 3: 4s delay
        ├── ... up to max delay
        └── Reset counter on successful reconnect
```

### 11.2 Stale Stream Watchdog

**File**: `backend/app/application/watchdog_manager.py`

```
_stale_stream_watchdog() [runs every 5 seconds]
    │
    ├── Check last tick timestamp per symbol
    ├── If stale (> 10 seconds):
    │   ├── Log warning
    │   ├── Trigger reconnect
    │   └── If reconnect fails -> switch to REST polling
    └── If feed recovered:
        └── Switch back to WebSocket
```

---

## 12. How Persistence Works

### 12.1 SQLite Storage

**File**: `backend/app/infrastructure/storage/database.py`

**Configuration**:
- Raw SQLite3 (no ORM)
- WAL mode enabled: `PRAGMA journal_mode=WAL`
- `PRAGMA synchronous=NORMAL`
- `PRAGMA wal_autocheckpoint=500`
- Single persistent connection with `threading.Lock`

**Tick Batching**:
- Batches of 50 ticks or every 5 seconds
- Background `threading.Timer` flushes batch
- `INSERT OR REPLACE` with UNIQUE index on `(symbol, time)`

**Tables (10 total)**:

| Table | Purpose | Key Indexes |
|-------|---------|-------------|
| `ticks` | OHLCV candle data with delta and JSON extra | `(symbol, time)` unique |
| `trades` | Closed trade records with PnL, source, reason, LLM analysis | `(symbol, open_time)`, `(close_time)` |
| `llm_decisions` | Every LLM decision with full prompt, output, context | `(symbol, timestamp)` |
| `performance_snapshots` | Equity, balance, win rate snapshots | `(timestamp)` |
| `session_profiles` | Daily volume profile data (POC, VAH, VAL) | `(symbol, date)` |
| `open_positions` | Crash-survivable open position state | `(id)` unique, upsert |
| `position_events` | Lifecycle events per position | `(position_id, timestamp)` |
| `npoc_records` | Naked POC tracking (unfilled/filled state) | `(symbol, date)` |
| `fine_tuning_features` | ML training dataset with AMT state, aggression, etc. | `(symbol, timestamp)` |
| `kv_store` | Generic key-value store for crash-safe state | `(key)` unique |

### 12.2 Async Persistence Bus

**File**: `backend/app/infrastructure/async_persistence.py`

```
Dual-Queue Architecture:
    │
    ├── Critical Queue (max 100)
    │   └── Trade writes, position writes
    │   └── Always drained first to prevent starvation
    │
    ├── Main Queue (max 5000)
    │   └── Tick writes, LLM decisions, snapshots
    │
    └── Background Daemon Thread:
        ├── Drain critical queue first
        ├── Then drain main queue
        ├── Batch writes for efficiency
        └── Graceful shutdown:
            ├── Flush pending writes
            ├── Drain critical queue as safety net
            └── Report dropped count
```

**Read Path**: Reads pass through synchronously to underlying storage for consistency.

---

## 13. How Risk Management Works

### 13.1 Circuit Breakers

**File**: `backend/app/domain/services/circuit_breakers.py`

| Breaker | Threshold | Action |
|---------|-----------|--------|
| Daily Loss Limit | 5% from day's peak equity | Halt all trading |
| Consecutive Losses | 5 consecutive losses | Halt all trading |
| Max Concurrent Positions | 5 open positions | Block new entries |
| Portfolio Notional Cap | 60% of equity total | Block new entries |
| Per-Symbol Notional Cap | 20% per underlying | Block new entries for symbol |

### 13.2 Risk Sizing Engine

**File**: `backend/app/domain/services/risk_sizing_engine.py`

```
Signal + Portfolio + Confidence
    │
    ▼
RiskSizingEngine.calculate()
    │
    ├── Determine risk tier:
    │   ├── STANDARD: Normal conditions
    │   ├── REDUCED: Elevated volatility, lower confidence
    │   └── ELEVATED: High conviction, favorable conditions
    │
    ├── Kelly criterion sizing:
    │   └── f* = (p*b - q) / b
    │
    ├── Apply tier multiplier:
    │   ├── STANDARD: 100% of Kelly
    │   ├── REDUCED: 50% of Kelly
    │   └── ELEVATED: 125% of Kelly (capped)
    │
    ├── Fabio 40/30/30 scale-in plan:
    │   ├── Phase 1: 40% of target size at entry
    │   ├── Phase 2: 30% on confirmation
    │   └── Phase 3: 30% on further confirmation
    │
    └── Lot snapping to exchange lot size
```

### 13.3 Session Risk Coordinator

**File**: `backend/app/application/services/session_risk_coordinator.py`

```
SessionRiskCoordinator
    │
    ├── Per-symbol RiskManager + SessionRiskManager
    ├── Optional RiskTierEngine (feature flag)
    ├── Trade recording with tier engine integration
    ├── Entry validation against risk limits
    ├── Global emergency kill switch (halt/resume)
    ├── SystemRiskState aggregation:
    │   ├── halted: bool
    │   ├── drawdown: float
    │   ├── consecutive_losses: int
    │   └── drift_alerts: List[str]
    └── Risk state persistence to KV store
```

### 13.4 Portfolio Coordinator (Cross-Symbol)

**File**: `backend/app/application/services/portfolio_coordinator.py`

```
PortfolioCoordinator [asyncio coroutine]
    │
    ├── RULE-1: MAX_POSITIONS (default 5)
    │   └── Block if open positions >= max
    │
    ├── RULE-2: PORTFOLIO_NOTIONAL (max 60% of capital)
    │   └── Block if total notional > 60% equity
    │
    ├── RULE-3: SYMBOL_NOTIONAL (max 20% per underlying)
    │   └── Block if symbol notional > 20% equity
    │
    ├── RULE-4: DAILY_LOSS halt
    │   └── Block if daily loss limit reached
    │
    └── RULE-5: CORRELATION_GUARD
        └── Block NIFTY/BANKNIFTY/FINNIFTY same-direction entries
```

---

## 14. How Options Selection Works

### 14.1 Option Scanner

**File**: `backend/app/domain/fabio_ai/services/option_scanner.py`

```
Underlying + Expiry + Option Chain
    │
    ▼
OptionScanner.scan()
    │
    ├── Hard filters:
    │   ├── Minimum OI per underlying
    │   ├── Max spread 2.5%
    │   └── Positive LTP
    │
    ├── Scoring (100 points total):
    │   ├── ATM proximity: 40 pts (closer = better)
    │   ├── OI liquidity: 30 pts (higher = better)
    │   ├── Volume: 20 pts (higher = better)
    │   └── Delta sweet spot (0.40-0.60): 10 pts
    │
    └── Returns: Top N contracts ranked by score
```

### 14.2 Underlying Futures Provider

```
Options Symbol -> Underlying Futures Symbol
    │
    ├── Parse option symbol: "NIFTY 27 MAR 24000 CALL"
    │   └── Extract underlying: "NIFTY"
    │
    ├── Map to futures symbol for AMT analysis
    │   └── Options analysis uses underlying futures data
    │
    └── Prevents theta decay distortion in AMT analysis
```

---

## 15. How WebSocket Frontend Updates Work

### 15.1 Generation Counter Pattern

**File**: `backend/app/application/engine.py`

```
TradingEngine._latest_states: Dict[symbol, StateSnapshot]
    │
    ├── _generation_counter: int (monotonically increasing)
    ├── _state_condition: asyncio.Condition
    │
    └── On each tick:
        ├── Update _latest_states[symbol]
        ├── Increment _generation_counter
        └── Notify _state_condition (wake all waiting WS viewers)
```

### 15.2 WebSocket Game Loop

```
WebSocket Connection
    │
    ▼
Game Loop [async task]
    │
    ├── Wait for _state_condition notification
    ├── Read current generation counter
    ├── Build state snapshot:
    │   ├── Portfolio state
    │   ├── AMT analysis (POC, VAH, VAL, LVNs)
    │   ├── Footprint data
    │   ├── AI analysis results
    │   ├── Model weights
    │   ├── Strategy stats
    │   ├── Playbook guard status
    │   ├── Explainability monitor
    │   ├── Agent decision DTO
    │   └── Risk state
    │
    ├── Serialize to JSON (camelCase for frontend)
    └── Send to WebSocket client
```

---

## 16. How Crash Recovery Works

### 16.1 Position Recovery

**File**: `backend/app/application/services/position_recovery_service.py`

```
TradingEngine.start() -> _recover_open_positions()
    │
    ├── Load open positions from SQLite (open_positions table)
    ├── For each open position:
    │   ├── Restore to Portfolio aggregate
    │   ├── Register with TradeManager
    │   └── Exchange-aware filtering:
    │       └── Skip positions from other exchanges
    │
    └── Log recovery summary
```

### 16.2 SL/TP Watchdog

**File**: `backend/app/application/watchdog_manager.py`

```
_sl_watchdog_loop() [runs every 1 second]
    │
    ├── Get all open positions
    ├── For each position:
    │   ├── Get last known LTP
    │   ├── Check SL boundary
    │   ├── Check TP boundary
    │   └── If breached -> force close
    │       └── Even when stream is disconnected
    │
    └── Ensures positions are protected during feed outages
```

---

## 17. How Observability Works

### 17.1 Structured Logging

**File**: `backend/app/infrastructure/observability.py`

**8 JSONL Log Files**:

| Log File | Event Types |
|----------|-------------|
| `data_events.jsonl` | MARKET_DATA, tick processing |
| `feature_values.jsonl` | FEATURE_GENERATION, feature drift |
| `model_inference.jsonl` | MODEL_INFERENCE, latency, confidence |
| `model_explainability.jsonl` | SHAP values, feature importance |
| `strategy_decisions.jsonl` | STRATEGY_DECISION, entry/exit rationale |
| `risk_engine.jsonl` | RISK_VALIDATION, circuit breaker triggers |
| `order_lifecycle.jsonl` | ORDER_SUBMITTED, ORDER_FILLED, ORDER_CANCELLED |
| `event_flow.jsonl` | All domain events with correlation IDs |

**Event Types**:
MARKET_DATA, FEATURE_GENERATION, MODEL_INFERENCE, STRATEGY_DECISION, RISK_VALIDATION, SIGNAL_GENERATED, ORDER_SUBMITTED, ORDER_FILLED, ORDER_CANCELLED, POSITION_OPENED, POSITION_CLOSED, OVERSEER_ACTION

**Trace Context**:
- Correlation ID propagation via `contextvars`
- Span stack tracking for nested operations
- `@traced` decorator for automatic function tracing

### 17.2 Model Tracing

**File**: `backend/app/infrastructure/model_tracing.py`

```
ModelTracer
    │
    ├── Captures complete inference records:
    │   ├── Model type, version
    │   ├── Input features
    │   ├── Output, confidence
    │   ├── Feature importance, SHAP values
    │   ├── Reasoning chain
    │   ├── Latency
    │   └── Correlation ID
    │
    └── Persists to JSONL in logs/observability/

FeatureTracker
    │
    ├── Records feature values over time
    ├── Rolling statistics (1000-value windows):
    │   ├── Mean, min, max
    │   └── Last 10 values
    │
    └── Drift detection:
        └── Z-score > 2.0 -> drift alert
```

### 17.3 Metrics Collector

**File**: `backend/app/infrastructure/metrics.py`

```
MetricsCollector (singleton)
    │
    ├── Inference latency: avg, p50, p95 (rolling 500 samples)
    ├── Signal counts by direction
    ├── Total PnL
    ├── Cache hit/miss rates
    ├── Regime change count
    ├── Ticks processed
    └── Uptime
```

### 17.4 Trade Reconstruction

**File**: `backend/app/infrastructure/trade_reconstruction.py`

```
TradeReconstructor
    │
    ├── Reconstructs complete trade lifecycle from JSONL logs
    ├── Groups events by correlation ID
    └── Produces full trade narrative

RootCauseAnalyzer
    │
    ├── Analyzes losing/winning trades
    ├── Factors: low confidence, risk failures, slippage
    └── Produces improvement report

AIAnalysisWorkflow
    │
    ├── AI agent workflow for analyzing recent losses
    ├── Detects model drift
    ├── Finds anomalies
    └── Generates improvement reports
```

---

## 18. How RL Training Works

### 18.1 Valentini AMT Environment

**File**: `backend/app/domain/fabio_ai/rl/valentini_env.py`

```
ValentiniAMTEnv (Gymnasium Environment)
    │
    ├── Observation Space: 12 features
    │   ├── dist_to_poc, is_in_balance, delta_divergence
    │   ├── nearest_lvn, cvd_slope, profile_shape
    │   ├── poc_migration, session, opening_relation
    │   ├── aggression_sigma, obi, norm_delta
    │
    ├── Action Space: 5 discrete actions
    │   ├── HOLD
    │   ├── TREND_BUY
    │   ├── TREND_SELL
    │   ├── REVERT_BUY
    │   └── REVERT_SELL
    │
    ├── Action Masking:
    │   └── Based on market state (e.g., block TREND_BUY in BALANCED)
    │
    ├── Aggression Trigger:
    │   └── 2.5-sigma threshold for action validity
    │
    └── Dynamic SL/TP:
        └── Based on market conditions
```

### 18.2 Reward Shaping

**File**: `backend/app/domain/fabio_ai/rl/reward_shaper.py`

| Outcome | Reward |
|---------|--------|
| Target hit | +1.0 |
| Break-even exit | +0.5 |
| Velocity bonus | +0.1 to +0.3 |
| Drawdown penalty | -10.0 |
| Hesitation penalty | -2.0 |
| Fighting flow penalty | -3.0 |

### 18.3 Training Pipeline

**File**: `backend/app/domain/fabio_ai/rl/trainer.py`

```
ValentiniTrainer
    │
    ├── MaskablePPO algorithm
    ├── Sharpe ratio callback (early stopping)
    ├── Checkpointing (periodic model saves)
    ├── Train/validation split
    └── Training metrics logging
```

---

## 19. Complete Flow Diagrams

### 19.1 Full Tick-to-Trade Flow

```
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              TICK RECEIVED                                          │
│                                                                                     │
│   Dhan WebSocket -> StreamManager -> TradingEngine._tick_loop()                     │
└──────────────────────────────────┬──────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                           VALIDATION & AGGREGATION                                  │
│                                                                                     │
│   1. Validate tick (NaN, Inf, negative, high<low)                                   │
│   2. Per-symbol circuit breaker check                                               │
│   3. Aggregate into OHLC candle (CandleAggregator)                                  │
│   4. Throttle to 500ms per symbol                                                   │
│   5. Route to underlying futures for options                                        │
└──────────────────────────────────┬──────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                         TRADING SESSION PROCESSING                                  │
│                                                                                     │
│   TradingSessionService.process_tick()                                              │
│   ├── Drain pending LLM signals                                                     │
│   ├── Update candle data store                                                      │
│   ├── Process portfolio tick (SL/TP checks)                                         │
│   └── _on_tick() pipeline:                                                          │
└──────────────────────────────────┬──────────────────────────────────────────────────┘
                                   │
              ┌────────────────────┼────────────────────┐
              │                    │                    │
              ▼                    ▼                    ▼
┌─────────────────────┐  ┌─────────────────────┐  ┌─────────────────────┐
│    AMT ANALYSIS     │  │  PROBABILITY ENGINE │  │  TRADE LIFECYCLE    │
│                     │  │                     │  │                     │
│  Incremental VP     │  │  RegimeAgent        │  │  Spread blowout     │
│  AMTAnalyzer        │  │  DirectionAgent     │  │  CVD kill           │
│  FootprintAnalyzer  │  │  TimingAgent        │  │  VWAP trail         │
│  Market State       │  │  SizingAgent        │  │  Partition exits    │
│  Aggression         │  │  (<1ms total)       │  │  SL/TP/Trail/Time   │
└──────────┬──────────┘  └──────────┬──────────┘  └──────────┬──────────┘
           │                        │                        │
           └────────────────────────┼────────────────────────┘
                                    │
                                    ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                            ENTRY DECISION PATH                                      │
│                                                                                     │
│   Agent Decision -> Pending Decision                                                │
│       │                                                                             │
│       ├── Gate Pipeline (EntryGateCoordinator)                                      │
│       │   ├── Three-Align gate                                                      │
│       │   ├── Momentum fade gate                                                    │
│       │   ├── 12-gate validation                                                    │
│       │   ├── CVD hard gate                                                         │
│       │   ├── Profile shape gate                                                    │
│       │   └── VWAP bias check                                                       │
│       │                                                                             │
│       ├── LLM Entry (if gates pass)                                                 │
│       │   ├── Build session context                                                 │
│       │   ├── LLM inference (MLX/OpenRouter)                                        │
│       │   ├── Parse response -> Signal                                              │
│       │   └── Signal construction + conviction                                      │
│       │                                                                             │
│       └── Signal Validation (RiskManager)                                           │
│           ├── Kill switch check                                                     │
│           ├── Daily halt check                                                      │
│           ├── Max positions check                                                   │
│           ├── Notional caps                                                         │
│           └── Correlation guard                                                     │
└──────────────────────────────────┬──────────────────────────────────────────────────┘
                                   │
                                   ▼
┌─────────────────────────────────────────────────────────────────────────────────────┐
│                              EXECUTION                                              │
│                                                                                     │
│   EntryCoordinator:                                                                 │
│   1. Validate trade thesis                                                          │
│   2. Check duplicate signal ID                                                      │
│   3. Validate risk                                                                  │
│   4. Enrich with option selection                                                   │
│   5. Execute via broker (broker.execute_order())                                    │
│   6. Register with TradeManager                                                     │
│   7. Publish PositionOpened event                                                   │
│   8. Persist to storage                                                             │
└─────────────────────────────────────────────────────────────────────────────────────┘
```

### 19.2 Event Flow Diagram

```
TickReceived
    │
    ├── AIAnalysisCompleted
    │   └── Triggers LLM entry check
    │
    ├── SignalGenerated
    │   └── Triggers risk validation
    │
    ├── SignalValidated
    │   └── Triggers order placement
    │
    ├── OrderPlaced
    │   └── Trades with broker
    │
    ├── FillReceived (source of truth)
    │   └── Derives position state
    │
    ├── PositionOpened
    │   └── Triggers TradeManager registration
    │
    ├── PositionChanged
    │   └── Ongoing position updates
    │
    └── PositionClosed (with reason, PnL, hold time)
        └── Triggers RiskManager.record_trade_result()
            └── TradeJournal.log_trade()
```

### 19.3 Sequence Diagram -- Entry Flow

```
Dhan WS -> TradingEngine -> CandleAggregator -> TradingSessionService
    │
    ├── AMTHandler.analyze() -> AMTResult
    │
    ├── AgentPipeline: Regime -> Direction -> Timing -> Sizing
    │
    ├── EntryGateCoordinator: Three-Align + 12 gates
    │
    ├── LLMEntryHandler: prompt -> LLM -> parse -> Signal
    │
    ├── SignalConstructor: enrich with thesis, conviction
    │
    ├── RiskManager.validate() -> approved
    │
    ├── EntryCoordinator: execute -> register -> publish -> persist
    │
    └── Portfolio.open_position() -> TradeManager.register()
```

---

## 20. Exchange Support Matrix

| Feature | NSE (NIFTY/BANKNIFTY/FINNIFTY) | MCX (CRUDEOIL/GOLD/NATURALGAS) |
|---------|-------------------------------|--------------------------------|
| **Session Hours** | 09:15 - 15:15 IST | 09:00 - 23:15 IST |
| **CVD Block Threshold** | 5,000 | 50 |
| **Aggression Sigma** | 2.5 | 2.0 |
| **Displacement Multiplier** | 1.5x | 1.2x |
| **Balance Ratio** | 0.70 | 0.55 |
| **Big Trade Multiplier** | 3.0x | 5.0x |
| **EIA Suppression** | None | CRUDEOIL (Wed 21:00), NATURALGAS (Thu 21:00) |
| **WebSocket Streaming** | Full support | Full support (with polling fallback) |
| **Depth Streaming** | 20-level support | Limited |
| **Delta Approximation** | Body ratio (no taker_buy_volume) | Available from feed |
| **Options** | Index options (NFO) | Commodity options |

---

## 21. Performance Characteristics

### 21.1 Latency Budget

| Operation | Latency | Notes |
|-----------|---------|-------|
| Tick reception -> candle aggregation | < 1ms | In-memory, no I/O |
| AMT analysis | 5-20ms | Depends on candle count |
| Probability agent pipeline | < 1ms | 4-agent cascade |
| LLM inference | 1-2s | GPU-bound, serialized |
| Gate pipeline | < 5ms | Pure computation |
| Signal construction | < 1ms | Pure computation |
| Risk validation | < 1ms | Pure computation |
| Order execution (paper) | < 1ms | In-memory |
| Order execution (live) | 100-500ms | Network round-trip |
| Database write (async) | 0ms (offloaded) | Background thread |
| WebSocket notification | < 5ms | JSON serialization + send |

### 21.2 Memory Management

| Component | Strategy |
|-----------|----------|
| Candle data | MAX_CANDLES_PER_SYMBOL = 2000 cap |
| Session state | Eviction after 24h idle (no open positions) |
| LLM queues | Bounded (max 10 per symbol) |
| Event bus | In-memory, no persistence |
| Database | WAL mode, auto-checkpoint at 500 pages |
| GC loop | Periodic garbage collection every 30 minutes |

### 21.3 Scalability Limits

| Component | Current Limit | Bottleneck |
|-----------|--------------|------------|
| Symbols | ~10-20 | Single-threaded tick loop |
| LLM inference | 1 concurrent | GPU serialization lock |
| Database writes | ~10K/sec | Single-writer SQLite |
| WebSocket clients | ~100 | Single-process FastAPI |
| Event handlers | Unlimited | In-memory pub/sub |

---

## 22. Configuration & Feature Flags

### 22.1 Environment Configs

| Environment | File | Purpose |
|-------------|------|---------|
| Development | `config/environments/development.yaml` | Local testing, paper trading |
| Paper | `config/environments/paper.yaml` | Simulated trading with realistic costs |
| Live | `config/environments/live.yaml` | Production trading with Dhan broker |

### 22.2 Configuration Files

| File | Purpose |
|------|---------|
| `config/base.yaml` | Base configuration loaded into domain constants |
| `config/feature_flags.yaml` | Toggle features on/off |
| `config/instruments.json` | Instrument definitions and mappings |
| `config/market_config.yaml` | Market-specific configuration |
| `config/consolidated.py` | Consolidated configuration loader |

### 22.3 Key Feature Flags

| Flag | Default | Description |
|------|---------|-------------|
| `use_probability_engine` | True | Enable 4-agent cascade |
| `use_llm_entry` | True | Enable LLM-based entry decisions |
| `use_llm_overseer` | True | Enable LLM position management |
| `use_rl` | False | Enable reinforcement learning |
| `risk_tier_engine` | False | Enable dynamic risk tiering |
| `dry_run` | True | Intercept orders (paper mode) |

### 22.4 Configuration Models

**File**: `backend/app/config_models/`

```
ConfigLoader -> ConfigValidator -> TypedConfig
    │
    ├── Load YAML configs
    ├── Validate against schema
    ├── Merge environment overrides
    └── Provide typed access to all settings
```

---

## 23. API Layer (`backend/app/api/`)

### 23.1 Dependency Injection

**File**: `backend/app/api/dependencies.py`

`ServiceGraph` is the root DI container, wired once at application startup via `@lru_cache(maxsize=1)`:

```
get_service_graph()
    │
    ├── event_bus (InMemoryEventBus)
    ├── exchange_config (ExchangeConfig from YAML)
    ├── symbol_registry (SymbolRegistry)
    ├── exchange_strategy (NSEExchangeStrategy or MCXExchangeStrategy)
    ├── session_factory (SessionContextFactory)
    ├── market_data (DhanMarketDataAdapter)
    ├── broker (PaperBrokerAdapter)
    ├── llm_inference (MLXInferenceAdapter)
    ├── gen_ai_service (GenerativeAIService)
    ├── storage (SQLiteStorageAdapter → AsyncPersistenceBus)
    ├── probability_engine (LGBMProbabilityAdapter)
    ├── composite_profile, alert_manager, delta_profile, vp_contract_selector
    ├── trading_session (TradingSessionService)
    ├── npoc_tracker, gate_tracker, latency_tracker, oi_analyzer, signal_tracker
    │
    └── Auto-selects option contracts on startup:
        ├── OptionScannerService.scan_top_n()
        └── VPContractSelector (parallel ThreadPoolExecutors)
```

FastAPI dependency helpers: `get_market_data()`, `get_trading_session()`, `get_gen_ai_service()`, `get_storage()`, `get_active_symbol()`, `get_active_symbols()`, `get_exchange_config()`, `get_exchange_strategy()`, `get_symbol_registry()`, `get_session_factory()`, `get_vp_contract_selector()`.

### 23.2 REST Endpoints

| Router | File | Endpoints |
|--------|------|-----------|
| **Health** | `routers/health.py` | `GET /health`, `GET /v1/metrics`, `POST /system/halt`, `POST /system/resume`, `POST /system/playbook-guard/reset`, `GET /system/risk-state`, `GET /system/config`, `POST /scanner/rescan`, `GET /debug/memory` |
| **Trading** | `routers/trading.py` | `POST /trading/portfolio/create`, `POST /trading/stats`, `GET /trading/positions/events`, `GET /trading/positions/{id}/lifecycle` |
| **Market** | `routers/market.py` | `GET /market/scan`, `GET /market/history/{symbol}`, `GET /market/orderbook/{symbol}` |
| **AI** | `routers/ai.py` | `POST /ai/analyze`, `POST /ai/command`, `GET /ai/history`, `GET /ai/journal`, `GET /ai/journal/trades`, `GET /ai/journal/summary`, `GET /ai/journal/report`, `GET /ai/journal/compare`, `GET /ai/journal/promotion` |
| **Analysis** | `routers/analysis.py` | `POST /analysis/amt`, `POST /analysis/predict`, `POST /analysis/footprint` |
| **RL** | `routers/rl.py` | `POST /rl/train`, `GET /rl/status`, `POST /rl/predict`, `GET /rl/models`, `POST /rl/load/{model_name}` |
| **Metrics** | `routers/metrics.py` | `GET /v1/metrics/gates`, `GET /v1/metrics/latency`, `GET /v1/metrics/session-health` |

**Health Router** (`health.py`):
- `/health` checks database, LLM, and probability engine readiness → returns "ok", "degraded", or "unhealthy"
- `/system/halt` and `/system/resume` are the emergency kill switch
- `/system/risk-state` returns halted status, drawdown, consecutive losses, peak/current equity, drift alerts
- `/system/config` returns backend configuration for frontend auto-detection (dataSource, exchange, symbols, LLM readiness, probability readiness, model family, runId)
- `/debug/memory` returns RSS, GC collections, tracemalloc stats

**Trading Router** (`trading.py`):
- `/trading/positions/events` returns append-only lifecycle events (queryable by positionId or symbol)
- `/trading/positions/{id}/lifecycle` returns replay-friendly lifecycle view for a single position
- `_build_lifecycle_summary(events)` helper summarizes events: opened, closed, partial exits, stale reconciliations

**AI Router** (`ai.py`):
- `/ai/analyze` analyzes market data using fine-tuned model via GenerativeAIService
- `/ai/command` processes natural-language chart/config commands (symbol switching, interval switching, color changes, toggle volume profile/predictions/footprint) using keyword maps: `_SYMBOL_KEYWORDS`, `_INTERVAL_KEYWORDS`, `_COLOR_KEYWORDS`
- `/ai/journal/promotion` assesses whether paper-trading runs are ready for promotion (configurable thresholds: minTrades, minExpectancy, minProfitFactor, maxDrawdown)
- `/ai/journal/compare` compares runs across date ranges

**Analysis Router** (`analysis.py`):
- Stateless singletons: `_amt_analyzer`, `_prediction_engine`, `_footprint_analyzer`
- Accepts DTOs (`AMTRequestDTO`, `PredictionRequestDTO`, `FootprintRequestDTO`) and returns domain analysis results

**RL Router** (`rl.py`):
- All imports are lazy (returns 503 if numpy/gymnasium not installed)
- `POST /rl/train` starts training in background via `ThreadPoolExecutor(max_workers=1)` (returns 409 if already training)
- `POST /rl/predict` runs inference with trained model (12-float observation, 5-bool action mask)
- Request/Response DTOs: `TrainRequest`, `PredictRequest`, `PredictResponse`, `StatusResponse`, `ModelInfo`

**Metrics Router** (`metrics.py`):
- Module-level `_gate_tracker` and `_latency_tracker` singletons set by ServiceGraph init
- Gate rejection rates per symbol, per gate
- Tick-to-signal latency percentiles per symbol
- Combined session health snapshot

### 23.3 WebSocket Game Loop

**File**: `backend/app/api/websocket/gameloop.py`

Thin read-only viewer. Frontend connects to receive live state from TradingEngine. Disconnecting a viewer does NOT stop trading.

**Two Modes**:
1. **Server-driven mode**: Client sends "subscribe" message → enters `_viewer_loop` (streams engine state with delta compression)
2. **Client-driven mode** (backward compat): Client sends tick data → processes via TradingSessionService → sends state back

**Viewer Loop** (`_viewer_loop`):
```
1. Send config
2. Send history for all symbols
3. Send current snapshots
4. Poll engine for updates via generation counter
5. Delta compress (30s keyframe interval)
6. Send delta to client
```

**Delta Compression** (`_compute_delta`):
- Compares previous state with current state
- Returns only changed keys to minimize bandwidth
- Keyframe sent every 30 seconds for full state sync

**Utilities**:
- `_safe_send(ws, data)` -- safe WS send with error handling
- `_parse_tick(tick_raw)` -- parses raw tick dict to OHLC value object
- `_parse_order_book(ob_raw)` -- parses raw order book dict to OrderBook
- `_validate_tick(tick)` -- validates tick data (no NaN/Inf, high >= low, positive prices)
- `_listen_for_client(ws)` -- background task listening for client unsubscribe/ping

---

## 24. Pipeline Layer (`backend/app/pipeline/`)

**Status**: Parallel execution path (~2,000 lines). NiFi-style message pipeline with typed channels and processors. Currently not used in the main trading flow (see Section 28 for technical debt).

### 24.1 Channel Abstraction

**File**: `backend/app/pipeline/channel.py`

`Channel[T]` -- Generic bounded async queue providing backpressure:

```python
class Channel[T]:
    def __init__(name, capacity=1000)   # asyncio.Queue with maxsize
    async def send(msg)                  # Blocking send (backpressure)
    def send_nowait(msg)                 # Non-blocking (returns False if full)
    async def receive()                  # Blocking receive
    def close()                          # Sends None sentinel to stop consumers
    @property def qsize                  # Current queue size
    @property def stats                  # {name, capacity, qsize, sent, received}
```

### 24.2 Message Types

**File**: `backend/app/pipeline/message.py`

All messages are frozen dataclasses with a generic envelope:

```python
class Message[T] (frozen dataclass):
    payload: T
    symbol: str
    timestamp: datetime          # IST
    message_id: str
    correlation_id: str
    produced_at: datetime
    source_processor: str
    pipeline_id: str
```

**Payload Types**:
| Payload | Fields |
|---------|--------|
| `RawTickPayload` | ltp, volume, ltq, oi, total_buy_qty, total_sell_qty, depth_bids, depth_asks, source |
| `CandlePayload` | time, open, high, low, close, volume, delta, vwap, closed |
| `AMTResultPayload` | market_state, leg_state, poc, vah, val, cvd_slope, cvd_divergence, profile_shape, delta_score, aggression, balance_pct, near_level, confirmation_score, dev_poc/vah/val, leg_poc/vah/val, session_vwap, lvns, hvns, lvn_play, aggressive_prints, bubble_retests, tick_size |
| `SignalGatePayload` | passed, reason, setup_grade, confidence, full AMT context, session context, cvd_hard_block |
| `LLMDecisionPayload` | direction, logic, trigger, probability, latency_ms |
| `OverseerDecisionPayload` | action, reason, position_id |
| `OrderPayload` | direction, symbol, size, order_type, stop_loss, take_profit, signal_id |
| `PositionEventPayload` | event_type, position_id, pnl, reason |

**Typed Aliases**: `RawTickMessage`, `CandleMessage`, `AMTResultMessage`, `SignalGateMessage`, `LLMDecisionMessage`, `OverseerDecisionMessage`, `OrderMessage`, `PositionEventMessage`.

### 24.3 Processor Protocol

**File**: `backend/app/pipeline/processor.py`

```python
class ProcessorConfig (dataclass):
    name: str
    processor_class: str          # Dotted import path
    inbox: Dict[str, str]         # alias -> channel_name
    outbox: Dict[str, str]        # alias -> channel_name
    settings: Dict

class Processor (Protocol, runtime_checkable):
    name: str
    def setup(config: ProcessorConfig)
    def process(inbox, outbox)    # Main processing loop
    def teardown()

class BaseProcessor:
    def _safe_send(channel, msg)  # Sends to channel with error handling
```

**Design Principle**: Processors MUST NOT import other processor classes. Only coupling is via Message types.

### 24.4 Registry & Pipeline Wiring

**File**: `backend/app/pipeline/registry.py`

```python
class ProcessorRegistry:
    def resolve(dotted_path)      # Imports and caches processor class

class Pipeline:
    def run()                     # Starts all processors as concurrent asyncio tasks
    def stop()                    # Cancels all processor tasks
    def channel_stats()           # Returns stats for all channels

def build_pipeline_from_yaml(yaml_path, registry):
    # Load YAML -> Create channels -> For each processor:
    #   resolve class, instantiate, setup, wire inbox/outbox -> Return Pipeline
```

**Error Isolation**: Each processor runs in its own asyncio task. A crash in one processor doesn't kill the pipeline.

### 24.5 Pipeline Processors

**Directory**: `backend/app/pipeline/processors/`

| Processor | File | Responsibility |
|-----------|------|----------------|
| **Ingest** | `ingest.py` | Receives raw ticks from Dhan WebSocket, validates, emits `RawTickMessage` |
| **Candle** | `candle.py` | Aggregates ticks into OHLCV candles, emits `CandleMessage` |
| **Analysis** | `analysis.py` | Runs AMT analysis on candles, emits `AMTResultMessage` |
| **Gate** | `gate.py` | Signal gate validation (Three-Align + 12 gates), emits `SignalGateMessage` |
| **LLM Entry** | `llm_entry.py` | LLM-based entry decisions, emits `LLMDecisionMessage` |
| **Overseer** | `overseer.py` | Position overseer, emits `OverseerDecisionMessage` |

**Pipeline Flow** (when active):
```
Dhan WS → Ingestor → [Channel: raw_ticks] → CandleBuilder → [Channel: candles]
    → AnalysisProcessor → [Channel: amt_results] → GateProcessor → [Channel: signals]
    → LLMEntryProcessor → [Channel: llm_decisions] → OverseerProcessor
```

---

## 25. Fabio AI Strategy Engine

### 25.1 Strategy Protocols

**File**: `backend/app/domain/fabio_ai/strategy/protocols.py`

Defines the modular strategy engine interfaces:

```python
class Setup:                    # Identified trading setup
    setup_type, confidence, thesis, key_levels, trigger_conditions

class MarketContext:            # Complete market state snapshot
    symbol, current_price, market_state, regime, vwap, vah, val, poc,
    cvd_slope, delta, profile_shape, volume_bubbles, lvns, hvns

class EntrySignal:              # Generated entry signal
    symbol, direction, entry_price, stop_loss, take_profit,
    position_size, setup, confidence, thesis

class RiskResult:               # Risk validation outcome
    approved, rejection_reason, risk_metrics

class Order:                    # Planned order for execution
    order_id, trade_id, symbol, side, order_type, price, quantity, time_in_force
```

**Protocols**:
| Protocol | Method |
|----------|--------|
| `SetupDetector` | `identify(context) -> Setup \| None` |
| `MarketAnalyzer` | `analyze(symbol, data, tick) -> MarketContext` |
| `SignalGenerator` | `generate(context, setup) -> EntrySignal \| None` |
| `RiskCalculator` | `validate(signal, portfolio_state) -> RiskResult` |
| `ExecutionPlanner` | `plan_entry(signal) -> Order`, `plan_exit(trade_id, symbol, reason, price) -> Order` |
| `ExitEngine` | `check_exit(trade_id, position_state, current_price, context) -> tuple[bool, str]` |

**Composite Strategy**:
```python
class Strategy:
    # 5-step pipeline:
    def evaluate_entry(symbol, data, tick, portfolio_state) -> Order | None:
        1. analyze()        → MarketContext
        2. identify()       → Setup
        3. generate()       → EntrySignal
        4. validate()       → RiskResult
        5. plan_entry()     → Order

    def evaluate_exit(trade_id, position_state, current_price, context) -> Order | None:
        1. check_exit()     → (should_exit, reason)
        2. plan_exit()      → Order
```

### 25.2 Setup Detector

**File**: `backend/app/domain/fabio_ai/strategy/setup_detector.py`

`AMTSetupDetector` identifies 4 setup types in priority order:

| Setup | Conditions |
|-------|-----------|
| **AAA** (Aggressive Accumulation) | Price near VAL/LVN, positive delta/CVD, balanced market |
| **MOMENTUM** | Imbalanced market, price at VAH, volume confirmation |
| **MEAN_REVERSION** | Price far from VWAP in balanced market, returns toward value |
| **FAILED_AUCTION** | Requires historical context (simplified, returns None) |

Factory: `create_setup_detector(detector_type, **config)` -- currently only supports "amt" type. Configurable `min_confidence` (default 0.5).

---

## 26. Fabio AI Models

### 26.1 AMT Observation (RL State Vector)

**File**: `backend/app/domain/fabio_ai/models/observation.py`

`AMTObservation` (frozen dataclass) -- 12-field RL state vector for the Valentini AMT environment:

| Field | Description |
|-------|-------------|
| `dist_to_poc` | Normalized distance to Point of Control |
| `is_in_balance` | Price inside prior session's Value Area? |
| `delta_divergence` | Z-score of Price vs CVD divergence |
| `nearest_lvn` | Price level of closest Low Volume Node |
| `cvd_slope` | CVD linear-regression slope |
| `profile_shape` | "D" / "P" / "b" |
| `poc_migration` | "RISING" / "FALLING" / "STABLE" |
| `session` | "LONDON" / "NEW_YORK" / "ASIA" / "OVERLAP" |
| `opening_relation` | "IN_BALANCE" / "OUT_ABOVE" / "OUT_BELOW" |
| `aggression_sigma` | Volume spike in standard-deviation units |
| `obi` | Order book imbalance [-1, 1] |
| `norm_delta` | Normalized candle delta |

### 26.2 Prediction Models

**File**: `backend/app/domain/fabio_ai/models/predictions.py`

Re-exports from `app.domain.trading.models.value_objects` for backward compatibility:
- `ModelWeights` -- Adaptive weights: trend, momentum, delta, order_book, volatility
- `FactorBreakdown` -- Individual factor contributions
- `AIAnalysisResult` -- sentiment, confidence, long_term_trend, volatility_score, quant_score, projected_price, reasoning, factor_breakdown

`PredictionResult` (frozen dataclass) -- predictions (tuple of OHLC), analysis (AIAnalysisResult | None).

---

## 27. Trading Value Objects & Aggregates

### 27.1 Value Objects (`domain/trading/models/value_objects.py`)

Pure dataclasses with no framework dependencies (no Pydantic). All immutable unless noted.

| Value Object | Mutability | Key Fields |
|-------------|------------|------------|
| `OHLC` | Frozen | time, open/high/low/close/volume/vwap/taker_buy_volume/delta (all Decimal). Factory: `create()` accepts float or Decimal |
| `OrderBookLevel` | Frozen | price, quantity |
| `OrderBook` | Frozen | bids, asks (tuples of OrderBookLevel) |
| `VolumeProfileLevel` | Mutable | price, volume, buy_volume, sell_volume |
| `AggressivePrint` | Frozen | price, time, side, volume, delta |
| `AMTResult` | Mutable | 150+ fields: market_state, poc, vah, val, lvns, hvns, aggression, signal, setup, profile, aggressive_prints, profile_shape, cvd_slope, cvd_divergence, session_vwap, vwap bands, balance_ratio, leg_profile, market_structure, ib_high/low, prior day levels, acceptance/rejection, break detection, POC migration, lvn_play, ofi, developing VA, cushion_tier, session_pnl, npoc_above/below, bubble_retests |
| `StrategyStats` | Frozen | total_trades, wins, losses, win_rate, net_profit, avg_profit, largest_win/loss |
| `StackedImbalance` | Frozen | direction, price_low, price_high, magnitude, candle_time |
| `FootprintLevel` | Frozen | price, bid, ask, delta, imbalance, stacked |
| `FootprintCandle` | Frozen | time, levels, poc_price, total_delta, step_price |
| `AICommandResponse` | Frozen | message, config_updates, action |
| `ModelWeights` | Frozen | trend, momentum, delta, order_book, volatility (adaptive weights) |
| `FactorBreakdown` | Frozen | Individual factor contributions to AI analysis |
| `AIAnalysisResult` | Frozen | sentiment, confidence, long_term_trend, volatility_score, quant_score, projected_price, reasoning, factor_breakdown |

### 27.2 Trade Aggregate (`domain/trading/models/trade_aggregate.py`)

DDD aggregate root where `Trade` is the aggregate, `EntrySignal`/`Fill` are immutable value objects, `Position` is derived from fills, and `TradeEvents` provide the audit trail.

**Enums**:
```
TradeStatus: PENDING, OPEN, CLOSED
CloseReason: STOP_LOSS, TAKE_PROFIT, PARTIAL_TP, TIME_STOP, MANUAL, SIGNAL_REJECTED, BROKER_REJECTED
Confidence: HIGH, MEDIUM, LOW
Direction: LONG, SHORT, FLAT
FillType: ENTRY, PARTIAL, EXIT, SCALE_IN, SCALE_OUT
```

**Value Objects**:
```
TradeThesis (frozen):
    market_state, location_type, location_level, aggression_trigger,
    session_context, invalidation_level

EntrySignal (frozen):
    signal_id, timestamp, direction, entry_price, stop_loss, take_profit,
    position_size, setup_type, confidence, thesis
    Properties: is_long, is_short, risk_per_share, reward_per_share, risk_reward_ratio

Fill (frozen):
    fill_id, trade_id, order_id, symbol, side, price, quantity,
    commission, slippage, timestamp, fill_type
    Properties: total_cost

Position (frozen):
    trade_id, side, quantity, avg_entry_price, current_price
    Static factory: from_fills() -- ONLY way to create a Position
    Properties: is_open, market_value, cost_basis, unrealized_pnl, unrealized_pnl_pct

TradeEvent (frozen):
    event_id, trade_id, event_type, timestamp, data
```

**Trade Aggregate Root**:
```python
class Trade (dataclass):
    # State
    trade_id, symbol, status, entry_signal
    fills: tuple[Fill]          # Append-only
    events: tuple[TradeEvent]   # Append-only
    entry_time, close_time, close_reason

    # Derived properties
    get_position()              # Position.from_fills(self.fills)
    position                    # Cached derived position
    is_open, is_pending, is_closed
    side, entry_price, stop_loss, take_profit, position_size
    unrealized_pnl              # From current price
    realized_pnl                # FIFO matching of fills
    total_commission, total_slippage
    risk_per_share, risk_reward_ratio

    # Commands (state transitions -- return new Trade, immutable)
    open(entry_signal, timestamp)
    add_fill(fill)
    close(reason, timestamp)
    cancel(reason, timestamp)

    # Query
    get_event_history()
    to_snapshot()
```

**Factories**:
- `create_trade(symbol, entry_signal, timestamp)` -- Creates new trade in PENDING state
- `create_trade_from_snapshot(snapshot)` -- Reconstructs trade from snapshot for replay

### 27.3 Trading Context (`domain/trading/models/trading_context.py`)

`TradingContext` (frozen dataclass) -- Immutable context object passed through the trading pipeline. Eliminates parameter clumps.

```python
class TradingContext:
    tick: OHLC
    amt_result: AMTResult
    order_book: OrderBook
    session_info: Any
    agent_decision: Any

    # Convenience properties (delegated)
    price, volume, delta, market_state, poc, vah, val
    cvd_slope, aggression, vwap, profile_shape
    session_phase, opening_relation
    agent_direction, agent_probability, agent_regime

    # Immutable update methods (return new context)
    with_tick(tick) -> TradingContext
    with_agent_decision(agent_decision) -> TradingContext
```

---

## 28. Serialization Layer (`backend/app/infrastructure/serialization/schemas.py`)

Pydantic DTOs for API serialization. Handles camelCase aliasing for frontend JSON contract. API layer uses these exclusively; domain layer never imports Pydantic.

### 28.1 DTO Categories

| Category | DTOs |
|----------|------|
| **Market Data** | `OHLCDataDTO`, `OrderBookLevelDTO`, `OrderBookDTO` |
| **AMT Analysis** | `VolumeProfileLevelDTO`, `AggressivePrintDTO`, `TradeSignalDTO`, `AMTAnalysisDTO` |
| **AI/Prediction** | `ModelWeightsDTO`, `FactorBreakdownDTO`, `AIAnalysisDTO` |
| **Trading** | `TradePositionDTO`, `PortfolioDTO`, `StrategyStatsDTO`, `PositionEventDTO` |
| **Footprint** | `FootprintLevelDTO`, `FootprintCandleDTO` |
| **Chat/AI** | `ChatMessageDTO`, `AICommandResponseDTO` |
| **Requests** | `AMTRequestDTO`, `PredictionRequestDTO`, `FootprintRequestDTO`, `StatsRequestDTO`, `CommandRequestDTO` |

### 28.2 Converter Functions

| Converter | Direction | Purpose |
|-----------|-----------|---------|
| `ohlc_to_dto(o)` | Domain → Dict | Domain OHLC to serializable dict (camelCase) |
| `dto_to_ohlc(d)` | Dict → Domain | Pydantic DTO to domain OHLC |
| `dto_to_order_book(d)` | Dict → Domain | DTO OrderBook to domain |
| `dto_to_weights(d)` | Dict → Domain | DTO ModelWeights to domain |
| `position_to_dto(p)` | Domain → Dict | Domain Position to serializable dict |
| `position_event_to_dto(event)` | DB Row → Dict | Persisted event row to serializable dict |
| `portfolio_to_dto(p)` | Domain → Dict | Domain Portfolio to serializable dict |
| `signal_to_dto(s)` | Domain → Dict | Domain Signal to serializable dict |
| `amt_result_to_dto(r)` | Domain → Dict | Domain AMTResult to serializable dict (with optional llm_thinking, llm_json) |
| `stats_to_dto(s)` | Domain → Dict | StrategyStats to serializable dict |
| `footprint_to_dto(fp)` | Domain → Dict | Domain FootprintCandle to serializable dict |

---

## 29. Configuration Models

### 29.1 Config Loader (`backend/app/config_models/loader.py`)

**Merge Sequence**:
```
1. Load base.yaml (defaults)
2. Load environments/{GLASSYTRADE_ENV}.yaml (deep-merge overrides)
3. Load strategies/*.yaml (deep-merge overrides)
4. Read ENV vars for secrets
5. Build typed SystemConfig (immutable, frozen)
6. Run ConfigValidator (fail fast)
7. Log startup summary
```

**Parsed Types**: `SystemConfig`, `RiskConfig`, `LLMConfig`, `FeatureFlags`, `ExchangeConfig`, `SymbolConfig`, `CostProfile`, `MLThresholds`.

### 29.2 Config Validator (`backend/app/config_models/validator.py`)

**Hard Errors (block boot)**:

| Rule | Check |
|------|-------|
| RULE-1 | At least 1 active symbol |
| RULE-2 | Live mode requires broker_mode='live' |
| RULE-3 | Live mode requires llm_entry_gate=false |
| RULE-4 | Live mode requires capital >= 10,00,000 |
| RULE-5 | risk_per_trade_pct <= 2% |
| RULE-6 | portfolio_notional_cap <= 0.80 |
| RULE-7 | value_area_pct in [0.60, 0.85] for all symbols |
| RULE-8 | min_rr_ratio >= 1.0 for all symbols |
| RULE-9 | sum of max_notional_pct <= 1.50 |
| RULE-10 | cvd_slope_warning < cvd_slope_hard_block < cvd_slope_extreme |
| RULE-11 | lvn_threshold < lvn_removal_threshold |
| RULE-12 | ML model files exist for all active symbols |

**Warnings (log but allow boot)**:

| Warning | Condition |
|---------|-----------|
| WARN-1 | Paper mode with unusually high capital (>50M) |
| WARN-2 | Short signals without walk-forward validation |
| WARN-3 | Risk tier engine with bootstrap_trade_count < 30 |
| WARN-4 | min_rr_ratio below 1.5 (Fabio's floor) |
| WARN-5 | LLM pre-candle advisory enabled but no model |
| WARN-6 | MCX enabled with futures-only symbols |

---

## 30. Domain Services Catalog

**Directory**: `backend/app/domain/services/` (47 files)

### 30.1 Signal & Entry Services

| Service | File | Responsibility |
|---------|------|----------------|
| `signal_generator.py` | Signal construction from market state + aggression (3 playbooks: PROBING, Trend Continuation, Mean Reversion) |
| `signal_bus.py` | Asyncio Queue-based signal routing for multi-symbol coordination |
| `signal_validator.py` | Signal validation against risk constraints |
| `aaa_precondition_engine.py` | AAA model precondition checks before entry |
| `fifteen_sec_trigger.py` | 15-second trigger mechanism for rapid entries |
| `short_signal_gates.py` | Short signal gating logic |

### 30.2 Risk & Exit Services

| Service | File | Responsibility |
|---------|------|----------------|
| `risk_sizing_engine.py` | Kelly-based position sizing with tiered risk (STANDARD/REDUCED/ELEVATED), 40/30/30 scale-in plan |
| `exit_engine.py` | Deterministic exit logic: POC target, stop hit, 30% premium drop, time stop, Phase 5 forced exit |
| `circuit_breakers.py` | Hard circuit breakers: consecutive loss rule, daily drawdown, profit target lock |
| `breakeven_trailing_engine.py` | Breakeven and trailing stop management |
| `scalp_exit_rules.py` | Scalp-specific exit rules |
| `scalp_gate_pipeline.py` | Scalp-specific gate pipeline |
| `risk_tier_engine.py` | Dynamic risk tier management |

### 30.3 Market Analysis Services

| Service | File | Responsibility |
|---------|------|----------------|
| `market_state_router.py` | Routes to correct model based on market state (hard blocks AAA in BALANCED sessions) |
| `break_detector.py` | Break/breakout detection |
| `displacement_detector.py` | Price displacement detection |
| `lvn_detector.py` | Low Volume Node detection |
| `lvn_play_detector.py` | LVN play identification |
| `acceptance_rejection.py` | Acceptance vs rejection analysis |
| `mean_reversion_engine.py` | Mean reversion strategy logic |
| `initial_balance.py` / `initial_balance_engine.py` | Initial Balance (IB) calculation |
| `ib_breakout_scalp.py` | Initial Balance breakout scalp strategy |
| `session_phase_gate.py` | Session phase gating |
| `volume_profile.py` | Volume profile computation |
| `vwap_tracker.py` | Session VWAP tracking |
| `volatility_features.py` | Volatility feature extraction |
| `candle_metrics.py` | Candlestick metric calculations |
| `aggressive_prints.py` | Aggressive print detection |

### 30.4 Position & Recovery Services

| Service | File | Responsibility |
|---------|------|----------------|
| `position_reconciliation.py` | Position state reconciliation between sources |
| `startup_reconciliation.py` | Startup position reconciliation |
| `self_healing.py` | Self-healing/recovery mechanisms |
| `option_selection_engine.py` | Option contract selection |
| `underlying_futures_provider.py` | Underlying futures data provider for options |

### 30.5 Infrastructure & Utility Services

| Service | File | Responsibility |
|---------|------|----------------|
| `watchdog.py` | System watchdog monitoring |
| `mobile_alerts.py` | Mobile alert dispatch |
| `latency_tracker.py` | Latency monitoring |
| `symbol_registry.py` | Symbol-to-exchange mapping |
| `decimal_utils.py` | Decimal precision utilities |
| `tick_delta.py` | Tick-level delta calculations |
| `tick_utils.py` | Tick-level utility functions |
| `flash_crash_protector.py` | Flash crash protection |
| `one_min_bar_engine.py` | 1-minute bar construction |
| `walk_forward_validator.py` | Walk-forward validation |
| `capital_ladder.py` | Capital compounding ladder |
| `gate_rejection_tracker.py` | Gate rejection tracking |
| `spread_normalizer.py` | Bid-ask spread normalization |
| `trade_thesis.py` | Trade thesis construction |
| `rr_validator.py` | Risk:Reward validation |

---

## 31. Fabio AI Services Catalog

**Directory**: `backend/app/domain/fabio_ai/services/` (53 files)

### 31.1 Core AMT Services

| Service | File | Responsibility |
|---------|------|----------------|
| `amt_analyzer.py` | Core AMT analysis pipeline |
| `aggression_scorer.py` | Institutional aggression scoring |
| `cvd_tracker.py` | Cumulative Volume Delta tracking |
| `volume_profile.py` / `composite_profile.py` | Volume profile computation |
| `market_state_engine.py` | Market state classification |
| `market_structure_classifier.py` | 5-state structure classifier |
| `footprint_analyzer.py` | Footprint chart analysis |
| `regime_detector.py` | Market regime detection |

### 31.2 Entry & Gate Services

| Service | File | Responsibility |
|---------|------|----------------|
| `entry_gate.py` | Multi-gate entry validation pipeline |
| `gate_pipeline.py` | Full 12-gate execution pipeline |
| `signal_coordinator.py` | Signal coordination |
| `absorption_validator.py` | Absorption pattern validation |
| `rr_validator.py` | Risk:Reward validation |
| `spread_normalizer.py` | Bid-ask spread normalization |

### 31.3 LLM & AI Services

| Service | File | Responsibility |
|---------|------|----------------|
| `generative_ai_service.py` | LLM integration |
| `llm_contract.py` | LLM interface contract |
| `prompt_builder.py` | LLM prompt construction |
| `prompt_engineering_service.py` | Prompt engineering |
| `llm_rationale_service.py` | Trade rationale generation |
| `rule_based_rationale.py` | Rule-based rationale |
| `learning_engine.py` | Adaptive learning |
| `prediction_engine.py` | Prediction pipeline |

### 31.4 Position Management Services

| Service | File | Responsibility |
|---------|------|----------------|
| `trade_manager.py` | Trade lifecycle management |
| `position_sizer.py` | Position sizing logic |
| `partition_exit_manager.py` | Partition-based exit management |
| `pyramid_manager.py` | Pyramid/position adding management |
| `session_risk_manager.py` | Session-level risk |
| `session_warmup.py` | Session warmup logic |
| `alert_manager.py` | Alert management |
| `level_tracker.py` | Key level tracking |

### 31.5 Market Context Services

| Service | File | Responsibility |
|---------|------|----------------|
| `session_context.py` / `session_context_factory.py` | Session-aware context |
| `npoc_tracker.py` | Naked POC tracking |
| `lvn_play_engine.py` | LVN play detection |
| `lvn_quality_scorer.py` | LVN quality scoring |
| `underlying_profile_router.py` | Routes to correct underlying profile |
| `vp_contract_selector.py` | Volume profile contract selection |
| `option_scanner.py` / `option_selector.py` | Options chain analysis |
| `oi_analyzer.py` | Open Interest analysis |
| `order_book_analyzer.py` | Order book analysis |
| `orderflow_detectors.py` | Order flow pattern detection |
| `profile_classifier.py` / `profile_factory.py` / `profile_selector.py` | Volume profile classification |
| `eia_calendar.py` | EIA data release calendar (MCX-specific) |

### 31.6 Drive & Momentum Services

| Service | File | Responsibility |
|---------|------|----------------|
| `drive_tracker.py` | Price drive tracking |
| `drive_decay.py` | Drive decay detection |
| `mlx_compute.py` | MLX (Apple Silicon) compute optimization |
| `trade_thesis.py` | Trade thesis construction |

---

## 32. Design Patterns Summary

### 23.1 SOLID Principles

| Principle | Implementation |
|-----------|----------------|
| **Single Responsibility** | Each handler has one concern (AMT, LLM Entry, Overseer, Lifecycle) |
| **Open/Closed** | Ports/Adapters pattern allows new implementations without changing domain |
| **Liskov Substitution** | All adapters implement port interfaces correctly |
| **Interface Segregation** | StoragePort split into TickStoragePort, TradeStoragePort, etc. |
| **Dependency Inversion** | Domain depends on ports, infrastructure implements ports |

### 23.2 Design Patterns

| Pattern | Where Used |
|---------|------------|
| **Hexagonal Architecture** | Ports in `domain/ports/`, Adapters in `infrastructure/adapters/` |
| **Dependency Injection** | ServiceGraph factory in `api/dependencies.py` |
| **Observer Pattern** | EventBusPort for pub/sub events |
| **Strategy Pattern** | Pluggable broker (Paper/Dhan), ExchangeStrategy (NSE/MCX) |
| **Facade Pattern** | TradingSessionService coordinates multiple handlers |
| **Mediator Pattern** | Handlers communicate through session, not directly |
| **State Machine** | ManagedPosition tracks position lifecycle states |
| **Circuit Breaker** | PerEntityCircuitBreaker for symbol failures |
| **Worker Thread Pattern** | Per-symbol background threads for LLM inference |
| **Queue Pattern** | Bounded queues prevent regime-change storms |
| **Pure Functions** | Entry gate logic -- stateless, side-effect-free |
| **Template Method** | TradeManager.check_position() orchestrates exit checks |
| **Event Sourcing** | FillReceived as source of truth, ReplayEngine |
| **Generation Counter** | Push-based WebSocket updates without polling |
| **Double-Checked Locking** | Session creation, RegimeDetector initialization |

---

## 33. Known Limitations & Technical Debt

### 24.1 Architectural Weaknesses

| Issue | Impact | Recommendation |
|-------|--------|----------------|
| Two parallel execution paths | ~2,000 lines of unused pipeline code | Document as future migration path or remove |
| Duplicate market state logic | `amt_analyzer.py` and `market_structure_classifier.py` compute different states | Pick one authoritative source |
| Inconsistent CVD thresholds | 50, 100, 150 in different files | Single constant `CVD_EXTREME_THRESHOLD` |
| Large file sizes | `trading_session.py` (~1400 lines), `llm_entry_handler.py` (1030 lines) | Split into smaller modules |
| Magic numbers | Thresholds scattered across files | Move to centralized config |

### 24.2 Performance Risks

| Risk | Mitigation |
|------|------------|
| LLM inference latency (1-2s) | Background threads, bounded queues, cooldowns |
| Volume profile rebuild on day boundary | IncrementalVolumeProfile with O(buckets) updates |
| Memory growth in long-running sessions | MAX_CANDLES_PER_SYMBOL = 2000 cap |
| Database write contention | AsyncPersistenceBus with background thread |

### 24.3 Scalability Issues

| Issue | Current State | Improvement |
|-------|---------------|-------------|
| Single-threaded LLM inference | 1 worker per handler | Increase ThreadPoolExecutor workers |
| In-memory event bus | Single process | Replace with Redis/NATS for multi-process |
| SQLite storage | Single-writer | Migrate to PostgreSQL for production |
| Per-symbol state | Dict-based | Consider sharding for 100+ symbols |

---

*Analysis completed: 2026-03-31*
*Files analyzed: 200+ backend files*
*Lines analyzed: ~35,000+*
*Sections: 33 (expanded from 24 with full API, Pipeline, Strategy, Models, Value Objects, Serialization, Config, and complete service catalogs)*
