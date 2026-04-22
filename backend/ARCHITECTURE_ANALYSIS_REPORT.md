# GlassyTrade AI Backend — Architecture & Flow Analysis Report

## 1. Executive Summary

GlassyTrade AI is an algorithmic trading system built with FastAPI, targeting Indian derivatives markets (MCX commodities, NSE/NFO equity options). It features a hybrid decision engine combining **LLM-based reasoning** (GGUF/MLX models) with **LightGBM quantitative signals**, gated by an extensive **Volume Profile / AMT (Auction Market Theory)** analysis pipeline. The system runs as a standalone backend engine; the frontend WebSocket is a read-only viewer.

**Key characteristics:**
- Event-driven tick processing pipeline
- Dual-signal architecture (LLM + ML)
- Portfolio-aware risk management with session-level circuit breakers
- SQLite persistence with WAL mode and tick batching
- Dhan broker integration (paper/live trading)

---

## 2. System Architecture

### 2.1 Layered Architecture (Clean/Hexagonal)

```
┌──────────────────────────────────────────────────────────────────┐
│                        PRESENTATION LAYER                        │
│  FastAPI App │ REST Routers │ WebSocket (gameloop) │ CORS MW     │
├──────────────────────────────────────────────────────────────────┤
│                      APPLICATION LAYER                           │
│  TradingEngine │ TradingSessionService │ SessionEventRouter      │
│  Handlers: AMT │ LLM Entry │ Trade Lifecycle │ RL │ Overseer    │
│  Services: Entry/Exit Coord │ Risk Coord │ State Broadcast       │
├──────────────────────────────────────────────────────────────────┤
│                         DOMAIN LAYER                             │
│  Events (DomainEvent) │ Models (Entities, Aggregates, VOs)       │
│  Ports: IMarketData │ IBroker │ IStorage │ ILLMInference         │
│  Services: AMT Analyzer │ Regime Detector │ Option Selector      │
│  Probability Pipeline │ RL Training │ Generative AI              │
├──────────────────────────────────────────────────────────────────┤
│                     INFRASTRUCTURE LAYER                         │
│  Dhan Adapter │ Paper Broker │ SQLite Storage │ GGUF/MLX LLM     │
│  LGBM Probability │ MCX/NSE Strategy │ Delta Profile │ NPOC      │
│  Metrics (Prometheus) │ Serialization Schemas                   │
├──────────────────────────────────────────────────────────────────┤
│                      CONFIGURATION LAYER                         │
│  YAML Config (base/env/strategy) │ .env (secrets)               │
│  ServiceGraph (DI Container) │ Settings Adapter                 │
└──────────────────────────────────────────────────────────────────┘
```

### 2.2 Directory Structure

| Layer | Path | Responsibility |
|-------|------|---------------|
| Entry | `app/main.py` | FastAPI app, lifespan, DI graph setup |
| API | `app/api/routers/` | REST endpoints: health, market, trading, AI, RL, metrics |
| API WS | `app/api/websocket/gameloop.py` | WebSocket server-driven viewer loop |
| Application | `app/application/engine.py` | TradingEngine — orchestrates streaming |
| Application | `app/application/service_graph.py` | DI container — port-to-adapter binding |
| Handlers | `app/application/handlers/` | AMT, LLM Entry, Trade Lifecycle, RL, Overseer, etc. |
| Services | `app/application/services/` | Entry/Exit coordination, risk, session state, journal |
| Domain Events | `app/domain/trading/events.py` | Immutable frozen dataclass events |
| Domain Models | `app/domain/trading/models/` | Entities (Signal, Position), Aggregates (Portfolio, Stats) |
| Domain Ports | `app/domain/ports/` | Abstract interfaces (IBroker, IMarketData, IStorage, etc.) |
| Domain Services | `app/domain/fabio_ai/services/` | AMT Analyzer, Regime Detector, Entry Gate, Option Scanner |
| Domain Probability | `app/domain/probability/` | LightGBM feature extraction, agent pipeline |
| Infrastructure | `app/infrastructure/adapters/` | Dhan, Paper Broker, GGUF/MLX, LGBM, Delta, NPOC |
| Infrastructure | `app/infrastructure/storage/database.py` | SQLite adapter with WAL, batching |
| Infrastructure | `app/infrastructure/strategies/` | MCX and NSE exchange-specific strategies |
| Config | `app/config.py`, `config_models/` | YAML-based config hierarchy with .env fallback |

---

## 3. Dependency Injection (ServiceGraph)

The `ServiceGraph` class (`app/application/service_graph.py:43`) acts as a **poor-man's DI container** with lazy initialization:

