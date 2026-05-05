# Existing Module → Target Pipeline Mapping

> Maps every backendv2 source file to its target pipeline stage in the new architecture.

---

## Market Data Pipeline

| Existing File | Target Module | Action | Priority |
|-------------|---------------|--------|----------|
| *(none)* | `MarketDataIngestion` | Create new feed abstraction | P0 |
| *(none)* | `TickSequencer` | Create new sequencing stage | P0 |
| *(none)* | `TickNormalizer` | Create new normalization stage | P0 |

## Candle Pipeline

| Existing File | Target Module | Action | Priority |
|-------------|---------------|--------|----------|
| *(none)* | `CandlePipeline` | Create new candle builder | P0 |

## Order Flow Pipeline

| Existing File | Target Module | Action | Priority |
|-------------|---------------|--------|----------|
| `amt/service/cvd_tracker.py` (168L) | `OrderFlowPipeline.cvd_tracker` | Move file, keep API | P0 |
| `amt/service/orderflow_detectors.py` (171L) | `OrderFlowPipeline.detectors` | Move file, keep API | P0 |

## Microstructure Analysis

| Existing File | Target Module | Action | Priority |
|-------------|---------------|--------|----------|
| *(none)* | `MicrostructureAnalysis` | Create new depth analysis module | P1 |

## Market Structure Pipeline

| Existing File | Target Module | Action | Priority |
|-------------|---------------|--------|----------|
| `amt/service/volume_profile.py` (130L) | `MarketStructureAnalysis.volume_profile` | Move, no changes | P0 |
| `amt/service/lvn_detector.py` (173L) | `MarketStructureAnalysis.lvn_detector` | Move, no changes | P0 |
| `amt/service/market_state_engine.py` (119L) | `MarketStructureAnalysis.market_state` | Move, no changes | P0 |
| `amt/service/acceptance_rejection.py` (256L) | `MarketStructureAnalysis.acceptance_rejection` | Move, no changes | P0 |
| `amt/service/break_detector.py` (105L) | `MarketStructureAnalysis.break_detector` | Move, no changes | P0 |
| `amt/service/displacement_detector.py` (100L) | `MarketStructureAnalysis.displacement` | Move, no changes | P0 |
| `amt/service/initial_balance_engine.py` (112L) | `MarketStructureAnalysis.initial_balance` | Move, no changes | P0 |
| `amt/service/session_context.py` (119L) | `MarketStructureAnalysis.session_context` | Move, no changes | P0 |
| `amt/service/profile_classifier.py` (136L) | `MarketStructureAnalysis.profile` | Move, no changes | P0 |
| `amt/service/drive_tracker.py` (74L) | `MarketStructureAnalysis.drive` | Move, no changes | P0 |
| `amt/service/mtf_analyzer.py` (116L) | `MarketStructureAnalysis.mtf` | Move, no changes | P0 |
| `amt/service/amt_analyzer.py` (427L) | `MarketStructureAnalysis.orchestrator` | Refactor to sub-component orchestrator | P1 |
| `amt/model/amt_models.py` (201L) | `MarketStructureAnalysis.models` | Keep as shared models | P0 |

## Feature Computation

| Existing File | Target Module | Action | Priority |
|-------------|---------------|--------|----------|
| *(none)* | `FeatureComputation.vwap` | Create VWAP + σ bands | P1 |
| *(none)* | `FeatureComputation.atr` | Create ATR computation | P1 |
| *(none)* | `FeatureComputation.rsi` | Create RSI computation | P2 |
| *(none)* | `FeatureComputation.rolling_stats` | Create rolling windows | P2 |

## Signal Pipeline

| Existing File | Target Module | Action | Priority |
|-------------|---------------|--------|----------|
| `amt/service/signal_generator.py` (131L) | `SignalGeneration.generator` | Move, rename class | P0 |
| *(none)* | `SignalGeneration.pipeline` | Create pipeline wrapper | P1 |

## Gate Pipeline

| Existing File | Target Module | Action | Priority |
|-------------|---------------|--------|----------|
| `amt/service/aggression_scorer.py` (211L) | `GateEvaluation.aggression_gate` | Move, add gate wrapper | P0 |
| *(none)* | `GateEvaluation.confidence_gate` | Create confidence threshold gate | P1 |
| *(none)* | `GateEvaluation.session_phase_gate` | Create session phase gate | P1 |
| *(none)* | `GateEvaluation.playbook_gate` | Create playbook guard | P1 |
| *(none)* | `GateEvaluation.pipeline` | Create gate pipeline runner | P0 |

## Risk Pipeline

| Existing File | Target Module | Action | Priority |
|-------------|---------------|--------|----------|
| `trading/service/risk_manager.py` (200L) | `RiskEvaluation.manager` | Move, add pipeline wrapper | P0 |
| `risk/service/risk_sizing_engine.py` (61L) | `RiskEvaluation.sizing_engine` | Expand with tiered sizing | P1 |
| *(none)* | `RiskEvaluation.circuit_breakers` | Create from scratch | P1 |
| *(none)* | `RiskEvaluation.self_healing` | Create from scratch | P2 |

## Position Lifecycle

