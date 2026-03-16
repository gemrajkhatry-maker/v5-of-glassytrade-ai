# GlassyTrade AI v5 - Full Architecture Analysis

*Generated: March 5, 2026*

---

## Table of Contents

1. [System Overview](#system-overview)
2. [Technology Stack](#technology-stack)
3. [High-Level Architecture](#high-level-architecture)
4. [Data Flow](#data-flow)
5. [Domain-Driven Design Structure](#domain-driven-design-structure)
6. [Key Domain Services](#key-domain-services)
7. [Clean Architecture in Brokers Module](#clean-architecture-in-brokers-module)
8. [AIML Pipeline](#aiml-pipeline)
9. [WebSocket Gameloop & Frontend Sync](#websocket-gameloop--frontend-sync)
10. [Risk Management](#risk-management)
11. [Persistence & Observability](#persistence--observability)
12. [Research & Evolution](#research--evolution)
13. [Known Issues & Recommendations](#known-issues--recommendations)
14. [Scalability & Performance](#scalability--performance)
15. [Security & Compliance](#security--compliance)
16. [Testing Strategy](#testing-strategy)
17. [Deployment & Operations](#deployment--operations)
18. [Future Roadmap](#future-roadmap)
19. [Conclusion](#conclusion)

---

## System Overview

**GlassyTrade AI** is an AI-powered options trading platform implementing **Fabio Valentini's Auction Market Theory (AMT)** methodology. It features a **dual-engine architecture**:

- **Theorist Engine (AMT):** Analyzes market structure using Volume Profile, POC, VWAP, order flow, and acceptance/rejection logic.
- **Quant Engine (AI):** Combines multiple predictive systems:
  - **LLM (Large Language Model):** Fine-tuned model for discretionary narrative reading (entries only)
  - **LightGBM Micro-Agents:** Sub-millisecond probability pipeline for fast decisions
  - **RL (Reinforcement Learning):** PPO-based agent for alternative perspective
  - **Learning Engine:** Reinforcement backpropagation to adjust model weights based on trade outcomes

The system is **backend-driven**: the FastAPI backend runs the entire trading logic autonomously, while the React frontend is a pure visualization layer that subscribes to state updates via WebSocket.

---

## Technology Stack

### Backend

| Component | Technology | Purpose |
|-----------|------------|---------|
| **Language** | Python 3.11+ with type hints | Core implementation |
| **Framework** | FastAPI | Async HTTP + WebSocket |
| **Database** | SQLite | Local persistence with WAL |
| **Event Bus** | In-memory synchronous pub/sub | Decoupled handlers |
| **LLM Backend** | MLX (Apple Silicon) / CUDA (NVIDIA) | GPU-accelerated inference |
| **Probability Models** | LightGBM (4-bit quantized) | Fast micro-agents |
| **RL** | Stable-Baselines3 (PPO) | Alternative decision engine |
| **Broker API** | Dhan REST + WebSocket | Market data & order execution |

### Frontend

| Component | Technology | Purpose |
|-----------|------------|---------|
| **Framework** | React 19 + TypeScript | UI layer |
| **Visualization** | TradingView Lightweight Charts | Canvas 2D charting |
| **Styling** | Tailwind CSS | Glassmorphism theme |
| **Module Loading** | Import maps via CDN | No bundler required |
| **Icons** | Lucide React | Icon set |

### Architecture Patterns

- **Domain-Driven Design (DDD)** with Clean/Hexagonal architecture
- **Port/Adapter pattern** for broker integrations
- **Event-driven** with domain events
- **Reactive programming** with RxPY (in brokers module)
- **Factory pattern** for broker creation
- **Circuit breaker** for fault tolerance

---

## High-Level Architecture

```
┌─────────────────────────────────────────────────────────────────────────┐
│                            FRONTEND (React)                             │
│  • ChartScene (Lightweight Charts)                                      │
│  • MarketSidebar (scanner)                                             │
│  • AIAnalysisPanel (LLM decisions)                                     │
│  • JournalPage (trade history)                                         │
│  • AIControls (natural language commands)                             │
│  └── WebSocket → gameloop (state snapshots)                           │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                         BACKEND (FastAPI)                               │
│                                                                         │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  TradingEngine (standalone, independent of WS viewers)          │  │
│  │  • Dhan WebSocket stream                                         │  │
│  │  • Candle aggregation                                            │  │
│  │  • Tick processing → TradingSession.process_tick()              │  │
│  │  • Footprint accumulation, OI tracking                          │  │
│  │  • State snapshot broadcast to WS viewers                       │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                  │                                       │
│                                  ▼                                       │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  TradingSessionService (event-driven pipeline)                  │  │
│  │  • subscribes to TickReceived                                   │  │
│  │  • manages per-symbol SessionState (data, portfolio, learning) │  │
│  │  • coordinates handlers: AMT, LLM Entry, Trade Lifecycle, RL,  │  │
│  │    Overseer                                                      │  │
│  └───────────────────────────────────────────────────────────────────┘  │
│                                  │                                       │
│                                  ▼                                       │
│  ┌───────────────────────────────────────────────────────────────────┐  │
│  │  Service Graph (singleton, created at startup)                  │  │
│  │  ├─ market_data (DhanAdapter)                                   │  │
│  │  ├─ broker (PaperBrokerAdapter)                                 │  │
│  │  ├─ llm_inference (MLXInferenceAdapter)                         │  │
│  │  ├─ probability_engine (LGBMProbabilityAdapter)                 │  │
│  │  ├─ storage (AsyncPersistenceBus → SQLite)                      │  │
│  │  ├─ event_bus (InMemoryEventBus)                                │  │
│  │  └─ trading_session (TradingSessionService)                     │  │
│  └───────────────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────────────┘
                                  │
                                  ▼
┌─────────────────────────────────────────────────────────────────────────┐
│                    INFRASTRUCTURE / ADAPTERS                            │
│  • DhanMarketDataAdapter (REST + WebSocket)                            │
│  • PaperBrokerAdapter (in-memory simulation)                           │
│  • MLXInferenceAdapter (background model loading, GPU lock)            │
│  • LGBMProbabilityAdapter (LightGBM model loading)                    │
│  • AsyncPersistenceBus (background SQLite writer)                     │
└─────────────────────────────────────────────────────────────────────────┘
```

---

## Data Flow

### 1. Market Data Ingestion

```
TradingEngine:
  while running:
    ticks = await market_data.stream_ticker(symbols)
    for tick in ticks:
      candle = aggregate(tick)
      session.process_tick(symbol, candle, order_book)
      state = session.get_latest_state(symbol)
      self._latest_states[symbol] = state
      self._generation += 1
      self._condition.notify_all()  # wake WS viewers
```

### 2. Event Pipeline (Synchronous Handlers)

```
TickReceived event:
  ├─ Portfolio.process_tick() → SL/TP exits (mechanical)
  ├─ AMTHandler → AMT analysis (VP, POC, LVN, displacement, A/R)
  ├─ LLMEntryHandler (async worker) → build prompt, call LLM, emit SignalGenerated
  ├─ LLMOverseerHandler (async) → monitor open positions, decide HOLD/EXIT
  ├─ RLHandler → alternative RL inference (optional)
  └─ TradeLifecycleHandler → execute signals, manage exits
```

### 3. Signal → Position

```
SignalGenerated event:
  → TradeManager._execute_signal()
    → Risk validation (max risk, duplicate check)
    → Position opened via broker
    → Position stored in portfolio & database
```

### 4. Exits

```
Portfolio.process_tick():
  if price hits SL/TP → close position → emit PositionClosed

TradeLifecycleHandler:
  - Monitors time stops
  - Monitors CVD kill signals
  - Monitors overseer exits
  → Triggers position.close()
```

---

## Domain-Driven Design Structure

```
backend/app/
├── domain/
│   ├── ports/                    # Abstract interfaces
│   │   ├── market_data.py        # MarketDataPort
│   │   ├── llm_inference.py      # LLMInferencePort
│   │   ├── probability_inference.py  # ProbabilityInferencePort
│   │   ├── storage.py            # StoragePort
│   │   ├── broker.py             # BrokerPort
│   │   └── event_bus.py          # EventBusPort
│   ├── trading/
│   │   ├── models/               # Domain entities & value objects
│   │   │   ├── entities.py       # Signal, Position
│   │   │   ├── aggregates.py     # Portfolio
│   │   │   ├── value_objects.py  # OHLC, OrderBook, AMTResult
│   │   │   └── enums.py          # Side, Source, SetupType, PositionStatus
│   │   ├── events.py             # Domain events
│   │   └── services/
│   │       ├── risk_manager.py   # Position sizing, circuit breaker
│   ├── fabio_ai/                 # AI-specific subdomain
│   │   ├── services/
│   │   │   ├── generative_ai_service.py   # LLM prompt building & parsing
│   │   │   ├── learning_engine.py         # Backpropagation of trade results
│   │   │   ├── option_scanner.py          # Multi-symbol option scanning
│   │   │   ├── trade_manager.py           # Exit management (mechanical)
│   │   │   ├── session_risk_manager.py    # Intraday compounding (cushion)
│   │   │   └── overseer_handler.py        # LLM overseer for position monitoring
│   │   └── rl/                   # Reinforcement learning
│   │       └── trainer.py        # ValentiniTrainer (PPO)
│   ├── probability/              # LightGBM micro-agent pipeline
│   │   ├── features.py           # 42 feature extraction
│   │   ├── agent_pipeline.py     # Regime, Direction, Timing, Sizing agents
│   │   └── labels.py             # Outcome labeling for training
│   └── models/                   # Persisted model artifacts
│       ├── glassytrade-qwen-mlx-fused/  # MLX LLM (4-bit)
│       ├── fp_long.txt                  # LightGBM first-passage (LONG)
│       ├── fp_short.txt                 # LightGBM first-passage (SHORT)
│       └── mfe_*_q50.txt                # MFE quantile models
├── application/
│   ├── services/
│   │   ├── trading_session.py    # Main coordinator (event handlers subscription)
│   │   ├── backtest_engine.py    # Historical simulation
│   │   ├── daily_reporter.py     # End-of-day reporting
│   │   └── trade_journal.py      # JSONL trade logging
│   ├── handlers/                 # Event handlers (application layer)
│   │   ├── amt_handler.py        # AMT analysis on every tick
│   │   ├── llm_entry_handler.py  # Async LLM inference worker
│   │   ├── llm_overseer_handler.py  # Position monitoring
│   │   ├── trade_lifecycle_handler.py  # Signal execution, exit triggers
│   │   └── rl_handler.py         # RL inference
│   └── engine.py                 # TradingEngine (independent market data loop)
├── infrastructure/
│   ├── adapters/
│   │   ├── dhan_adapter.py       # Dhan broker REST/WS client
│   │   ├── paper_broker.py       # In-memory simulation
│   │   ├── mlx_inference_adapter.py  # LLM loading & generation
│   │   └── lgbm_probability_adapter.py  # LightGBM loading & inference
│   ├── storage/
│   │   └── database.py           # SQLite with batch writes
│   ├── event_bus.py              # In-memory synchronous bus
│   ├── async_persistence.py      # Background writer
│   ├── resilience.py             # Circuit breaker, rate limiter
│   └── serialization/
│       └── schemas.py            # DTO conversions
├── api/
│   ├── routers/                  # REST endpoints
│   │   ├── health.py             # /health, /metrics, /system/*
│   │   ├── market.py             # Market data queries
│   │   ├── analysis.py           # AMT analysis results
│   │   ├── trading.py            # Portfolio & stats
│   │   ├── ai.py                 # LLM / command processing
│   │   └── rl.py                 # RL training & inference
│   ├── websocket/
│   │   └── gameloop.py           # State stream to frontend
│   ├── dependencies.py           # Service graph factory (singleton)
│   └── main.py                   # FastAPI app + lifespan
└── config.py                     # Settings from .env
```

---

## Key Domain Services

### Fabio AI Services (19 modules in `backend/app/domain/fabio_ai/services/`)

The top 10 by importance:

| Service | File | Purpose |
|---------|------|---------|
| **AMT Analyzer** | `amt_analyzer.py` | Volume Profile, POC, VWAP, acceptance/rejection analysis |
| **Trade Manager** | `trade_manager.py` | Mechanical exit management (SL, TP, trailing, time stops) |
| **Prompt Builder** | `prompt_builder.py` | LLM prompt construction and response parsing (entry + overseer) |
| **Entry Gate** | `entry_gate.py` | Pure quant gates (three_align_check, confirmation_bundle, volatility_filter) |
| **Regime Detector** | `regime_detector.py` | Market regime classification, second-drive detection, squeeze detection |
| **Session Context** | `session_context.py` | Session-aware bias (London=MeanRev, NY=Trend, Asia=selective) |
| **Option Scanner** | `option_scanner.py` | Multi-symbol option scanning and selection |
| **Footprint Analyzer** | `footprint_analyzer.py` | Footprint candle analysis, stacked imbalances |
| **Market Structure Classifier** | `market_structure_classifier.py` | BALANCED/IMBALANCED/TRANSITION classification with bypass confidence |
| **MLX Compute** | `mlx_compute.py` | Optimized math (pure Python for small arrays, MLX GPU for batch) |

Additional services: `cvd_tracker`, `level_tracker`, `oi_analyzer`, `option_selector`, `prediction_engine`, `profile_classifier`, `session_risk_manager`, `learning_engine`, `generative_ai_service`.

### Notification System

- **NotificationPort** (`backend/app/domain/ports/notifications.py`): Abstract interface
- **TelegramAdapter** (`backend/app/infrastructure/adapters/telegram_adapter.py`): Production notifications (if TELEGRAM_BOT_TOKEN set)
- **NullNotificationAdapter** (`backend/app/infrastructure/adapters/null_notification_adapter.py`): Silent fallback

### AsyncPersistenceBus

Background write buffering for SQLite (`backend/app/infrastructure/async_persistence.py`). Implements `StoragePort`, enqueues all writes to a daemon thread so tick processing is never blocked by I/O.

### Serialization Layer

499-line Pydantic DTO module (`backend/app/infrastructure/serialization/schemas.py`) with camelCase aliasing for frontend compatibility. Converts all domain entities to REST/WebSocket-safe JSON.

### Application Services

| Service | File | Purpose |
|---------|------|---------|
| **DailyReporter** | `daily_reporter.py` | End-of-day P&L summaries, wired as asyncio background task |
| **ForwardTestLogger** | `forward_test_logger.py` | Logs signals/exits to `live_trading_logs/forward_*.csv` |
| **SnapshotBuilder** | `snapshot_builder.py` | Builds state snapshots for WebSocket broadcast |
| **BacktestEngine** | `backtest_engine.py` | Historical simulation with walk-forward support |

---

## Clean Architecture in Brokers Module

The `brokers/` directory implements a **port/adapter pattern** with clean architecture:

```
┌─────────────────────────────────────────────────────┐
│            Usage Layer (gateway.py)                 │
│  • BrokerGateway (factory + circuit breaker)       │
│  • ReactiveBroker (RxPY wrapper)                   │
└─────────────────────────┬───────────────────────────┘
                          │ uses
┌─────────────────────────▼───────────────────────────┐
│              IBrokerPort (abstract)                │
│  • get_quote(), stream_ticker(), place_order()     │
│  • get_option_chain(), get_positions()             │
└─────────────────────────┬───────────────────────────┘
                          │ implemented by
          ┌───────────────┼───────────────┐
          ▼               ▼               ▼
┌──────────────┐ ┌──────────────┐ ┌──────────────┐
│ PaperBroker  │ │  DhanBroker  │ │ FutureBroker │
│ (in-memory)  │ │ (production) │ │              │
└──────────────┘ └──────────────┘ └──────────────┘
```

### DhanBroker Internal Structure

```
DhanBroker (Application Layer)
├── Services
│   ├── MarketDataService
│   ├── OrderService
│   ├── PortfolioService
│   ├── OptionsService
│   ├── StreamingService
│   └── HistoricalService
├── Infrastructure Layer
│   ├── HTTPClient (REST API)
│   ├── WebSocketClient (real-time)
│   ├── SymbolMapper (internal → exchange codes)
│   ├── AuthProvider (token management)
│   ├── Resilience (circuit breaker, rate limiter)
│   └── TOTPGenerator (2FA)
├── Domain Layer
│   ├── Entities (Dhan-specific)
│   ├── ValueObjects
│   ├── Constants
│   └── Errors (domain exceptions)
└── Ports (interfaces)
    ├── HTTPPort
    ├── WebSocketPort
    ├── AuthPort
    ├── MapperPort
    └── ResiliencePort
```

### Key Patterns

- **Factory:** `BrokerFactory.create(BrokerType.PAPER)` or `.DHAN`
- **Circuit Breaker:** Wraps all calls, isolates failures
- **Reactive Wrapper:** `ReactiveBroker.paper().ticker_stream(...)` returns `Observable[Tick]`
- **Dependency Injection:** Ports defined in domain, implemented in infrastructure
- **Composition over Inheritance:** `ReactiveBroker` wraps any `IBrokerPort` implementation

---

## AI/ML Pipeline

### LLM (Narrative Reader)

| Aspect | Details |
|--------|---------|
| **Production Model** | Qwen 3.5 (4-bit quantized, 404MB) at `backend/models/glassytrade-qwen-mlx-fused/` |
| **Prior Iteration** | Nanbeige 3B (2.1GB) at `poc3/models/glassytrade-options-fused/` |
| **Research Only** | LFM2-24B-A2B (MoE) in `poc_lfm2/` — experimental, not production |
| **Fine-Tuning** | LoRA/QLoRA (r=8, alpha=16) via Unsloth (r=16 only in poc_lfm2 experimental) |
| **Training Data** | `poc/training_data_fabio.jsonl` (5,000 synthetic ChatML), `poc3/training_data_v2.jsonl` (17,459 real options examples) |
| **Format** | ChatML with 5-line structured output |
| **Inference Backend** | MLX on Apple Silicon (4-bit ≈ 2GB VRAM) |
| **Prompt Structure** | System: AMT methodology + 5-line format constraint<br>User: Market data + indicators<br>Assistant: Market State, Logic, Trigger, Confidence, Key Levels |
| **Temperature** | Entry=0.4, Overseer=0.3, Base=0.3 (deterministic) |
| **Latency** | 200-300ms on MLX, 500ms on CUDA |

### Micro-Agent Pipeline (Fast Path)

Functions in `agent_pipeline.py` (not classes) for low-latency options scalping (<1ms):

1. **RegimeAgent** (rule-based, ~0.05ms): TRENDING/BALANCED/VOLATILE/DEAD -- pure heuristic, no ML
2. **DirectionAgent** (LightGBM via ProbabilityInferencePort, ~0.1ms): P(LONG), P(SHORT) -- the **only** agent using LightGBM
3. **TimingAgent** (rule-based, ~0.1ms): P(better entry next bar) -- upgradeable to LightGBM but currently heuristic
4. **SizingAgent** (Kelly formula, ~0.01ms): Optimal fraction based on edge -- pure math, no ML

The LLM runs only on **regime changes** (every 5-15 minutes) to adjust agent thresholds.

### Reinforcement Learning

| Aspect | Details |
|--------|---------|
| **Algorithm** | PPO (Proximal Policy Optimization) |
| **Observation** | 12-dimensional market state (price, volume, deltas, regime) |
| **Action Space** | 5 discrete: HOLD, LONG, SHORT, EXIT, REDUCE |
| **Reward** | Risk-adjusted P&L with drawdown penalties |
| **Checkpoints** | Every 10k steps in `backend/rl_models/` |
| **Usage** | Optional ensemble with LLM+LightGBM |

### Feature Extraction (42 features)

```python
FEATURE_NAMES = (
    # Price Microstructure (12)
    "close_vs_poc_pct", "close_vs_vah_pct", "close_vs_val_pct",
    "close_vs_vwap_pct", "atr_5", "atr_20", "atr_ratio",
    "bar_range_pct", "body_pct", "upper_wick_ratio",
    "lower_wick_ratio", "close_position_in_range",
    # Order Flow (8)
    "delta_normalized", "cvd_slope", "cvd_divergence_flag",
    "aggression", "volume_vs_ema20", "delta_acceleration",
    "cumulative_delta_3bar", "aggressive_print_imbalance",
    # Volume Profile (6)
    "profile_shape_encoded", "balance_ratio", "va_width_pct",
    "market_state_encoded", "hvn_count", "nearest_lvn_distance_pct",
    # Order Book (6)
    "bid_ask_spread_bps", "book_imbalance_l1", "book_imbalance_l5",
    "bid_depth_total", "ask_depth_total", "book_pressure_ratio",
    # Temporal (4)
    "minutes_since_open", "session_flag", "day_of_week",
    "bars_since_last_displacement",
    # Options-Specific (6)
    "oi_change_pct", "option_type_flag", "underlying_return_5bar",
    "moneyness_pct", "dte_normalized", "oi_volume_ratio",
)
```

---

## WebSocket Gameloop & Frontend Sync

### Backend (TradingEngine)

```python
class TradingEngine:
    async def start(self):
        self._running = True
        self._stream_task = asyncio.create_task(self._stream_with_reconnect())

    async def _stream_with_reconnect(self):
        # Includes auto-reconnect with exponential backoff
        async for tick in self._market_data.stream_ticker(self._active_symbols):
            symbol = tick.instrument.symbol
            candle = self._aggregate_candle(symbol, tick)
            session_state = self._session_service.process_tick(
                symbol=symbol,
                tick=candle,
                order_book=tick.order_book,
            )
            self._latest_states[symbol] = session_state
            self._generation += 1
            async with self._condition:
                self._condition.notify_all()

    async def get_latest_state(self, symbol: str) -> dict:
        return self._latest_states.get(symbol, {})

    async def wait_for_update(self, known_generation: int) -> int:
        async with self._condition:
            await self._condition.wait_for(lambda: self._generation > known_generation)
            return self._generation
```

### Frontend (useServerTradingSystem Hook)

```typescript
export const useServerTradingSystem = (config: ChartConfig) => {
  const [instruments, setInstruments] = useState<Record<string, InstrumentState>>({});
  const [activeSymbol, setActiveSymbol] = useState<string>('');
  const [connected, setConnected] = useState(false);
  const tickBusRef = useRef<EventTarget>(new EventTarget());
  const wsRef = useRef<WebSocket | null>(null);

  // 1. Fetch backend config on mount → get active symbols
  // 2. Initialize instrument states for each symbol
  // 3. Open WebSocket to /api/gameloop?symbols=...
  // 4. Receive state updates, merge into instruments
  // 5. Broadcast high-frequency ticks via tickBus (EventTarget)
  //    → ChartScene subscribes to tickBus for real-time rendering
  // 6. Handle reconnection with exponential backoff
  // 7. Send commands via /api/ai/command

  return {
    instruments,
    activeSymbol,
    setActiveSymbol,
    activeInstrument: instruments[activeSymbol],
    connected,
    connectionStatus,
    tickBus: tickBusRef.current,
  };
};
```

---

## Risk Management

### Portfolio-Level

| Parameter | Value | Purpose |
|-----------|-------|---------|
| **Initial Capital** | ₹1,000,000 | Base equity |
| **Leverage** | 1x | No leverage (LEVERAGE=1 in aggregates.py) |
| **Risk-per-trade** | 1% default, scaled by confidence (0.25%-0.5%) | Position sizing |
| **Commission** | ₹50 round-trip per lot + 0.05% slippage | Transaction costs |

### Session Risk Manager (Cushion System)

Intraday dynamic sizing based on P&L streak:

| Condition | Risk-per-trade |
|-----------|----------------|
| Start of session | 0.25% (conservative) |
| After 2 consecutive wins | 0.40% (momentum) |
| Positive session P&L | 0.35% + 20% of profit (cushion) |
| 2 consecutive losses | DEFENSIVE tier: 0.25% risk (SessionRiskManager) |

**Note:** Actual trading HALT is in **RiskManager** (not SessionRiskManager) at **5 consecutive losses** OR **5% daily drawdown from peak equity**. SessionRiskManager only controls risk tier sizing.

### TradeManager Exits (Mechanical)

| Exit Type | Trigger | Notes |
|-----------|---------|-------|
| **Initial Stop** | ATR × multiplier | Based on entry bar's ATR |
| **Take Profit** | 2R or 3R | Configurable |
| **Partial TP** | 50% at 1R, remainder trails | Reduces risk |
| **Breakeven** | 1R profit OR CVD confirmation (whichever first) | Locks in risk-free |
| **Time Stop** | 4× interval (e.g., 20 min on 5m) | If no progress |
| **Trailing** | Activates at 1R, trails at 0.5R distance | Locks profits |
| **CVD Kill** | Opposite aggression | Immediate exit |
| **VWAP Tighten** | Price reaches VWAP ± 2σ | Reduce SL to 50% distance |

### Circuit Breaker

Global halt triggers:
- 5% daily drawdown from peak equity (RiskManager.MAX_DAILY_DRAWDOWN_PCT)
- 5 consecutive losses (RiskManager.MAX_CONSECUTIVE_LOSSES)
- Exchange outage (WebSocket disconnect)
- Manual `/api/system/halt` endpoint

---

## Persistence & Observability

### Database Schema (SQLite)

```sql
-- Every tick for audit/replay
CREATE TABLE ticks (
    id INTEGER PRIMARY KEY,
    symbol TEXT NOT NULL,
    time TEXT NOT NULL,
    open, high, low, close, volume, delta,
    extra TEXT, created_at TEXT DEFAULT (datetime('now'))
);

-- Closed positions with P&L
CREATE TABLE trades (
    id INTEGER PRIMARY KEY,
    position_id TEXT, symbol, side,
    entry_price, exit_price, size, pnl,
    source, reason, opened_at, closed_at, extra,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Every LLM call for analysis
CREATE TABLE llm_decisions (
    id INTEGER PRIMARY KEY,
    symbol, direction, confidence, rationale,
    input_prompt, raw_output, market_state, aggression,
    price, vah, val, poc, delta, volume, profile_shape,
    extra, created_at TEXT DEFAULT (datetime('now'))
);

-- Periodic equity snapshots
CREATE TABLE performance_snapshots (
    id INTEGER PRIMARY KEY,
    symbol, equity, balance, open_pnl, open_positions,
    total_trades, win_rate, extra,
    created_at TEXT DEFAULT (datetime('now'))
);

-- VP per day for gap analysis
CREATE TABLE session_profiles (
    id INTEGER PRIMARY KEY,
    symbol NOT NULL, market DEFAULT 'NSE', session_date NOT NULL,
    poc, vah, val, profile_shape, total_volume, extra,
    created_at TEXT DEFAULT (datetime('now'))
);

-- Crash recovery
CREATE TABLE open_positions (
    id TEXT PRIMARY KEY,
    symbol NOT NULL, side NOT NULL, entry_price,
    ...  -- full position fields
);
```

### Async Persistence

The `AsyncPersistenceBus` runs a background thread with a queue:

```python
class AsyncPersistenceBus(StoragePort):
    def __init__(self, storage: StoragePort):
        self._storage = storage
        self._queue = queue.Queue()
        self._thread = threading.Thread(target=self._worker, daemon=True)
        self._running = True

    def start(self):
        self._thread.start()

    def save_tick(self, symbol: str, tick_data: dict):
        # Non-blocking: enqueue, returns immediately
        self._queue.put(("tick", symbol, tick_data))

    def _worker(self):
        while self._running:
            try:
                item = self._queue.get(timeout=1.0)
                method, symbol, data = item
                getattr(self._storage, f"save_{method}")(symbol, data)
            except queue.Empty:
                continue
```

### Logging

- **Structured JSON logs** with timestamp, level, component, message, exception
- Output to stdout (Docker/systemd captures)
- Backend log: `backend.log` for debugging
- **Metrics endpoint** `/api/v1/metrics`:
  - Ticks processed, trades executed
  - LLM latency, error rates
  - Memory usage, GC stats

---

## Research & Evolution (poc directories)

The project maintains **parallel research tracks**:

| Track | Purpose | Models | Status |
|-------|---------|--------|--------|
| **poc/** | Initial model training & validation | Nanbeige 3B + LoRA | Baseline |
| **poc3/** | Qwen 3.5 fine-tuning + options data (17,459 examples) | Qwen 3.5 + LoRA (r=8) | Production (fused model deployed) |
| **poc4/** | MLX optimization & 0.8B distillation | Qwen 0.8B (4-bit MLX) | Experimental |
| **poc_lfm2/** | Large MoE model (24B total, 2B active) | LFM2-24B-A2B | Promising, needs more data |

### LFM2-24B-A2B

- **Architecture:** Mixture of Experts (MoE) with 2B active parameters out of 24B
- **Inference Speed:** Comparable to 3B model thanks to sparsity
- **Quality:** Significantly better reasoning than Nanbeige 3B
- **Training:** 2000 LoRA steps on 8000 ChatML examples
- **MLX Conversion:** 4-bit quantized → ~6GB, fast on Apple Silicon

---

## Known Issues & Recommendations

### Critical (P0)

- ❌ **Duplicate Circuit Breaker:** STILL OPEN -- 3 implementations found (`gateway.py`, `dhan/infrastructure/resilience.py`, `RiskManager`). **Unify.**
- ⚠️ **BrokerGateway API duplication:** PARTIALLY FIXED -- wrapper still duplicates some `IBrokerPort` methods.

### High (P1)

- ⚠️ **DhanFacade duplicates methods:** Should extend or delegate to `DhanBroker`.
- ✅ **Hardcoded paths** in Dhan broker config: FIXED -- now uses environment variables.
- ❌ **Order entity missing fields:** STILL OPEN -- `average_trade_price`, `fills`, `commission` still missing.
- ✅ **Transition buffer too conservative:** FIXED -- bypass confidence = 70% (`_BYPASS_CONFIDENCE` in `market_structure_classifier.py`).
- ⚠️ **First-drive vs second-drive:** EntryGate doesn't enforce second-drive entries. LVN touches tracked but not enforced as "must wait for retrace".

### Medium (P2)

- ✅ **Aggressive prints integration:** FIXED -- wired as structural levels with stacked imbalances in entry prompt and grade_score.
- ✅ **Prior session VP:** FIXED -- persistence loads into AMT correctly on new session for gap analysis.
- ⚠️ **CVD kill signals:** May not be fast enough (CVD updates per tick, but exit order routing latency).
- ⚠️ **Volume bubble unification:** PARTIALLY ADDRESSED -- three separate systems (aggressive prints, footprint, accumulator) still exist but better integrated.

### Low (P3)

- 📝 **Overseer context missing:** Session phase, profile shape, OI/PCR, LVN plays, stacked imbalances not all passed to overseer prompt.
- 📝 **VWAP bands for trailing:** Not implemented.
- 📝 **LLM instruction tuning:** Rewrite to frame LLM as AMT reader, not predictor.

---

## Scalability & Performance

### Current Capacity (Single-Symbol, Single-Account)

| Metric | Value |
|--------|-------|
| **Tick processing** | ~5ms per tick (Python, single-threaded) |
| **LLM inference** | 200-300ms on MLX (Apple Silicon) |
| **LightGBM agents** | <1ms |
| **Database writes** | Batched (50 ticks or 5s) → ~20ms overhead |
| **Memory footprint** | ~500MB (Python) + 2GB (MLX model) + SQLite |

### Bottlenecks

1. **Single-threaded tick loop** → Cannot scale to 50+ symbols without sharding.
   - *Solution:* Per-symbol worker threads or async tasks (already per-symbol `TradingSession` but main loop still single).
2. **LLM GPU lock** → Metal GPU not thread-safe, serialized with lock. Acceptable since LLM is only 1-2 Hz.
3. **SQLite write contention** → AsyncPersistenceBus serializes writes. Could upgrade to WAL + connection pool if needed.

### Horizontal Scaling

**Not designed** — would require:
- Shared state via Redis
- Distributed event bus (e.g., NATS, Kafka)
- Sharded symbol assignment
- Load balancer for API tier

Current design is a **single-server monolith**.

---

## Security & Compliance

| Aspect | Implementation |
|--------|----------------|
| **Credentials** | Loaded from `.env` (root and backend/.env). Never in git. |
| **Dhan Token** | `.strip("'")` to handle copy-paste errors. |
| **Rate Limiting** | In-memory 100 req/min per IP (middleware). Not distributed. |
| **Authentication** | None — assumes same-origin frontend or trusted network. Production needs API keys/OAuth. |
| **Data Privacy** | All data stored locally (SQLite). No third-party analytics. |
| **GDPR/Compliance** | Not implemented — user responsible for data handling. |

---

## Testing Strategy

### Current Coverage

| Test Type | Location | Status |
|-----------|----------|--------|
| **Unit tests** | `backend/tests/unit/` | Partial coverage |
| **Integration tests** | `backend/tests/integration/` | Growing |
| **E2E tests** | `test_lfm2_integration.py` | Manual verification |
| **Broker tests** | `brokers_backup/tests/` | Comprehensive (100+ tests) |
| **Backtesting** | `poc3/backtest_agent_pipeline.py` | Offline validation |
| **Benchmarks** | `poc_lfm2/benchmark.py` | Model comparison |

### Missing

- End-to-end test framework with market data replay
- Contract tests for broker APIs
- Load testing for WebSocket scaling
- Chaos engineering (failure injection)

---

## Deployment & Operations

### Local Development

```bash
cd backend
source venv/bin/activate
pip install -r requirements.txt
cp ../.env .env
uvicorn app.main:app --reload

cd ../frontend
npm install
npm run dev  # Vite dev server on :5173
```

### Production (Linux/macOS)

- Run as **systemd service** or **Docker container**
- Requirements: Python 3.11, Node 20+, SQLite on SSD
- **Apple Silicon:** MLX backend (fastest)
- **NVIDIA GPU:** CUDA + bitsandbytes for training; inference CPU fallback OK

### Monitoring

| Endpoint | Purpose |
|----------|---------|
| `/api/health` | Database, LLM, probability engine checks |
| `/api/v1/metrics` | Ticks, trades, LLM latency, errors |
| `/api/debug/memory` | RSS, GC stats, tracemalloc |
| `/api/system/risk-state` | Current risk manager state |
| `/api/system/halt` / `resume` | Emergency kill switch |

---

## Future Roadmap (from Design Specs)

### Batch 1 — Defense (Small, Independent)

- ✅ Breakeven at 1R
- ✅ CVD-based breakeven
- ✅ Session time stops
- ✅ Spread blowout detection
- ✅ LLM instruction + temperature tuning

### Batch 2 — Entry Quality (Depends on Batch 1)

- ✅ VWAP bands for bias filtering
- ✅ VWAP trailing (to be fully implemented)
- ✅ Aggressive prints as structural levels
- ✅ Prior session VP loading

### Batch 3 — Structural (Builds on Batch 2)

- ⏳ Second drive enforcement (+2 grade)
- ⏳ Overseer context enrichment
- ⏳ Volume bubble integration (stacked imbalances)

### Ultimate Goal

Evaluate **LFM2-24B-A2B** (MoE, 2B active params) against current production Qwen 3.5 -- adopt if benchmarks show >20% improvement in win rate/Sharpe.

---

## Conclusion

**GlassyTrade AI v5** is a **sophisticated, production-grade trading system** with:

### Strengths

- ✅ Clean DDD architecture with clear separation of concerns
- ✅ Event-driven core with domain events
- ✅ Multi-layered AI stack (LLM + LightGBM + RL) with fallbacks
- ✅ Robust risk management (portfolio, session, mechanical exits)
- ✅ Persistence for crash recovery and audit
- ✅ Reactive frontend with server-driven state
- ✅ Ongoing research track for model evolution

### Weaknesses

- ❌ Single-threaded tick loop limits symbol count
- ✅ ~~Transition state buffer too conservative~~ FIXED (bypass confidence = 70%)
- ❌ First-drive not distinguished from second-drive
- ✅ ~~Aggressive prints & stacked imbalances not fully integrated~~ FIXED (wired into entry prompt + grade_score)
- ❌ Overseer prompt missing critical context
- ❌ No distributed deployment path

### Overall Grade: **A-**

Very solid architecture with clear research path. The parallel POC directories show active experimentation, and the Fabio review confirms the design philosophy is correct. The next 3-6 months of gap-closing will push this to **A+**.

---

## References

- `README.md` — Project overview and quick start
- `specs/design.md` — 10 prioritized improvements with batch plan
- `specs/requirements.md` — Detailed acceptance criteria for each gap
- `specs/tasks.md` — Implementation task breakdown
- `fabio_system_analysis.md` — Fabio Valentini's original code review
- `brokers/ARCHITECTURE.md` — Brokers module deep dive
- `poc_lfm2/README.md` — LFM2 research track documentation
- `poc4/README.md` — MLX optimization experiments

---

*End of analysis*