**Adapter Registrations:**
| Port | Implementation | Notes |
|------|---------------|-------|
| `IMarketData` | `DhanMarketDataAdapter` | Live streaming + historical data via Dhan API |
| `IBroker` | `PaperBrokerAdapter` | Paper trading (simulated execution) |
| `IStorage` | `SQLiteStorageAdapter` | Thread-safe SQLite with WAL mode |
| `ILLMInference` | `GGUFInferenceAdapter` or `MLXInferenceAdapter` | Selected by model file extension (.gguf vs other) |
| `IProbabilityInference` | `LGBMProbabilityAdapter` | LightGBM model for entry probability |
| `INotification` | `NullNotificationAdapter` | Logs only; swap for Telegram/Slack in prod |
| `IDeltaProfile` | `DeltaProfileAdapter` | Delta volume profile computation |
| `INPOC` | `NPOCAdapter` | Naked POC tracking |
| `IExchangeStrategy` | `MCXExchangeStrategy` or `NSEExchangeStrategy` | Selected by `DEFAULT_EXCHANGE` config |

**Lazy Service Creation:**
Services like `AMTAnalysisService`, `GatePipeline`, and `GenerativeAIService` are created on-demand via `_create_service()`. The `TradingSessionService` is eagerly created at startup.

---

## 4. Startup Flow

```
main.py → create_application()
  │
  ├─ FastAPI lifespan startup:
  │   ├─ OptionScannerService.scan_top_n() → selects MCX/NSE contracts
  │   │   (runs in ThreadPoolExecutor, 120s timeout)
  │   │
  │   ├─ TradingEngine(graph) created
  │   │   ├─ StreamManager — market data streaming
  │   │   ├─ CandleAggregator — tick-to-candle aggregation
  │   │   ├─ RangeBarBuilder — range bar construction
  │   │   ├─ WatchdogManager — SL/TP watchdog + stream health
  │   │   ├─ TickProcessor — OI tracking + depth building
  │   │   └─ StateBroadcaster — WS state assembly
  │   │
  │   └─ engine.start()
  │       ├─ EngineLifecycle.startup() — recovery, seeding, background tasks
  │       ├─ _tick_loop_forever() — main streaming loop
  │       └─ UnderlyingFuturesProvider — maps options → futures for AMT
  │
  └─ Routes registered: /health, /market, /trading, /api/*, /rl/*, /metrics/*
```

---

## 5. Core Trading Pipeline (Tick Flow)

This is the heart of the system. Every tick follows this path:

### 5.1 Market Data Ingestion

```
Dhan WebSocket Stream
  │
  ▼
TradingEngine._tick_loop()
  │
  ├─ stream_manager.stream_with_reconnect() — async generator
  ├─ Circuit breaker check (5 failures → 300s cooldown)
  ├─ Market hours check (is_market_open)
  ├─ OI tracking (tick_processor.track_oi)
  ├─ Depth building from packet (tick_processor.build_depth_from_packet)
  ├─ Footprint accumulator (candle_aggregator.update_footprint)
  └─ CandleAggregator.aggregate() — tick → OHLC candle
```

### 5.2 Tick Processing (Throttled)

**Throttling:** Full `process_tick` runs max once per 500ms per symbol. Between full runs, throttled state updates keep the UI current.

```
TradingSessionService.process_tick()
  │
  ├─ 0. Session phase check (force-exit at 15:15 IST)
  │
  ├─ 1. AMT Analysis (AMTHandler)
  │   ├─ Data source: underlying futures (preferred) or option premium
  │   ├─ Volume Profile: POC, VAH, VAL, profile shape (D/P/b/B)
  │   ├─ Footprint: aggressive prints, stacked imbalances
  │   ├─ Market state: BALANCED / IMBALANCED / NO_TRADE
  │   ├─ Aggression scoring
  │   ├─ CVD (Cumulative Volume Delta) slope
  │   ├─ OFI (Order Flow Imbalance)
  │   └─ Initial Balance (IB) tracking
  │
  ├─ 1b. Micro-Agent Pipeline (LightGBM)
  │   ├─ Feature extraction (candle history + AMT result + order book)
  │   ├─ LGBMProbabilityAdapter.predict()
  │   └─ AgentDecision: direction, probability, regime, timing, kelly fraction
  │
  ├─ 2. Trade Lifecycle (TradeLifecycleHandler)
  │   ├─ Check exits: SL, TP, time stops, CVD divergence
  │   ├─ Position management: trailing stops, partial exits
  │   └─ Has open position? → run overseer
  │
  ├─ 3. Overseer (LLMOverseerHandler)
  │   └─ LLM reviews open positions for management advice
  │
  ├─ 4a. Entry Execution (SessionEventRouter)
  │   ├─ Gate Pipeline: market state, drive number, aggression, risk tier
  │   ├─ SHORT gates (if applicable)
  │   ├─ Signal construction (build_entry_signal)
  │   └─ EntryCoordinator.execute_signal()
  │
  └─ 4b. LLM Advisory (LLMEntryHandler)
      ├─ Trigger: new candle + no position + cooldown passed
      ├─ Background thread pool (per-symbol queue, max 10)
      ├─ Rich prompt: AMT data, regime, session phase, episodic memory
      ├─ Timeout: 15s → fallback to quant signal
      └─ Signal construction (advisory only — actual entry via agent pipeline)
```

