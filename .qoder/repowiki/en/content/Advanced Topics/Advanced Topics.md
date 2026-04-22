# Advanced Topics

<cite>
**Referenced Files in This Document**
- [main.py](file://appv2/backend/appv2/main.py)
- [trading_engine.py](file://appv2/backend/appv2/application/trading_engine.py)
- [strategy_orchestrator.py](file://appv2/backend/appv2/application/strategy_orchestrator.py)
- [data_pipeline.py](file://appv2/backend/appv2/application/data_pipeline.py)
- [mlx_adapters.py](file://appv2/backend/appv2/domain/services/mlx_adapters.py)
- [risk_orchestrator.py](file://appv2/backend/appv2/application/risk_orchestrator.py)
- [entry_coordinator.py](file://appv2/backend/appv2/application/entry_coordinator.py)
- [exit_coordinator.py](file://appv2/backend/appv2/application/exit_coordinator.py)
- [settings.py](file://appv2/backend/appv2/config/settings.py)
- [gate_pipeline.py](file://appv2/backend/appv2/domain/services/gate_pipeline.py)
- [session_strategy_selector.py](file://appv2/backend/appv2/domain/services/session_strategy_selector.py)
- [stream_manager.py](file://appv2/backend/appv2/infrastructure/stream_manager.py)
- [incremental_finetune.py](file://backend/scripts/incremental_finetune.py)
- [convert_to_mlx.py](file://backend/scripts/convert_to_mlx.py)
- [walk_forward_validator.py](file://backend/app/domain/services/walk_forward_validator.py)
- [backtest_engine.py](file://backend/app/application/services/backtest_engine.py)
- [rl_handler.py](file://backend/app/application/handlers/rl_handler.py)
- [signal_constructor.py](file://backend/app/application/handlers/signal_constructor.py)
- [regime_detector.py](file://backend/app/domain/fabio_ai/services/regime_detector.py)
- [risk_sizing_engine.py](file://backend/app/domain/services/risk_sizing_engine.py)
- [position_sizer.py](file://backend/app/domain/fabio_ai/services/position_sizer.py)
- [entities.py](file://backend/app/domain/trading/models/entities.py)
- [enums.py](file://backend/app/domain/trading/models/enums.py)
- [session_risk_coordinator.py](file://backend/app/application/services/session_risk_coordinator.py)
</cite>

## Update Summary
**Changes Made**
- Added comprehensive appv2 architecture documentation with new TradingEngine and StrategyOrchestrator components
- Integrated advanced MLX adapter system with LLMEntryDecider and LLMOverseer
- Documented new gate pipeline system with 12 hard and soft gates
- Added session strategy selector with exchange-specific configurations
- Included performance optimization features like tick throttling and latency tracking
- Enhanced risk management with circuit breakers and position sizing
- Added comprehensive WebSocket streaming with auto-reconnect capabilities

## Table of Contents
1. [Introduction](#introduction)
2. [Project Structure](#project-structure)
3. [Core Components](#core-components)
4. [Architecture Overview](#architecture-overview)
5. [Detailed Component Analysis](#detailed-component-analysis)
6. [Dependency Analysis](#dependency-analysis)
7. [Performance Considerations](#performance-considerations)
8. [Troubleshooting Guide](#troubleshooting-guide)
9. [Conclusion](#conclusion)
10. [Appendices](#appendices)

## Introduction
This document provides advanced guidance for GlassyTrade AI v5, focusing on custom strategy development with the new appv2 architecture, machine learning model training and fine-tuning, reinforcement learning implementation, and performance optimization. The appv2 architecture introduces a comprehensive trading engine with advanced MLX adapters, sophisticated gate pipelines, and enhanced risk management systems. It documents the incremental fine-tuning process, MLX model conversion workflows, and walk-forward validation methodologies. Practical examples show how to develop custom entry/exit strategies, train custom AI models, and optimize system performance. Advanced trading concepts such as position sizing algorithms, risk management strategies, and market regime detection are explained, along with security considerations, system hardening, and scalability optimization. Guidance is included for extending the system with custom components, integrating new data sources, and developing proprietary trading algorithms.

## Project Structure
GlassyTrade AI v5 appv2 is organized into a comprehensive layered architecture:
- Application layer orchestrates the TradingEngine, StrategyOrchestrator, and specialized coordinators
- Domain layer encapsulates trading models, services, and AI-related logic including MLX adapters
- Infrastructure layer manages WebSocket streaming, broker adapters, and storage systems
- Config layer provides environment-based settings and strategy configurations
- Scripts provide ML workflows for incremental fine-tuning and model conversion
- Tests validate behavior across integration, unit, and validation suites

```mermaid
graph TB
subgraph "Application Layer - Trading Engine"
TE["TradingEngine<br/>trading_engine.py"]
SO["StrategyOrchestrator<br/>strategy_orchestrator.py"]
EC["EntryCoordinator<br/>entry_coordinator.py"]
XC["ExitCoordinator<br/>exit_coordinator.py"]
RO["RiskOrchestrator<br/>risk_orchestrator.py"]
end
subgraph "Domain Layer - Advanced Services"
MLX["MLX Adapters<br/>mlx_adapters.py"]
GP["Gate Pipeline<br/>gate_pipeline.py"]
SSS["Session Strategy<br/>session_strategy_selector.py"]
end
subgraph "Infrastructure Layer - Streaming"
SM["StreamManager<br/>stream_manager.py"]
end
subgraph "Config Layer"
SET["Settings<br/>settings.py"]
end
subgraph "Legacy Components"
SCR1["incremental_finetune.py"]
SCR2["convert_to_mlx.py"]
SCR3["walk_forward_validator.py"]
end
TE --> SO
TE --> EC
TE --> XC
TE --> RO
SO --> MLX
SO --> GP
SO --> SSS
TE --> SM
SET --> TE
```

**Diagram sources**
- [main.py:1-241](file://appv2/backend/appv2/main.py#L1-L241)
- [trading_engine.py:1-638](file://appv2/backend/appv2/application/trading_engine.py#L1-L638)
- [strategy_orchestrator.py:1-245](file://appv2/backend/appv2/application/strategy_orchestrator.py#L1-L245)
- [mlx_adapters.py:1-658](file://appv2/backend/appv2/domain/services/mlx_adapters.py#L1-L658)
- [gate_pipeline.py:1-238](file://appv2/backend/appv2/domain/services/gate_pipeline.py#L1-L238)
- [session_strategy_selector.py:1-198](file://appv2/backend/appv2/domain/services/session_strategy_selector.py#L1-L198)
- [risk_orchestrator.py:1-160](file://appv2/backend/appv2/application/risk_orchestrator.py#L1-L160)
- [entry_coordinator.py:1-185](file://appv2/backend/appv2/application/entry_coordinator.py#L1-L185)
- [exit_coordinator.py:1-178](file://appv2/backend/appv2/application/exit_coordinator.py#L1-L178)
- [settings.py:1-123](file://appv2/backend/appv2/config/settings.py#L1-L123)
- [stream_manager.py:1-271](file://appv2/backend/appv2/infrastructure/stream_manager.py#L1-L271)

**Section sources**
- [main.py:1-241](file://appv2/backend/appv2/main.py#L1-L241)
- [trading_engine.py:1-638](file://appv2/backend/appv2/application/trading_engine.py#L1-L638)
- [strategy_orchestrator.py:1-245](file://appv2/backend/appv2/application/strategy_orchestrator.py#L1-L245)
- [mlx_adapters.py:1-658](file://appv2/backend/appv2/domain/services/mlx_adapters.py#L1-L658)
- [gate_pipeline.py:1-238](file://appv2/backend/appv2/domain/services/gate_pipeline.py#L1-L238)
- [session_strategy_selector.py:1-198](file://appv2/backend/appv2/domain/services/session_strategy_selector.py#L1-L198)
- [risk_orchestrator.py:1-160](file://appv2/backend/appv2/application/risk_orchestrator.py#L1-L160)
- [entry_coordinator.py:1-185](file://appv2/backend/appv2/application/entry_coordinator.py#L1-L185)
- [exit_coordinator.py:1-178](file://appv2/backend/appv2/application/exit_coordinator.py#L1-L178)
- [settings.py:1-123](file://appv2/backend/appv2/config/settings.py#L1-L123)
- [stream_manager.py:1-271](file://appv2/backend/appv2/infrastructure/stream_manager.py#L1-L271)

## Core Components
- **Trading Engine**: Complete live trading engine with all advanced features including throttle mechanism, footprint accumulator, opening classifier, regime detector, market structure classifier, structural stop engine, partition exit manager, drive decay tracker, latency tracker, gate rejection tracker, playbook guard, session risk tiers, capital ladder, session cache, volatility features, state snapshot builder, and MLX adapters.
- **Strategy Orchestrator**: Per-symbol strategy orchestration that processes candles through AMT analysis, market state machine, gate pipeline, and signal generation.
- **MLX Adapters**: Advanced LLM integration with LLMEntryDecider for entry decisions and LLMOverseer for active trade management, including lazy model loading and JSON response parsing.
- **Gate Pipeline**: Sophisticated 12-gate entry validation system with 8 hard gates (fail-fast) and 4 soft gates (quorum-based) for comprehensive trade filtering.
- **Session Strategy Selector**: Exchange-specific strategy configuration with different modes (TREND_FOLLOWING, MEAN_REVERSION, NO_TRADE, EXIT_ONLY, SELECTIVE) for various market sessions.
- **Risk Orchestrator**: Comprehensive risk management with daily loss tracking, circuit breakers, position sizing validation, and exposure limits.
- **Streaming Infrastructure**: Robust WebSocket management with auto-reconnect, heartbeat monitoring, and emergency pause/resume functionality.
- **Data Pipeline**: Multi-symbol, multi-timeframe processing pipeline that transforms ticks into AMT-ready observations.

**Section sources**
- [trading_engine.py:1-638](file://appv2/backend/appv2/application/trading_engine.py#L1-L638)
- [strategy_orchestrator.py:1-245](file://appv2/backend/appv2/application/strategy_orchestrator.py#L1-L245)
- [mlx_adapters.py:1-658](file://appv2/backend/appv2/domain/services/mlx_adapters.py#L1-L658)
- [gate_pipeline.py:1-238](file://appv2/backend/appv2/domain/services/gate_pipeline.py#L1-L238)
- [session_strategy_selector.py:1-198](file://appv2/backend/appv2/domain/services/session_strategy_selector.py#L1-L198)
- [risk_orchestrator.py:1-160](file://appv2/backend/appv2/application/risk_orchestrator.py#L1-L160)
- [stream_manager.py:1-271](file://appv2/backend/appv2/infrastructure/stream_manager.py#L1-L271)
- [data_pipeline.py:1-151](file://appv2/backend/appv2/application/data_pipeline.py#L1-L151)

## Architecture Overview
The appv2 architecture introduces a comprehensive trading system that integrates advanced MLX adapters with sophisticated risk controls and deterministic sizing. The TradingEngine serves as the central orchestrator, managing multiple per-symbol services including AMT analysis, market structure classification, and session-specific strategy execution. The StrategyOrchestrator processes market data through a multi-stage pipeline, while the MLX adapters provide intelligent decision-making capabilities. Advanced gate systems filter potential trades, and comprehensive risk management ensures systematic safety controls.

```mermaid
graph TB
subgraph "Trading Engine Core"
TE["TradingEngine"]
SO["StrategyOrchestrator"]
EC["EntryCoordinator"]
XC["ExitCoordinator"]
RO["RiskOrchestrator"]
end
subgraph "Advanced Services"
MLX["MLX Adapters"]
GP["Gate Pipeline"]
SSS["Session Strategy"]
LAT["Latency Tracker"]
GR["Gate Rejection Tracker"]
end
subgraph "Streaming & Infrastructure"
SM["StreamManager"]
BR["Broker Adapter"]
ST["SQLite Storage"]
end
TE --> SO
TE --> EC
TE --> XC
TE --> RO
SO --> MLX
SO --> GP
SO --> SSS
TE --> LAT
TE --> GR
TE --> SM
SM --> BR
TE --> ST
```

**Diagram sources**
- [trading_engine.py:77-638](file://appv2/backend/appv2/application/trading_engine.py#L77-L638)
- [strategy_orchestrator.py:54-245](file://appv2/backend/appv2/application/strategy_orchestrator.py#L54-L245)
- [mlx_adapters.py:386-658](file://appv2/backend/appv2/domain/services/mlx_adapters.py#L386-L658)
- [gate_pipeline.py:197-238](file://appv2/backend/appv2/domain/services/gate_pipeline.py#L197-L238)
- [session_strategy_selector.py:125-198](file://appv2/backend/appv2/domain/services/session_strategy_selector.py#L125-L198)
- [risk_orchestrator.py:35-160](file://appv2/backend/appv2/application/risk_orchestrator.py#L35-L160)
- [stream_manager.py:33-271](file://appv2/backend/appv2/infrastructure/stream_manager.py#L33-L271)

## Detailed Component Analysis

### Trading Engine Architecture
The TradingEngine serves as the central orchestrator for all trading activities, implementing a comprehensive system with 500ms tick throttling, footprint accumulation, and advanced market classification services.

```mermaid
classDiagram
class TradingEngine {
+add_symbol(symbol, underlying, tick_size)
+on_tick(symbol, tick)
+_on_candle(symbol, candle, interval)
+_on_signal_generated(symbol, signal)
+_broadcast_update(symbol)
+start()
+stop()
+reconciliation_loop()
+latency_tracker
+gate_rejections
+cross_index
+regime_detectors
}
class StrategyOrchestrator {
+process_candle(candle)
+check_gates(direction)
+generate_signal(direction, entry, sl, tp)
+check_exit(current_price, stop_loss, take_profit, is_long)
+reset()
}
class MLXEntryDecider {
+decide(symbol, observation, market_context, allow_short)
+_prompt_builder
+_response_parser
+is_ready
}
class MLXOverseer {
+manage(symbol, position, observation)
+_prompt_builder
+_response_parser
+is_ready
}
TradingEngine --> StrategyOrchestrator : "manages"
TradingEngine --> MLXEntryDecider : "uses"
TradingEngine --> MLXOverseer : "uses"
```

**Diagram sources**
- [trading_engine.py:77-638](file://appv2/backend/appv2/application/trading_engine.py#L77-L638)
- [strategy_orchestrator.py:54-245](file://appv2/backend/appv2/application/strategy_orchestrator.py#L54-L245)
- [mlx_adapters.py:386-658](file://appv2/backend/appv2/domain/services/mlx_adapters.py#L386-L658)

**Section sources**
- [trading_engine.py:77-638](file://appv2/backend/appv2/application/trading_engine.py#L77-L638)
- [strategy_orchestrator.py:54-245](file://appv2/backend/appv2/application/strategy_orchestrator.py#L54-L245)
- [mlx_adapters.py:386-658](file://appv2/backend/appv2/domain/services/mlx_adapters.py#L386-L658)

### MLX Adapter System
The MLX adapter system provides intelligent decision-making through advanced LLM integration with lazy loading, prompt building, and response parsing capabilities.

```mermaid
classDiagram
class MLXModelLoader {
+is_ready bool
+error str
+generate(prompt, temperature, max_tokens) str
+_load_model()
}
class MLXPromptBuilder {
+build_entry_prompt(symbol, observation, market_context, allow_short) str
+build_overseer_prompt(symbol, position, observation) str
}
class MLXResponseParser {
+parse_entry_response(text) dict
+parse_overseer_response(text) dict
}
class LLMEntryDecider {
+decide(symbol, observation, market_context, allow_short) MLXEntryDecision
+_rule_based_decision(observation, allow_short, start_time)
}
class LLMOverseer {
+manage(symbol, position, observation) MLXOverseerAction
+_rule_based_overseer(position, observation, start_time)
}
MLXModelLoader --> MLXPromptBuilder : "provides"
MLXModelLoader --> MLXResponseParser : "provides"
LLMEntryDecider --> MLXModelLoader : "uses"
LLMEntryDecider --> MLXPromptBuilder : "uses"
LLMEntryDecider --> MLXResponseParser : "uses"
LLMOverseer --> MLXModelLoader : "uses"
LLMOverseer --> MLXPromptBuilder : "uses"
LLMOverseer --> MLXResponseParser : "uses"
```

**Diagram sources**
- [mlx_adapters.py:50-124](file://appv2/backend/appv2/domain/services/mlx_adapters.py#L50-L124)
- [mlx_adapters.py:150-311](file://appv2/backend/appv2/domain/services/mlx_adapters.py#L150-L311)
- [mlx_adapters.py:313-384](file://appv2/backend/appv2/domain/services/mlx_adapters.py#L313-L384)
- [mlx_adapters.py:386-533](file://appv2/backend/appv2/domain/services/mlx_adapters.py#L386-L533)
- [mlx_adapters.py:535-658](file://appv2/backend/appv2/domain/services/mlx_adapters.py#L535-L658)

**Section sources**
- [mlx_adapters.py:50-124](file://appv2/backend/appv2/domain/services/mlx_adapters.py#L50-L124)
- [mlx_adapters.py:150-311](file://appv2/backend/appv2/domain/services/mlx_adapters.py#L150-L311)
- [mlx_adapters.py:313-384](file://appv2/backend/appv2/domain/services/mlx_adapters.py#L313-L384)
- [mlx_adapters.py:386-533](file://appv2/backend/appv2/domain/services/mlx_adapters.py#L386-L533)
- [mlx_adapters.py:535-658](file://appv2/backend/appv2/domain/services/mlx_adapters.py#L535-L658)

### Gate Pipeline System
The gate pipeline implements a sophisticated 12-gate validation system with both hard gates (fail-fast) and soft gates (quorum-based) for comprehensive trade filtering.

```mermaid
flowchart TD
Start(["Gate Pipeline Start"]) --> HardGates["Hard Gates (8/8 required)"]
HardGates --> SessionWarmup["Session Warmup"]
HardGates --> DataQuality["Data Quality"]
HardGates --> RiskHalt["Risk Halt"]
HardGates --> NoTradeState["No Trade State"]
HardGates --> ProbingAggression["Probing Aggression"]
HardGates --> KeyLevel["Key Level Proximity"]
HardGates --> DriveValidation["Drive Validation"]
HardGates --> SignalAge["Signal Age"]
HardGates --> CVDHard["CVD Hard"]
HardGates --> ThetaViability["Theta Viability"]
SessionWarmup --> HardGates
DataQuality --> HardGates
RiskHalt --> HardGates
NoTradeState --> HardGates
ProbingAggression --> HardGates
KeyLevel --> HardGates
DriveValidation --> HardGates
SignalAge --> HardGates
CVDHard --> HardGates
ThetaViability --> HardGates
HardGates --> SoftGates["Soft Gates (≥ 3/4 required)"]
SoftGates --> EntryZone["Entry Zone"]
SoftGates --> Aggression["Aggression"]
SoftGates --> Cushion["Cushion"]
SoftGates --> RR["R:R Ratio"]
EntryZone --> SoftGates
Aggression --> SoftGates
Cushion --> SoftGates
RR --> SoftGates
SoftGates --> Result["Final Decision"]
Result --> Pass["Trade Allowed"]
Result --> Fail["Trade Rejected"]
```

**Diagram sources**
- [gate_pipeline.py:197-238](file://appv2/backend/appv2/domain/services/gate_pipeline.py#L197-L238)
- [gate_pipeline.py:48-155](file://appv2/backend/appv2/domain/services/gate_pipeline.py#L48-L155)
- [gate_pipeline.py:159-193](file://appv2/backend/appv2/domain/services/gate_pipeline.py#L159-L193)

**Section sources**
- [gate_pipeline.py:1-238](file://appv2/backend/appv2/domain/services/gate_pipeline.py#L1-L238)

### Session Strategy Configuration
The session strategy selector provides exchange-specific configurations with different trading modes for various market sessions and exchanges.

```mermaid
classDiagram
class SessionStrategySelector {
+get_config(session_phase, exchange) SessionStrategyConfig
+can_enter_trade(session_phase, direction, aggression_score, rr_ratio, exchange) tuple
}
class SessionStrategyConfig {
+mode StrategyMode
+allowed_directions str[]
+min_aggression_score float
+min_rr_ratio float
+max_position_size_pct float
+description str
}
class StrategyMode {
<<enumeration>>
TREND_FOLLOWING
MEAN_REVERSION
NO_TRADE
EXIT_ONLY
SELECTIVE
}
SessionStrategySelector --> SessionStrategyConfig : "returns"
SessionStrategyConfig --> StrategyMode : "uses"
```

**Diagram sources**
- [session_strategy_selector.py:125-198](file://appv2/backend/appv2/domain/services/session_strategy_selector.py#L125-L198)
- [session_strategy_selector.py:28-44](file://appv2/backend/appv2/domain/services/session_strategy_selector.py#L28-L44)

**Section sources**
- [session_strategy_selector.py:1-198](file://appv2/backend/appv2/domain/services/session_strategy_selector.py#L1-L198)

### Risk Management and Circuit Breakers
The risk orchestrator implements comprehensive risk controls including daily loss tracking, circuit breakers, and position sizing validation.

```mermaid
classDiagram
class RiskOrchestrator {
+pre_trade_check(symbol, entry_price, stop_loss, lot_size, open_positions_for_symbol) RiskCheckResult
+post_trade_update(symbol, pnl, is_win)
+position_opened(symbol)
+position_closed(symbol)
+reset_daily()
+daily_pnl float
+is_halted bool
}
class RiskCheckResult {
+allowed bool
+reason str
+details str
}
class DailyLossTracker {
+daily_pnl float
+is_halted bool
+record_trade(pnl)
+reset()
}
class CircuitBreaker {
+is_open bool
+remaining_cooldown_seconds float
+record_win()
+record_loss()
}
RiskOrchestrator --> RiskCheckResult : "returns"
RiskOrchestrator --> DailyLossTracker : "uses"
RiskOrchestrator --> CircuitBreaker : "manages"
```

**Diagram sources**
- [risk_orchestrator.py:35-160](file://appv2/backend/appv2/application/risk_orchestrator.py#L35-L160)
- [risk_orchestrator.py:28-33](file://appv2/backend/appv2/application/risk_orchestrator.py#L28-L33)

**Section sources**
- [risk_orchestrator.py:1-160](file://appv2/backend/appv2/application/risk_orchestrator.py#L1-L160)

### Streaming Infrastructure and WebSocket Management
The StreamManager provides robust WebSocket connectivity with auto-reconnect, heartbeat monitoring, and emergency pause/resume functionality.

```mermaid
sequenceDiagram
participant Client as "TradingEngine"
participant SM as "StreamManager"
participant WS as "WebSocket Server"
participant Broker as "Dhan Adapter"
Client->>SM : start()
SM->>WS : connect()
WS-->>SM : connected
SM->>Broker : start_stream(handle_tick)
SM->>SM : start heartbeat loop
loop Tick Processing
SM->>WS : receive tick
WS-->>SM : tick data
SM->>Client : on_tick(symbol, tick)
Client->>Client : process tick
end
Note over SM,WS : Heartbeat Monitoring
SM->>SM : check last_tick_time
alt No ticks for >30s
SM->>SM : mark disconnected
SM->>SM : schedule reconnect
else Normal operation
SM->>SM : continue monitoring
end
SM->>Broker : restart stream
Broker-->>SM : reconnected
SM->>SM : resubscribe symbols
```

**Diagram sources**
- [stream_manager.py:82-271](file://appv2/backend/appv2/infrastructure/stream_manager.py#L82-L271)

**Section sources**
- [stream_manager.py:1-271](file://appv2/backend/appv2/infrastructure/stream_manager.py#L1-L271)

### Data Pipeline and AMT Analysis
The data pipeline processes raw ticks through a comprehensive AMT analysis pipeline producing ready-to-use market observations.

```mermaid
flowchart TD
A["Raw Tick Input"] --> B["Candle Aggregation"]
B --> C["Volume Profile Update"]
C --> D["VWAP Calculation"]
D --> E["CVD Tracking"]
E --> F["POC + Value Area Computation"]
F --> G["AMT Observation Output"]
G --> H["StrategyOrchestrator"]
H --> I["Gate Pipeline"]
I --> J["Signal Generation"]
J --> K["Entry Execution"]
```

**Diagram sources**
- [data_pipeline.py:67-114](file://appv2/backend/appv2/application/data_pipeline.py#L67-L114)
- [strategy_orchestrator.py:75-136](file://appv2/backend/appv2/application/strategy_orchestrator.py#L75-L136)

**Section sources**
- [data_pipeline.py:1-151](file://appv2/backend/appv2/application/data_pipeline.py#L1-L151)
- [strategy_orchestrator.py:1-245](file://appv2/backend/appv2/application/strategy_orchestrator.py#L1-L245)

## Dependency Analysis
The appv2 architecture establishes clear dependency relationships between components:
- TradingEngine depends on StrategyOrchestrator, EntryCoordinator, ExitCoordinator, and RiskOrchestrator
- StrategyOrchestrator depends on MLX adapters, gate pipeline, and session strategy selector
- MLX adapters integrate with existing prompt builders and response parsers
- Gate pipeline provides validation for all trading decisions
- Session strategy selector configures appropriate trading modes per market session
- Risk orchestrator coordinates with position sizing and circuit breakers
- Stream manager provides robust connectivity for all trading activities

```mermaid
graph LR
TE["TradingEngine"] --> SO["StrategyOrchestrator"]
TE --> EC["EntryCoordinator"]
TE --> XC["ExitCoordinator"]
TE --> RO["RiskOrchestrator"]
SO --> MLX["MLX Adapters"]
SO --> GP["Gate Pipeline"]
SO --> SSS["Session Strategy"]
EC --> RO
XC --> RO
TE --> SM["StreamManager"]
SM --> BR["Broker Adapter"]
TE --> SET["Settings"]
```

**Diagram sources**
- [trading_engine.py:114-129](file://appv2/backend/appv2/application/trading_engine.py#L114-L129)
- [strategy_orchestrator.py:138-162](file://appv2/backend/appv2/application/strategy_orchestrator.py#L138-L162)
- [mlx_adapters.py:386-402](file://appv2/backend/appv2/domain/services/mlx_adapters.py#L386-L402)
- [gate_pipeline.py:197-238](file://appv2/backend/appv2/domain/services/gate_pipeline.py#L197-L238)
- [session_strategy_selector.py:129-159](file://appv2/backend/appv2/domain/services/session_strategy_selector.py#L129-L159)
- [risk_orchestrator.py:107-141](file://appv2/backend/appv2/application/risk_orchestrator.py#L107-L141)
- [stream_manager.py:33-73](file://appv2/backend/appv2/infrastructure/stream_manager.py#L33-L73)
- [settings.py:12-123](file://appv2/backend/appv2/config/settings.py#L12-L123)

**Section sources**
- [trading_engine.py:1-638](file://appv2/backend/appv2/application/trading_engine.py#L1-L638)
- [strategy_orchestrator.py:1-245](file://appv2/backend/appv2/application/strategy_orchestrator.py#L1-L245)
- [mlx_adapters.py:1-658](file://appv2/backend/appv2/domain/services/mlx_adapters.py#L1-L658)
- [gate_pipeline.py:1-238](file://appv2/backend/appv2/domain/services/gate_pipeline.py#L1-L238)
- [session_strategy_selector.py:1-198](file://appv2/backend/appv2/domain/services/session_strategy_selector.py#L1-L198)
- [risk_orchestrator.py:1-160](file://appv2/backend/appv2/application/risk_orchestrator.py#L1-L160)
- [stream_manager.py:1-271](file://appv2/backend/appv2/infrastructure/stream_manager.py#L1-L271)
- [settings.py:1-123](file://appv2/backend/appv2/config/settings.py#L1-L123)

## Performance Considerations
The appv2 architecture implements several performance optimization strategies:
- **Tick Throttling**: 500ms minimum interval per symbol reduces computational overhead while maintaining responsiveness
- **Lazy MLX Loading**: Model loading occurs on-demand with thread-safe initialization to minimize startup time
- **Asynchronous Processing**: All MLX inference operations use asyncio with configurable timeouts to prevent blocking
- **Efficient Data Structures**: Bounded deques and cached state objects minimize memory overhead
- **Heartbeat Monitoring**: Automatic WebSocket reconnect with exponential backoff prevents resource waste during disconnections
- **Latency Tracking**: Comprehensive p50/p95/p99 latency metrics enable performance monitoring and optimization
- **Gate Rejection Tracking**: Statistical tracking of gate failures helps identify bottlenecks in the decision pipeline
- **Vectorized Computations**: AMT calculations use optimized mathematical operations for candle processing

## Troubleshooting Guide
Common issues and resolutions for the appv2 architecture:
- **MLX Model Loading Failures**: Verify MLX model path exists and mlx-lm/mlx_vlm packages are installed; check lazy loader error messages
- **Gate Pipeline Rejections**: Review gate failure reasons and adjust thresholds in constants.py; ensure sufficient data quality
- **Session Strategy Misconfiguration**: Verify exchange settings and session phase detection; check strategy mode compatibility
- **Risk Orchestrator Failures**: Confirm daily loss limits and circuit breaker settings; review position sizing calculations
- **WebSocket Connectivity Issues**: Check heartbeat monitoring logs; verify auto-reconnect functionality and symbol resubscription
- **MLX Timeout Errors**: Increase timeout values in MLX adapters; consider rule-based fallback implementation
- **Tick Throttle Delays**: Monitor 500ms interval effectiveness; adjust throttle settings based on market conditions
- **Gate Rejection Statistics**: Analyze rejection rates to identify systematic pipeline issues

**Section sources**
- [mlx_adapters.py:87-116](file://appv2/backend/appv2/domain/services/mlx_adapters.py#L87-L116)
- [gate_pipeline.py:224-237](file://appv2/backend/appv2/domain/services/gate_pipeline.py#L224-L237)
- [session_strategy_selector.py:147-159](file://appv2/backend/appv2/domain/services/session_strategy_selector.py#L147-L159)
- [risk_orchestrator.py:69-105](file://appv2/backend/appv2/application/risk_orchestrator.py#L69-L105)
- [stream_manager.py:169-256](file://appv2/backend/appv2/infrastructure/stream_manager.py#L169-L256)

## Conclusion
GlassyTrade AI v5 appv2 represents a comprehensive evolution in algorithmic trading architecture, integrating advanced MLX adapters with sophisticated risk management, gate validation systems, and robust streaming infrastructure. The modular design enables seamless extension through custom strategies, ML workflows, and regime-aware logic. By leveraging the TradingEngine's comprehensive service orchestration, the MLX adapter system's intelligent decision-making, and the extensive gate pipeline validation, teams can develop and deploy proprietary algorithms with enhanced reliability and performance. The architecture's emphasis on observability, resilience, and scalability provides a solid foundation for production trading systems.

## Appendices

### Practical Examples Index
- **Custom Strategy Development**: Implement new market state machines in StrategyOrchestrator; extend gate pipeline with custom validation rules
- **MLX Model Integration**: Deploy custom LLM models through MLX adapters; implement custom prompt builders and response parsers
- **Advanced Risk Management**: Configure custom circuit breakers and position sizing algorithms; implement session-specific risk controls
- **Performance Optimization**: Tune tick throttling intervals; optimize MLX inference parameters; implement custom latency tracking
- **Streaming Enhancements**: Extend StreamManager with custom broker adapters; implement advanced heartbeat monitoring
- **Session Strategy Extension**: Add new exchange configurations; implement custom trading modes for different market conditions