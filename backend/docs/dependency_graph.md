# GlassyTrade AI — Dependency Graph

**Date:** 2026-03-23

## Critical Dependency Chain

```
ServiceGraph (api/dependencies.py)
  ├── EventBus ──────────────────────────────────────────┐
  ├── MarketData (DhanMarketDataAdapter)                 │
  ├── Broker (PaperBrokerAdapter / DhanBrokerAdapter)    │
  ├── LLMInference (MLXInferenceAdapter)                 │
  ├── ProbabilityEngine (LGBMProbabilityAdapter)         │
  ├── Storage (SQLiteStorageAdapter → AsyncPersistence)  │
  ├── SignalTracker (SignalTrackingService)              │
  └── TradingSessionService                              │
        ├── AMTHandler                                   │
        │     └── AMTAnalyzer                            │
        │           ├── PersistentAggressionScorer       │
        │           ├── CVDTracker                       │
        │           ├── LVNPersistenceTracker             │
        │           ├── MarketStateEngine                 │
        │           ├── MarketStructureClassifier         │
        │           └── ProfileClassifier                │
        ├── LLMEntryHandler                              │
        │     ├── EntryGateCoordinator                   │
        │     │     └── EntryGate (three_align_check)    │
        │     │           └── GatePipeline (12 gates)    │
        │     ├── SignalConstructor                      │
        │     └── GenerativeAIService                    │
        ├── TradeLifecycleHandler                        │
        │     └── LLMOverseerHandler                     │
        └── SessionRiskCoordinator                       │
              └── SessionRiskManager                     │

Pipeline (alternative path, same logic)
  Ingest → Candle → Analysis → Gate → LLM → Overseer
    │         │         │         │      │        │
    └─────────┴─────────┴─────────┴──────┴────────┘
              Connected by typed Channels
```

## Module Coupling Map

| Module | Depends On | Depended By |
|--------|-----------|-------------|
| AMTAnalyzer | OHLC, VolumeProfileLevel, constants, mlx_compute | AMTHandler, GateProcessor |
| AggressionScorer | constants | AMTAnalyzer |
| CVDTracker | OHLC, mlx_compute, constants | AMTAnalyzer |
| MarketStateEngine | OHLC | AMTAnalyzer |
| MarketStructureClassifier | OHLC, mlx_compute, constants | AMTAnalyzer |
| EntryGate | OHLC, AMTResult, OrderBook | EntryGateCoordinator, GateProcessor |
| GatePipeline | MarketState | EntryGate, GateProcessor |
| AgentPipeline | AMTResult, ProbabilityInferencePort, OHLC | TradingSessionService |
| SignalTrackingService | StoragePort | ServiceGraph, GateProcessor |
| TradingSessionService | ALL handlers + services | ServiceGraph, Engine |

## Interface Contracts (Ports)

| Port | Interface | Implementations |
|------|-----------|-----------------|
| MarketDataPort | fetch_history, stream_full, stream_depth_20, get_ltp | DhanMarketDataAdapter |
| LLMInferencePort | predict, is_ready, wait_until_ready | MLXInferenceAdapter |
| ProbabilityInferencePort | estimate, is_ready | LGBMProbabilityAdapter |
| BrokerPort | execute_order, cancel_order | PaperBrokerAdapter, DhanBrokerAdapter |
| StoragePort | save_tick, save_trade, save_decision, save_position, query_* | SQLiteStorageAdapter (via AsyncPersistenceBus) |
| EventBusPort | publish, subscribe | InMemoryEventBus |