### 5.3 Entry Decision Resolution

The system uses a **unified entry path** with priority:

1. **Agent Decision (LightGBM)** — Primary entry driver
   - Probability >= threshold (AGENT_DECISION_THRESHOLD)
   - Direction != FLAT
   - New candle boundary

2. **Pending Decision** — Carried over from previous tick
   - Saved when valid agent decision exists
   - Executed on next new candle

3. **LLM Advisory** — Contextual analysis for UI
   - Runs asynchronously, doesn't block entry pipeline
   - Provides rationale and market context for dashboard

### 5.4 Gate Pipeline

Before any entry, signals pass through multiple gates:

```
run_gate_pipeline()
  │
  ├─ Market state gate (must be IMBALANCED for trend, any for mean-reversion)
  ├─ Drive number gate (first/second drive detection)
  ├─ Aggression score gate
  ├─ Risk tier / session PnL cushion
  ├─ Playbook guard (re-entry blocking after stop-out)
  ├─ Session phase gate (entries blocked in certain phases)
  ├─ Circuit breaker (consecutive losses)
  └─ SHORT-specific gates (if short signals enabled)
```

---

## 6. WebSocket Architecture

**Server-Driven Mode** (primary):
```
Frontend WS → /api/trading/ws/gameloop
  │
  ├─ subscribe message → _viewer_loop()
  │   ├─ Send config (symbol, exchange, interval)
  │   ├─ Send history (last 500 candles per symbol)
  │   ├─ Send current snapshot (full state)
  │   └─ Polling loop:
  │       ├─ engine.wait_for_update(known_gen) — blocks until new data
  │       ├─ Delta compression (30s keyframe, deltas in between)
  │       └─ Send to client
  │
  └─ Client-driven mode (backward compat)
      └─ Direct process_tick calls (dev only)
```

**Key design:** The TradingEngine runs independently. Frontend disconnect has **zero impact** on trading. WS is purely a state viewer.

---

## 7. Data Models

### 7.1 Domain Events (Immutable)

All events are frozen dataclasses with idempotency keys:

| Event | Purpose |
|-------|---------|
| `TickReceived` | Market tick arrived (foundational event) |
| `AIAnalysisCompleted` | LLM analysis finished |
| `SignalGenerated` | Trade signal created |
| `SignalValidated` | Risk checks passed |
| `OrderPlaced` / `OrderCancelled` | Broker order events |
| `FillReceived` | **Source of truth** for position state |
| `PositionChanged` / `Opened` / `Closed` | Derived position events |
| `RiskCheckFailed` | Signal rejected by risk |
| `DailyLossLimitReached` | Trading halt trigger |

### 7.2 Core Entities

- **Signal**: direction, entry_price, stop_loss, take_profit, position_size, confidence, setup_type
- **Position**: id, side, entry_price, size, stop_loss, take_profit, source, status, pnl
- **Portfolio**: collection of positions, equity, balance, stats tracking
- **OHLC**: time, open, high, low, close, volume, vwap, delta, taker_buy_volume
- **AMTResult**: market_state, poc, vah, val, aggression, cvd_slope, ofi, profile_shape, lvns, hvns

---

## 8. Database Schema (SQLite)

| Table | Purpose | Key Columns |
|-------|---------|-------------|
| `ticks` | OHLCV candle history | symbol, time, OHLC, volume, delta |
| `trades` | Closed trade log | position_id, symbol, side, entry/exit, pnl |
| `llm_decisions` | LLM analysis audit trail | symbol, direction, confidence, rationale, AMT data |
| `open_positions` | Crash recovery | id, symbol, side, entry, SL, TP |
| `position_events` | Position lifecycle events | position_id, event_type, event_time |
| `session_profiles` | Daily volume profiles | symbol, poc, vah, val, profile_shape |
| `npoc_records` | Naked POC tracking | underlying, poc_price, is_filled |
| `fine_tuning_features` | ML training dataset | trade features, result, pnl |
| `kv_store` | Crash-safe state persistence | key, value (JSON) |
| `performance_snapshots` | Portfolio snapshots over time | equity, balance, win_rate |

