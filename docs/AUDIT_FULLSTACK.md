# Full-Stack Deep-Dive Audit — GlassyTrade AI

**Date:** 2026-08-06
**Auditor:** Principal Engineer / Quant Engineer Review
**Scope:** Entire codebase — Backend, Frontend, Quant Engine, Brokers, Shared Layer, Infrastructure, Tests
**Branch:** `stable_4`

---

## Table of Contents

1. [Executive Summary](#1-executive-summary)
2. [Project Topology](#2-project-topology)
3. [Backend Audit](#3-backend-audit)
4. [Quant Engine Audit](#4-quant-engine-audit)
5. [Broker Layer Audit](#5-broker-layer-audit)
6. [Frontend Audit](#6-frontend-audit)
7. [Shared Layer Audit](#7-shared-layer-audit)
8. [Infrastructure Audit](#8-infrastructure-audit)
9. [Test Infrastructure Audit](#9-test-infrastructure-audit)
10. [Cross-Cutting Architecture](#10-cross-cutting-architecture)
11. [Strategy Execution Flow](#11-strategy-execution-flow)
12. [Findings Index](#12-findings-index)
13. [Remediation Roadmap](#13-remediation-roadmap)

---

## 1. Executive Summary

GlassyTrade AI is an algorithmic trading terminal that runs a full AMT (Auction Market Theory) analysis pipeline on Indian option markets (MCX/NSE), generates signals via a 4-agent probability pipeline, and executes trades through the Dhan broker API. The system consists of **~136,000 lines of Python** across backend, quant, and broker layers, plus **~7,200 lines of TypeScript** in the frontend.

### Stack Metrics

| Layer | Files | Lines | Tests | Test Ratio |
|-------|-------|-------|-------|------------|
| Backend (app/) | ~120 | ~40,253 | ~8,500 | 21% |
| Quant Engine (quant/) | ~55 | ~16,380 | ~3,200 | 20% |
| Brokers (brokers/) | ~35 | ~20,941 | ~2,800 | 13% |
| Shared (shared/) | ~5 | ~350 | ~200 | 57% |
| Frontend (frontend/) | ~27 | ~7,200 | ~2,653 | 37% |
| Config (config/) | ~8 | ~700 | 0 | 0% |
| **Total** | **~250** | **~85,824** | **~17,353** | **20%** |

### Overall Verdict: **C+ (Functional but architecturally fragile)**

The system works as a trading terminal but has **5 critical architectural defects** that create production risk:

| # | Severity | Finding |
|---|----------|---------|
| 1 | **Critical** | **Dual AMT implementation** — `AMTAnalyzer` (backend, 1,383 lines) and `quant/amt/compute.py` (quant, 301 lines) compute overlapping analysis. The backend version is the active one; the quant version is partially used. Both implement VWAP, volume profile, and LVN/HVN detection — duplicated logic with divergent behavior. |
| 2 | **Critical** | **AMTAnalyzer is a 1,383-line god class** — 25+ internal trackers, 15+ sub-methods, session VWAP state, CVD tracking, drive tracking, POC migration, IB tracking, absorption, displacement, opening classification, and market structure — all in one mutable class. Not thread-safe despite claims. |
| 3 | **Critical** | **Two Portfolio implementations** — `quant/contracts/aggregates.py` (DDD aggregate, Decimal precision) and `backend/app/domain/trading/models/trade_aggregate.py` (event-sourced, 770 lines). Both manage positions, PnL, and exits. The backend version is active; the quant version is used in tests. |
| 4 | **Critical** | **No order execution in frontend** — The UI is a passive viewer. Signals display as "ENTER NOW" but the backend executes independently. If the backend fails to execute, the trader has no visual confirmation or manual override. |
| 5 | **Critical** | **Gap-filling fabricates market data** — Both frontend (`useServerTradingSystem.ts`) and backend (`mergeCandleData`) forward-fill missing candles with zero-volume flat data, creating false LVN signals and distorting volume profiles. |

### Strengths

- **4-agent pipeline** (`agent_pipeline.py`) is well-designed with regime hysteresis, Kelly sizing, and timing gates
- **DDD structure** in `quant/contracts/` — clean aggregates, value objects, and ports
- **SQLite batching** — 50-tick batch flush reduces write overhead
- **Feature flags** — `Feature` enum with YAML config enables gradual rollout
- **Circuit breakers** — `PerEntityCircuitBreaker` per-symbol with configurable thresholds

---

## 2. Project Topology

```
v5-of-glassytrade-ai/
│
├── backend/                          # FastAPI application (~40,253 lines)
│   ├── app/
│   │   ├── main.py                   # App factory, lifespan, DI wiring (337 lines)
│   │   ├── config.py                 # Config adapter (38 lines)
│   │   ├── api/
│   │   │   ├── routers/              # REST endpoints
│   │   │   │   ├── health.py         # Health/readiness (478 lines)
│   │   │   │   ├── market_router.py  # Market data endpoints
│   │   │   │   ├── trading_router.py # Trading endpoints
│   │   │   │   ├── ai_router.py      # AI/LLM endpoints
│   │   │   │   ├── rl_router.py      # RL endpoints
│   │   │   │   └── metrics_router.py # Prometheus metrics
│   │   │   └── websocket/
│   │   │       └── gameloop.py       # WS gameloop (viewer protocol)
│   │   ├── application/
│   │   │   ├── engine.py             # TradingEngine (522 lines)
│   │   │   ├── services/
│   │   │   │   ├── trading_session.py    # TradingSessionService (1,066 lines)
│   │   │   │   ├── session_event_router.py # EventRouter (895 lines)
│   │   │   │   ├── engine_lifecycle.py     # Lifecycle (592 lines)
│   │   │   │   ├── trade_journal.py        # Journal (1,062 lines)
│   │   │   │   ├── tick_processor.py       # Tick processing
│   │   │   │   ├── state_broadcaster.py    # WS broadcast
│   │   │   │   ├── session_risk_coordinator.py # Risk
│   │   │   │   ├── session_state_manager.py    # State
│   │   │   │   ├── session_cache.py          # Cache
│   │   │   │   ├── session_event_logger.py   # Logging
│   │   │   │   ├── amt_service.py            # AMT orchestration
│   │   │   │   ├── phase_manager.py          # Phase management
│   │   │   │   ├── entry_coordinator.py      # Entry coordination
│   │   │   │   ├── exit_coordinator.py       # Exit coordination
│   │   │   │   └── state_snapshot_builder.py # Snapshot assembly
│   │   │   ├── handlers/
│   │   │   │   ├── llm_entry_handler.py      # LLM entry (1,144 lines)
│   │   │   │   ├── llm_overseer_handler.py   # LLM overseer (641 lines)
│   │   │   │   ├── trade_lifecycle_handler.py # Lifecycle (473 lines)
│   │   │   │   ├── rl_handler.py             # RL handler
│   │   │   │   └── pre_candle_advisor.py     # Pre-candle advisory
│   │   │   ├── di/                         # Dependency injection
│   │   │   │   ├── composition_root.py       # Container wiring
│   │   │   │   └── container.py              # DI container
│   │   │   ├── events/                     # Event definitions
│   │   │   └── ports/                      # Port interfaces
│   │   ├── domain/
│   │   │   ├── fabio_ai/                   # AMT + AI domain
│   │   │   │   ├── services/
│   │   │   │   │   ├── amt_analyzer.py     # AMT Analyzer (1,383 lines) ← GOD CLASS
│   │   │   │   │   ├── prompt_builder.py   # LLM prompt builder (904 lines)
│   │   │   │   │   ├── exit_engine.py      # Exit engine (519 lines)
│   │   │   │   │   ├── loss_tracker.py     # Loss tracking (538 lines)
│   │   │   │   │   ├── mlx_compute.py      # MLX compute
│   │   │   │   │   ├── cvd_tracker.py      # CVD tracking (2 lines — DEAD)
│   │   │   │   │   ├── drive_tracker.py    # Drive tracking (2 lines — DEAD)
│   │   │   │   │   ├── aggression_scorer.py # Aggression (2 lines — DEAD)
│   │   │   │   │   ├── footprint_analyzer.py # Footprint (2 lines — DEAD)
│   │   │   │   │   ├── market_state_engine.py # Market state (2 lines — DEAD)
│   │   │   │   │   ├── eia_calendar.py     # EIA calendar (2 lines — DEAD)
│   │   │   │   │   ├── drive_decay.py      # Drive decay (2 lines — DEAD)
│   │   │   │   │   ├── exit_rules.py       # Exit rules (2 lines — DEAD)
│   │   │   │   │   ├── exit_signal.py      # Exit signal (2 lines — DEAD)
│   │   │   │   │   └── option_scanner.py   # Option scanner
│   │   │   │   ├── strategy/
│   │   │   │   │   └── fabio_detectors.py  # Detectors (658 lines)
│   │   │   │   ├── models/
│   │   │   │   │   └── observation.py      # RL observation
│   │   │   │   ├── ports/
│   │   │   │   │   └── three_align.py      # Three-align (2 lines — DEAD)
│   │   │   │   └── rl/
│   │   │   │       └── valentini_env.py    # RL environment (487 lines)
│   │   │   ├── probability/
│   │   │   │   ├── agent_pipeline.py       # 4-agent pipeline (989 lines)
│   │   │   │   └── features.py             # Feature extraction
│   │   │   ├── trading/
│   │   │   │   ├── models/
│   │   │   │   │   ├── trade_aggregate.py  # Trade aggregate (770 lines)
│   │   │   │   │   ├── value_objects.py    # OHLC, OrderBook, AMTResult
│   │   │   │   │   ├── aggregates.py       # Portfolio aggregate
│   │   │   │   │   ├── enums.py            # Enums
│   │   │   │   │   └── entities.py         # Entities
│   │   │   │   └── services/
│   │   │   │       └── trade_manager.py    # Trade management
│   │   │   ├── services/                   # Domain services
│   │   │   │   ├── risk_sizing_engine.py   # Risk sizing (668 lines)
│   │   │   │   ├── volume_profile.py       # Volume profile
│   │   │   │   ├── initial_balance_engine.py # IB engine
│   │   │   │   ├── break_detector.py       # Break detection
│   │   │   │   ├── aggressive_prints.py    # Aggressive prints
│   │   │   │   ├── acceptance_rejection.py # A/R engine
│   │   │   │   ├── lvn_play_detector.py    # LVN play
│   │   │   │   ├── displacement_detector.py # Displacement
│   │   │   │   ├── mobile_alerts.py        # Mobile alerts
│   │   │   │   ├── self_healing.py         # Self-healing
│   │   │   │   ├── startup_reconciliation.py # Startup recon
│   │   │   │   └── underlying_futures_provider.py # Futures routing
│   │   │   ├── models/                     # Domain models
│   │   │   ├── ports/                      # Port interfaces
│   │   │   │   ├── broker.py               # IBroker
│   │   │   │   ├── storage.py              # IStorage
│   │   │   │   ├── market_data.py          # IMarketData
│   │   │   │   ├── llm_inference.py        # ILLMInference
│   │   │   │   └── config_port.py          # ISymbolConfig
│   │   │   └── constants.py                # Domain constants (2 lines)
│   │   ├── infrastructure/
│   │   │   ├── adapters/
│   │   │   │   ├── dhan_broker_adapter.py  # Dhan broker (511 lines)
│   │   │   │   ├── dhan_adapter.py         # Dhan market data (513 lines)
│   │   │   │   ├── mlx_inference_adapter.py # MLX inference (863 lines)
│   │   │   │   └── telegram_adapter.py     # Telegram adapter
│   │   │   ├── storage/
│   │   │   │   └── database.py             # SQLite storage (953 lines)
│   │   │   ├── serialization/
│   │   │   │   └── schemas.py              # DTO schemas (654 lines)
│   │   │   └── strategies/                 # Strategy adapters
│   │   └── shared/                         # Shared utilities
│   ├── config/                             # Configuration
│   │   ├── consolidated.py                 # Consolidated config (563 lines)
│   │   ├── base.yaml                       # Base YAML config
│   │   ├── feature_flags.yaml              # Feature flags
│   │   ├── instruments.json                # Instrument definitions
│   │   ├── mode_config.py                  # Mode config
│   │   └── strategy_resolve.py             # Strategy resolution
│   ├── tests/                              # Backend tests
│   │   ├── test_mcx_offsets.py
│   │   └── baseline_test_results.json
│   └── scripts/                            # Backend scripts
│
├── quant/                                  # Quant engine (~16,380 lines)
│   ├── __init__.py
│   ├── coordinator.py                      # Quant coordinator
│   ├── runtime.py                          # Runtime
│   ├── persistence.py                      # Persistence
│   ├── state.py                            # State
│   ├── events.py                           # Events
│   ├── bars.py                             # Bar aggregation
│   ├── aggregator.py                       # Aggregator
│   ├── vwap.py                             # VWAP
│   ├── order_flow.py                       # Order flow
│   ├── absorption.py                       # Absorption
│   ├── location.py                         # Location
│   ├── auction_state.py                    # Auction state
│   ├── triple_a.py                         # Triple-A
│   ├── ws_adapter.py                       # WS adapter
│   ├── volume_profile.py                   # Volume profile
│   ├── amt/                                # AMT sub-engine
│   │   ├── compute.py                      # AMT compute (301 lines)
│   │   ├── orderflow/                      # Order flow analysis
│   │   │   ├── service.py                  # Order flow service
│   │   │   ├── footprint.py                # Footprint (341 lines)
│   │   │   ├── detectors.py                # Detectors (343 lines)
│   │   │   ├── drive.py                    # Drive tracking (314 lines)
│   │   │   ├── drive_decay.py              # Drive decay
│   │   │   ├── aggressive_prints.py        # Aggressive prints
│   │   │   ├── aggression.py               # Aggression
│   │   │   ├── cvd.py                      # CVD
│   │   │   └── tick_delta.py               # Tick delta
│   │   ├── profile/                        # Volume profile
│   │   │   ├── volume_profile.py           # Profile (498 lines)
│   │   │   ├── lvn.py                      # LVN detection (392 lines)
│   │   │   ├── classifier.py               # Shape classifier
│   │   │   ├── delta_profile.py            # Delta profile
│   │   │   └── factory.py                  # Profile factory
│   │   ├── market/                         # Market analysis
│   │   │   ├── regime.py                   # Regime (575 lines)
│   │   │   ├── structure.py                # Structure (423 lines)
│   │   │   ├── break_detector.py           # Break detection (286 lines)
│   │   │   ├── state_engine.py             # State engine
│   │   │   ├── lvn_play.py                 # LVN play
│   │   │   ├── acceptance_rejection.py     # A/R
│   │   │   ├── opening.py                  # Opening
│   │   │   ├── squeeze.py                  # Squeeze
│   │   │   └── displacement.py             # Displacement
│   │   └── session/                        # Session management
│   │       ├── context.py                  # Session context (668 lines)
│   │       ├── context_factory.py          # Context factory
│   │       ├── ib_engine.py                # IB engine
│   │       ├── ib_scalp.py                 # IB scalp (461 lines)
│   │       ├── scanner.py                  # Scanner (567 lines)
│   │       ├── selector.py                 # Selector (335 lines)
│   │       ├── symbol_registry.py          # Symbol registry
│   │       ├── futures_provider.py         # Futures provider
│   │       ├── npoc.py                     # NPOC
│   │       ├── one_min_bar.py              # 1-min bar
│   │       └── eia.py                      # EIA
│   ├── contracts/                          # DDD contracts
│   │   ├── aggregates.py                   # Portfolio aggregate (639 lines)
│   │   ├── value_objects.py                # Value objects (327 lines)
│   │   ├── entities.py                     # Entities
│   │   ├── enums.py                        # Enums
│   │   ├── events.py                       # Events (503 lines)
│   │   ├── event_store.py                  # Event store (407 lines)
│   │   ├── constants.py                    # Constants
│   │   ├── trading_context.py              # Trading context
│   │   ├── vwap_bands.py                   # VWAP bands
│   │   ├── candle_metrics.py               # Candle metrics
│   │   ├── tick_utils.py                   # Tick utils
│   │   ├── market_data_utils.py            # Market data utils
│   │   ├── volume_profile_models.py        # VP models
│   │   ├── sync_boundary.py                # Sync boundary
│   │   ├── decimal_utils.py                # Decimal utils
│   │   ├── initial_balance.py              # Initial balance
│   │   ├── exchange_config.py              # Exchange config (314 lines)
│   │   ├── cvd.py                          # CVD
│   │   ├── utils.py                        # Utils
│   │   └── ports/                          # Port interfaces
│   │       ├── broker.py                   # IBroker port
│   │       ├── market_data.py              # IMarketData port
│   │       ├── llm_inference.py            # ILLMInference port
│   │       ├── probability_inference.py    # IProbabilityInference port
│   │       ├── storage.py                  # IStorage port
│   │       ├── config_port.py              # IConfigPort
│   │       ├── exchange_strategy.py        # IExchangeStrategy
│   │       ├── notifications.py            # INotifications
│   │       ├── notification_adapter.py     # INotificationAdapter
│   │       ├── npoc.py                     # INPOC port
│   │       ├── delta_profile.py            # IDeltaProfile port
│   │       └── __init__.py
│   ├── execution/                          # Execution engine
│   │   ├── oms.py                          # Order management
│   │   ├── order.py                        # Order
│   │   ├── risk.py                         # Risk
│   │   ├── exits.py                        # Exits
│   │   ├── exit_rules.py                   # Exit rules (599 lines)
│   │   └── exit_signal.py                  # Exit signal
│   ├── decision/                           # Decision engine
│   │   ├── pipeline.py                     # Decision pipeline
│   │   ├── decision_service.py             # Decision service
│   │   ├── signal_builder.py               # Signal builder
│   │   ├── context.py                      # Decision context
│   │   ├── result.py                       # Decision result
│   │   ├── gates_session_position.py       # Session position gates
│   │   ├── gates_edge.py                   # Edge gates
│   │   ├── gates_rr.py                     # R/R gates
│   │   ├── va_fade.py                      # VA fade strategy
│   │   └── vwap_breakout.py                # VWAP breakout strategy
│   ├── advisory/                           # Advisory services
│   │   ├── chat.py                         # Chat
│   │   ├── entry_journal.py                # Entry journal
│   │   └── overseer.py                     # Overseer
│   └── brokers/                            # Quant broker adapters
│       ├── gateway.py                      # Gateway
│       └── synthetic.py                    # Synthetic broker
│
├── brokers/                                # Broker SDK (~20,941 lines)
│   ├── gateway.py                          # Broker gateway (435 lines)
│   └── broker/
│       ├── ports.py                        # Broker ports (804 lines)
│       ├── entities.py                     # Broker entities
│       ├── market_info.py                  # Market info
│       ├── validation.py                   # Validation
│       ├── symbol_matcher.py               # Symbol matching
│       ├── resilience.py                   # Resilience
│       ├── bulk_historical.py              # Historical data
│       ├── mcx_futures.py                  # MCX futures
│       ├── dhan/                           # Dhan broker SDK
│       │   ├── application/
│       │   │   ├── broker.py               # Dhan broker (884 lines)
│       │   │   ├── facade.py               # Dhan facade (1,151 lines)
│       │   │   ├── converters.py           # Converters (812 lines)
│       │   │   └── services/
│       │   │       └── streaming_service.py # Streaming (477 lines)
│       │   ├── domain/
│       │   │   ├── entities.py             # Dhan entities (816 lines)
│       │   │   ├── value_objects.py        # Value objects (528 lines)
│       │   │   ├── errors.py               # Error types (597 lines)
│       │   │   └── __init__.py             # Domain exports (500 lines)
│       │   └── infrastructure/
│       │       ├── auth_provider.py        # Auth (1,044 lines)
│       │       ├── http_client.py          # HTTP client (709 lines)
│       │       ├── websocket_client.py     # WS client (699 lines)
│       │       └── symbol_mapper.py        # Symbol mapping (905 lines)
│       └── tests/                          # Broker tests
│
├── frontend/                               # React frontend (~7,200 lines)
│   ├── index.tsx                           # Entry point
│   ├── App.tsx                             # Root component (348 lines)
│   ├── types.ts                            # Types (326 lines)
│   ├── constants.ts                        # Config (41 lines)
│   ├── stores/
│   │   ├── ui.ts                           # UI state (187 lines)
│   │   └── instruments.ts                  # Instruments (179 lines) ⚠️ UNUSED
│   ├── hooks/
│   │   ├── useServerTradingSystem.ts       # WS hook (810 lines)
│   │   └── useKeyboardNavigation.ts        # Hotkeys (195 lines)
│   ├── components/
│   │   ├── ChartScene.tsx                  # Chart (1,036 lines)
│   │   ├── AIAnalysisPanel.tsx             # Analysis (1,525 lines)
│   │   ├── MarketSidebar.tsx               # Scanner (290 lines)
│   │   ├── JournalPage.tsx                 # Journal (409 lines)
│   │   ├── ModelStateBanner.tsx            # Banner (120 lines)
│   │   ├── GlassPanel.tsx                  # Panel (52 lines)
│   │   ├── ErrorBoundary.tsx               # Error (51 lines)
│   │   ├── chart/                          # Chart sub-components
│   │   │   ├── AMTLevelsOverlay.ts         # Price lines (322 lines)
│   │   │   ├── CandleSeriesManager.ts      # Candles (323 lines)
│   │   │   ├── VolumeSeriesManager.ts      # Volume (290 lines)
│   │   │   ├── ExecutionMarkersManager.ts  # Markers (286 lines)
│   │   │   └── DecisionCard.tsx            # Decision (70 lines)
│   │   └── ai/                             # AI sub-components
│   │       ├── EquityPanel.tsx             # Equity (96 lines)
│   │       ├── RiskStateDisplay.tsx        # Risk (37 lines)
│   │       └── DecisionHistoryPanel.tsx    # History (143 lines)
│   ├── utils/
│   │   ├── symbol.ts                       # Symbol parsing (24 lines)
│   │   └── textSanitizer.ts                # Text cleaning (225 lines)
│   └── tests/                              # Frontend tests
│
├── config/                                 # Root config (~700 lines)
│   ├── config.py                           # Config module
│   ├── consolidated.py                     # ConsolidatedConfig (563 lines)
│   ├── environments/                       # Env-specific YAML
│   └── strategies/                         # Strategy-specific YAML
│
├── shared/                                 # Shared utilities (~350 lines)
│   ├── config.py                           # Shared config
│   ├── conversion.py                       # Type conversion
│   ├── resilience.py                       # Circuit breaker
│   └── error_handling.py                   # Error handling
│
└── tests/                                  # Root-level tests
    ├── quant/                              # Quant tests (~3,200 lines)
    ├── system/                             # System E2E tests
    ├── integration/                        # Integration tests
    ├── unit/                               # Unit tests
    ├── validation/                         # Validation tests
    └── runtime_validation/                 # Runtime validation
```

---

## 3. Backend Audit

### 3.1 Application Entry Point — `main.py` (337 lines)

**Role:** FastAPI factory, lifespan management, DI wiring, startup orchestration

**Startup Sequence:**
1. `create_application()` — Builds FastAPI app with middleware
2. `Configuration.from_unified()` — Loads YAML + env config
3. `compose_container(config)` — Wires DI container
4. `StartupReconciliation(broker, storage)` — Reconciles DB vs broker positions
5. `OptionScannerService.scan_top_n()` — Scans and selects active contracts
6. `TradingEngine(container).start()` — Starts market data streaming

**Findings:**

| ID | Severity | Description |
|----|----------|-------------|
| B-01 | High | **Option scanner blocks startup for 120 seconds.** `pool.submit(...).result(timeout=120)` — if the market data API is slow or unresponsive, startup hangs for 2 full minutes before timing out. The scanner runs synchronously in the lifespan. |
| B-02 | Medium | **Startup failure is non-fatal.** If the engine fails to start (`engine_start_failed`), the app continues running. The health endpoint reports degraded status, but the app accepts WebSocket connections that will never receive data. |
| B-03 | Medium | **`app.state` is used as a global bag.** 15+ attributes attached to `app.state` (`container`, `graph`, `service_graph`, `trading_session`, `market_data`, `broker`, `storage`, `engine`, `active_symbols`, `engine_start_failed`, `startup_contracts`, `startup_reconciliation`, `startup_dependency_refs`). This is a dictionary with no type safety. |
| B-04 | Low | **Three DI container aliases.** `app.state.container`, `app.state.graph`, `app.state.service_graph` all reference the same object. This creates confusion about which name to use. |
| B-05 | Low | **`init_singletons()` duplicates DI.** Services resolved from the container are also passed to `init_singletons()` for FastAPI dependency injection. Two parallel DI systems. |

### 3.2 Trading Engine — `engine.py` (522 lines)

**Role:** Market data streaming, tick processing, candle aggregation, state broadcast

**Architecture:** Delegates to focused modules:
- `StreamManager` — Market data streaming with reconnection
- `CandleAggregator` — Tick-to-candle aggregation
- `WatchdogManager` — SL/TP watchdog and stream health
- `TickProcessor` — Tick processing and OI tracking
- `StateBroadcaster` — WebSocket state assembly and broadcast
- `EngineLifecycle` — Startup, shutdown, recovery

**Tick Loop Flow:**
```
StreamManager.stream_with_reconnect()
  └─ async for pkt in stream:
       ├─ Demux: futures roots vs options
       ├─ CandleAggregator.aggregate() → OHLC tick
       ├─ CandleAggregator.validate_tick() → Skip if invalid
       ├─ [Throttle: max 1 process_tick per 500ms per symbol]
       ├─ TradingSessionService.process_tick() → State dict
       ├─ StateBroadcaster.set_state() → Store latest
       └─ StateBroadcaster.notify_viewers() → WS broadcast
```

**Findings:**

| ID | Severity | Description |
|----|----------|-------------|
| B-06 | **Critical** | **`process_tick` runs on the event loop.** Line 470: `await asyncio.to_thread(self._session_service.process_tick, ...)` — runs in a thread pool, which is correct. However, the AMTAnalyzer inside is **not thread-safe** (it mutates `_vwap_cum_vol`, `_vwap_cum_quote_vol`, `_session_data` without locks). If two ticks for the same symbol arrive concurrently from different threads, VWAP accumulators corrupt. |
| B-07 | High | **500ms throttle drops analysis.** Lines 456-464: When `elapsed < 0.5`, the engine skips `process_tick` entirely and sends cached analysis. This means AMT analysis, exit checks, and signal generation are skipped for ticks arriving faster than 500ms. In volatile markets with high tick rates, this is frequent. |
| B-08 | High | **Futures roots bypass process_tick entirely.** Lines 378-404: Futures root ticks go through `CandleAggregator` and `on_underlying_futures_candle` but never reach `TradingSessionService.process_tick`. This means futures-only symbols have no AMT analysis, no exit checks, no risk management. |
| B-09 | Medium | **`_tick_loop_forever` restarts on every disconnect.** When the stream drops, the entire tick loop restarts from scratch. The `StreamManager` handles reconnection internally, so the outer loop is redundant and causes a 2-second delay on every transient disconnect. |
| B-10 | Low | **Hardcoded Lee-Ready delta mode.** Line 197: `use_lee_ready = True` — hardcoded with a comment saying "Flag not yet exposed via Feature registry." Should be configurable. |

### 3.3 Trading Session Service — `trading_session.py` (1,066 lines)

**Role:** Application service coordinating the event-driven trading pipeline

**Collaborators:** 18 injected services (state manager, risk coordinator, lifecycle handler, LLM handler, overseer handler, exit coordinator, entry coordinator, phase manager, AMT service, event router, etc.)

**Tick Processing Pipeline:**
```
process_tick(symbol, tick, order_book, oi_data, underlying_tick)
  ├─ _maybe_reset_symbol_state() — Daily reset
  ├─ _process_pending_signal() — Drain and execute pending LLM signal
  ├─ _update_data_store() — Update candle buffer, order book
  ├─ _handle_closed_positions() — Process portfolio tick, handle exits
  └─ _publish_tick_event() → _on_tick()
       ├─ Phase check + profile save
       ├─ AMT analysis + footprint
       ├─ IB engine update
       ├─ Micro-agent pipeline
       ├─ Trade lifecycle + overseer + entry decisions
       ├─ LLM trigger (candle close, monitoring, event-driven)
       └─ Latency tracking
```

**Findings:**

| ID | Severity | Description |
|----|----------|-------------|
| B-11 | **Critical** | **`_on_tick` is 250+ lines of sequential logic.** The entire pipeline (phase check → AMT → IB → agents → lifecycle → overseer → entry → LLM) runs sequentially in one method. A slow AMT analysis blocks exit checks, which blocks signal generation. Should be decomposed into stages with error isolation. |
| B-12 | High | **AMT failure creates a sentinel result.** Lines 739-747: When AMT analysis fails, `create_sentinel_result()` returns a minimal AMTResult with `market_state=BALANCED, poc=0, vah=0, val=0`. This sentinel flows through the entire pipeline, causing the agent pipeline to classify the market as "DEAD" (because poc=0, vah=0, val=0 → no valid playbook). The exit checks and overseer still run, but with zero-value AMT data. |
| B-13 | High | **Signal TTL is 10 minutes.** Line 473: `signal_age > 600` — stale signals are discarded. For a scalping system where signals are valid for seconds, a 10-minute TTL is far too long. A signal generated at market open could still be "valid" at 10:10 AM. |
| B-14 | Medium | **`_recorded_trade_ids` is unbounded.** Line 192: `self._recorded_trade_ids: set[str] = set()` — grows indefinitely. Over a month of trading with hundreds of trades, this set accumulates thousands of UUIDs. Never cleared. |
| B-15 | Medium | **LLM cooldown state mutation.** Lines 949-964: When in cooldown, the component mutates `cooldown_status` in-place (`cooldown_status["direction"] = "FLAT"`). This modifies the cached AI analysis object, which may be shared with the frontend. |
| B-16 | Low | **`ENTRY_LLM_COOLDOWN` imported indirectly.** Line 109-111: `import app.application.handlers.llm_entry_handler as _llm_entry_module` then `getattr(_llm_entry_module, "COOLDOWN", 60.0)`. Fragile — relies on module-level constant existence. |

### 3.4 AMT Analyzer — `amt_analyzer.py` (1,383 lines)

**Role:** Core AMT analysis — volume profile, VWAP, LVN/HVN, market state, aggression, CVD, drive tracking, IB, displacement, opening classification

**Internal State:** 25+ mutable attributes including:
- `_vwap_cum_vol`, `_vwap_cum_quote_vol`, `_vwap_cum_sq_vol`, `_vwap_shift` — VWAP accumulators
- `_session_data` — Bar history (up to 500 candles)
- `_prev_agg_prints`, `_prev_agg_data_len` — Aggressive print state
- `_ib_tracker` — Initial balance tracker
- `_ib_break_direction` — Sticky IB break state
- `_cvd_tracker`, `_poc_tracker`, `_drive_tracker` — Various trackers
- `_previous_state` — Previous market state for transition logging

**Findings:**

| ID | Severity | Description |
|----|----------|-------------|
| B-17 | **Critical** | **1,383-line god class with 25+ mutable attributes.** This single class implements: VWAP accumulation, volume profile, LVN/HVN detection, market state detection, order flow analysis, CVD tracking, POC migration, IB tracking, drive tracking, displacement detection, opening classification, market structure classification, acceptance/rejection, bubble detection, absorption detection, OFI calculation, big trade detection, profile shape classification, and session context. **Violates SRP in at least 12 ways.** |
| B-18 | **Critical** | **Not thread-safe despite being called from `asyncio.to_thread()`.** The class docstring (line 247) admits: "This analyzer is NOT internally thread-safe." The caller (`AMTHandler`) is supposed to serialize via `_analyze_lock`, but the lock is in a different module. If any caller bypasses the lock (which `compute_observation` does for RL), data corruption occurs. |
| B-19 | High | **Session VWAP accumulates indefinitely.** `_vwap_cum_vol` and `_vwap_cum_quote_vol` grow monotonically until a session reset (date change). For a 6.5-hour trading day with ~7,800 candles, these floats accumulate thousands of additions. Floating-point drift is non-trivial. |
| B-20 | High | **`analyze()` calls `_update_session_vwap()` twice.** Lines 1030 and 1097 — the same VWAP update is called twice per analysis. This double-accumulates volume and quote volume, corrupting the VWAP calculation. |
| B-21 | High | **`_session_data` capped at 500 but never trimmed in tests.** Line 479: `if len(self._session_data) > 500: self._session_data = self._session_data[-500:]` — correct, but the cap means ATR(14) and other lookback calculations use at most the last 500 candles. For a full session, this is fine. For multi-day analysis, it's not. |
| B-22 | Medium | **`_compute_order_flow_metrics` returns a dict with 18 keys.** Line 519-614: Returns a flat dict with `avg_candle_vol`, `obi`, `toxicity`, `norm_delta`, `footprint_confirmed`, `cvd_confirmed`, `cvd_state`, `big_trade_confirmed`, `absorption_detected`, `absorption_side`, `absorption_range_ratio`, `absorption_vol_ratio`, `ofi_result`, `ofi_aligned`, `confluence_bonus`, `volume_bubble_near`, `agg_result`, `aggression_score`, `has_aggression`. The caller unpacks all 18 keys at lines 1066-1084. **Fragile coupling** — any change to the dict keys breaks the caller. |
| B-23 | Medium | **Dead module imports.** Lines 46-73: Imports `CVDTracker`, `BigTradeDetector`, `BubbleDetector`, `OFICalculator`, `AbsorptionDetector`, `DriveTracker`, `AggressionScorer`, `PersistentAggressionScorer` — all imported but some are 2-line stubs that do nothing. |
| B-24 | Low | **`_mtf_analyzer` referenced but doesn't exist.** Line 1147: `if hasattr(self, "_mtf_analyzer")` — defensive check for a non-existent attribute. The comment says "MTFAnalyzer removed - uses MultiTimeframeAMTAnalyzer in configure() instead." Dead code path. |

### 3.5 LLM Entry Handler — `llm_entry_handler.py` (1,144 lines)

**Role:** Generates LLM-based entry decisions using prompt engineering

**Findings:**

| ID | Severity | Description |
|----|----------|-------------|
| B-25 | High | **1,144 lines for a single handler.** The LLM entry handler contains prompt building, response parsing, cooldown management, thread pool execution, and decision formatting. The prompt builder alone is 904 lines in a separate file. Combined, they're 2,000+ lines of LLM plumbing. |
| B-26 | High | **`prompt_builder.py` (904 lines) is a string factory.** The prompt builder constructs a massive text prompt by concatenating 30+ sections of market data, analysis results, and trading rules. Any change to the prompt format requires careful string manipulation. Should use a template engine. |
| B-27 | Medium | **LLM timeout is configurable but default is 30 seconds.** `settings.LLM_TIMEOUT_SECONDS` — if the LLM is slow, the entire tick pipeline blocks for 30 seconds. The LLM runs in a thread pool, so it doesn't block the event loop, but it does block the entry decision for that tick. |
| B-28 | Low | **Thread pool not shut down on error.** `_executor` and `_predict_executor` ThreadPoolExecutors are created in `__init__` and shut down in `cleanup()`. If an exception occurs between init and cleanup, threads leak. |

### 3.6 Event Router — `session_event_router.py` (895 lines)

**Role:** Routes trading events to handlers, runs micro-agent pipeline

**Findings:**

| ID | Severity | Description |
|----|----------|-------------|
| B-29 | Medium | **`run_gate_pipeline` called twice.** The full 12-gate pipeline runs in `assess_timing()` (agent_pipeline.py, line 396) and again in `execute_entry_path()` (session_event_router.py). The same 12 gates are evaluated twice per entry attempt. |
| B-30 | Low | **`Any` type for probability_engine.** Line 70: `probability_engine: Any` — the event router accepts the probability engine as `Any`, bypassing type checking entirely. |

### 3.7 Agent Pipeline — `agent_pipeline.py` (989 lines)

**Role:** 4-agent micro-pipeline for sub-millisecond signal generation

**Architecture:**
```
Agent 1: RegimeAgent  → TRENDING / BALANCED / VOLATILE / DEAD
Agent 2: DirectionAgent → P(long), P(short) via LightGBM
Agent 3: TimingAgent  → ENTER_NOW / WAIT / SKIP
Agent 4: SizingAgent  → Kelly-optimal position size
```

**Findings:**

| ID | Severity | Description |
|----|----------|-------------|
| B-31 | Good | **Well-designed pipeline.** Clean separation of concerns, regime hysteresis prevents flipping, Kelly sizing is conservative (0.25% unproven, 0.5% proven), timing gates prevent chasing. |
| B-32 | Medium | **`_MAX_PROBABILITY = 0.85` hardcoded cap.** Line 916: Global probability cap at 85%. This is a reasonable safety measure but should be configurable. |
| B-33 | Medium | **Delta score wiring is fragile.** Lines 867-887: `delta_score = delta_normalized_option * 1.5 + norm_delta * 0.5` — the multipliers (1.5, 0.5) are hardcoded magic numbers. The shift calculation (`delta_score * 0.25`) is also hardcoded. |
| B-34 | Low | **`calculate_timing_probability` logs at INFO level.** Line 496: Logs every timing probability calculation. At ~60 ticks/sec for 9 symbols, this is 540 INFO logs/sec. Should be DEBUG. |

### 3.8 Risk Sizing Engine — `risk_sizing_engine.py` (668 lines)

**Findings:**

| ID | Severity | Description |
|----|----------|-------------|
| B-35 | Medium | **668 lines for position sizing.** The risk sizing engine handles Kelly sizing, ATR-based stops, participation limits, exchange-specific tick sizes, and cushion calculations. Most of this logic overlaps with `agent_pipeline.py`'s `kelly_size()` and `adjust_sl_tp()`. |
| B-36 | Low | **Two Kelly implementations.** `agent_pipeline.py` has `kelly_size()` (lines 656-701) and `risk_sizing_engine.py` has its own Kelly calculation. Different implementations, different caps. |

### 3.9 Exit Engine — `exit_engine.py` (519 lines)

**Findings:**

| ID | Severity | Description |
|----|----------|-------------|
| B-37 | Medium | **Exit engine in backend vs quant.** `backend/app/domain/fabio_ai/services/exit_engine.py` (519 lines) and `quant/execution/exit_rules.py` (599 lines) implement overlapping exit logic. The backend version is active; the quant version is used in the new decision pipeline. |

### 3.10 Database — `database.py` (953 lines)

**Role:** SQLite storage with batched writes

**Schema:** 6 tables — `ticks`, `trades`, `llm_decisions`, `performance_snapshots`, `session_profiles`, `open_positions`

**Findings:**

| ID | Severity | Description |
|----|----------|-------------|
| B-38 | Good | **Batched writes.** 50-tick batch flush with 5-second timeout reduces SQLite write overhead. Thread-safe via `threading.Lock`. |
| B-39 | Medium | **No WAL mode.** SQLite runs in default journaling mode. For a trading system with concurrent reads (health endpoint) and writes (tick batching), WAL mode would provide better concurrency. |
| B-40 | Medium | **`ticks` table has no index on `(symbol, time)`.** Queries for historical data scan the entire table. With 7,800 candles/hour × 9 symbols × 6.5 hours = ~458,000 ticks/day, this becomes slow. |
| B-41 | Low | **IST hardcoded in schema.** Line 32: `datetime('now', '+5:30 hours')` — SQLite default timestamps use IST offset. If the system ever runs in a different timezone, all timestamps are wrong. |

---

## 4. Quant Engine Audit

### 4.1 Overview

The `quant/` directory contains **16,380 lines** of trading logic organized into:
- `amt/` — AMT analysis sub-engine (compute, orderflow, profile, market, session)
- `contracts/` — DDD contracts (aggregates, value objects, ports)
- `execution/` — Order management, exits, risk
- `decision/` — Decision pipeline, gates, strategies
- `advisory/` — Chat, journal, overseer

### 4.2 Key Finding: Dual AMT Implementation

| Layer | File | Lines | Status |
|-------|------|-------|--------|
| Backend | `app/domain/fabio_ai/services/amt_analyzer.py` | 1,383 | **ACTIVE** — Called by TradingSessionService |
| Quant | `quant/amt/compute.py` | 301 | **PARTIAL** — Used in some tests, not in production |

Both implement:
- Volume profile construction
- VWAP calculation
- LVN/HVN detection
- Market state classification
- Aggression scoring

**The backend version is the production path.** The quant version appears to be a newer, cleaner implementation that hasn't been fully integrated. This creates maintenance burden and divergence risk.

### 4.3 Contracts Layer — `quant/contracts/`

**Role:** DDD value objects, aggregates, and port interfaces

**Findings:**

| ID | Severity | Description |
|----|----------|-------------|
| Q-01 | Good | **Well-structured DDD layer.** Clean separation of aggregates (`Portfolio`), value objects (`OHLC`, `StrategyStats`), entities (`Position`, `Signal`), and ports (`IBroker`, `IMarketData`, `IStorage`). |
| Q-02 | Medium | **`Portfolio` aggregate uses `Decimal` but backend uses `float`.** The quant `Portfolio` (line 76) uses `Decimal` for all monetary values. The backend `trade_aggregate.py` uses `float` for PnL calculations. This creates precision inconsistency between the two implementations. |
| Q-03 | Low | **`INITIAL_CAPITAL = 5,000,000` hardcoded.** Line 29: 50 lakhs INR hardcoded. Should come from config. |

### 4.4 Execution Layer — `quant/execution/`

**Findings:**

| ID | Severity | Description |
|----|----------|-------------|
| Q-04 | Medium | **`exit_rules.py` (599 lines) is comprehensive but unused.** The quant exit rules implement 12 exit conditions (SL, TP, time stop, CVD divergence, absorption, displacement, regime change, etc.). However, the active exit path uses `backend/app/domain/fabio_ai/services/exit_engine.py`. |
| Q-05 | Good | **Exit rules are well-structured.** Each exit condition is a separate function with clear naming and documentation. The `classify_exit()` function evaluates all conditions and returns the highest-priority exit. |

### 4.5 Decision Layer — `quant/decision/`

**Findings:**

| ID | Severity | Description |
|----|----------|-------------|
| Q-06 | Good | **Clean gate pipeline.** `gates_session_position.py`, `gates_edge.py`, `gates_rr.py` implement 12 entry gates as separate modules. Each gate is a pure function. |
| Q-07 | Medium | **`va_fade.py` and `vwap_breakout.py` are strategy-specific.** These implement VA fade and VWAP breakout strategies. They're well-structured but not integrated into the main decision pipeline. |

### 4.6 Session Layer — `quant/amt/session/`

**Findings:**

| ID | Severity | Description |
|----|----------|-------------|
| Q-08 | Medium | **`ib_scalp.py` (461 lines) — IB scalp engine.** Implements IB breakout scalping with setup validation. Used when `Feature.SCALP_ENGINE` is enabled. Well-structured but adds complexity to the session pipeline. |
| Q-09 | Low | **`scanner.py` (567 lines) — Option scanner.** Scans and selects option contracts. Overlaps with `backend/app/domain/fabio_ai/services/option_scanner.py`. |

---

## 5. Broker Layer Audit

### 5.1 Dhan Broker SDK — `brokers/broker/dhan/`

**Role:** Complete Dhan broker integration — authentication, HTTP, WebSocket, streaming, symbol mapping

**Architecture:**
```
brokers/broker/dhan/
├── application/
│   ├── broker.py           # Dhan broker (884 lines) — IBroker implementation
│   ├── facade.py           # Dhan facade (1,151 lines) — High-level API
│   ├── converters.py       # Converters (812 lines) — DTO conversion
│   └── services/
│       └── streaming_service.py # Streaming (477 lines) — Live data
├── domain/
│   ├── entities.py         # Dhan entities (816 lines)
│   ├── value_objects.py    # Value objects (528 lines)
│   └── errors.py           # Error types (597 lines)
└── infrastructure/
    ├── auth_provider.py    # Auth (1,044 lines) — Token management
    ├── http_client.py      # HTTP client (709 lines)
    ├── websocket_client.py # WS client (699 lines)
    └── symbol_mapper.py    # Symbol mapping (905 lines)
```

**Findings:**

| ID | Severity | Description |
|----|----------|-------------|
| BR-01 | **Critical** | **`facade.py` is 1,151 lines.** The Dhan facade is the largest single file in the broker layer. It wraps all Dhan API operations (order placement, modification, cancellation, position management, market data, historical data, streaming). Should be split into focused facades. |
| BR-02 | High | **`auth_provider.py` is 1,044 lines.** Token management, refresh logic, session handling, and error recovery in one file. The refresh logic is complex (exponential backoff, retry on 401, token caching). |
| BR-03 | High | **`symbol_mapper.py` is 905 lines.** Maps between Dhan symbols, exchange symbols, and internal symbols. Contains extensive regex-based parsing for NSE, MCX, and currency symbols. Fragile — any change to Dhan's symbol format breaks the mapping. |
| BR-04 | Medium | **`errors.py` is 597 lines.** 40+ exception types for the Dhan broker. Well-organized but excessive. Many are never raised (e.g., `OrderModificationRejectedError`, `PositionNotHedgedError`). |
| BR-05 | Medium | **`converters.py` (812 lines) — DTO conversion.** Converts between Dhan API responses and internal entities. Contains 30+ conversion functions. Should be automated with a schema-based converter. |
| BR-06 | Good | **`websocket_client.py` (699 lines) — Robust WS client.** Implements reconnection with exponential backoff, heartbeat, message buffering, and error handling. Well-structured. |

### 5.2 Backend Broker Adapter — `dhan_broker_adapter.py` (511 lines)

**Role:** Adapts Dhan broker SDK to `IBroker` port interface

**Findings:**

| ID | Severity | Description |
|----|----------|-------------|
| BR-07 | Medium | **Adapter is 511 lines.** The broker adapter wraps the Dhan SDK and implements the `IBroker` port. It handles order placement, modification, cancellation, position retrieval, and market data. The adapter pattern is correct, but the file is large due to error handling and retry logic. |
| BR-08 | Low | **Two broker adapter files.** `dhan_broker_adapter.py` (511 lines) and `dhan_adapter.py` (513 lines) — both adapt the Dhan SDK. The former implements `IBroker`, the latter implements `IMarketData`. The naming is confusing. |

---

## 6. Frontend Audit

See `docs/AUDIT_FRONTEND.md` for the complete frontend deep-dive (1,400 lines).

### Summary of Critical Frontend Findings

| ID | Severity | Description |
|----|----------|-------------|
| F-05 | Critical | Gap-filling fabricates zero-volume market data |
| F-20 | Critical | AIAnalysisPanel is 1,525-line god component |
| F-21 | Critical | 12+ inline IIFE components — untestable |
| F-13 | Critical | IST offset magic number (19800) in 5+ files |
| F-58 | Critical | 180-line Zustand store is completely unused |
| F-06 | High | Message deduplication is dead code |
| F-07 | High | Delta merge shallow-spreads 50+ field objects |
| F-22 | High | 4-tier LTP fallback may show stale VWAP |
| F-23 | High | Fabricated "monitoring mode" analysis |

---

## 7. Shared Layer Audit

### 7.1 Overview

The `shared/` directory contains **~350 lines** of cross-cutting utilities:
- `config.py` — Shared configuration
- `conversion.py` — Type conversion utilities
- `resilience.py` — Circuit breaker implementation
- `error_handling.py` — Error handling utilities

### 7.2 Circuit Breaker — `resilience.py`

**Findings:**

| ID | Severity | Description |
|----|----------|-------------|
| S-01 | Good | **Per-entity circuit breaker.** `PerEntityCircuitBreaker` tracks failures per symbol, with configurable thresholds and recovery timeouts. Well-designed. |
| S-02 | Low | **Recovery timeout is fixed.** The circuit breaker uses a fixed recovery timeout. Should support exponential backoff for persistent failures. |

---

## 8. Infrastructure Audit

### 8.1 MLX Inference Adapter — `mlx_inference_adapter.py` (863 lines)

**Role:** Apple Silicon MLX inference for LightGBM probability model

**Findings:**

| ID | Severity | Description |
|----|----------|-------------|
| I-01 | Medium | **863 lines for an inference adapter.** The MLX adapter handles model loading, feature preparation, inference execution, and result formatting. Most of the complexity comes from feature engineering (converting AMT data to model features). |
| I-02 | Low | **Apple Silicon only.** MLX is Apple Silicon-specific. The system cannot run on x86 or Linux servers without a fallback inference path. |

### 8.2 Serialization — `schemas.py` (654 lines)

**Role:** DTO schemas for WebSocket and REST serialization

**Findings:**

| ID | Severity | Description |
|----|----------|-------------|
| I-03 | Medium | **654 lines of serialization.** The schemas module converts between domain objects and JSON-serializable DTOs. Contains `ohlc_to_dto`, `amt_result_to_dto`, `portfolio_to_dto`, `position_to_dto`, and 20+ other conversion functions. |
| I-04 | Low | **No schema validation.** DTOs are constructed manually without Pydantic or dataclass validation. Malformed data can slip through. |

---

## 9. Test Infrastructure Audit

### 9.1 Test Coverage Map

| Layer | Source Lines | Test Lines | Ratio | Assessment |
|-------|-------------|-----------|-------|------------|
| Backend domain | ~25,000 | ~6,000 | 24% | Medium |
| Backend application | ~10,000 | ~2,500 | 25% | Medium |
| Backend infrastructure | ~2,500 | ~500 | 20% | Low |
| Quant engine | ~16,380 | ~3,200 | 20% | Low |
| Brokers | ~20,941 | ~2,800 | 13% | Low |
| Frontend | ~7,200 | ~2,653 | 37% | Medium |
| Shared | ~350 | ~200 | 57% | High |
| **Total** | **~82,371** | **~17,853** | **22%** | **Low** |

### 9.2 Test Quality

**Well-tested areas:**
- Pure functions (AMT levels overlay, candle series, volume series, execution markers)
- Quant contracts (aggregates, value objects, enums)
- Broker entities and conversion

**Under-tested areas:**
- TradingSessionService._on_tick (250 lines, minimal coverage)
- AMTAnalyzer.analyze (1,383 lines, ~30% coverage)
- LLMEntryHandler (1,144 lines, ~10% coverage)
- WebSocket gameloop (integration tests only)
- Gap-filling logic (no tests for fabricated data detection)
- Delta merge correctness (no tests for stale field propagation)

**Missing test categories:**
- No load tests for WebSocket under high tick rates
- No integration tests for broker order placement
- No tests for circuit breaker behavior
- No tests for startup reconciliation
- No tests for feature flag behavior

---

## 10. Cross-Cutting Architecture

### 10.1 Dependency Injection

**Two DI systems coexist:**
1. `app/application/di/composition_root.py` — Container-based DI for services
2. `app/api/dependencies.py` — FastAPI dependency injection for endpoints

The container resolves services at startup. FastAPI dependencies resolve per-request. The two systems are wired together via `init_singletons()`, which stores container-resolved services in module-level globals.

**Finding:** This dual-DI approach creates confusion. New code may use one system while existing code uses the other. The `init_singletons()` pattern is a code smell — it bypasses FastAPI's built-in DI.

### 10.2 Configuration

**Three config systems:**
1. `config/consolidated.py` — `ConsolidatedConfig` from YAML + env
2. `backend/app/config_models/settings_adapter.py` — Backward-compatible settings
3. `backend/config/feature_flags.yaml` — Feature flags

**Finding:** The config hierarchy is complex: `base.yaml` → `environments/{ENV}.yaml` → `strategies/{STRATEGY}.yaml` → `.env`. The `settings_adapter` provides backward compatibility for 25+ files that import `from app.config import settings`. This works but creates a fragile dependency chain.

### 10.3 Feature Flags

**12 feature flags defined:**
- `SCALP_ENGINE` — IB scalp engine
- `RISK_TIER_ENGINE` — Tiered risk by confidence
- `LLM_POST_TRADE` — Post-trade LLM analysis
- `LLM_PRE_CANDLE_ADVISORY` — Pre-candle advisory
- 8+ more

**Finding:** Feature flags are checked via `feature_enabled(settings, Feature.X)`. The pattern is correct, but there's no flag cleanup strategy. Old flags accumulate.

### 10.4 Event Bus

**Finding:** The `EventBus` in `app/domain/trading/event_store.py` is optional — `TradingSessionService` accepts it as a parameter. When provided, `TickReceived` events flow through pub/sub. When not provided, `_on_tick` is called directly. This dual path creates testing complexity.

---

## 11. Strategy Execution Flow

### 11.1 Full Signal-to-Execution Pipeline

```
┌─────────────────────────────────────────────────────────────────────┐
│  TICK ARRIVES (~every 5s for 5-min candles)                        │
│                                                                     │
│  1. StreamManager.stream_with_reconnect()                           │
│     └─ Dhan WebSocket → Market data packet                          │
│                                                                     │
│  2. CandleAggregator.aggregate()                                    │
│     └─ Tick → OHLC candle (with Lee-Ready delta classification)    │
│                                                                     │
│  3. [Throttle: max 1 process_tick per 500ms per symbol]             │
│                                                                     │
│  4. TradingSessionService.process_tick()                            │
│     ├─ _maybe_reset_symbol_state()                                  │
│     ├─ _process_pending_signal()                                    │
│     ├─ _update_data_store()                                         │
│     ├─ _handle_closed_positions()                                   │
│     └─ _publish_tick_event() → _on_tick()                           │
│                                                                     │
│  5. _on_tick() — THE PIPELINE                                       │
│     ├─ PhaseManager.check_and_handle_phase()                        │
│     │   └─ Session phase detection (IB, lunch, closing)             │
│     │                                                                 │
│     ├─ AMTService.run_analysis()                                    │
│     │   └─ AMTAnalyzer.analyze() ← 1,383-line god class             │
│     │       ├─ Volume profile + LVN/HVN                              │
│     │       ├─ VWAP + σ bands                                        │
│     │       ├─ Market state detection                                │
│     │       ├─ Order flow analysis                                   │
│     │       ├─ CVD tracking                                          │
│     │       ├─ Drive tracking                                        │
│     │       ├─ IB tracking                                           │
│     │       ├─ Displacement detection                                │
│     │       └─ Opening classification                                │
│     │                                                                 │
│     ├─ InitialBalanceEngine.update()                                │
│     │   └─ IB state tracking                                         │
│     │                                                                 │
│     ├─ [If SCALP_ENGINE enabled]                                    │
│     │   └─ IBBreakoutScalpEngine.evaluate_setup_a()                  │
│     │                                                                 │
│     ├─ SessionEventRouter.run_micro_agent_pipeline()                │
│     │   ├─ Agent 1: RegimeAgent → TRENDING/BALANCED/VOLATILE/DEAD   │
│     │   ├─ Agent 2: DirectionAgent → P(long), P(short)              │
│     │   ├─ Agent 3: TimingAgent → ENTER_NOW/WAIT/SKIP               │
│     │   └─ Agent 4: SizingAgent → Kelly-optimal size                 │
│     │                                                                 │
│     ├─ TradeLifecycleHandler.check_exits()                          │
│     │   └─ Exit checks for open positions                            │
│     │                                                                 │
│     ├─ SessionOrchestrator.update_pending_decision()                │
│     │   └─ Save last good decision for next candle                    │
│     │                                                                 │
│     ├─ SessionOrchestrator.resolve_entry_decision()                 │
│     │   └─ Resolve entry from agent or pending decision               │
│     │                                                                 │
│     ├─ SessionEventRouter.run_overseer_if_needed()                  │
│     │   └─ Overseer checks for open positions                         │
│     │                                                                 │
│     ├─ SessionEventRouter.execute_entry_path()                      │
│     │   ├─ Gate pipeline (12 gates)                                  │
│     │   ├─ EntryCoordinator.execute()                                │
│     │   │   ├─ RiskSizingEngine.calculate_size()                     │
│     │   │   ├─ Broker.place_order()                                  │
│     │   │   └─ Portfolio.open_position()                             │
│     │   └─ [If SCALP_ENGINE]                                         │
│     │       └─ Scalp entry execution                                 │
│     │                                                                 │
│     └─ [LLM Entry — async, on triggers only]                        │
│         ├─ Candle close trigger                                      │
│         ├─ 5-min monitoring cadence                                  │
│         └─ Structural event triggers                                 │
│             └─ LLMEntryHandler.predict() → async thread pool          │
│                                                                     │
│  6. StateBroadcaster.set_state()                                    │
│     └─ Store latest state for symbol                                │
│                                                                     │
│  7. StateBroadcaster.notify_viewers()                               │
│     └─ WebSocket delta broadcast to frontend                        │
│                                                                     │
│  8. Frontend receives delta                                         │
│     ├─ RAF-batched merge into instruments state                     │
│     ├─ React re-render (ChartScene, AIAnalysisPanel, etc.)          │
│     └─ Native canvas update (tick bus bypasses React)               │
└─────────────────────────────────────────────────────────────────────┘
```

### 11.2 Critical Path Latency

| Stage | Latency | Notes |
|-------|---------|-------|
| Stream → Aggregate | ~0.1ms | In-memory |
| AMT Analysis | ~0.5-2ms | 1,383-line class, 25+ trackers |
| Agent Pipeline | <1ms | 4 agents, sub-millisecond target |
| Exit Checks | ~0.2ms | Portfolio scan |
| State Broadcast | ~0.1ms | In-memory |
| **Total (no LLM)** | **~2-4ms** | Per symbol, per tick |
| LLM Entry (async) | ~300ms | Thread pool, not on critical path |

### 11.3 Execution Gaps

| Gap | Impact |
|-----|--------|
| No order confirmation feedback to frontend | Trader doesn't know if order was placed |
| No manual override capability | Cannot intervene from UI |
| No fill confirmation display | PnL is stale until next tick |
| No rejection reason display | Rejected orders are silent |
| No audit trail in frontend | Cannot see what happened |

---

## 12. Findings Index

### Critical (10)

| ID | Layer | Finding |
|----|-------|---------|
| B-06 | Backend | `process_tick` thread-safety issue with AMTAnalyzer |
| B-11 | Backend | `_on_tick` is 250+ lines of sequential logic |
| B-17 | Backend | AMTAnalyzer is 1,383-line god class with 25+ mutable attributes |
| B-18 | Backend | AMTAnalyzer not thread-safe |
| B-20 | Backend | `analyze()` calls `_update_session_vwap()` twice — double-accumulates |
| BR-01 | Broker | `facade.py` is 1,151 lines |
| F-05 | Frontend | Gap-filling fabricates zero-volume market data |
| F-20 | Frontend | AIAnalysisPanel is 1,525-line god component |
| Q-DUAL | Cross | Dual AMT implementation (backend vs quant) |
| Q-DUAL2 | Cross | Dual Portfolio implementation (backend vs quant) |

### High (15)

| ID | Layer | Finding |
|----|-------|---------|
| B-01 | Backend | Option scanner blocks startup for 120 seconds |
| B-07 | Backend | 500ms throttle drops analysis |
| B-08 | Backend | Futures roots bypass process_tick entirely |
| B-12 | Backend | AMT failure creates sentinel with zero values |
| B-13 | Backend | Signal TTL is 10 minutes (too long for scalping) |
| B-25 | Backend | LLM entry handler is 1,144 lines |
| B-26 | Backend | Prompt builder is 904 lines of string concatenation |
| B-29 | Backend | 12-gate pipeline called twice per entry |
| B-39 | Backend | SQLite not in WAL mode |
| B-40 | Backend | No index on ticks(symbol, time) |
| BR-02 | Broker | Auth provider is 1,044 lines |
| BR-03 | Broker | Symbol mapper is 905 lines of regex |
| F-07 | Frontend | Delta merge shallow-spreads 50+ field objects |
| F-22 | Frontend | 4-tier LTP fallback may show stale VWAP |
| F-23 | Frontend | Fabricated "monitoring mode" analysis |

### Medium (20)

| ID | Layer | Finding |
|----|-------|---------|
| B-02 | Backend | Startup failure is non-fatal |
| B-03 | Backend | `app.state` is a global bag with 15+ attributes |
| B-09 | Backend | `_tick_loop_forever` restarts on every disconnect |
| B-14 | Backend | `_recorded_trade_ids` is unbounded |
| B-15 | Backend | LLM cooldown state mutation |
| B-19 | Backend | Session VWAP accumulates indefinitely |
| B-22 | Backend | `_compute_order_flow_metrics` returns 18-key dict |
| B-27 | Backend | LLM timeout blocks entry decision for 30s |
| B-31 | Backend | `_MAX_PROBABILITY = 0.85` hardcoded |
| B-32 | Backend | Delta score wiring uses magic numbers |
| B-35 | Backend | Risk sizing engine overlaps with agent pipeline |
| B-37 | Backend | Exit engine duplicated in quant |
| I-01 | Infra | MLX inference adapter is 863 lines |
| I-03 | Infra | 654 lines of serialization schemas |
| S-01 | Shared | Circuit breaker has fixed recovery timeout |
| Q-02 | Quant | Portfolio uses Decimal but backend uses float |
| Q-04 | Quant | 599-line exit rules unused in production |
| Q-08 | Quant | IB scalp engine adds complexity |
| F-08 | Frontend | Race condition on symbol switch during reconnect |
| F-35 | Frontend | JournalPage fetches with no abort controller |

### Low (15)

| ID | Layer | Finding |
|----|-------|---------|
| B-04 | Backend | Three DI container aliases |
| B-05 | Backend | `init_singletons()` duplicates DI |
| B-10 | Backend | Hardcoded Lee-Ready delta mode |
| B-16 | Backend | `ENTRY_LLM_COOLDOWN` imported indirectly |
| B-24 | Backend | `_mtf_analyzer` referenced but doesn't exist |
| B-28 | Backend | Thread pool not shut down on error |
| B-30 | Backend | `Any` type for probability_engine |
| B-34 | Backend | Timing probability logs at INFO level |
| B-36 | Backend | Two Kelly implementations |
| B-41 | Backend | IST hardcoded in SQLite schema |
| BR-04 | Broker | 40+ exception types, many never raised |
| BR-05 | Broker | 812 lines of manual DTO conversion |
| BR-08 | Broker | Two confusingly-named adapter files |
| F-13 | Frontend | IST_OFFSET duplicated in 5+ files |
| F-58 | Frontend | 180-line Zustand store completely unused |

---

## 13. Remediation Roadmap

### Phase 1: Critical Fixes (Weeks 1-2)

| Priority | Task | Effort | Impact |
|----------|------|--------|--------|
| P0 | Fix double VWAP accumulation in `analyze()` | 2h | Eliminates VWAP corruption |
| P0 | Fix AMTAnalyzer thread safety (add per-symbol lock) | 4h | Prevents data corruption |
| P1 | Remove gap-filling or mark fabricated candles | 4h | Eliminates false LVN signals |
| P1 | Decompose AIAnalysisPanel into 8+ sub-components | 3-5 days | Makes frontend testable |
| P1 | Delete unused `useInstrumentsStore` | 30m | Removes 180 lines of dead code |
| P2 | Consolidate dual AMT implementations | 1-2 weeks | Eliminates divergence |
| P2 | Consolidate dual Portfolio implementations | 1 week | Eliminates precision inconsistency |

### Phase 2: High-Impact (Weeks 3-4)

| Priority | Task | Effort | Impact |
|----------|------|--------|--------|
| P2 | Decompose AMTAnalyzer into focused services | 1-2 weeks | Reduces 1,383 lines to 8-10 modules |
| P2 | Add SQLite WAL mode + indexes | 2h | Improves concurrent read/write |
| P2 | Fix 500ms throttle to queue analysis | 4h | Prevents dropped analysis |
| P3 | Add order confirmation feedback to frontend | 1-2 days | Closes execution visibility gap |
| P3 | Reduce signal TTL from 10min to 60sec | 1h | Prevents stale signal execution |
| P3 | Fix delta merge to use deep comparison | 4h | Prevents stale field propagation |

### Phase 3: Architecture (Weeks 5-6)

| Priority | Task | Effort | Impact |
|----------|------|--------|--------|
| P3 | Decompose `_on_tick` into pipeline stages | 2-3 days | Isolates errors, improves reliability |
| P3 | Unify DI systems (remove `init_singletons`) | 1-2 days | Eliminates dual-DI confusion |
| P3 | Add schema validation to DTOs | 1-2 days | Catches malformed data |
| P4 | Add load tests for WebSocket under high tick rates | 2-3 days | Validates performance |
| P4 | Add integration tests for broker order placement | 2-3 days | Validates execution |

### Phase 4: Polish (Weeks 7-8)

| Priority | Task | Effort | Impact |
|----------|------|--------|--------|
| P4 | Centralize IST_OFFSET constant | 1h | Eliminates magic number duplication |
| P4 | Clean up dead code (2-line stubs, `_mtf_analyzer`) | 2h | Code hygiene |
| P4 | Add feature flag cleanup strategy | 2h | Prevents flag accumulation |
| P4 | Reduce log verbosity (INFO → DEBUG) | 1h | Reduces log noise |
| P4 | Add abort controllers to all async fetches | 2h | Prevents race conditions |

---

## Appendix A: God Classes and Files

| File | Lines | Layer | Decomposition Target |
|------|-------|-------|---------------------|
| `AIAnalysisPanel.tsx` | 1,525 | Frontend | 8-10 sub-components |
| `amt_analyzer.py` | 1,383 | Backend | 10-12 focused services |
| `dhan/application/facade.py` | 1,151 | Broker | 5-6 facades |
| `llm_entry_handler.py` | 1,144 | Backend | 3-4 handlers |
| `ChartScene.tsx` | 1,036 | Frontend | 5-6 sub-components |
| `mlx_inference_adapter.py` | 863 | Infra | 3 modules |
| `session_event_router.py` | 895 | Backend | 3 routers |
| `dhan/infrastructure/auth_provider.py` | 1,044 | Broker | 3 modules |
| `prompt_builder.py` | 904 | Backend | Template engine |
| `database.py` | 953 | Infra | 3 modules |
| `dhan/infrastructure/symbol_mapper.py` | 905 | Broker | 2 mappers |
| `agent_pipeline.py` | 989 | Backend | 4 agents (already split) |

**Total god files:** 12 files >800 lines
**Total lines in god files:** ~13,882 (16% of codebase)
**Target after decomposition:** ~8,000 lines (9% of codebase)

## Appendix B: Dead Code Inventory

| File | Lines | Type |
|------|-------|------|
| `fabio_ai/services/cvd_tracker.py` | 2 | Stub |
| `fabio_ai/services/drive_tracker.py` | 2 | Stub |
| `fabio_ai/services/aggression_scorer.py` | 2 | Stub |
| `fabio_ai/services/footprint_analyzer.py` | 2 | Stub |
| `fabio_ai/services/market_state_engine.py` | 2 | Stub |
| `fabio_ai/services/eia_calendar.py` | 2 | Stub |
| `fabio_ai/services/drive_decay.py` | 2 | Stub |
| `fabio_ai/services/exit_rules.py` | 2 | Stub |
| `fabio_ai/services/exit_signal.py` | 2 | Stub |
| `fabio_ai/ports/three_align.py` | 2 | Stub |
| `frontend/stores/instruments.ts` | 179 | Unused store |
| `quant/contracts/aggregates.py` | 639 | Unused Portfolio |
| `quant/execution/exit_rules.py` | 599 | Unused exit rules |
| `quant/amt/compute.py` | 301 | Partial AMT impl |

**Total dead code:** ~1,730 lines (2% of codebase)

## Appendix C: Duplication Map

| Logic | Location 1 | Location 2 | Lines Duplicated |
|-------|-----------|-----------|-----------------|
| AMT analysis | `backend/amt_analyzer.py` | `quant/amt/compute.py` | ~500 |
| Portfolio management | `backend/trade_aggregate.py` | `quant/contracts/aggregates.py` | ~400 |
| Exit rules | `backend/exit_engine.py` | `quant/execution/exit_rules.py` | ~300 |
| Kelly sizing | `agent_pipeline.py` | `risk_sizing_engine.py` | ~50 |
| IST offset | `frontend/` (5 files) | `backend/` (3 files) | ~10 |
| Volume profile | `backend/volume_profile.py` | `quant/amt/profile/volume_profile.py` | ~200 |
| VWAP calculation | `backend/amt_analyzer.py` | `quant/vwap.py` | ~100 |
| Option scanner | `backend/option_scanner.py` | `quant/amt/session/scanner.py` | ~300 |

**Total duplicated logic:** ~1,860 lines (2.2% of codebase)

---

*End of Full-Stack Audit Report*