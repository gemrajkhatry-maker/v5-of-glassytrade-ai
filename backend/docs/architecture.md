# GlassyTrade AI — Architecture Overview

**Date:** 2026-03-23
**Version:** Post-stability-fixes

## System Pattern

DDD + Hexagonal Architecture + Event-Driven + Pipeline (NiFi-style)

## Layer Structure

```
┌─────────────────────────────────────────────────────┐
│  API Layer (FastAPI)                                 │
│  routers: health, market, analysis, trading, ai, rl │
│  websocket: gameloop (read-only viewer)              │
│  dependencies.py: ServiceGraph singleton factory     │
├─────────────────────────────────────────────────────┤
│  Application Layer                                   │
│  engine.py: TradingEngine (tick loop)                │
│  services: trading_session, signal_tracking,         │
│            session_state, risk, event_logger,        │
│            trade_journal, backtest_engine             │
│  handlers: amt, llm_entry, entry_gate, signal,       │
│            position_sizer, trade_lifecycle,           │
│            llm_overseer, rl                           │
├─────────────────────────────────────────────────────┤
│  Domain Layer                                        │
│  fabio_ai/services: AMTAnalyzer, EntryGate,          │
│    GatePipeline, CVDTracker, AggressionScorer,       │
│    MarketStateEngine, MarketStructureClassifier,     │
│    LVNPersistenceTracker, LVNPlayEngine, etc.        │
│  trading/models: OHLC, Signal, Position, Portfolio,  │
│    MarketState, SignalType, enums                    │
│  probability: agent_pipeline (4-agent cascade)       │
│  ports: MarketData, LLMInference, Probability,       │
│         Broker, Storage, EventBus                    │
├─────────────────────────────────────────────────────┤
│  Infrastructure Layer                                │
│  adapters: Dhan, PaperBroker, MLX, LightGBM          │
│  storage: SQLiteStorageAdapter                       │
│  event_bus: InMemoryEventBus                         │
│  async_persistence: AsyncPersistenceBus              │
├─────────────────────────────────────────────────────┤
│  Pipeline Layer (NiFi-style)                         │
│  ingest → candle → analysis → gate → llm → overseer │
│  Connected by typed Channels (bounded async queues)  │
├─────────────────────────────────────────────────────┤
│  Shared Layer                                        │
│  config, error_handling, resilience, conversion      │
└─────────────────────────────────────────────────────┘
```

## Data Flow: Tick to Decision

```
Dhan WS/REST tick
  → StreamManager
  → TradingEngine._tick_loop()
  → CandleAggregator (tick → OHLCV)
  → TradingSessionService.process_tick()
  → AMTHandler.analyze() → AMTResult
  → AgentPipeline (<1ms): Regime → Direction → Timing → Size
  → GateProcessor: three_align_check + 12-gate validation
  → LLMEntryHandler: prompt → LLM inference → parse
  → Signal construction + SL/TP
  → BrokerPort.execute_order()
  → Position lifecycle (watchdog + overseer)
```

## Critical Modules

| Module | File | Responsibility |
|--------|------|----------------|
| AMTAnalyzer | domain/fabio_ai/services/amt_analyzer.py | Volume profile, LVN/HVN, market state, aggression, CVD |
| EntryGate | domain/fabio_ai/services/entry_gate.py | Three-Align check (state + location + confirmation) |
| GatePipeline | domain/fabio_ai/services/gate_pipeline.py | 12-gate sequential validation (Gates 0-12) |
| AgentPipeline | domain/probability/agent_pipeline.py | 4-agent cascade: regime, direction, timing, sizing |
| AggressionScorer | domain/fabio_ai/services/aggression_scorer.py | Multi-signal additive scoring with persistence |
| CVDTracker | domain/fabio_ai/services/cvd_tracker.py | Cumulative Volume Delta with slope persistence |
| MarketStateEngine | domain/fabio_ai/services/market_state_engine.py | BALANCED/IMBALANCED/PROBING/NO_TRADE detection |
| MarketStructureClassifier | domain/fabio_ai/services/market_structure_classifier.py | BALANCE/IMBALANCE/TRANSITION/EXPANSION/CHOP |
| LVNPersistenceTracker | domain/fabio_ai/services/amt_analyzer.py | LVN stability across bars |
| TradingEngine | application/engine.py | Tick loop, candle aggregation, WS viewer notification |
| TradingSessionService | application/services/trading_session.py | Tick processing coordinator |
| ServiceGraph | api/dependencies.py | DI container, wires all services |
| SQLiteStorageAdapter | infrastructure/storage/database.py | Persistence (ticks, trades, decisions, positions, events) |
| SignalGateProcessor | pipeline/processors/gate.py | Pipeline gate validation + decision tracking |