**Performance features:**
- WAL journal mode
- Tick batching (50 ticks or 5s flush)
- Thread-safe via persistent connection + lock
- UNIQUE index on (symbol, time) for deduplication

---

## 9. Risk Management

### 9.1 Session Risk Coordinator
- Per-symbol SessionRiskManager
- Daily loss limit tracking
- Max trades per session cap
- Stop-loss cushioning based on risk tier
- Session PnL-based trading halts

### 9.2 System-Level Controls
- Global emergency kill switch (`halt_trading()` / `resume_trading()`)
- Circuit breaker per symbol (5 failures → 300s cooldown)
- Phase 5 force-exit (15:15-15:30 IST — all positions closed)
- Cooldown between trades (60s minimum)
- Re-entry blocking after stop-out (RegimeDetector)

### 9.3 Signal Validation
- Risk-reward ratio filter
- Max distance to structural levels
- Session phase gates
- Playbook guard (prevents re-entering failed setups)

---

## 10. AI/ML Components

### 10.1 LLM Inference
- **GGUF adapter**: llama.cpp-based inference
- **MLX adapter**: Apple Silicon optimized
- **Timeout**: 15 seconds → fallback to quant signal
- **Per-symbol queues**: max 10 pending, dedicated worker thread
- **Staleness check**: drops requests queued > 20s
- **Output sanitization**: strips JSON artifacts from rationale

### 10.2 LightGBM Probability Engine
- Feature extraction from candle history + AMT + order book
- Regime detection (DEAD/EXPANSION/CONTRACTION)
- Kelly fraction for position sizing
- Latency tracking (microseconds)

### 10.3 Reinforcement Learning
- Valentini environment (custom gym env)
- Data loader for training data
- Reward shaper for RL optimization
- Trainer module
- RL models stored in `rl_models/` directory
- RL router endpoints for training/status

---

## 11. Exchange Strategies

| Strategy | Exchange | Purpose |
|----------|----------|---------|
| `MCXExchangeStrategy` | MCX (commodity options) | Tick size, contract specs, margin rules |
| `NSEExchangeStrategy` | NSE/NFO (equity options) | Tick size, lot sizes, expiry rules |

Strategy selection via `DEFAULT_EXCHANGE` config. NFO is mapped to NSE strategy.

---

## 12. API Routes

| Router | Prefix | Endpoints |
|--------|--------|-----------|
| Health | `/health`, `/api/health` | Health check |
| Market | `/market` | Market data queries |
| Trading | `/trading` | Trade control (halt/resume, reset) |
| AI | `/api` | AI analysis, decisions |
| RL | `/rl` | RL training, status |
| Metrics | `/metrics` | Prometheus metrics |
| WebSocket | `/api/trading/ws/gameloop` | Live state streaming |

---

## 13. Configuration Hierarchy

```
1. base.yaml          — All defaults
2. environments/{ENV}.yaml     — Environment overrides (paper/live)
3. strategies/{STRATEGY}.yaml  — Strategy-specific overrides (mcx/nse)
4. .env               — Secrets only (API keys, tokens)
```

Environment variables: `GLASSYTRADE_ENV`, `GLASSYTRADE_STRATEGY`, `TRADING_MODE`

---

## 14. Key Design Patterns

| Pattern | Implementation |
|---------|---------------|
| **Ports & Adapters** | Abstract interfaces in `domain/ports/`, concrete in `infrastructure/adapters/` |
| **Event Sourcing (partial)** | Immutable domain events, FillReceived as source of truth |
| **CQRS (read model)** | StateBroadcaster assembles read-only snapshots for WS |
| **Circuit Breaker** | PerEntityCircuitBreaker for tick processing |
| **Strategy Pattern** | IExchangeStrategy with MCX/NSE implementations |
| **Coordinator Pattern** | EntryCoordinator, ExitCoordinator orchestrate multi-step flows |
| **Handler Pattern** | Focused handlers (AMT, LLM, Lifecycle, RL, Overseer) |
| **Factory Pattern** | ServiceGraph._create_service() for lazy DI |
| **Observer Pattern** | StateBroadcaster notifies WS viewers on generation change |

---

## 15. Concurrency Model

