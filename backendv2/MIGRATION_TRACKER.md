# BackendV2 Migration Tracker

> TDD-driven migration: write tests FIRST, then implement, then verify.

---

## Progress Overview

| Phase | Stage | Tests | Impl | Status |
|-------|-------|-------|------|--------|
| **Skeleton** | PipelineStage trait | ✅ | ✅ | Done |
| **Skeleton** | SPSCQueue | ✅ | ✅ | Done |
| **Skeleton** | Events (20 types) | ⬜ | ✅ | Need tests |
| **Skeleton** | TickSequencer | ⬜ | ✅ | Need tests |
| **Skeleton** | FeedSource ABC | ⬜ | ✅ | Need tests |
| **Market Data** | MarketDataIngestion | ⬜ | ⬜ | Pending |
| **Market Data** | TickNormalizer | ⬜ | ⬜ | Pending |
| **Market Data** | CandlePipeline | ⬜ | ⬜ | Pending |
| **Order Flow** | OrderFlowPipeline | ⬜ | ⬜ | Pending |
| **Microstructure** | MicrostructureAnalysis | ⬜ | ⬜ | Pending |
| **Market Structure** | MarketStructureAnalysis | ⬜ | ⬜ | **NEXT** |
| **Signal** | SignalGeneration | ⬜ | ⬜ | Pending |
| **Gate** | GateEvaluation | ⬜ | ⬜ | Pending |
| **Risk** | RiskEvaluation | ⬜ | ⬜ | Pending |
| **Position** | PositionLifecycle | ⬜ | ⬜ | Pending |
| **Execution** | ExecutionPipeline | ⬜ | ⬜ | Pending |
| **Broker** | BrokerSynchronization | ⬜ | ⬜ | Pending |
| **Persistence** | EventPersistence | ⬜ | ⬜ | Pending |
| **Telemetry** | TelemetryPipeline | ⬜ | ⬜ | Pending |
| **Session** | SessionRuntime | ⬜ | ⬜ | Pending |
| **Orchestrator** | RuntimeOrchestrator | ⬜ | ⬜ | Pending |
| **Backtest** | BacktestRuntime | ⬜ | ⬜ | Pending |
| **Features** | FeatureComputation | ⬜ | ⬜ | Pending |
| **Strategy** | StrategyRuntime | ⬜ | ⬜ | Pending |

---

## Step 4: Market Structure Pipeline (Current)

Migrate 11 existing AMT services into one cohesive pipeline stage. Each service becomes a sub-component called by the orchestrator.

### Sub-components to port

| # | Service | Source File | Target | Lines | Tests | Status |
|---|---------|-------------|--------|-------|-------|--------|
| 1 | VolumeProfile | `amt/service/volume_profile.py` | sub-component | 130L | ⬜ | Ready to port |
| 2 | LVNDetector | `amt/service/lvn_detector.py` | sub-component | 173L | exists | Ready to port |
| 3 | MarketStateEngine | `amt/service/market_state_engine.py` | sub-component | 119L | exists | Ready to port |
| 4 | AcceptanceRejection | `amt/service/acceptance_rejection.py` | sub-component | 256L | exists | Ready to port |
| 5 | BreakDetector | `amt/service/break_detector.py` | sub-component | 105L | exists | Ready to port |
| 6 | DisplacementDetector | `amt/service/displacement_detector.py` | sub-component | 100L | exists | Ready to port |
| 7 | InitialBalanceEngine | `amt/service/initial_balance_engine.py` | sub-component | 112L | exists | Ready to port |
| 8 | SessionContext | `amt/service/session_context.py` | sub-component | 119L | exists | Ready to port |
| 9 | ProfileClassifier | `amt/service/profile_classifier.py` | sub-component | 136L | exists | Ready to port |
| 10 | DriveTracker | `amt/service/drive_tracker.py` | sub-component | 74L | exists | Ready to port |
| 11 | MTFAnalyzer | `amt/service/mtf_analyzer.py` | sub-component | 116L | exists | Ready to port |
| 12 | AMTAnalyzer (orchestrator) | `amt/service/amt_analyzer.py` | orchestrator wrapper | 427L | exists | Ready to port |

### Test Plan (write first)

```
tests/unit/runtime/pipeline/test_market_structure.py
```

| Test | Description |
|------|-------------|
| `test_empty_state` | No candles processed → empty result, defaults |
| `test_single_candle` | One candle → basic POC/VAH/VAL, no break, no displacement |
| `test_full_session` | 390 candles → complete market structure output |
| `test_break_detected` | Candle sequence triggers break → break fields populated |
| `test_displacement_detected` | Large move candle → displacement fields populated |
| `test_lvn_hvn_detected` | Volume below 15% mean → LVN level |
| `test_market_state_balanced` | Price inside VA → BALANCED |
| `test_market_state_imbalanced` | Price outside VA → IMBALANCED |
| `test_session_context_populated` | Gap, OBI, session phase filled |
| `test_profile_shape_classified` | Top-heavy volume → P shape |
| `test_drive_tracked` | Multiple level tests → drive number incremented |
| `test_mtf_alignment` | Daily + hourly alignment computed |
| `test_reset` | Reset between runs → all sub-components reset |