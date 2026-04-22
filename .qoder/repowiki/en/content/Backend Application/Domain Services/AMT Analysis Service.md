# AMT Analysis Service

<cite>
**Referenced Files in This Document**
- [amt_handler.py](file://backend/app/application/handlers/amt_handler.py)
- [state_broadcaster.py](file://backend/app/application/services/state_broadcaster.py)
- [signal_tracking_service.py](file://backend/app/application/services/signal_tracking_service.py)
- [post_trade_analyst.py](file://backend/app/application/handlers/post_trade_analyst.py)
- [state_snapshot_builder.py](file://backend/app/application/services/state_snapshot_builder.py)
- [entry_coordinator.py](file://backend/app/application/services/entry_coordinator.py)
- [exit_coordinator.py](file://backend/app/application/services/exit_coordinator.py)
- [DEPLOYMENT_GUIDE.md](file://appv2/DEPLOYMENT_GUIDE.md)
- [ARCHITECTURE_DEEP_DIVE.md](file://backend/ARCHITECTURE_DEEP_DIVE.md)
</cite>

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

## Introduction
The AMT Analysis Service is the core market context analysis engine responsible for generating Advanced Market Timing insights and order flow footprint data on every incoming tick. It processes OHLC market data, order book snapshots, and historical context to produce actionable market state information including Point of Control (POC), Value Area High (VAH), Value Area Low (VAL), Liquidity Zone Numbers (LVN/HVN), and aggression scores. The service operates continuously alongside the trading pipeline, providing real-time market structure analysis that informs higher-level decision-making systems.

## Project Structure
The AMT Analysis Service is organized within the backend application's application layer, with clear separation of concerns between analysis handlers, state management, and integration services. The service integrates deeply with the trading engine while maintaining independence for analysis-only operations.

```mermaid
graph TB
subgraph "AMT Analysis Layer"
AMTH[AMTHandler]
FP[FootprintAnalyzer]
IVP[IncrementalVolumeProfile]
end
subgraph "State Management"
SB[StateBroadcaster]
SSB[StateSnapshotBuilder]
STS[SignalTrackingService]
end
subgraph "Integration Layer"
ECS[EntryCoordinator]
XCS[ExitCoordinator]
PTA[PostTradeAnalyst]
end
subgraph "External Systems"
WS[WebSocket Clients]
LLM[LLM Services]
BROKER[Broker Adapter]
end
AMTH --> FP
AMTH --> IVP
AMTH --> SB
SB --> SSB
SB --> WS
ECS --> AMTH
XCS --> PTA
PTA --> LLM
ECS --> BROKER
```

**Diagram sources**
- [amt_handler.py:45-196](file://backend/app/application/handlers/amt_handler.py#L45-L196)
- [state_broadcaster.py:27-364](file://backend/app/application/services/state_broadcaster.py#L27-L364)
- [signal_tracking_service.py:72-386](file://backend/app/application/services/signal_tracking_service.py#L72-L386)

**Section sources**
- [DEPLOYMENT_GUIDE.md:111-141](file://appv2/DEPLOYMENT_GUIDE.md#L111-L141)
- [ARCHITECTURE_DEEP_DIVE.md:365-440](file://backend/ARCHITECTURE_DEEP_DIVE.md#L365-L440)

## Core Components

### AMTHandler - Primary Analysis Engine
The AMTHandler serves as the central orchestrator for all market context analysis. It manages incremental volume profile updates, handles day-boundary detection, and coordinates between different analysis components.

**Key Features:**
- **Incremental Volume Profile Management**: Maintains two profile windows - a long-term 1000-candle profile and a short-term developing VA profile
- **Session-Aware Data Filtering**: Applies appropriate data filtering based on instrument type (options vs commodities)
- **Real-time State Caching**: Caches profile arrays to minimize frontend redraws during sub-candle updates
- **Day Boundary Detection**: Automatically rebuilds profiles when trading sessions change

**Processing Pipeline:**
1. Convert Decimal-based OHLC to float for analysis
2. Detect trading day boundaries and reset profiles accordingly
3. Filter data based on session requirements
4. Update incremental volume profiles (full rebuild or incremental update)
5. Execute AMT analysis with both profiles
6. Generate footprint data for order flow visualization
7. Cache results for efficient state broadcasting

**Section sources**
- [amt_handler.py:45-196](file://backend/app/application/handlers/amt_handler.py#L45-L196)

### StateBroadcaster - Real-time State Distribution
The StateBroadcaster manages the distribution of analysis results to connected WebSocket clients, implementing sophisticated throttling and generation tracking mechanisms.

**Core Responsibilities:**
- **Generation Counter Management**: Tracks state updates across all symbols
- **Throttled Notifications**: Prevents client flooding through configurable intervals
- **Thread-Safe State Updates**: Provides safe access patterns for concurrent environments
- **Viewer Synchronization**: Enables clients to track state changes via generation counters

**Notification Flow:**
```mermaid
sequenceDiagram
participant Engine as TradingEngine
participant SB as StateBroadcaster
participant Clients as WebSocket Clients
Engine->>SB : trigger_immediate_update()
SB->>SB : build_state_snapshot()
SB->>SB : set_state(symbol, state)
SB->>SB : notify_viewers()
SB->>Clients : Broadcast state update
Clients->>SB : Wait for generation advance
SB->>Clients : Generation counter update
```

**Diagram sources**
- [state_broadcaster.py:234-306](file://backend/app/application/services/state_broadcaster.py#L234-L306)

**Section sources**
- [state_broadcaster.py:27-364](file://backend/app/application/services/state_broadcaster.py#L27-L364)

### SignalTrackingService - Decision Analytics
The SignalTrackingService provides comprehensive analytics of the signal generation pipeline, tracking every decision point from gate evaluations to final signal execution.

**Tracking Capabilities:**
- **Gate Block Analysis**: Detailed tracking of why signals are blocked at various gates
- **Generation Rate Monitoring**: Statistics on signal generation vs rejection rates
- **Quality Assessment**: Win rate analysis by gate passage
- **Timing Pattern Recognition**: When signals cluster and market conditions

**Data Structure:**
The service maintains a comprehensive decision log with timestamps, gate information, market context, and agent/LMM inputs for post-trade analysis and system optimization.

**Section sources**
- [signal_tracking_service.py:72-386](file://backend/app/application/services/signal_tracking_service.py#L72-L386)

## Architecture Overview

The AMT Analysis Service operates within a sophisticated trading engine architecture that separates concerns across multiple layers while maintaining tight integration for optimal performance.

```mermaid
graph TB
subgraph "Data Ingestion Layer"
Tick[Tick Stream]
Candle[Candle Aggregation]
end
subgraph "Analysis Layer"
AMTH[AMTHandler]
Analyzer[AMTAnalyzer]
FP[FootprintAnalyzer]
IVP[IncrementalVolumeProfile]
end
subgraph "State Management"
SB[StateBroadcaster]
SSB[StateSnapshotBuilder]
SS[Session State]
end
subgraph "Decision Layer"
EC[EntryCoordinator]
RC[RiskCoordinator]
LC[TradeLifecycleHandler]
end
subgraph "External Interfaces"
WS[WebSocket API]
Broker[Broker Adapter]
LLM[LLM Services]
end
Tick --> Candle
Candle --> AMTH
AMTH --> Analyzer
AMTH --> FP
AMTH --> IVP
AMTH --> SB
SB --> SSB
SSB --> SS
SS --> EC
EC --> RC
EC --> LC
LC --> Broker
SB --> WS
EC --> LLM
```

**Diagram sources**
- [ARCHITECTURE_DEEP_DIVE.md:365-440](file://backend/ARCHITECTURE_DEEP_DIVE.md#L365-L440)
- [amt_handler.py:89-196](file://backend/app/application/handlers/amt_handler.py#L89-L196)

The architecture follows several key design patterns:
- **Facade Pattern**: AMTHandler provides a unified interface to complex analysis operations
- **Observer Pattern**: StateBroadcaster notifies interested parties of state changes
- **Command Pattern**: EntryCoordinator encapsulates execution logic for signals
- **Strategy Pattern**: Different analysis strategies can be applied based on market conditions

## Detailed Component Analysis

### AMTHandler Implementation Details

The AMTHandler implements a sophisticated incremental analysis system designed for high-frequency market data processing with minimal computational overhead.

```mermaid
classDiagram
class AMTHandler {
-_LOOKBACK : int
-_DEV_LOOKBACK : int
-_amt_analyzer : AMTAnalyzer
-_footprint_analyzer : FootprintAnalyzer
-_inc_profile : IncrementalVolumeProfile
-_dev_profile : IncrementalVolumeProfile
-_prev_data_len : int
-_session_only_vp : bool
-_trading_date : str
-_cached_profile : list
-_cached_leg_profile : list
+analyze(data, order_book, prior_poc, prior_vah, prior_val) tuple
+_to_float_ohlc(data) list
+_filter_today_session(data) list
}
class IncrementalVolumeProfile {
+update(candle, oldest) void
+get_profile() dict
+get_developing_profile() dict
}
class AMTAnalyzer {
+analyze(data, order_book, incremental_profile, prior_poc, prior_vah, prior_val) AMTResult
}
class FootprintAnalyzer {
+generate(data) dict
}
AMTHandler --> IncrementalVolumeProfile : manages
AMTHandler --> AMTAnalyzer : uses
AMTHandler --> FootprintAnalyzer : uses
```

**Diagram sources**
- [amt_handler.py:45-196](file://backend/app/application/handlers/amt_handler.py#L45-L196)

**Processing Logic Flow:**
```mermaid
flowchart TD
Start([Tick Received]) --> Convert["Convert OHLC to float"]
Convert --> DayCheck{"Day Boundary?"}
DayCheck --> |Yes| ResetProfiles["Reset Incremental Profiles"]
DayCheck --> |No| FilterData["Filter Today's Session Data"]
ResetProfiles --> FilterData
FilterData --> CheckGrowth{"Data Growth?"}
CheckGrowth --> |New Candle| IncUpdate["Incremental Profile Update"]
CheckGrowth --> |Bulk Load| FullRebuild["Full Profile Rebuild"]
CheckGrowth --> |No Change| SkipUpdate["Skip Profile Update"]
IncUpdate --> RunAnalysis["Execute AMT Analysis"]
FullRebuild --> RunAnalysis
SkipUpdate --> CacheCheck{"New Candle?"}
CacheCheck --> |Yes| CacheProfiles["Cache Profile Arrays"]
CacheCheck --> |No| UseCached["Use Cached Profiles"]
CacheProfiles --> RunAnalysis
UseCached --> RunAnalysis
RunAnalysis --> GenerateFootprint["Generate Footprint Data"]
GenerateFootprint --> ReturnResults["Return Analysis Results"]
```

**Diagram sources**
- [amt_handler.py:89-196](file://backend/app/application/handlers/amt_handler.py#L89-L196)

**Performance Optimizations:**
- **Profile Caching**: Prevents redundant calculations during sub-candle updates
- **Adaptive Lookback**: Adjusts profile window size based on available data
- **Session-Aware Filtering**: Optimizes data processing for different instrument types
- **Memory Management**: Efficient list reuse to minimize garbage collection pressure

**Section sources**
- [amt_handler.py:45-196](file://backend/app/application/handlers/amt_handler.py#L45-L196)

### State Management and Distribution

The state management system provides a robust foundation for real-time market data distribution with sophisticated concurrency controls and notification mechanisms.

```mermaid
sequenceDiagram
participant Producer as AMTHandler
participant SB as StateBroadcaster
participant SS as StateSnapshotBuilder
participant Clients as WebSocket Clients
Producer->>SB : trigger_immediate_update()
SB->>SS : build_state_snapshot(session, risk, rl, lifecycle)
SS->>SS : Build portfolio DTO
SS->>SS : Extract last AMT results
SS->>SS : Add AI analysis and stats
SS-->>SB : Complete state snapshot
SB->>SB : set_state(symbol, state)
SB->>SB : notify_viewers()
loop For each waiting client
Clients->>SB : wait_for_update(known_gen)
SB->>Clients : Generation counter advance
Clients->>SB : get_latest_state(symbol)
SB-->>Clients : Shallow copy of state
end
```

**Diagram sources**
- [state_broadcaster.py:247-306](file://backend/app/application/services/state_broadcaster.py#L247-L306)
- [state_snapshot_builder.py:23-85](file://backend/app/application/services/state_snapshot_builder.py#L23-L85)

**Concurrency Controls:**
- **Per-Symbol Locks**: Prevent race conditions during state updates
- **Thread-Safe Access**: Copy-on-read patterns prevent data corruption
- **Event Loop Integration**: Cross-thread notifications via asyncio event loops
- **Generation Tracking**: Client-side synchronization through generation counters

**Section sources**
- [state_broadcaster.py:27-364](file://backend/app/application/services/state_broadcaster.py#L27-L364)
- [state_snapshot_builder.py:23-190](file://backend/app/application/services/state_snapshot_builder.py#L23-L190)

### Signal Generation and Tracking

The signal tracking system provides comprehensive analytics of the entire signal generation pipeline, enabling detailed post-trade analysis and system optimization.

```mermaid
classDiagram
class SignalTrackingService {
-_storage : IStorage
-_decisions : dict[str, list[SignalDecision]]
-_stats : dict[str, dict]
+track_signal_generated() SignalDecision
+track_gate_block() SignalDecision
+track_waiting() SignalDecision
+track_cooldown() SignalDecision
+get_stats(symbol) dict
+get_recent_decisions(limit) list
+clear(symbol) void
}
class SignalDecision {
+decision_id : str
+symbol : str
+timestamp : str
+decision_type : str
+gate_name : str
+gate_reason : str
+direction : str
+confidence : str
+aggression_score : float
+market_state : str
+price : float
+poc : float
+vah : float
+val : float
+cvd_slope : float
}
SignalTrackingService --> SignalDecision : manages
```

**Diagram sources**
- [signal_tracking_service.py:72-386](file://backend/app/application/services/signal_tracking_service.py#L72-L386)

**Analytics Features:**
- **Gate Performance Analysis**: Detailed breakdown of which gates block most frequently
- **Quality Metrics**: Win rate analysis by gate passage and market state
- **Timing Intelligence**: Pattern recognition for signal clustering and timing
- **Context Tracking**: Comprehensive market context for each decision point

**Section sources**
- [signal_tracking_service.py:72-386](file://backend/app/application/services/signal_tracking_service.py#L72-L386)

### Post-Trade Analysis Integration

The post-trade analysis system provides automated quality assessment of completed trades, integrating with LLM services for continuous improvement.

```mermaid
sequenceDiagram
participant EC as ExitCoordinator
participant PTA as PostTradeAnalyst
participant LLM as GenerativeAIService
participant Storage as IStorage
EC->>PTA : analyze(symbol, prices, pnl, duration, reason)
PTA->>PTA : build_post_trade_prompt()
PTA->>LLM : predict(instruction, prompt)
LLM-->>PTA : raw_response
PTA->>PTA : parse_post_trade_response()
PTA->>Storage : kv_set(post_trade : symbol, analysis)
PTA-->>EC : analysis complete
Note over PTA : Non-blocking with 30s timeout
```

**Diagram sources**
- [post_trade_analyst.py:136-262](file://backend/app/application/handlers/post_trade_analyst.py#L136-L262)

**Analysis Capabilities:**
- **Quality Scoring**: Automated 1-10 quality assessment of trades
- **Mistake Identification**: Systematic identification of trading mistakes
- **Improvement Recommendations**: Actionable suggestions for performance enhancement
- **Learning Integration**: Results fed back into the learning system

**Section sources**
- [post_trade_analyst.py:118-262](file://backend/app/application/handlers/post_trade_analyst.py#L118-L262)

## Dependency Analysis

The AMT Analysis Service exhibits excellent modularity with clear dependency boundaries and well-defined interfaces between components.

```mermaid
graph TB
subgraph "Internal Dependencies"
AMTH[AMTHandler] --> Analyzer[AMTAnalyzer]
AMTH --> FP[FootprintAnalyzer]
AMTH --> IVP[IncrementalVolumeProfile]
SB[StateBroadcaster] --> SSB[StateSnapshotBuilder]
EC[EntryCoordinator] --> AMTH
XCS[ExitCoordinator] --> PTA[PostTradeAnalyst]
end
subgraph "External Dependencies"
SB --> WS[WebSocket Protocol]
EC --> Broker[Broker Interface]
PTA --> LLM[Generative AI Service]
STS[SignalTrackingService] --> Storage[IStorage]
end
subgraph "Infrastructure"
Logger[Logging Framework]
Timezone[IST Timezone Utils]
Serialization[DTO Serialization]
end
AMTH --> Logger
SB --> Logger
EC --> Logger
XCS --> Logger
PTA --> Logger
AMTH --> Timezone
AMTH --> Serialization
SB --> Serialization
```

**Dependency Characteristics:**
- **High Cohesion**: Each component has a single, well-defined responsibility
- **Low Coupling**: Clear interfaces minimize inter-component dependencies
- **Testability**: All dependencies are injectable, enabling comprehensive testing
- **Extensibility**: Well-defined interfaces support easy extension and replacement

**Potential Issues:**
- **Circular Dependencies**: None detected in current implementation
- **Tight Coupling**: Some components share common interfaces that could be extracted
- **External Dependencies**: LLM services introduce latency and reliability concerns

**Section sources**
- [amt_handler.py:9-11](file://backend/app/application/handlers/amt_handler.py#L9-L11)
- [state_broadcaster.py:18-21](file://backend/app/application/services/state_broadcaster.py#L18-L21)

## Performance Considerations

The AMT Analysis Service is designed for high-frequency market data processing with several built-in optimizations:

**Memory Management:**
- Profile array caching prevents unnecessary object creation during sub-candle updates
- Incremental profile updates minimize computational overhead
- Adaptive lookback windows optimize memory usage based on available data

**Processing Efficiency:**
- Float conversion occurs only once per analysis cycle
- Session-aware filtering reduces data processing volume
- Thread-safe operations minimize contention in concurrent environments

**Network Optimization:**
- State broadcasting implements throttling to prevent client flooding
- Generation counters enable efficient client synchronization
- DTO serialization minimizes payload sizes

**Scalability Factors:**
- Per-symbol state management supports multi-symbol deployments
- Asynchronous processing enables non-blocking operations
- Modular design allows for horizontal scaling

## Troubleshooting Guide

### Common Issues and Solutions

**AMTHandler Performance Degradation:**
- **Symptoms**: Slow analysis times, increased memory usage
- **Causes**: Large lookback windows, insufficient data filtering
- **Solutions**: Adjust `_LOOKBACK` values, implement proper session filtering

**State Broadcasting Failures:**
- **Symptoms**: Clients not receiving updates, generation counter stalls
- **Causes**: Event loop not properly configured, connection timeouts
- **Solutions**: Verify event loop setup, check network connectivity

**Signal Tracking Inconsistencies:**
- **Symptoms**: Missing or duplicate tracking entries
- **Causes**: Race conditions, storage failures
- **Solutions**: Implement proper locking, add retry mechanisms

**Post-Trade Analysis Failures:**
- **Symptoms**: Analysis timeouts, LLM service unavailability
- **Causes**: Network latency, service downtime
- **Solutions**: Implement fallback mechanisms, add monitoring alerts

**Section sources**
- [state_broadcaster.py:207-222](file://backend/app/application/services/state_broadcaster.py#L207-L222)
- [post_trade_analyst.py:254-257](file://backend/app/application/handlers/post_trade_analyst.py#L254-L257)

### Monitoring and Debugging

**Key Metrics to Monitor:**
- Analysis processing time per tick
- State broadcast frequency and latency
- Signal generation rates and quality scores
- Post-trade analysis completion rates

**Debugging Tools:**
- Logging at INFO level for normal operations
- DEBUG level for detailed analysis traces
- Performance profiling for bottleneck identification

**Section sources**
- [signal_tracking_service.py:129-137](file://backend/app/application/services/signal_tracking_service.py#L129-L137)
- [state_broadcaster.py:213-221](file://backend/app/application/services/state_broadcaster.py#L213-L221)

## Conclusion

The AMT Analysis Service represents a sophisticated, production-ready market context analysis system that successfully balances performance, scalability, and maintainability. Its modular design enables seamless integration with broader trading systems while providing comprehensive market structure analysis capabilities.

**Key Strengths:**
- **Robust Architecture**: Clear separation of concerns with well-defined interfaces
- **Performance Optimization**: Sophisticated caching and incremental processing strategies
- **Real-time Capabilities**: Efficient state broadcasting and client synchronization
- **Comprehensive Analytics**: Detailed signal tracking and post-trade analysis integration

**Areas for Enhancement:**
- **Error Resilience**: Enhanced fallback mechanisms for external service dependencies
- **Monitoring**: Expanded metrics collection and alerting capabilities
- **Testing**: Additional integration tests for complex failure scenarios
- **Documentation**: Inline code documentation for complex algorithms

The service provides a solid foundation for advanced trading applications, with clear pathways for extension and optimization as trading requirements evolve.