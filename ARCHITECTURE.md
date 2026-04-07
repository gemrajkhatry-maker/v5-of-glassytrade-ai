# GlassyTrade v5 — Architecture Reference

## Table of Contents
1. [System Overview](#1-system-overview)
2. [Layer Diagram (Mermaid)](#2-layer-diagram)
3. [Class Hierarchy & Relationships](#3-class-hierarchy--relationships)
4. [Tick-to-Trade Data Flow](#4-tick-to-trade-data-flow)
5. [WebSocket Pipeline Architecture](#5-websocket-pipeline-architecture)
6. [Service Graph (DI Container)](#6-service-graph-di-container)
7. [TradingEngine — Standalone Core](#7-tradingengine--standalone-core)
8. [Handler Architecture](#8-handler-architecture)
9. [Domain Model](#9-domain-model)
10. [Risk Engine](#10-risk-engine)
11. [Frontend-Backend Integration](#11-frontend-backend-integration)

---

## 1. System Overview

GlassyTrade v5 is a production-grade, event-driven algo-trading system for Indian derivatives markets (NSE & MCX). It implements Fabio Valentini's Auction Market Theory (AMT) methodology with AI-assisted entry decisions.

### Architecture Pattern
- **Ports & Adapters (Hexagonal)**: Domain logic is isolated behind abstract ports; broker, LLM, and storage implementations are swappable adapters.
- **Event-Driven**: `TickReceived` events flow through a pipeline of handlers (AMT → Agent → Gate → LLM → Signal → Execution).
- **Server-Driven Trading**: The backend's `TradingEngine` streams market data, runs the pipeline, and executes trades independently of any frontend connection. The frontend is a read-only viewer.

### Technology Stack
| Layer | Technology |
|-------|-----------|
| Backend Framework | FastAPI + uvicorn |
| Streaming | `websockets` v14+ (asyncio WebSocket) |
| AI/ML Inference | MLX (Apple Silicon GPU) + LoRA fine-tuned Nanbeige 3B/Qwen |
| Probability Engine | LightGBM (first-passage binary classifiers) |
| Storage | SQLite async writes via background thread |
| Frontend | React + Vite + custom WS hooks |
| Broker | Dhan (via `brokers/` library with ports/adapters) |
| Notifications | Telegram (when configured) |

---

## 2. Layer Diagram

```
┌────────────────────────────────────────────────────────────────────────┐
│                           FRONTEND (React)                             │
│                                                                        │
│  useServerTradingSystem ─────────────────────┐                         │
│  ├─ WS /api/trading/ws/gameloop (read-only)  │                         │
│  ├─ Generation-based polling                 │                         │
│  ├─ Delta-compressed updates                  │                         │
│  └─ HTTP /api/system/config                   │                         │
└──────────────────────────────────────────────│─────────────────────────┘
                                               │
                                               ▼
┌────────────────────────────────────────────────────────────────────────┐
│                         BACKEND (FastAPI)                              │
│                                                                        │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │                     API ROUTERS                                  │ │
│  │  /api/health  /api/market  /api/analysis  /api/trading           │ │
│  │  /api/ai  /api/rl  /api/metrics  /api/trading/ws/gameloop       │ │
│  └──────────────────────────┬───────────────────────────────────────┘ │
│                             │                                          │
│  ┌──────────────────────────▼───────────────────────────────────────┐ │
│  │                      ServiceGraph (DI)                            │ │
│  │  ┌────────────┐ ┌─────────────┐ ┌──────────────┐ ┌────────────┐ │ │
│  │  │ DhanAdapter│ │MLX_LLM     │ │SQLiteStorage │ │GBM Engine  │ │ │
│  │  │(MarketData) │ │(Inference) │ │ (Persistence)│ │(Probabilty)│ │ │
│  │  └──────┬─────┘ └──────┬──────┘ └──────┬───────┘ └──────┬─────┘ │ │
│  │         │              │              │                  │        │ │
│  │  ┌──────▼──────────────▼──────────────▼──────────────────▼─────┐ │ │
│  │  │              TradingSessionService (Orchestrator)           │ │ │
│  │  │                                                              │ │ │
│  │  │  ┌────────────┐ ┌──────────┐ ┌──────────┐ ┌──────────┐    │ │ │
│  │  │  │AMTHandler  │ │LLMEntry  │ │Overseer  │ │Lifecycle │    │ │ │
│  │  │  │(analysis)  │ │Handler   │ │Handler   │ │Handler   │    │ │ │
│  │  │  └────────────┘ └──────────┘ └──────────┘ └──────────┘    │ │ │
│  │  │  ┌────────────┐ ┌──────────┐ ┌──────────┐                 │ │ │
│  │  │  │EntryCoord  │ │ExitCoord │ │RiskCoord │                 │ │ │
│  │  │  └────────────┘ └──────────┘ └──────────┘                 │ │ │
│  │  └──────────────────────────────────────────────────────────┘ │ │
│  │                             │                                  │ │
│  │  ┌──────────────────────────▼──────────────────────────────┐   │ │
│  │  │                    TradingEngine                        │   │ │
│  │  │  ┌───────────┐ ┌───────────┐ ┌───────────┐            │   │ │
│  │  │  │StreamMgr  │ │CandleAgg  │ │WatchdogMgr│            │   │ │
│  │  │  └───────────┘ └───────────┘ └───────────┘            │   │ │
│  │  │  ┌─────────────────────────────────────┐               │   │ │
│  │  │  │    _tick_loop() (core event loop)   │               │   │ │
│  │  │  │    session_service.process_tick()   │               │   │ │
│  │  │  └─────────────────────────────────────┘               │   │ │
│  │  └──────────────────────────────────────────────────────────┘ │ │
│  └───────────────────────────────────────────────────────────────┘ │
│                                                                      │
│  ┌──────────────────────────────────────────────────────────────────┐ │
│  │                     BROKERS LIBRARY                              │ │
│  │  ┌──────────────┐  ┌──────────────────┐                         │ │
│  │  │DhanWebSocket │  │StreamingService │                         │ │
│  │  │Client        │  │(persistent WS)  │                         │ │
│  │  │(binary pkt   │  │                 │                         │ │
│  │  │ decoder)     │  │                 │                         │ │
│  │  └──────────────┘  └──────────────────┘                         │ │
│  └──────────────────────────────────────────────────────────────────┘ │
└────────────────────────────────────────────────────────────────────────┘
```

---

## 3. Class Hierarchy & Relationships

### 3.1 Abstract Port Definitions

```
┌─────────────────────────────────────────────────────────┐
│                    PORTS (Abstract Interfaces)           │
├─────────────────────────────────────────────────────────┤
│  MarketDataPort           — fetch OHLCV, live streams   │
│  BrokerPort               — order execution, balances   │
│  LLMInferencePort         — text generation inference   │
│  StoragePort              — persistence + KV store      │
│  OpenPositionStoragePort  — open position lifecycle     │
│  ProbabilityInferencePort — LightGBM probability output │
│  NotificationPort         — Telegram/messages           │
│  IWebSocketClient         — WS connect/subscribe/msgs   │
│  IEventBus                — event publish/subscribe     │
└─────────────────────────────────────────────────────────┘
```

### 3.2 Concrete Adapters

```
┌─────────────────────────────────────────────────────────┐
│              CONCRETE ADAPTERS                          │
├─────────────────────────────────────────────────────────┤
│  MarketDataPort ←─ DhanMarketDataAdapter                │
│    └─ Uses DhanBroker → StreamingService.persistent WS  │
│    └─ Instrument cache + option chain + historical      │
│                                                             │
│  BrokerPort ←─ PaperBrokerAdapter                       │
│    └─ Simulated execution with slippage + commissions   │
│                                                             │
│  LLMInferencePort ←─ MLXInferenceAdapter                │
│    └─ MLX + LoRA fine-tuned model (Nanbeige 3B)         │
│    └─ ChatML format + response prefill                  │
│    └─ ThreadPoolExecutor + timeout guard               │
│                                                             │
│  IWebSocketClient ←─ DhanWebSocketClient                │
│    └─ Binary packet decoder (rc=2,4,5,6,8)             │
│    └─ Auto-reconnect (exponential backoff, max 30)     │
│    └─ Auth URL: ?version=2&token=...&clientId=...       │
└─────────────────────────────────────────────────────────┘
```

### 3.3 Key Application Classes

```
TradingEngine (lifespan-started, runs independently of frontend WS)
├── stream_manager: StreamManager (dual WS: full + depth)
├── candle_aggregator: CandleAggregator (tick → OHLCV conversion)
├── range_bar_builders: dict[str, RangeBarBuilder]
├── watchdog_manager: WatchdogManager (health monitors, GC loop)
├── circuit_breakers: dict[str, PerEntityCircuitBreaker]
├── _latest_states: dict[str, dict] (cached for frontend WS)
├── _generation: int (incremented on each new state snapshot)
├── _condition: asyncio.Condition (viewer notification)
│
│── Core Loop:
│    _tick_loop()  ← runs in asyncio task
│    1. Receives tick packets from StreamManager
│    2. Validates (NaN check, market open check)
│    3. Updates OI tracking + depth book + footprint
│    4. Aggregates into OHLC candle
│    5. Calls session_service.process_tick() via asyncio.to_thread()
│    6. Updates _latest_states + increments _generation
│    7. Notifies all frontend viewers via asyncio.Condition

TradingSessionService (central orchestrator for one tick → decision)
├── _state_manager: SessionStateManager (per-symbol session state)
├── _risk_coordinator: SessionRiskCoordinator
├── _amt_handlers: dict[str, AMTHandler]  (per-symbol)
├── _lifecycle_handler: TradeLifecycleHandler
├── _llm_handler: LLMEntryHandler (per-symbol worker threads)
├── _overseer_handler: LLMOverseerHandler
├── _exit_coordinator: ExitCoordinator
├── _entry_coordinator: EntryCoordinator
├── _probability_engine: LGBMProbabilityAdapter
│
│── Pipeline (per tick):
│    1. Drain pending LLM signal from worker
│    2. Append tick to session.data (cap at 2000 candles)
│    3. portfolio.process_tick() → check SL/TP
│    4. Run LightGBM agent decision
│    5. AMT analysis (Volume Profile, CVD, Aggression, Imbalance)
│    6. Overseer (if positions open)
│    7. Gate pipeline → build_entry_signal → execute
│    8. LLM trigger (if no position + 30s cooldown + model ready)

SessionState (per-symbol mutable state)
├── data: list[OHLC] (session candles, max 2000)
├── order_book: dict (5-level depth)
├── portfolio: TradingPortfolio
├── _pending_signal: Signal | None (from LLM worker)
├── _executed_signal_ids: set (deduplication)
├── learning: LearningEngine

TradingPortfolio (per symbol)
├── positions: dict[str, ManagedPosition]
├── cash: float
├── balance: float
├── initial_cash: float
│
│── Methods:
│    add_position(signal, max_pos)   → ManagedPosition
│    process_tick(tick)               → list[Position] (closed)
│    close_position(symbol, price, qty)
│    recover_position(position)
```

### 3.4 Broker Layer Architecture

```
┌─────────────────────────────────────────────────────────────────┐
│                    brokers/broker/dhan/                          │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  ┌─────────────────────────────────────────────────────────┐    │
│  │                DhanBroker (Factory)                      │    │
│  │  create(client_id, access_token, config) → instance      │    │
│  │  ├─ get_option_chain()                                   │    │
│  │  ├─ get_instrument_by_symbol()                           │    │
│  │  ├─ place_order(), cancel_order(), get_orders()          │    │
│  │  ├─ get_balance(), get_positions(), get_holdings()       │    │
│  │  └─ ensure_initialized()  ← loads instrument cache      │    │
│  └────────────────────────┬─────────────────────────────────┘    │
│                           │                                       │
│  ┌────────────────────────▼─────────────────────────────────┐    │
│  │            StreamingService (Persistent WS)               │    │
│  │  ┌───────────────────────────────────────────────────┐   │    │
│  │  │  _persistent_ws: DhanWebSocketClient (shared)     │   │    │
│  │  │  _persistent_depth_ws: DepthWebSocketClient       │   │    │
│  │  └───────────────────────────────────────────────────┘   │    │
│  │                                                            │    │
│  │  stream_full(instruments) → AsyncIterator[FullPacket]     │    │
│  │  stream_depth_20(instruments) → AsyncIterator[Depth]      │    │
│  │  stream_quotes(instruments) → AsyncIterator[QuotePacket]  │    │
│  │  disconnect_persistent()  → shutdown all persistent WS    │    │
│  └─────────────────────────────────────────────────────────┘    │
│                           │                                       │
│  ┌────────────────────────▼────────────────────────────────┐    │
│  │             DhanWebSocketClient                          │    │
│  │                                                          │    │
│  │  URL: wss://api-feed.dhan.co?key=val                    │    │
│  │                                                          │    │
│  │  ┌──────────────────────────────────────────────────┐   │    │
│  │  │                connect()                          │   │    │
│  │  │  ├─ ws = websockets.connect(auth_url)             │   │    │
│  │  │  ├─ receive_task = create_task(_receive_loop())   │   │    │
│  │  │  └─ Replay subscriptions if reconnecting          │   │    │
│  │  └──────────────────────────────────────────────────┘   │    │
│  │                                                          │    │
│  │  ┌──────────────────────────────────────────────────┐   │    │
│  │  │                _receive_loop()                    │   │    │
│  │  │  pkt_count = 0                                   │   │    │
│  │  │  while connected:                                │   │    │
│  │  │    raw = ws.recv()  ← blocks until data arrives  │   │    │
│  │  │    pkt_count += 1                                │   │    │
│  │  │    for chunk in _split_raw(raw):                 │    │    │
│  │  │      msg = _parse_message(chunk)                 │    │   │
│  │  │      _message_queue.put_nowait(msg)              │    │   │
│  │  │  except ConnectionClosed:                        │    │   │
│  │  │    _attempt_reconnect()                           │    │   │
│  │  └──────────────────────────────────────────────────┘   │    │
│  │                                                          │    │
│  │  ┌──────────────────────────────────────────────────┐   │    │
│  │  │              messages() iterator                  │    │   │
│  │  │  while True:                                      │   │    │
│  │  │    msg = await queue.get(timeout=1.0)            │    │   │
│  │  │    yield msg                                     │    │   │
│  │  └──────────────────────────────────────────────────┘   │    │
│  │                                                          │    │
│  │  ┌──────────────────────────────────────────────────┐   │    │
│  │  │           _decode_binary()                        │    │   │
│  │  │                                                   │    │   │
│  │  │  Header (8 bytes, LE):                            │    │   │
│  │  │    [0]   ResponseCode     uint8                   │    │   │
│  │  │    [1]   ExchangeSegment  uint8                   │    │   │
│  │  │    [2:4] Sub-exchange/    uint16                  │    │   │
│  │  │    [4:8] SecurityId       uint32                  │    │   │
│  │  │                                                   │    │   │
│  │  │  rc=2  → Ticker   (16B):  LTP, LastTradeTime     │    │   │
│  │  │  rc=4  → Quote    (50B):  LTP,LTQ,LTT,ATP,Vol.. │    │   │
│  │  │  rc=5  → OI       (12B):  OI                     │    │   │
│  │  │  rc=6  → PrevClose(16B):  PrevClose, PrevOI      │    │   │
│  │  │  rc=8  → Full    (162B): Quote+OI+5-level-depth │    │   │
│  │  │  rc=50 → Disconnect(10B):  ReasonCode            │    │   │
│  │  └──────────────────────────────────────────────────┘   │    │
│  └─────────────────────────────────────────────────────────┘    │
└─────────────────────────────────────────────────────────────────┘
```

### 3.5 Depth WebSocket Client

```
┌─────────────────────────────────────────────────────────────────┐
│                  DepthWebSocketClient                           │
│                  (subclass/related to DhanWebSocketClient)       │
│                                                                  │
│  URLs:                                                          │
│    20-level depth:  wss://depth-api-feed.dhan.co/twentydepth    │
│    200-level depth: wss://full-depth-api.dhan.co/twohundreddepth│
│                                                                  │
│  Auth URL (DIFFERENT from regular feed):                         │
│    ?token=...&clientId=...&authType=2  (no version=2)            │
│                                                                  │
│  Subscription:  RequestCode=23 (DEPTH_REQUEST_CODE)             │
│  Unsubscribe:   RequestCode=12 (DEPTH_UNSUBSCRIBE_CODE)         │
│                                                                  │
│  Binary packets:                                                │
│    12-byte header per sub-packet                                │
│    rc=41 → Bid side                                             │
│    rc=51 → Ask side                                             │
│    rc=50 → Disconnect                                           │
│                                                                  │
│  _split_raw() overrides base to split multi-packet frames       │
└─────────────────────────────────────────────────────────────────┘
```

---

## 4. Tick-to-Trade Data Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                         EXTERNAL                                 │
│                                                                  │
│  Dhan WebSocket Feed ─────>  NSE/MCX Market Data               │
│  wss://api-feed.dhan.co                                        │
│  ┌─────────────────────────────────────────────┐                │
│  │  Instruments: [54761, 54763, 54764]         │                │
│  │  Feed Type: 17 (Quote: LTP+OHLC+Vol+OI)     │                │
│  │  Depth Feed: 20 (Level 20 on separate server)│               │
│  └─────────────────────────────────────────────┘                │
└────────────────────────────┬────────────────────────────────────┘
                             │ raw binary packets
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 1: Binary Packet Decoding (DhanWebSocketClient)          │
│                                                                  │
│  raw bytes → struct.unpack() → Typed WSMessage                  │
│  Example Quote (50B) → {security_id, ltp, volume, ohlc, ...}    │
└────────────────────────────┬────────────────────────────────────┘
                             │ WSMessage (queue)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 2: StreamingService.persistent WS (subscription loop)     │
│                                                                  │
│  Single WebSocket connection survives multiple subscriptions    │
│  stream_full(instruments) yields FullPacket objects             │
│  No new connections per call → no rate limit exposure           │
└────────────────────────────┬────────────────────────────────────┘
                             │ FullPacket
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 3: StreamManager (reconnection, dual-stream merge)        │
│                                                                  │
│  stream_with_reconnect() → handles:                             │
│    ├─ Depth 20 WS (NSE only, separate connection)               │
│    ├─ Primary full feed WS                                     │
│    ├─ Exponential backoff reconnect (max 10 retries)            │
│    ├─ REST polling fallback if WS dead >60s                    │
│    └─ Merges depth data into full packets on-the-fly            │
└────────────────────────────┬────────────────────────────────────┘
                             │ tick dict/FullPacket
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 4: TradingEngine._tick_loop()                            │
│                                                                  │
│  For each received tick packet:                                 │
│    1. Market open check (is_market_open)                       │
│    2. Circuit breaker check (per symbol)                        │
│    3. LTP validation (no NaN/inf, LTP > 0)                     │
│    4. OI change detection                                      │
│    5. Order book (depth) update                                │
│    6. Footprint accumulation                                   │
│    7. CandleAggregator.aggregate() → tick → OHLCV candle       │
│    8. Throttle: max process_tick once per 500ms                │
│    9. Dual feed: underlying futures for AMT analysis            │
│   10. session_service.process_tick(symbol, tick, depth, ...)    │
│   11. Range bar builder (ATR-based visualization)               │
│   12. _latest_states update + generation bump                   │
└────────────────────────────┬────────────────────────────────────┘
                             │ (process_tick returns state snapshot)
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 5: TradingSessionService.process_tick()                   │
│                                                                  │
│  Thread: asyncio.to_thread() → runs on ThreadPoolExecutor       │
│                                                                  │
│  1. Get/create SessionStateManager.get_or_create_session()     │
│  2. Drain pending LLM signal, validate & execute if valid       │
│  3. Append tick to session.data (cap 2000)                     │
│  4. Portfolio.process_tick() → check SL/TP → close positions   │
│  5. For each closed position:                                   │
│     ├─ ExitCoordinator.on_position_closed()                     │
│     ├─ PostTradeAnalyst.fire() (async)                          │
│     └─ storage.save_trade()                                     │
│  6. Build TickReceived event → dispatch to _on_tick()          │
└────────────────────────────┬────────────────────────────────────┘
                             │
                             ▼
┌─────────────────────────────────────────────────────────────────┐
│  Step 6: _on_tick(event) — Full Decision Pipeline              │
│                                                                  │
│  ┌────────────────────┐                                         │
│  │  6.1 Agent Decision │                                      │
│  │  run_micro_agent_pipeline()  → LightGBM models             │
│  │  Output: direction, probability, regime, timing, kelly_size │
│  └────────┬───────────┘                                         │
│           ▼                                                     │
│  ┌────────────────────┐                                         │
│  │  6.2 Session Phase  │                                       │
│  │  Force exit at Phase 5 (15:15-15:30 IST)                    │
│  └────────┬───────────┘                                         │
│           ▼                                                     │
│  ┌────────────────────────┐                                     │
│  │  6.3 AMT Analysis      │                                     │
│  │  AMTHandler.analyze(data, order_book, ...)                  │
│  │  Returns: amt_result, amt_dto, fp_dto                        │
│  │  Computes: Volume Profile, CVD slope+div, Aggression σ,     │
│  │            Imbalance analysis, Market state, Profile shape  │
│  └────────┬───────────────┘                                     │
│           ▼                                                     │
│  ┌───────────────────────────┐                                  │
│  │  6.4 Overseer (positions) │                                  │
│  │  LLMOverseerHandler.run_overseer()                          │
│  │  Output: HOLD / TIGHTEN_SL / PARTIAL_EXIT / FULL_EXIT / ADD │
│  │  Probability override: P(adverse)>0.80 → force exit         │
│  └───┬───────────────────────┘                                 │
│       ▼                                                        │
│  ┌──────────────────────────┐                                   │
│  │  6.5 Entry Gate Pipeline │                                  │
│  │  if run_entry + 60s cooldown:                               │
│  │    ├─ SessionRiskManager.can_trade? (3-loss breaker)       │
│  │    ├─ run_gate_pipeline() (VWAP, CVD, displacement,         │
│  │    │   profile shape, structure, distance-to-level)         │
│  │    ├─ Check momentum fade                                     │
│  │    ├─ Confirmation bundle (2/3: Volume+Delta+Spread)        │
│  │    └─ build_entry_signal() → Signal object                  │
│  │                                                               │
│  │  If gate passed → _execute_signal():                         │
│  │    ├─ EntryCoordinator.execute_signal()                      │
│  │    │   ├─ Confluence grade score ≥ 1                         │
│  │    │   ├─ Risk validation                                   │
│  │    │   ├─ Option selection enrichment                        │
│  │    │   ├─ broker.execute_order()                             │
│  │    │   ├─ lifecycle.register_position()                      │
│  │    │   └─ storage.save_trade()                               │
│  │    └─ SignalTrackingService.persist_gate_decision()         │
│  └───┬──────────────────────┘                                  │
│       ▼                                                        │
│  ┌─────────────────────────┐                                   │
│  │  6.6 LLM Trigger        │                                  │
│  │  if _should_trigger_llm(): (30s cooldown, ready model)      │
│  │    LLMEntryHandler.run_entry() → queue to worker thread    │
│  └───┬─────────────────────┘                                   │
│       ▼                                                        │
│  ┌──────────────────────────┐                                  │
│  │  6.7 Pre-Candle Advisor  │                                  │
│  │  Fire at T-60s (bar_minute==4) before 5m bar close          │
│  │  12s timeout, debounced 250s                                │
│  │  Pushes to React dashboard via callback                     │
│  └──────────────────────────┘                                  │
└─────────────────────────────────────────────────────────────────┘
```

---

## 5. WebSocket Pipeline Architecture

### 5.1 Connection Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                     Dhan External Servers                        │
│                                                                   │
│  ┌──────────────────────┐  ┌──────────────────────────┐        │
│  │  Primary Feed Server │  │  Depth Server (20-level) │        │
│  │  wss://api-feed.dhan.co │  wss://depth-api-feed.dhan.co  │  │
│  │  Auth: ?version=2&   │  │  Auth: ?token=...&       │        │
│  │  token=...&clientId  │  │  clientId=...&authType=2 │        │
│  │  =...&authType=2     │  │  (no version=2)          │        │
│  └──────────────────────┘  └──────────────────────────┘        │
│                                                                   │
│  ┌──────────────────────────────────────────────────┐           │
│  │  Full Depth Server (200-level, single instrument)│           │
│  │  wss://full-depth-api.dhan.co/twohundreddepth    │           │
│  └──────────────────────────────────────────────────┘           │
└────────────────────────────┬─────────────────────────────────────┘
                             │
      ┌──────────────────────┼──────────────────────┐
      ▼                      ▼                      ▼
┌───────────┐  ┌────────────────────┐  ┌──────────────┐
│ Persistent│  │ Persistent Depth   │  │ Depth 200    │
│ WS (rc=17)│  │ WS (rc=20/23)      │  │ WS           │
│           │  │                    │  │              │
│ DhanWS    │  │ DepthWSClient      │  │ DepthWSClient│
│ Client    │  │                    │  │              │
│           │  │ Sub: RequestCode=23│  │ Separate     │
│ 1 conn   │  │ Sub: 1 instrument   │  │ server       │
│ multiple │  │                     │  │              │
│ symbols  │  │                     │  │              │
└─────┬─────┘  └──────────┬─────────┘  └──────────────┘
      │                   │
      ▼                   ▼
┌─────────────────────────────────────────────┐
│         StreamingService                    │
│  stream_full()  stream_depth_20()           │
│  ┌───────────────────────────────────────┐ │
│  │ No new connections per call!          │ │
│  │ Dynamic subscribe/unsubscribe on      │ │
│  │ same persistent WS connection         │ │
│  └───────────────────────────────────────┘ │
└──────────────────┬──────────────────────────┘
                   ▼
┌──────────────────────────────────────────────┐
│         StreamManager                        │
│  stream_with_reconnect()                     │
│  ├─ Dual stream: full + depth merge          │
│  ├─ 60s zero-tick timeout → REST fallback    │
│  ├─ Exponential backoff (max 10 retries)     │
│  └─ Yields { "_stream_dead": True }          │
│     if all retries exhausted                  │
└──────────────────┬───────────────────────────┘
                   ▼
┌──────────────────────────────────────────────┐
│         TradingEngine._tick_loop()           │
│  Receives tick dicts/FullPacket objects      │
│  Processes into the trading pipeline          │
└──────────────────────────────────────────────┘
```

### 5.2 WebSocket Binary Protocol Detail

```
┌─────────────────────────────────────────────────┐
│  HEADER (8 bytes, Little Endian)               │
│  ═════════════════════════════════════════════  │
│  Offset  Size  Field            Type            │
│  ─────────────────────────────────────────────  │
│  0       1     ResponseCode     uint8           │
│  1       1     ExchangeSegment  uint8           │
│  2       2     Sub-exchange/    uint16          │
│                  reserved                      │
│  4       4     SecurityId       uint32          │
└─────────────────────────────────────────────────┘

Response Codes (RC):
  2  → Ticker (16 bytes total including header)
  4  → Quote  (50 bytes total)
  5  → OI     (12 bytes total)
  6  → PrevClose (16 bytes total)
  8  → Full/Depth (162 bytes total)
  50 → Disconnect (10 bytes total)

Exchange Segment Codes:
  1  → NSE_EQ   2  → NSE_FNO   3  → NSE_CURRENCY
  4  → BSE_EQ   5  → BSE_FNO   6  → BSE_CURRENCY
  7  → MCX_COMM 13 → MCX_FNO   16 → IDX_I

Quote Packet (50B) Layout:
  Header: 8B (above)
  Offset 8:   LTP              float32
  Offset 12:  LTQ              uint16
  Offset 14:  LastTradeTime    uint32
  Offset 18:  ATP (VWAP)       float32
  Offset 22:  Volume           uint32
  Offset 26:  TotalSellQty     uint32
  Offset 30:  TotalBuyQty      uint32
  Offset 34:  Open             float32
  Offset 38:  Close            float32
  Offset 42:  High             float32
  Offset 46:  Low              float32

Full Packet (162B) = Quote + OI + Depth:
  Quote fields (50B)
  Offset 58:  OI               uint32
  Offset 62:  HighOI           uint32
  Offset 66:  LowOI            uint32
  Offset 70:  5× Depth Levels  (18 bytes × 5 = 90 bytes)

Depth Level (18 bytes each):
  bid_qty(4) + ask_qty(4) + bid_orders(2) + ask_orders(2)
  + bid_price(4) + ask_price(4)

Full Packet Total: 8 + 162 = 170 bytes

Subscription JSON Message:
  {
    "RequestCode": 17,          // Feed type: 15=Ticker, 17=Quote, 20=Depth20
    "InstrumentCount": 3,
    "InstrumentList": [
      {"SecurityId": "54761", "ExchangeSegment": "NSE_FNO"},
      {"SecurityId": "54763", "ExchangeSegment": "NSE_FNO"},
      {"SecurityId": "54764", "ExchangeSegment": "NSE_FNO"}
    ]
  }
```

### 5.3 Subscription Loop Pattern

```
Persistent WS Connection Lifecycle:

  ┌─────────────────────────────────────────┐
  │  _get_persistent_ws(instruments)        │
  │                                          │
  │  lock(ws_lock):                         │
  │    if ws and ws.connected:              │
  │      return ws  ← reuse existing        │
  │    ws = make_ws_client()                │
  │    await ws.connect()                    │
  │    receive_task = create_task(loop())   │
  │    persistent_ws = ws                   │
  │    return ws                            │
  └────────────────┬────────────────────────┘
                   ▼
  ┌─────────────────────────────────────────┐
  │  stream_full(instruments)               │
  │                                          │
  │  ws = await _get_persistent_ws()        │
  │  await ws.subscribe(ids, feed, segs)    │
  │  try:                                   │
  │    async for msg in ws.messages():      │
  │      yield FullPacket(msg)              │
  │  except CancelledError: raise           │
  │  except Exception:                      │
  │    lock(ws_lock):                       │
  │      persistent_ws = None  ← invalidate  │
  └────────────────┬────────────────────────┘
                   ▼
  ┌─────────────────────────────────────────┐
  │  _receive_loop() (background task)      │
  │                                          │
  │  pkt_count = 0                          │
  │  while is_connected and ws:             │
  │    raw = await ws.recv()                │
  │    pkt_count += 1                       │
  │    for chunk in _split_raw(raw):        │
  │      msg = _parse_message(chunk)        │
  │      queue.put_nowait(msg)              │
  │  except ConnectionClosed:               │
  │    _attempt_reconnect()  ← exponential  │
  │  except CancelledError: break           │
  └─────────────────────────────────────────┘

Key: ONE WebSocket connection per feed type.
     Dynamic subscribe/unsubscribe on same connection.
     NO new connections per call → avoids rate limits.
```

---

## 6. Service Graph (DI Container)

### 6.1 Creation Order

```
get_service_graph()  →  @lru_cache → singleton per process

  1. ExchangeConfig       ← get_exchange_config(exchange)
  2. SymbolRegistry       ← SymbolRegistry()
  3. ExchangeStrategy     ← MCXExchangeStrategy or NSEExchangeStrategy
  4. SessionContextFactory ← SessionContextFactory(exchange_config)

  5. DhanMarketDataAdapter (implements MarketDataPort)
     └─ Uses DhanBroker.create(client_id, access_token)

  6. PaperBrokerAdapter (implements BrokerPort)
     └─ DRY_RUN: Simulated execution with slippage + commission

  7. MLXInferenceAdapter (implements LLMInferencePort)
     └─ MLX model + LoRA fine-tuned weights
     └─ Config: MLX_MODEL_PATH (fused model, ~2.1GB)

  8. GenerativeAIService
     └─ Wraps LLM adapter with instruction templates

  9. SQLiteStorageAdapter → AsyncPersistenceBus
     └─ Async wrapper over SQLite via background thread
     └─ Implements: StoragePort + OpenPositionStoragePort

  10. LGBMProbabilityAdapter (implements ProbabilityInferencePort)
      └─ fp_long.txt, fp_short.txt (LightGBM models)

  11. CompositeProfile, AlertManager, DeltaProfileAdapter,
      VPContractSelector, OIAnalyzer

  12. TradingSessionService(service_graph)
      └─ Wires all handlers, coordinators, coordinators

  13. GateRejectionTracker, LatencyTracker
  14. SignalTrackingService
  15. OptionScannerService → scans for top N contracts
  16. VPContractSelector → volume-profile based contract choice
  17. active_symbols ← scanner results or DEFAULT_SYMBOL
  18. engine = None (set later by TradingEngine.start())
```

### 6.2 ServiceGraph Attributes

```python
class ServiceGraph:
    exchange_config: ExchangeConfig
    exchange_strategy: ExchangeStrategy
    symbol_registry: SymbolRegistry
    session_factory: SessionContextFactory
    market_data: DhanMarketDataAdapter      # MarketDataPort
    broker: PaperBrokerAdapter              # BrokerPort
    llm_inference: MLXInferenceAdapter      # LLMInferencePort
    gen_ai_service: GenerativeAIService
    storage: AsyncPersistenceBus            # StoragePort + OpenPositionStoragePort
    probability_engine: LGBMProbabilityAdapter  # ProbabilityInferencePort
    trading_session: TradingSessionService
    engine: TradingEngine | None
    active_symbols: list[str]
    rejection_tracker: GateRejectionTracker
    latency_tracker: LatencyTracker
    signal_tracking: SignalTrackingService
    vp_contract_selector: VPContractSelector
    option_scanner: OptionScannerService
```

---

## 7. TradingEngine — Standalone Core

### 7.1 Lifecycle

```
lifespan(app):
  graph = get_service_graph()           # Create DI container
  llm = graph.llm_inference
  llm.wait_until_ready(timeout=120)     # Block until MLX model loaded
  llm.validate()                         # Test inference
  engine = TradingEngine(graph)
  graph.engine = engine
  await engine.start()
  yield                                  # Server accepts connections
  # === Shutdown ===
  await engine.stop()
  storage._flush_ticks()                # Persist pending ticks
  handler.cleanup()                     # Kill thread pools
```

### 7.2 Engine.start()

```python
async def start():
    # 1. Seed historical data
    for symbol in active_symbols:
        candles = await market_data.fetch_history(symbol, interval="5m")
        candle_builder.ingest_historical(candles)

    # 2. Recover open positions from DB
    _recover_open_positions()

    # 3. Start streaming task
    asyncio.create_task(_tick_loop())

    # 4. Start watchdog tasks
    asyncio.create_task(sl_watchdog_loop())
    asyncio.create_task(stale_stream_detector())
    asyncio.create_task(gc_loop())
```

### 7.3 Engine._tick_loop() — Core Event Loop

```python
async def _tick_loop():
    async for tick_packet in stream_manager.stream_with_reconnect():
        async with _generation_lock:
            symbol = tick_packet.symbol
            tick = tick_packet.tick

            # Validate
            if not is_market_open(): continue
            if circuit_breaker.is_open(symbol): continue
            if tick.ltp <= 0 or math.isnan(tick.ltp): continue

            # Track OI changes
            _update_oi_tracking(symbol, tick)

            # Update depth (order book)
            _update_depth(symbol, tick)

            # Update footprint accumulator
            _update_footprint(symbol, tick)

            # Tick → OHLCV candle aggregation
            candle = candle_aggregator.aggregate(symbol, tick)
            if candle and candle.closed:
                # Closed candle → save to DB
                storage.save_candle(symbol, candle)

            # Throttle: max once per 500ms per symbol
            now = time.monotonic()
            if now - _last_process_times.get(symbol, 0)  bool    │
   │  current_pnl(price) -> float                  │
   │  r_multiple(price) -> float                   │
   └──────────────────────────────────────────────┘
```

### 9.2 Signal Object

```
Signal (dataclass):
  symbol: str
  direction: str ("LONG"/"SHORT"/"FLAT"/"NO_TRADE")
  entry_price: float
  stop_loss: float
  take_profit: float
  quantity: int
  confidence: str ("High"/"Medium"/"Low")
  confluence_score: float
  setup_type: str
  trade_thesis: str
  grade_score: float
  conviction_multiplier: float
  session_risk_pct: float
  id: str  (UUID)
  created_at: datetime
```

### 9.3 Session Phases (NSE)

```
Phase 1: 09:15-10:00  — Opening Balance
Phase 2: 10:00-12:00  — Early Exploration
Phase 3: 12:00-14:00  — European Open / Continuation
Phase 4: 14:00-15:15  — Late Day / Trend continuation
Phase 5: 15:15-15:30  — Settlement (force exit all)
```

---

## 10. Risk Engine

### 10.1 Three-Layer Risk Architecture

```
┌─────────────────────────────────────────────────────────────┐
│  Layer 1: Signal Validation (Pre-Entry)                     │
│  ├─ Confluence grade score ≥ 1                              │
│  └─ Trade thesis must be non-empty                          │
│                                                              │
│  Layer 2: Session Risk Manager                              │
│  ├─ 3-loss circuit breaker (can_trade?)                     │
│  ├─ Daily loss limit check                                  │
│  └─ Consecutive loss tracking                              │
│                                                              │
│  Layer 3: RiskManager + RiskTierEngine                      │
│  ├─ Position sizing validation                              │
│  ├─ Exposure limits                                         │
│  ├─ Max drawdown check                                      │
│  ├─ Risk tier assignment (AGGRESSIVE/BALANCED/CAUTIOUS/     │
│  │   DEFENSIVE/STOPPED)                                     │
│  └─ Global emergency halt/resume                            │
└─────────────────────────────────────────────────────────────┘

Cushion System (SessionRiskManager):

  0 losses  → TIER_NORMAL:     Full position sizing
  1 loss    → TIER_WARNING:    Reduced sizing, heightened monitoring
  2 losses  → TIER_COOLDOWN:   Cooldown period, minimal risk
  3+ losses → TIER_CIRCUIT_BREAKER:  ALL TRADING HALTED

Risk Tiers (RiskTierEngine):
  AGGRESSIVE   — Green: PnL positive, WR > 55%, cushion > 5R
  BALANCED     — Blue: Stable, acceptable drawdown
  CAUTIOUS     — Yellow: Elevated risk, reduced sizing
  DEFENSIVE    — Orange: Near max DD, minimal exposure
  STOPPED      — Red: Circuit breaker triggered, halt all
```

### 10.2 Position Sizing

```
Position Sizer (PositionSizer.calculate()):
  1. Base risk = account_balance × (risk_pct / 100)
  2. SL per unit = |entry_price - stop_loss|
  3. Raw quantity = base_risk / SL_per_unit
  4. Apply conviction_multiplier
  5. Apply option_lot_size rounding (floor to nearest lot)
  6. Enforce max_position_value cap
  7. Enforce max_loss_cap (max ₹ loss per trade)
```

---

## 11. Frontend-Backend Integration

### 11.1 WebSocket Game Loop

```
Frontend: useServerTradingSystem.ts
  │
  ├─ Auto-detects server-driven mode via GET /api/system/config
  │  → serverDriven: true  (backend has its own WS + Dhan feed)
  │  → serverDriven: false (frontend must push ticks manually)
  │
  ├─ Server-driven mode:
  │    1. Connects WS to /api/trading/ws/gameloop
  │    2. Sends: {"subscribe": "<symbol>"}
  │    3. Receives: generation-based state updates
  │
  │    Viewer Loop:
  │      a. Initial sync: full state dump for all symbols
  │      b. Wait for engine.wait_for_update(known_generation)
  │      c. When generation advances:
  │         - Compute delta (compare known_state vs latest_state)
  │         - Send only changed fields (delta compression)
  │         - Keyframe (full sync) every 30 seconds
  │      d. Never mutates trading state — read-only

Backend: gameloop.py
  │
  async def _viewer_loop(ws, graph, symbol):
      # Initial sync
      config = get_system_config()
      history = engine.get_history(symbol)
      snapshots = engine.get_all_latest_states()
      await send_full(ws, config, history, snapshots)

      while True:
          known_gen = await engine.wait_for_update(known_gen, timeout=30)
          delta = compute_delta(known_state, engine.get_latest_state())
          await send_delta(ws, delta)

          if time.time() - keyframe_time > 30:
              await send_full(ws, ...)  # Keyframe every 30s
              keyframe_time = time.time()
```

### 11.2 REST API Endpoints

```
GET  /api/health              — Health check + model status
GET  /api/system/config       — Server-driven mode flag, scanner config
POST /api/market/data         — Historical OHLCV data
POST /api/analysis/amt        — AMT analysis on demand
POST /api/trading/signal      — Manual signal request
POST /api/ai/command          — Keyword-based chart config commands
POST /api/rl/train            — RL training coordination
GET  /api/metrics             — Prometheus-style metrics

WebSocket: /api/trading/ws/gameloop
  Client → Server: {"subscribe": "SYMBOL"}, tick data (client-driven)
  Server → Client: Full state, delta-compressed state updates
```

---

## Key Directory Structure

```
v5-of-glassytrade-ai/
├── backend/
│   ├── app/
│   │   ├── api/
│   │   │   ├── dependencies.py      # ServiceGraph (DI container)
│   │   │   ├── routers/             # Health, market, analysis, trading, AI, RL, metrics
│   │   │   └── websocket/
│   │   │       └── gameloop.py      # Frontend WS viewer
│   │   ├── application/
│   │   │   ├── handlers/
│   │   │   │   ├── amt_handler.py       # AMT analysis + VP + footprint
│   │   │   │   ├── llm_entry_handler.py # LLM entry decisions (worker threads)
│   │   │   │   ├── llm_overseer_handler.py # Position management (worker threads)
│   │   │   │   ├── position_sizer.py    # Position sizing calculator
│   │   │   │   └── post_trade_analyst.py # Post-trade LLM analysis
│   │   │   ├── services/
│   │   │   │   ├── trading_session.py   # Central orchestrator
│   │   │   │   ├── session_state_manager.py
│   │   │   │   ├── session_risk_coordinator.py
│   │   │   │   ├── entry_coordinator.py
│   │   │   │   ├── exit_coordinator.py
│   │   │   │   ├── portfolio_coordinator.py
│   │   │   │   ├── trade_journal.py
│   │   │   │   └── signal_tracking_service.py
│   │   │   ├── stream_manager.py    # WS streaming + reconnect + fallback
│   │   │   ├── candle_aggregator.py # Tick → OHLCV
│   │   │   ├── watchdog_manager.py  # Health monitors + GC
│   │   │   ├── utils.py
│   │   │   └── engine.py            # TradingEngine (standalone core)
│   │   ├── config.py                # Settings (extends SharedSettings)
│   │   ├── main.py                  # FastAPI entry point
│   │   ├── domain/                  # Domain models + logic
│   │   │   ├── constants.py         # Domain constants (from YAML)
│   │   │   ├── fabio_ai/            # AMT, CVD, regime, probability engines
│   │   │   ├── trading/             # Portfolio, positions, signals
│   │   │   └── notifications/       # Telegram, alerts
│   │   ├── infrastructure/adapters/ # Concrete port implementations
│   │   └── models/                  # ML models (on-disk)
│   ├── config/                      # YAML-based config
│   ├── start.sh                     # Startup script
│   └── conftest.py                  # Test fixtures
├── brokers/
│   └── broker/dhan/
│       ├── domain/
│       │   ├── constants.py         # Dhan API constants
│       │   └── models.py            # Value objects
│       ├── application/
│       │   └── services/
│       │       └── streaming_service.py  # Persistent WS management
│       ├── infrastructure/
│       │   └── websocket_client.py     # Binary packet decoder
│       └── ports.py                    # IWebSocketClient, WSMessage
├── shared/
│   ├── config.py                    # SharedSettings (Pydantic BaseSettings)
│   └── ...                          # Shared entity types, resilience
└── frontend/
    └── hooks/
        └── useServerTradingSystem.ts  # WS viewer hook
```

---

## Summary of Key Design Decisions

| Decision | Rationale |
|----------|-----------|
| Server-driven trading | Frontend disconnection ≠ trading stop |
| Generation-based WS updates | Efficient delta compression vs full push |
| Persistent WebSocket | Avoids rate limiting from per-call connections |
| Thread-pooled LLM inference | Non-blocking main async loop |
| Per-symbol work queues | Parallel LLM inference across symbols |
| Dual feed (option + futures) | Execution pricing + AMT analysis accuracy |
| LightGBM first-passage filter | Pre-filters LLM calls, saves tokens + latency |
| Three-Align gate pipeline | Only high-conviction setups reach LLM |
| Partition Exit Manager | Granular position management in-trade |
| Risk tier cushion system | Graduated risk reduction, not binary on/off |
| SQLite async persistence | Non-blocking DB writes via background thread |
| Position recovery on startup | Survives crashes — no orphaned positions |