| Component | Threading Model |
|-----------|----------------|
| TradingEngine._tick_loop() | Async (asyncio event loop) |
| LLM Inference | ThreadPoolExecutor + per-symbol queue (dedicated threads) |
| SQLite Storage | Single persistent connection + threading.Lock |
| Tick batching | Background Timer thread |
| CandleAggregator | Runs in tick loop (same thread) |
| WebSocket | Async (same event loop as engine) |
| StateBroadcaster | Cross-thread notifications via asyncio.CallSoon |

---

## 16. Observability

- **Prometheus metrics** via `app/infrastructure/metrics.py`
- **Structured logging** with symbol-tagged entries
- **Latency tracking** (tick-to-signal, agent pipeline, LLM inference)
- **Gate rejection tracking** (SignalTracker, GateRejectionTracker)
- **Trade journal** with full AMT + LLM context
- **Performance snapshots** saved on every closed position

---

## 17. Data Flow Summary Diagram

```
┌──────────────┐     ticks      ┌─────────────────┐
│  Dhan API    │ ──────────────▶ │ TradingEngine    │
│  (WebSocket) │                 │ _tick_loop()     │
└──────────────┘                 └────────┬─────────┘
                                          │
                               ┌──────────▼──────────┐
                               │ CandleAggregator     │
                               │ (tick → OHLC candle) │
                               └──────────┬───────────┘
                                          │
                               ┌──────────▼──────────────┐
                               │ TradingSessionService    │
                               │ process_tick()           │
                               └──────────┬───────────────┘
                                          │
                    ┌─────────────────────┼─────────────────────┐
                    ▼                     ▼                     ▼
           ┌───────────────┐   ┌──────────────────┐   ┌─────────────────┐
           │ AMT Handler   │   │ Agent Pipeline   │   │ Trade Lifecycle │
           │ (Volume       │   │ (LightGBM)       │   │ (Exits, SL/TP)  │
           │  Profile)     │   │ → AgentDecision  │   │                 │
           └───────┬───────┘   └────────┬─────────┘   └────────┬────────┘
                   │                    │                      │
                   └────────────────────┼──────────────────────┘
                                        ▼
                              ┌─────────────────────┐
                              │ SessionEventRouter   │
                              │ ├─ run_micro_pipeline│
                              │ ├─ execute_entry     │
                              │ ├─ trigger_llm       │
                              │ └─ run_overseer      │
                              └──────────┬──────────┘
                                         │
                              ┌──────────▼──────────┐
                              │ EntryCoordinator     │
                              │ ├─ Gate Pipeline     │
                              │ ├─ Signal Build      │
                              │ └─ Broker Execute    │
                              └──────────┬───────────┘
                                         ▼
                              ┌──────────────────────┐
                              │ PaperBrokerAdapter   │
                              │ (or Dhan live broker) │
                              └──────────┬───────────┘
                                         ▼
                              ┌──────────────────────┐
                              │ SQLite Storage       │
                              │ (trades, positions,  │
                              │  performance, kv)    │
                              └──────────────────────┘
```

---

## 18. Strengths

1. **Clean architecture** with clear layer separation
2. **Decoupled DI** via ServiceGraph — easy to swap adapters
3. **Robust risk management** — multiple safety layers
4. **Hybrid AI approach** — LLM + ML ensemble for better signals
5. **Server-driven WS** — frontend is stateless viewer
6. **Crash-safe persistence** — open positions survive restarts
7. **Tick batching** — efficient SQLite writes
8. **Circuit breakers** — prevents cascading failures
9. **Comprehensive observability** — metrics, logging, journaling
10. **Extensive gate pipeline** — prevents low-quality entries

---

## 19. Areas of Complexity

1. **LLMEntryHandler** (51KB, 1190 lines) — large, multi-responsibility module
2. **TradingSessionService** (1038 lines) — coordinator with many delegated calls
3. **Threading model** — mix of async + threads requires careful synchronization
4. **State management** — session state is mutable with many caches and flags
5. **Config hierarchy** — YAML + .env + settings adapter adds indirection
6. **Domain events** — defined but not actively used via event bus (direct calls)
7. **Duplicate tracking** — gate_tracker, signal_tracker, journal all track rejections

---

## 20. Technology Stack

| Component | Technology |
|-----------|-----------|
| Framework | FastAPI + Uvicorn |
| Language | Python 3.14 |
| Database | SQLite 3 (WAL mode) |
| Broker | Dhan API (via brokers/ library) |
| LLM | GGUF (llama.cpp) or MLX (Apple Silicon) |
| ML | LightGBM |
| ML Training | Reinforcement Learning (custom gym env) |
| Streaming | WebSocket (server-driven) |
| Metrics | Prometheus |
| Config | YAML + .env |
| Virtual Env | venv (Python 3.14) |
