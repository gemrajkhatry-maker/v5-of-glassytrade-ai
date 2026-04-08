# Custom Strategy Development

<cite>
**Referenced Files in This Document**
- [multi_timeframe_amt.py](file://backend/app/domain/fabio_ai/services/multi_timeframe_amt.py)
- [amt_handler.py](file://backend/app/application/handlers/amt_handler.py)
- [entry_gate_coordinator.py](file://backend/app/application/handlers/entry_gate_coordinator.py)
- [signal_constructor.py](file://backend/app/application/handlers/signal_constructor.py)
- [signal_tracking_service.py](file://backend/app/application/services/signal_tracking_service.py)
- [backtest_engine.py](file://backend/app/application/services/backtest_engine.py)
- [risk_sizing_engine.py](file://backend/app/domain/services/risk_sizing_engine.py)
- [protocols.py](file://backend/app/domain/fabio_ai/strategy/protocols.py)
- [probability_inference.py](file://backend/app/domain/ports/probability_inference.py)
- [lgbm_probability_adapter.py](file://backend/app/infrastructure/adapters/lgbm_probability_adapter.py)
- [events.py](file://backend/app/domain/trading/events.py)
- [signal_validator.py](file://backend/app/domain/trading/services/signal_validator.py)
- [experiment_context.py](file://backend/app/application/services/experiment_context.py)
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
10. [Appendices](#appendices)

## Introduction
This document explains how to develop custom trading strategies in GlassyTrade AI v5 using the gate pipeline architecture. It covers creating custom entry/exit strategies, implementing custom entry gates, composing strategies across multiple timeframes, integrating machine learning-enhanced rules, validating signals, and evaluating performance via backtesting and risk management. Practical examples include AMT-based strategies, multi-timeframe alignment strategies, and ML-enhanced trading rules. Guidance is also provided for parameter tuning, dynamic strategy switching, and integrating external market indicators and adaptive position sizing.

## Project Structure
GlassyTrade AI v5 organizes strategy development around:
- Domain services for market analysis (AMT, footprint, probability inference)
- Application handlers for gate coordination, signal construction, and lifecycle orchestration
- Infrastructure adapters for ML models and persistence
- Services for risk sizing, signal tracking, and backtesting

```mermaid
graph TB
subgraph "Domain"
A["AMT Analyzer<br/>multi_timeframe_amt.py"]
B["Probability Inference Port<br/>probability_inference.py"]
end
subgraph "Application Handlers"
C["Entry Gate Coordinator<br/>entry_gate_coordinator.py"]
D["Signal Constructor<br/>signal_constructor.py"]
E["AMT Handler<br/>amt_handler.py"]
end
subgraph "Infrastructure"
F["LGBM Adapter<br/>lgbm_probability_adapter.py"]
end
subgraph "Services"
G["Risk Sizing Engine<br/>risk_sizing_engine.py"]
H["Signal Tracking Service<br/>signal_tracking_service.py"]
I["Backtest Engine<br/>backtest_engine.py"]
end
E --> A
D --> C
C --> A
B --> F
D --> B
D --> G
H --> D
I --> D
```

**Diagram sources**
- [multi_timeframe_amt.py:1-507](file://backend/app/domain/fabio_ai/services/multi_timeframe_amt.py#L1-L507)
- [amt_handler.py:1-181](file://backend/app/application/handlers/amt_handler.py#L1-L181)
- [entry_gate_coordinator.py:1-235](file://backend/app/application/handlers/entry_gate_coordinator.py#L1-L235)
- [signal_constructor.py:1-275](file://backend/app/application/handlers/signal_constructor.py#L1-L275)
- [risk_sizing_engine.py:1-88](file://backend/app/domain/services/risk_sizing_engine.py#L1-L88)
- [signal_tracking_service.py:1-385](file://backend/app/application/services/signal_tracking_service.py#L1-L385)
- [backtest_engine.py:1-99](file://backend/app/application/services/backtest_engine.py#L1-L99)
- [probability_inference.py:1-43](file://backend/app/domain/ports/probability_inference.py#L1-L43)
- [lgbm_probability_adapter.py:1-166](file://backend/app/infrastructure/adapters/lgbm_probability_adapter.py#L1-L166)

**Section sources**
- [multi_timeframe_amt.py:1-507](file://backend/app/domain/fabio_ai/services/multi_timeframe_amt.py#L1-L507)
- [amt_handler.py:1-181](file://backend/app/application/handlers/amt_handler.py#L1-L181)
- [entry_gate_coordinator.py:1-235](file://backend/app/application/handlers/entry_gate_coordinator.py#L1-L235)
- [signal_constructor.py:1-275](file://backend/app/application/handlers/signal_constructor.py#L1-L275)
- [risk_sizing_engine.py:1-88](file://backend/app/domain/services/risk_sizing_engine.py#L1-L88)
- [signal_tracking_service.py:1-385](file://backend/app/application/services/signal_tracking_service.py#L1-L385)
- [backtest_engine.py:1-99](file://backend/app/application/services/backtest_engine.py#L1-L99)
- [probability_inference.py:1-43](file://backend/app/domain/ports/probability_inference.py#L1-L43)
- [lgbm_probability_adapter.py:1-166](file://backend/app/infrastructure/adapters/lgbm_probability_adapter.py#L1-L166)

## Core Components
- AMT-based analysis and footprint generation: Provides market context (POC, VA, CVD slope, profile shape) used by gates and signals.
- Multi-timeframe alignment: Combines higher, session, and entry timeframe biases to determine alignment quality and position size multipliers.
- Entry gate coordinator: Orchestrates gate checks (three-align, momentum fade, gate pipeline, CVD hard gate, profile shape gate).
- Signal constructor: Builds validated trade signals enriched with metadata, thesis, and grade scores.
- Risk sizing engine: Deterministic Kelly-inspired sizing with dynamic risk tiers and scale-in plans.
- Signal tracking service: Records decision points, gate block reasons, and generates statistics for performance analysis.
- Backtest engine: Computes performance metrics from historical trade logs.
- Probability inference port and adapter: Provides first-passage probability estimates and dynamic targets for ML-enhanced rules.

**Section sources**
- [multi_timeframe_amt.py:74-164](file://backend/app/domain/fabio_ai/services/multi_timeframe_amt.py#L74-L164)
- [entry_gate_coordinator.py:25-125](file://backend/app/application/handlers/entry_gate_coordinator.py#L25-L125)
- [signal_constructor.py:32-186](file://backend/app/application/handlers/signal_constructor.py#L32-L186)
- [risk_sizing_engine.py:44-88](file://backend/app/domain/services/risk_sizing_engine.py#L44-L88)
- [signal_tracking_service.py:72-330](file://backend/app/application/services/signal_tracking_service.py#L72-L330)
- [backtest_engine.py:33-99](file://backend/app/application/services/backtest_engine.py#L33-L99)
- [probability_inference.py:9-43](file://backend/app/domain/ports/probability_inference.py#L9-L43)
- [lgbm_probability_adapter.py:24-155](file://backend/app/infrastructure/adapters/lgbm_probability_adapter.py#L24-L155)

## Architecture Overview
The strategy pipeline integrates AMT analysis, gate checks, and signal construction, with optional ML enhancements and risk management.

```mermaid
sequenceDiagram
participant Tick as "Tick Stream"
participant AMT as "AMT Handler"
participant Gate as "Entry Gate Coordinator"
participant Sig as "Signal Constructor"
participant Prob as "Probability Adapter"
participant Risk as "Risk Sizing Engine"
participant Track as "Signal Tracking Service"
Tick->>AMT : "OHLC + OrderBook"
AMT-->>Gate : "AMTResult + context"
Gate->>Gate : "Three-align + momentum fade + pipeline"
Gate-->>Sig : "Eligible context"
Sig->>Prob : "Features → ProbabilityEstimate"
Prob-->>Sig : "p_long/p_short + MFE"
Sig->>Risk : "Entry/SL/TP + equity/session PnL"
Risk-->>Sig : "Lots + scale-in plan"
Sig-->>Track : "Signal metadata"
Sig-->>Tick : "Signal (validated)"
```

**Diagram sources**
- [amt_handler.py:89-180](file://backend/app/application/handlers/amt_handler.py#L89-L180)
- [entry_gate_coordinator.py:32-125](file://backend/app/application/handlers/entry_gate_coordinator.py#L32-L125)
- [signal_constructor.py:39-107](file://backend/app/application/handlers/signal_constructor.py#L39-L107)
- [probability_inference.py:19-28](file://backend/app/domain/ports/probability_inference.py#L19-L28)
- [lgbm_probability_adapter.py:119-155](file://backend/app/infrastructure/adapters/lgbm_probability_adapter.py#L119-L155)
- [risk_sizing_engine.py:77-88](file://backend/app/domain/services/risk_sizing_engine.py#L77-L88)
- [signal_tracking_service.py:83-138](file://backend/app/application/services/signal_tracking_service.py#L83-L138)

## Detailed Component Analysis

### AMT-Based Strategy Foundation
- AMT handler maintains incremental volume profiles and builds AMTResult DTOs for downstream use.
- Multi-timeframe AMT analyzer derives directional bias from three timeframes and computes alignment strength and trade implications.

```mermaid
flowchart TD
Start(["New OHLC batch"]) --> Filter["Filter session-only data if configured"]
Filter --> UpdateVP["Update incremental profiles"]
UpdateVP --> Analyze["Run AMT analysis"]
Analyze --> Result["AMTResult + DTOs"]
Result --> End(["Context for gates/signals"])
```

**Diagram sources**
- [amt_handler.py:89-180](file://backend/app/application/handlers/amt_handler.py#L89-L180)
- [multi_timeframe_amt.py:210-261](file://backend/app/domain/fabio_ai/services/multi_timeframe_amt.py#L210-L261)

**Section sources**
- [amt_handler.py:45-180](file://backend/app/application/handlers/amt_handler.py#L45-L180)
- [multi_timeframe_amt.py:74-164](file://backend/app/domain/fabio_ai/services/multi_timeframe_amt.py#L74-L164)

### Gate Pipeline and Custom Entry Gates
- Entry gate coordinator orchestrates:
  - Three-align gate (multi-timeframe alignment)
  - Momentum fade detection
  - Gate pipeline checks (context-dependent)
  - CVD hard gate and profile shape gate
- Custom gates can be integrated by extending the pipeline in the coordinator and adding supporting logic in the gate module.

```mermaid
flowchart TD
A["Entry Eligibility Request"] --> B["Three-align check"]
B --> |Fail| R["Block: Three-align failed"]
B --> |Pass| C["Momentum fade check"]
C --> |Fade| R
C --> |No fade| D["Gate pipeline"]
D --> |Fail| R
D --> |Pass| E["CVD hard gate"]
E --> |Opposing| R
E --> |Pass| F["Profile shape gate"]
F --> |Blocks| R
F --> |Pass| OK["Eligible"]
```

**Diagram sources**
- [entry_gate_coordinator.py:32-125](file://backend/app/application/handlers/entry_gate_coordinator.py#L32-L125)

**Section sources**
- [entry_gate_coordinator.py:25-125](file://backend/app/application/handlers/entry_gate_coordinator.py#L25-L125)

### Signal Construction and Validation
- Signal constructor builds signals from agent decisions, enriches with metadata (thesis, grade score, conviction), and validates basic constraints (prices, R:R).
- Signal validation enforces freshness, direction consistency, and structural constraints.

```mermaid
sequenceDiagram
participant Builder as "Signal Constructor"
participant Thesis as "Trade Thesis"
participant Gate as "Entry Gate Coordinator"
participant Validator as "Signal Validator"
Builder->>Gate : "Context + agent decision"
Gate-->>Builder : "Eligible context"
Builder->>Thesis : "Build trade thesis"
Thesis-->>Builder : "Thesis metadata"
Builder->>Builder : "Compute grade score + conviction"
Builder-->>Validator : "Signal (validated)"
Validator-->>Builder : "Approval + reason"
```

**Diagram sources**
- [signal_constructor.py:39-186](file://backend/app/application/handlers/signal_constructor.py#L39-L186)
- [signal_validator.py:52-92](file://backend/app/domain/trading/services/signal_validator.py#L52-L92)

**Section sources**
- [signal_constructor.py:32-275](file://backend/app/application/handlers/signal_constructor.py#L32-L275)
- [signal_validator.py:52-92](file://backend/app/domain/trading/services/signal_validator.py#L52-L92)
- [events.py:125-173](file://backend/app/domain/trading/events.py#L125-L173)

### Risk Management and Adaptive Position Sizing
- Risk sizing engine computes position size using deterministic Kelly-like logic, adjusting for session PnL, consecutive losses, and minimum/maximum risk tiers.
- Supports scale-in allocation across multiple entries.

```mermaid
flowchart TD
Start(["Entry/SL/TP + equity + session PnL"]) --> RR["Check R:R ≥ threshold"]
RR --> |Fail| Block["Block trade"]
RR --> |Pass| Risk["Compute risk amount (risk_pct × equity)"]
Risk --> Lot["risk_per_lot = distance × point_value"]
Lot --> Lots["lots = floor(max_risk / risk_per_lot)"]
Lots --> Scale["Apply scale-in plan (e.g., 40%/30%/30%)"]
Scale --> End(["Approved sizing"])
```

**Diagram sources**
- [risk_sizing_engine.py:77-88](file://backend/app/domain/services/risk_sizing_engine.py#L77-L88)

**Section sources**
- [risk_sizing_engine.py:44-88](file://backend/app/domain/services/risk_sizing_engine.py#L44-L88)

### Machine Learning-Enhanced Trading Rules
- Probability inference port abstracts first-passage probability models; adapter loads LightGBM models and returns calibrated probabilities and expected MFE.
- Strategy can incorporate dynamic TP/SL multipliers based on predicted MFE and confidence thresholds.

```mermaid
classDiagram
class ProbabilityInferencePort {
+estimate(features) ProbabilityEstimate
+is_ready() bool
}
class LGBMProbabilityAdapter {
-_model_dir : string
-_model_long
-_model_short
-_mfe_long
-_mfe_short
-_calibrators : dict
-_ready : bool
+estimate(features) ProbabilityEstimate
+is_ready() bool
}
class ProbabilityEstimate {
+p_long_target : float
+p_short_target : float
+expected_mfe_long : float
+expected_mfe_short : float
+calibrated : bool
}
ProbabilityInferencePort <|.. LGBMProbabilityAdapter
LGBMProbabilityAdapter --> ProbabilityEstimate : "returns"
```

**Diagram sources**
- [probability_inference.py:9-43](file://backend/app/domain/ports/probability_inference.py#L9-L43)
- [lgbm_probability_adapter.py:24-155](file://backend/app/infrastructure/adapters/lgbm_probability_adapter.py#L24-L155)

**Section sources**
- [probability_inference.py:1-43](file://backend/app/domain/ports/probability_inference.py#L1-L43)
- [lgbm_probability_adapter.py:1-166](file://backend/app/infrastructure/adapters/lgbm_probability_adapter.py#L1-L166)

### Strategy Protocols and Composition Patterns
- Strategy protocols define interfaces for setup detection, market context, entry signals, risk calculation, and execution planning.
- Strategy composition can be achieved by combining AMT-based gates, ML-driven probability estimates, and risk-managed sizing into modular components.

```mermaid
classDiagram
class Strategy {
<<abstract>>
+evaluate(context) EntrySignal?
+validate(signal, context) RiskResult
}
class Setup {
+type : string
+confidence : float
}
class MarketContext {
+symbol : string
+current_price : float
+market_state : string
+regime : string
+vwap : float
+vah : float
+val : float
+poc : float
+cvd_slope : float
+delta : float
+profile_shape : string
+lvns : list
+hvns : list
}
class EntrySignal {
+symbol : string
+direction : string
+price : float
+stop_loss : float
+take_profit : float
+size : float
+setup_type : string
+confidence : float
}
class RiskResult {
+approved : bool
+max_position_size : float
+reason : string
}
class Order {
+symbol : string
+side : string
+price : float
+quantity : float
+order_type : string
}
Strategy --> MarketContext : "consumes"
Strategy --> EntrySignal : "produces"
Strategy --> RiskResult : "validates"
Strategy --> Order : "executes"
```

**Diagram sources**
- [protocols.py:15-91](file://backend/app/domain/fabio_ai/strategy/protocols.py#L15-L91)

**Section sources**
- [protocols.py:1-91](file://backend/app/domain/fabio_ai/strategy/protocols.py#L1-L91)

### Multi-Timeframe Analysis Strategy
- Multi-timeframe AMT analyzer computes alignment among higher, session, and entry timeframes, returning an alignment state and position size multiplier.
- Strategy logic can gate entries based on alignment quality and scale position accordingly.

```mermaid
flowchart TD
A["Session AMTResult"] --> B["Derive bias (higher/session/entry)"]
B --> C["Compute alignment state"]
C --> D{"Alignment quality"}
D --> |Full| E["Allow full position"]
D --> |Partial| F["Reduce position (50%)"]
D --> |Conflict| G["Block entry"]
```

**Diagram sources**
- [multi_timeframe_amt.py:114-164](file://backend/app/domain/fabio_ai/services/multi_timeframe_amt.py#L114-L164)

**Section sources**
- [multi_timeframe_amt.py:74-164](file://backend/app/domain/fabio_ai/services/multi_timeframe_amt.py#L74-L164)

### Backtesting and Performance Evaluation
- Backtest engine computes key metrics from historical trade logs: total trades, win rate, average R:R, total PnL, max drawdown, Sharpe ratio, profit factor, and average win/loss.
- Use experiment context to attribute runs and compare configurations.

```mermaid
flowchart TD
Start(["Historical trades"]) --> Metrics["Compute PnL per trade"]
Metrics --> WinLoss["Separate wins/losses"]
WinLoss --> DD["Equity curve → Max drawdown"]
DD --> Sharpe["Mean/std → Annualized Sharpe"]
Sharpe --> PF["Gross profit / Gross loss"]
PF --> End(["BacktestResult"])
```

**Diagram sources**
- [backtest_engine.py:39-99](file://backend/app/application/services/backtest_engine.py#L39-L99)
- [experiment_context.py:37-70](file://backend/app/application/services/experiment_context.py#L37-L70)

**Section sources**
- [backtest_engine.py:1-99](file://backend/app/application/services/backtest_engine.py#L1-L99)
- [experiment_context.py:1-70](file://backend/app/application/services/experiment_context.py#L1-L70)

### Signal Tracking and Strategy Composition Insights
- Signal tracking service records every decision point, enabling analysis of gate block rates, generation rates, and timing patterns.
- Use aggregated stats to tune strategy composition and parameter thresholds.

```mermaid
flowchart TD
A["Decision point"] --> B{"Generated / Blocked / Waiting / Cooldown"}
B --> |Generated| C["Record signal metadata"]
B --> |Blocked| D["Record gate name/reason/detail"]
B --> |Waiting| E["Record waiting reason"]
B --> |Cooldown| F["Record cooldown time"]
C --> G["Update stats (generation/block rates)"]
D --> G
E --> G
F --> G
```

**Diagram sources**
- [signal_tracking_service.py:72-330](file://backend/app/application/services/signal_tracking_service.py#L72-L330)

**Section sources**
- [signal_tracking_service.py:72-385](file://backend/app/application/services/signal_tracking_service.py#L72-L385)

## Dependency Analysis
Key dependencies and coupling:
- AMT handler depends on AMT analyzer and footprint analyzer; caches profile arrays to minimize recomputation.
- Entry gate coordinator composes multiple gate checks and tick-size awareness.
- Signal constructor depends on gate-built context, probability inference, and risk sizing.
- Backtest engine consumes trade logs; experiment context attributes runs.

```mermaid
graph LR
AMT["AMT Handler"] --> MT["Multi-Timeframe AMT"]
AMT --> FP["Footprint Analyzer"]
Gate["Entry Gate Coordinator"] --> AMT
Sig["Signal Constructor"] --> Gate
Sig --> Prob["Probability Adapter"]
Sig --> Risk["Risk Sizing Engine"]
Track["Signal Tracking Service"] --> Sig
Backtest["Backtest Engine"] --> Sig
Exp["Experiment Context"] --> Backtest
```

**Diagram sources**
- [amt_handler.py:45-180](file://backend/app/application/handlers/amt_handler.py#L45-L180)
- [multi_timeframe_amt.py:74-164](file://backend/app/domain/fabio_ai/services/multi_timeframe_amt.py#L74-L164)
- [entry_gate_coordinator.py:25-125](file://backend/app/application/handlers/entry_gate_coordinator.py#L25-L125)
- [signal_constructor.py:32-186](file://backend/app/application/handlers/signal_constructor.py#L32-L186)
- [risk_sizing_engine.py:44-88](file://backend/app/domain/services/risk_sizing_engine.py#L44-L88)
- [signal_tracking_service.py:72-138](file://backend/app/application/services/signal_tracking_service.py#L72-L138)
- [backtest_engine.py:33-99](file://backend/app/application/services/backtest_engine.py#L33-L99)
- [experiment_context.py:37-70](file://backend/app/application/services/experiment_context.py#L37-L70)

**Section sources**
- [amt_handler.py:45-180](file://backend/app/application/handlers/amt_handler.py#L45-L180)
- [entry_gate_coordinator.py:25-125](file://backend/app/application/handlers/entry_gate_coordinator.py#L25-L125)
- [signal_constructor.py:32-186](file://backend/app/application/handlers/signal_constructor.py#L32-L186)
- [risk_sizing_engine.py:44-88](file://backend/app/domain/services/risk_sizing_engine.py#L44-L88)
- [signal_tracking_service.py:72-138](file://backend/app/application/services/signal_tracking_service.py#L72-L138)
- [backtest_engine.py:33-99](file://backend/app/application/services/backtest_engine.py#L33-L99)
- [experiment_context.py:37-70](file://backend/app/application/services/experiment_context.py#L37-L70)

## Performance Considerations
- Minimize redundant profile computations by caching DTOs in the AMT handler and updating incrementally.
- Use deterministic risk sizing to avoid model latency; integrate ML predictions asynchronously.
- Keep gate checks lightweight and early-exit when possible to reduce computation overhead.
- Batch process signals and leverage signal tracking to identify bottlenecks in the pipeline.

## Troubleshooting Guide
Common issues and resolutions:
- Gate pipeline failures: Inspect gate block reasons recorded by the signal tracking service; adjust thresholds or remove blocking gates for specific regimes.
- Signal validation failures: Verify price, stop loss, take profit, and R:R constraints; ensure freshness and direction consistency.
- Low signal generation rate: Review gate block summaries and reduce overly restrictive gates; improve confirmation bundles.
- Backtest discrepancies: Confirm trade logs include required fields (pnl, entry/exit prices, side); align session boundaries and initial capital.

**Section sources**
- [signal_tracking_service.py:140-185](file://backend/app/application/services/signal_tracking_service.py#L140-L185)
- [signal_validator.py:216-252](file://backend/app/domain/trading/services/signal_validator.py#L216-L252)
- [backtest_engine.py:39-99](file://backend/app/application/services/backtest_engine.py#L39-L99)

## Conclusion
GlassyTrade AI v5 provides a robust, modular framework for custom strategy development. By leveraging AMT-based market context, a configurable gate pipeline, ML-enhanced probability inference, and deterministic risk management, developers can implement sophisticated entry/exit strategies. The included backtesting and signal tracking services enable rigorous evaluation and continuous refinement of strategy performance.

## Appendices
- Practical examples:
  - AMT-based strategy: Use AMT handler outputs and multi-timeframe alignment to gate entries and size positions.
  - Multi-timeframe strategy: Combine higher, session, and entry timeframe biases to enforce alignment quality.
  - ML-enhanced rules: Integrate probability adapter outputs to dynamically adjust TP/SL and position sizing.
- Strategy composition tips:
  - Layer gates progressively (three-align → momentum fade → pipeline → hard gates).
  - Use signal tracking to identify which gates are most influential and adjust thresholds.
  - Parameter tuning: Sweep risk tiers, R:R minimums, and gate thresholds; evaluate using backtest engine.
  - Dynamic switching: Maintain multiple gate configurations keyed by regime or session phase; switch based on AMT market state and profile shape.