| Existing File | Target Module | Action | Priority |
|-------------|---------------|--------|----------|
| `exit/service/exit_engine.py` (226L) | `PositionLifecycle.exit_engine` | Move, split into sub-modules | P0 |
| `exit/service/exit_rules.py` (80L) | `PositionLifecycle.exit_rules` | Move | P0 |
| `exit/model/exit_models.py` (79L) | `PositionLifecycle.models` | Move | P0 |
| *(TrailEngine inside exit_engine.py)* | `PositionLifecycle.trail_engine` | Extract to own file | P1 |
| *(PartitionExitManager inside exit_engine.py)* | `PositionLifecycle.partition_manager` | Extract to own file | P1 |
| *(none)* | `PositionLifecycle.position_sizer` | Create from backend | P0 |
| *(none)* | `PositionLifecycle.pyramid_manager` | Create from backend | P1 |
| *(none)* | `PositionLifecycle.structural_stop` | Create from backend | P1 |
| *(none)* | `PositionLifecycle.loss_tracker` | Create from backend | P1 |

## Execution Pipeline

| Existing File | Target Module | Action | Priority |
|-------------|---------------|--------|----------|
| *(none)* | `ExecutionPipeline.submitter` | Create order submission | P0 |
| *(none)* | `ExecutionPipeline.tracker` | Create order lifecycle tracker | P1 |
| `infrastructure/adapters/dhan_adapter.py` (80L) | `ExecutionPipeline.broker_adapters.dhan` | Move, expand | P1 |
| *(none)* | `ExecutionPipeline.broker_adapters.paper` | Create paper broker | P0 |

## Broker Synchronization

| Existing File | Target Module | Action | Priority |
|-------------|---------------|--------|----------|
| *(none)* | `BrokerSynchronization.reconciler` | Create from backend | P1 |
| *(none)* | `BrokerSynchronization.startup_recovery` | Create from backend | P1 |

## Persistence

| Existing File | Target Module | Action | Priority |
|-------------|---------------|--------|----------|
| `infrastructure/storage/database.py` (373L) | `EventPersistence.sqlite` | Move, add pipeline interface | P0 |
| `infrastructure/adapters/postgresql_adapter.py` (163L) | `EventPersistence.postgres` | Move, keep as alternative | P2 |
| `infrastructure/cache/redis_cache.py` (103L) | `EventPersistence.cache` | Move, keep as cache layer | P2 |
| *(none)* | `EventPersistence.serialization` | Create serialization schemas | P1 |

## Session Runtime

| Existing File | Target Module | Action | Priority |
|-------------|---------------|--------|----------|
| `application/handlers/evaluate_entry_handler.py` (91L) | `SessionRuntime.entry_handler` | Refactor to pipeline stage | P1 |
| `application/handlers/check_exit_handler.py` (95L) | `SessionRuntime.exit_handler` | Refactor to pipeline stage | P1 |
| `application/handlers/update_tick_handler.py` (63L) | `SessionRuntime.tick_handler` | Refactor to pipeline stage | P1 |
| *(none)* | `SessionRuntime.session_manager` | Create session state manager | P0 |
| *(none)* | `SessionRuntime.orchestrator` | Create trading session orchestrator | P0 |

## Telemetry

| Existing File | Target Module | Action | Priority |
|-------------|---------------|--------|----------|
| `infrastructure/alerts/alert_manager.py` (108L) | `TelemetryPipeline.alerts` | Move, add pipeline hook | P2 |
| `api/routers/metrics.py` (30L) | `TelemetryPipeline.metrics` | Expand, add latency tracking | P1 |
| *(none)* | `TelemetryPipeline.latency_tracker` | Create latency measurement | P1 |

## Strategy Runtime

| Existing File | Target Module | Action | Priority |
|-------------|---------------|--------|----------|
| *(none)* | `StrategyRuntime.registry` | Create strategy registry | P2 |
| *(none)* | `StrategyRuntime.llm_strategy` | Create LLM-based strategy wrapper | P2 |
| *(none)* | `StrategyRuntime.rule_based` | Create rule-based strategy host | P2 |

## Infrastructure to Remove

| Existing File | Reason | Action |
|-------------|--------|--------|
| `application/event_bus.py` | Replaced by pipeline SPSC queues | Remove after migration |
| `application/di/container.py` | DI container replaced by explicit composition in RuntimeOrchestrator | Remove after migration |
| `application/commands/trading_commands.py` | Command pattern replaced by explicit pipeline stages | Remove after migration |
| `domain/shared/event/*.py` | Event types replaced by pipeline-specific event structs | Remove after migration (keep types) |
| `domain/shared/port/*.py` | Port abstractions replaced by concrete pipeline stage interfaces | Remove after migration |
| `domain/broker/port.py` | Broker port replaced by adapter plugin interface | Remove after migration |
| `infrastructure/messaging/event_bus.py` | Messaging replaced by pipeline queues | Remove after migration |
| `core/core_components.py` | Core abstractions replaced by pipeline stage trait | Remove after migration |

## Files to Keep (No Changes Needed)

| File | Reason |
|------|--------|
| `domain/trading/model/enums.py` (149L) | Core domain enums, no pipeline dependency |
| `domain/trading/model/value_objects.py` (279L) | Core value objects, no pipeline dependency |
| `domain/trading/model/entities.py` (253L) | Core entities (Position, Signal), no pipeline dependency |
| `domain/trading/model/aggregates.py` (364L) | Core aggregate (Portfolio), no pipeline dependency |
| `domain/trading/event_store.py` (144L) | Abstract event store interface, needed for persistence |
| `api/main.py` | FastAPI app, separate from pipeline |