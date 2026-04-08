# Data Models and Schemas

<cite>
**Referenced Files in This Document**
- [market_state.py](file://backend/app/domain/models/market_state.py)
- [schemas.py](file://backend/app/infrastructure/serialization/schemas.py)
- [trade_aggregate.py](file://backend/app/domain/trading/models/trade_aggregate.py)
- [exchange_config.py](file://backend/app/domain/models/exchange_config.py)
- [database.py](file://backend/app/infrastructure/storage/database.py)
- [models.py](file://shared/entities/models.py)
- [predictions.py](file://backend/app/domain/fabio_ai/models/predictions.py)
- [features.py](file://backend/app/domain/probability/features.py)
- [loader.py](file://backend/app/config_models/loader.py)
- [validator.py](file://backend/app/config_models/validator.py)
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
This document provides comprehensive data model documentation for the GlassyTrade AI v5 system. It covers trading entities (candles, trades, positions), market state objects, AI prediction models, configuration schemas, and persistence structures. It explains data validation rules, business rules, transformation logic, serialization formats, and performance characteristics. It also outlines database schema diagrams, data access patterns, lifecycle and retention considerations, and security/access control mechanisms.

## Project Structure
The data model spans three primary layers:
- Domain models: Immutable value objects and aggregates for trading and market state
- Serialization DTOs: Pydantic models for API transport and conversion helpers
- Infrastructure storage: SQLite schema and persistence adapters

```mermaid
graph TB
subgraph "Domain Layer"
DM1["Market State<br/>VolumeProfile, VWAPState, MarketMetrics"]
DM2["Trading Models<br/>Trade, Position, EntrySignal, Fill"]
DM3["Shared Entities<br/>Quote, Tick, Order, Option, OptionChain"]
DM4["Exchange Config<br/>ExchangeConfig"]
end
subgraph "Serialization Layer"
DTO1["OHLCDataDTO<br/>OrderBookDTO"]
DTO2["AMTAnalysisDTO<br/>AIAnalysisDTO"]
DTO3["TradePositionDTO<br/>PortfolioDTO"]
DTO4["FootprintCandleDTO"]
end
subgraph "Infrastructure Layer"
INF1["SQLite Storage Adapter<br/>Tables: ticks, trades, llm_decisions,<br/>session_profiles, open_positions, position_events,<br/>npoc_records, fine_tuning_features, kv_store"]
end
DM1 --> DTO1
DM2 --> DTO3
DM3 --> DTO1
DM4 --> DTO2
DTO1 --> INF1
DTO2 --> INF1
DTO3 --> INF1
DTO4 --> INF1
```

**Diagram sources**
- [market_state.py:20-173](file://backend/app/domain/models/market_state.py#L20-L173)
- [trade_aggregate.py:86-795](file://backend/app/domain/trading/models/trade_aggregate.py#L86-L795)
- [models.py:88-341](file://shared/entities/models.py#L88-L341)
- [exchange_config.py:20-307](file://backend/app/domain/models/exchange_config.py#L20-L307)
- [schemas.py:31-667](file://backend/app/infrastructure/serialization/schemas.py#L31-L667)
- [database.py:24-176](file://backend/app/infrastructure/storage/database.py#L24-L176)

**Section sources**
- [market_state.py:1-173](file://backend/app/domain/models/market_state.py#L1-L173)
- [schemas.py:1-667](file://backend/app/infrastructure/serialization/schemas.py#L1-L667)
- [trade_aggregate.py:1-795](file://backend/app/domain/trading/models/trade_aggregate.py#L1-L795)
- [exchange_config.py:1-307](file://backend/app/domain/models/exchange_config.py#L1-L307)
- [database.py:1-861](file://backend/app/infrastructure/storage/database.py#L1-L861)
- [models.py:1-341](file://shared/entities/models.py#L1-L341)

## Core Components
This section introduces the principal data structures and their roles.

- Market State Models
  - VolumeProfile: Immutable volume profile with VAL < POC < VAH and positivity constraints
  - VWAPState: Session VWAP with sigma ≥ 0, vwap > 0, and sign-congruence checks
  - MarketMetrics: Balanced-state metrics with normalized balance_pct ∈ [0, 1]
  - IndicatorLineage: Provenance tracking for indicator values
  - RuleChecklistResult: Gate results with pass/total invariants
  - SessionContext: Session identity with non-empty identifiers

- Trading Models
  - Trade: Aggregate root with immutable EntrySignal, append-only fills, and derived Position
  - Position: Derived from fills; supports unrealized PnL, market value, and cost basis
  - EntrySignal: Immutable decision with risk/reward and thesis
  - Fill: Immutable executed order with cost computation
  - TradeEvent: Audit trail event

- Shared Entities
  - Quote, Tick: Market data with optional depth
  - Order, Option, OptionChain: Broker-facing entities
  - Instrument: Symbol and option metadata

- Exchange Configuration
  - ExchangeConfig: Exchange-specific thresholds, symbols, tick/lot sizes, and point values

- Serialization DTOs
  - OHLCDataDTO, OrderBookDTO, OrderBookLevelDTO
  - AMTAnalysisDTO, AIAnalysisDTO, TradePositionDTO, PortfolioDTO, PositionEventDTO
  - FootprintCandleDTO, FootprintLevelDTO
  - Converters: ohlc_to_dto, dto_to_ohlc, dto_to_order_book, dto_to_weights, position_to_dto, etc.

- Infrastructure Storage
  - SQLite tables for ticks, trades, LLM decisions, performance snapshots, session profiles, open positions, position events, NPOC records, fine tuning features, and key-value store

**Section sources**
- [market_state.py:20-173](file://backend/app/domain/models/market_state.py#L20-L173)
- [trade_aggregate.py:86-795](file://backend/app/domain/trading/models/trade_aggregate.py#L86-L795)
- [models.py:88-341](file://shared/entities/models.py#L88-L341)
- [exchange_config.py:20-307](file://backend/app/domain/models/exchange_config.py#L20-L307)
- [schemas.py:31-667](file://backend/app/infrastructure/serialization/schemas.py#L31-L667)
- [database.py:24-176](file://backend/app/infrastructure/storage/database.py#L24-L176)

## Architecture Overview
The system enforces strict separation between domain and transport:
- Domain models are immutable and free of framework dependencies
- DTOs isolate API concerns and provide camelCase serialization
- Persistence adapters persist structured payloads to SQLite with indexes and WAL mode

```mermaid
sequenceDiagram
participant API as "API Router"
participant SER as "Serialization Layer"
participant DOM as "Domain Models"
participant STO as "SQLite Storage"
API->>SER : "Receive request DTOs"
SER->>DOM : "Convert DTOs to domain objects"
DOM-->>SER : "Return domain results"
SER->>STO : "Persist structured payloads"
STO-->>SER : "ACK"
SER-->>API : "Return response DTOs"
```

**Diagram sources**
- [schemas.py:367-667](file://backend/app/infrastructure/serialization/schemas.py#L367-L667)
- [database.py:254-479](file://backend/app/infrastructure/storage/database.py#L254-L479)

## Detailed Component Analysis

### Market State Models
Market state models enforce invariants to prevent anomalies and ensure deterministic behavior.

```mermaid
classDiagram
class VolumeProfile {
+string session_id
+string instrument_key
+float val
+float poc
+float vah
+float total_volume
+string computed_at
}
class VWAPState {
+string session_id
+string instrument_key
+float vwap
+float sigma
+float upper_1
+float lower_1
+float upper_2
+float lower_2
+float deviation_sigmas
+string computed_at
}
class MarketMetrics {
+string session_id
+string instrument_key
+float delta
+float cvd_slope
+float ofi
+float balance_pct
+string profile_shape
+float aggression_score
+string computed_at
}
class IndicatorLineage {
+string indicator
+string source
+int bar_count
+string session_id
+string instrument_key
+string computed_at
}
class RuleChecklistResult {
+int passed
+int total
+string[] gate_failures
+string computed_at
}
class SessionContext {
+string session_id
+string instrument_key
+string exchange
+string phase
+string start_ts
+string end_ts
}
VolumeProfile <.. IndicatorLineage : "shares session/instrument"
VWAPState <.. IndicatorLineage
MarketMetrics <.. IndicatorLineage
RuleChecklistResult <.. SessionContext
```

**Diagram sources**
- [market_state.py:20-173](file://backend/app/domain/models/market_state.py#L20-L173)

Validation rules:
- VolumeProfile: val > 0, poc > 0, vah > 0; val < poc; poc < vah
- VWAPState: sigma ≥ 0; vwap > 0; sign alignment between deviation_sigmas and (vwap ± sigma)
- MarketMetrics: 0.0 ≤ balance_pct ≤ 1.0
- RuleChecklistResult: total > 0; passed ≤ total
- SessionContext: session_id and instrument_key non-empty

**Section sources**
- [market_state.py:20-173](file://backend/app/domain/models/market_state.py#L20-L173)

### Trading Models
The trading aggregate encapsulates the entire lifecycle of a trade with immutable signals and append-only fills.

```mermaid
classDiagram
class Trade {
+string trade_id
+string symbol
+TradeStatus status
+EntrySignal entry_signal
+tuple~Fill~ fills
+tuple~TradeEvent~ events
+string entry_time
+string close_time
+CloseReason close_reason
+get_position(current_market_price) Position
+is_open() bool
+is_pending() bool
+is_closed() bool
+open(signal, timestamp) Trade
+add_fill(fill) Trade
+close(reason, timestamp) Trade
+cancel(reason, timestamp) Trade
+to_snapshot() dict
}
class Position {
+string trade_id
+Side side
+Decimal quantity
+Decimal avg_entry_price
+Decimal current_price
+from_fills(fills, current_price) Position
+is_open() bool
+market_value() Decimal
+cost_basis() Decimal
+unrealized_pnl() Decimal
+unrealized_pnl_pct() float
}
class EntrySignal {
+string signal_id
+string timestamp
+Direction direction
+Decimal entry_price
+Decimal stop_loss
+Decimal take_profit
+Decimal position_size
+SetupType setup_type
+Confidence confidence
+TradeThesis thesis
+is_long bool
+is_short bool
+risk_per_share() Decimal
+reward_per_share() Decimal
+risk_reward_ratio() float
}
class Fill {
+string fill_id
+string trade_id
+string order_id
+string symbol
+Side side
+Decimal price
+Decimal quantity
+Decimal commission
+Decimal slippage
+string timestamp
+FillType fill_type
+total_cost() Decimal
}
class TradeEvent {
+string event_id
+string trade_id
+string event_type
+string timestamp
+dict data
}
Trade --> EntrySignal : "owns"
Trade --> Fill : "append-only"
Trade --> TradeEvent : "audit trail"
Position ..> Fill : "derived from"
```

Key business rules:
- Position derived from fills; invariant: position = sum(fills.quantity)
- Status transitions: PENDING → OPEN → CLOSED
- Realized PnL computed by FIFO matching entry fills to exits
- Unrealized PnL computed using current price

**Diagram sources**
- [trade_aggregate.py:293-795](file://backend/app/domain/trading/models/trade_aggregate.py#L293-L795)

**Section sources**
- [trade_aggregate.py:35-795](file://backend/app/domain/trading/models/trade_aggregate.py#L35-L795)

### Shared Entities
Common domain entities used across backend and brokers.

```mermaid
classDiagram
class Instrument {
+string symbol
+Exchange exchange
+string security_id
+OptionType option_type
+float strike
+datetime expiry
+is_option() bool
}
class Quote {
+Instrument instrument
+float ltp
+float bid
+float ask
+int volume
+float open
+float high
+float low
+float close
+datetime timestamp
+int oi
+DepthLevel[] bid_depth
+DepthLevel[] ask_depth
+has_depth() bool
+spread() float
+spread_pct() float
}
class Tick {
+Instrument instrument
+float price
+int volume
+datetime timestamp
+float bid
+float ask
}
class Order {
+Instrument instrument
+OrderSide side
+float quantity
+float price
+float trigger_price
+string product_type
+string order_id
+OrderType order_type
+OrderStatus status
+datetime timestamp
+float filled_quantity
+float average_fill_price
+dict[] fills
+float commission
}
class Option {
+string symbol
+string security_id
+float strike
+string option_type
+datetime expiry
+float ltp
+int oi
+int volume
+float bid
+float ask
+int bid_qty
+int ask_qty
+int prev_oi
+int prev_volume
+float avg_price
+float iv
+float delta
+float gamma
+float theta
+float vega
+float open
+float high
+float low
+float close
+float prev_close
+datetime timestamp
+is_call() bool
+is_put() bool
}
class OptionChain {
+Instrument underlying
+datetime expiry
+float spot_price
+float atm_strike
+float step_size
+Dict~float,Option~ calls
+Dict~float,Option~ puts
+datetime timestamp
+strikes() float[]
}
class Position {
+Instrument instrument
+OrderSide side
+float quantity
+float entry_price
+datetime entry_time
+float stop_loss
+float take_profit
+OrderStatus status
+float exit_price
+datetime exit_time
+float pnl
+string id
+dict metadata
+avg_price() float
+is_open() bool
}
Instrument <.. Quote
Instrument <.. Order
Instrument <.. Option
Instrument <.. Position
Option <.. OptionChain
```

**Diagram sources**
- [models.py:72-341](file://shared/entities/models.py#L72-L341)

**Section sources**
- [models.py:17-341](file://shared/entities/models.py#L17-L341)

### Exchange Configuration
Centralized exchange-specific configuration to eliminate scattered constants.

```mermaid
classDiagram
class ExchangeConfig {
+string exchange
+FrozenSet~string~ underlyings
+string default_symbol
+string scanner_underlying
+FrozenSet~string~ scanner_underlyings
+float aggression_sigma
+float displacement_multiplier
+float balance_ratio_threshold
+float big_trade_multiplier
+int big_trade_cluster_count
+int big_trade_cluster_ticks
+int warm_up_minutes
+float cvd_block_threshold
+float max_distance_to_level_ticks
+string llm_instruction
+FrozenSet~string~ eia_symbols
+int eia_suppression_minutes
+Dict~string,float~ tick_sizes
+Dict~string,int~ lot_sizes
+Dict~string,float~ point_values
+get_tick_size(symbol_or_underlying) float
+get_lot_size(symbol_or_underlying) int
+get_point_value(symbol_or_underlying) float
+for_exchange(exchange) ExchangeConfig
+from_dict(exchange, data) ExchangeConfig
+is_mcx() bool
+is_nse() bool
+is_underlying(symbol) bool
}
```

**Diagram sources**
- [exchange_config.py:20-307](file://backend/app/domain/models/exchange_config.py#L20-L307)

**Section sources**
- [exchange_config.py:94-307](file://backend/app/domain/models/exchange_config.py#L94-L307)

### Serialization DTOs and Converters
Pydantic DTOs define the JSON contract and converters bridge domain and DTO worlds.

```mermaid
classDiagram
class OHLCDataDTO {
+string time
+float open
+float high
+float low
+float close
+float volume
+float vwap
+float takerBuyVolume
+float delta
}
class OrderBookDTO {
+OrderBookLevelDTO[] bids
+OrderBookLevelDTO[] asks
}
class OrderBookLevelDTO {
+float price
+float quantity
}
class AMTAnalysisDTO {
+string marketState
+float poc
+float valueAreaHigh
+float valueAreaLow
+float[] lvns
+float[] hvns
+float aggression
+TradeSignalDTO signal
+string setup
+VolumeProfileLevelDTO[] profile
+AggressivePrintDTO[] aggressivePrints
+float cvdSlope
+string cvdDivergence
+string profileShape
+float sessionVwap
+float vwapUpper1
+float vwapLower1
+float vwapUpper2
+float vwapLower2
+float balanceRatio
+VolumeProfileLevelDTO[] legProfile
+float[] legLvns
+float legPoc
+float legVah
+float legVal
+bool hasDisplacement
+string marketStructure
+int structureConfidence
+float ibHigh
+float ibLow
+bool ibComplete
+float priorPoc
+float priorVah
+float priorVal
+string gapType
+string openingBias
+bool acceptanceAbove
+bool acceptanceBelow
+bool rejectionAtHigh
+bool rejectionAtLow
+float priceVelocity
+string breakDirection
+string breakType
+float breakLevel
+string pocSignal
+string pocVsPrice
+dict lvnPlay
+string cushionTier
+string llmThinking
+string llmJson
+float sessionPnl
+string openingType
+string mtfAlignment
+float dailyVah
+float dailyVal
+float dailyPoc
+float hourlyVah
+float hourlyVal
+float hourlyPoc
}
class AIAnalysisDTO {
+string sentiment
+float confidence
+string longTermTrend
+float volatilityScore
+float quantScore
+float projectedPrice
+string[] reasoning
+FactorBreakdownDTO factorBreakdown
}
class TradePositionDTO {
+string id
+string symbol
+string side
+string source
+float entryPrice
+float size
+float stopLoss
+float takeProfit
+float pnl
+string entryTime
+string status
+float exitPrice
+string exitTime
+string closeReason
+dict metadata
+float partialRealizedPnl
+float originalSize
}
class PortfolioDTO {
+float balance
+float equity
+int leverage
+TradePositionDTO[] positions
+TradePositionDTO[] closedTrades
+dict[] history
}
class PositionEventDTO {
+int id
+string eventId
+string positionId
+string symbol
+string eventType
+string eventTime
+string createdAt
+string side
+float entryPrice
+float exitPrice
+float stopLoss
+float takeProfit
+string source
+float pnl
+string exitReason
+float partialPct
+float sizeClosed
+float sizeRemaining
+float realizedPnl
+float timeInTradeS
}
class FootprintCandleDTO {
+string time
+FootprintLevelDTO[] levels
+float pocPrice
+float totalDelta
+float stepPrice
}
class FootprintLevelDTO {
+float price
+float bid
+float ask
+float delta
+bool imbalance
}
OHLCDataDTO <.. OrderBookDTO
AMTAnalysisDTO <.. TradePositionDTO
PortfolioDTO <.. TradePositionDTO
PositionEventDTO <.. PortfolioDTO
FootprintCandleDTO <.. FootprintLevelDTO
```

Converters:
- ohlc_to_dto/dto_to_ohlc
- dto_to_order_book
- dto_to_weights
- position_to_dto
- portfolio_to_dto
- position_event_to_dto
- amt_result_to_dto
- stats_to_dto
- footprint_to_dto

**Diagram sources**
- [schemas.py:31-667](file://backend/app/infrastructure/serialization/schemas.py#L31-L667)

**Section sources**
- [schemas.py:31-667](file://backend/app/infrastructure/serialization/schemas.py#L31-L667)

### AI Prediction Models and Probability Features
AI models produce combined outputs and feature vectors for probabilistic inference.

```mermaid
classDiagram
class ModelWeights {
+float trend
+float momentum
+float delta
+float orderBook
+float volatility
}
class FactorBreakdown {
+float trend
+float momentum
+float delta
+float orderBook
+float volatility
}
class AIAnalysisResult {
+string sentiment
+float confidence
+string longTermTrend
+float volatilityScore
+float quantScore
+float projectedPrice
+string[] reasoning
+FactorBreakdown factorBreakdown
}
class PredictionResult {
+tuple~OHLC~ predictions
+AIAnalysisResult analysis
}
class FeatureExtractor {
+extract_features(data, amt_result, tick, order_book, ...) dict~string,float~
+extract_features_from_row(row, data_window, is_mcx) dict~string,float~
+active_model_features(features) dict~string,float~
}
PredictionResult --> AIAnalysisResult : "contains"
FeatureExtractor --> ModelWeights : "consumes"
```

Feature schema:
- 42-feature canonical schema with groups for price microstructure, order flow, volume profile structure, order book, temporal, and options-specific features
- Versioned schema: fp-42-v1

**Diagram sources**
- [predictions.py:27-32](file://backend/app/domain/fabio_ai/models/predictions.py#L27-L32)
- [features.py:18-71](file://backend/app/domain/probability/features.py#L18-L71)

**Section sources**
- [predictions.py:1-32](file://backend/app/domain/fabio_ai/models/predictions.py#L1-L32)
- [features.py:1-423](file://backend/app/domain/probability/features.py#L1-L423)

### Configuration Models and Validation
Configuration loading and validation ensure safe operation across environments.

```mermaid
flowchart TD
A["Load base.yaml"] --> B["Load environment overrides"]
B --> C["Load strategy overrides"]
C --> D["Load feature flags"]
D --> E["Parse typed SystemConfig"]
E --> F["Run ConfigValidator"]
F --> G{"Errors?"}
G --> |Yes| H["Raise ConfigValidationError"]
G --> |No| I["Log startup summary"]
```

Validation rules include:
- At least one active symbol
- Live mode constraints (broker_mode, llm_entry_gate, capital)
- Risk limits (risk_per_trade_pct, portfolio_notional_cap)
- Symbol-level constraints (value_area_pct, min_rr_ratio, thresholds)
- ML model availability for active symbols

**Diagram sources**
- [loader.py:139-245](file://backend/app/config_models/loader.py#L139-L245)
- [validator.py:22-170](file://backend/app/config_models/validator.py#L22-L170)

**Section sources**
- [loader.py:1-288](file://backend/app/config_models/loader.py#L1-L288)
- [validator.py:1-177](file://backend/app/config_models/validator.py#L1-L177)

## Dependency Analysis
The following diagram shows key dependencies among data models and persistence.

```mermaid
graph LR
MS["market_state.py"] --> SCH["schemas.py"]
TA["trade_aggregate.py"] --> SCH
EX["exchange_config.py"] --> SCH
MO["models.py"] --> SCH
FE["features.py"] --> SCH
PR["predictions.py"] --> SCH
LO["loader.py"] --> VA["validator.py"]
SCH --> DB["database.py"]
TA --> DB
MS --> DB
EX --> DB
MO --> DB
FE --> DB
PR --> DB
```

**Diagram sources**
- [market_state.py:1-173](file://backend/app/domain/models/market_state.py#L1-L173)
- [schemas.py:1-667](file://backend/app/infrastructure/serialization/schemas.py#L1-L667)
- [trade_aggregate.py:1-795](file://backend/app/domain/trading/models/trade_aggregate.py#L1-L795)
- [exchange_config.py:1-307](file://backend/app/domain/models/exchange_config.py#L1-L307)
- [models.py:1-341](file://shared/entities/models.py#L1-L341)
- [features.py:1-423](file://backend/app/domain/probability/features.py#L1-L423)
- [predictions.py:1-32](file://backend/app/domain/fabio_ai/models/predictions.py#L1-L32)
- [loader.py:1-288](file://backend/app/config_models/loader.py#L1-L288)
- [validator.py:1-177](file://backend/app/config_models/validator.py#L1-L177)
- [database.py:1-861](file://backend/app/infrastructure/storage/database.py#L1-L861)

**Section sources**
- [schemas.py:1-667](file://backend/app/infrastructure/serialization/schemas.py#L1-L667)
- [database.py:1-861](file://backend/app/infrastructure/storage/database.py#L1-L861)

## Performance Considerations
- SQLite batch writes: ticks buffered and flushed in batches with a timer to reduce I/O overhead
- WAL mode enabled for improved concurrency and durability
- Unique index on (symbol, time) for ticks to prevent duplicates
- Dedicated indexes on frequently queried columns (e.g., trades closed_at, llm_decisions created_at)
- DTO conversion helpers minimize object copying and preserve camelCase aliases for frontend compatibility
- Feature extraction computes rolling statistics efficiently and falls back gracefully for missing data

[No sources needed since this section provides general guidance]

## Troubleshooting Guide
Common issues and resolutions:
- Configuration validation failures: Review hard errors/warnings and adjust base.yaml, environment overrides, or strategy files accordingly
- Market state invariants: Ensure VAL < POC < VAH and positivity constraints; validate deviation_sign alignment for VWAP
- Trade state anomalies: Verify fills are append-only and position derivation matches expected quantities
- Persistence errors: Confirm WAL mode initialization and index creation succeeded; check batch flush intervals and locks

**Section sources**
- [validator.py:22-170](file://backend/app/config_models/validator.py#L22-L170)
- [market_state.py:37-89](file://backend/app/domain/models/market_state.py#L37-L89)
- [trade_aggregate.py:322-343](file://backend/app/domain/trading/models/trade_aggregate.py#L322-L343)
- [database.py:198-218](file://backend/app/infrastructure/storage/database.py#L198-L218)

## Conclusion
GlassyTrade AI v5 employs a robust, invariant-enforcing data model layered with typed DTOs and a durable SQLite persistence layer. The design emphasizes immutability, deterministic state, and strict validation to ensure reliable trading and analysis workflows. Configuration management and validation provide operational safety across environments.

[No sources needed since this section summarizes without analyzing specific files]

## Appendices

### Database Schema Diagram
```mermaid
erDiagram
TICKS {
integer id PK
string symbol
string time
float open
float high
float low
float close
float volume
float delta
text extra
string created_at
}
TRADES {
integer id PK
string position_id
string symbol
string side
float entry_price
float exit_price
float size
float pnl
string source
string reason
string opened_at
string closed_at
text extra
string llm_analysis
string created_at
}
LLM_DECISIONS {
integer id PK
string symbol
string direction
string confidence
string rationale
string input_prompt
string raw_output
string market_state
string aggression
float price
float vah
float val
float poc
float delta
float volume
string profile_shape
text extra
string created_at
}
PERFORMANCE_SNAPSHOTS {
integer id PK
string symbol
float equity
float balance
float open_pnl
int open_positions
int total_trades
float win_rate
text extra
string created_at
}
SESSION_PROFILES {
integer id PK
string symbol
string market
string session_date
float poc
float vah
float val
string profile_shape
float total_volume
text extra
string created_at
}
OPEN_POSITIONS {
string id PK
string symbol
string side
float entry_price
float size
float stop_loss
float take_profit
string source
string opened_at
text extra
}
POSITION_EVENTS {
integer id PK
string position_id
string symbol
string event_type
string event_time
text extra
string created_at
}
NPOC_RECORDS {
integer id PK
string underlying
string session_date
float poc_price
int is_filled
string filled_at
string created_at
}
FINE_TUNING_FEATURES {
integer id PK
int trade_id
string symbol
string direction
string market_state
float poc
float vah
float val
float aggression
float cvd_slope
float delta_normalized
float volume
float imbalance
float vix_normalized
string vix_regime
float iv_rank
float pcr_oi
string ib_location
float ib_width_pct
int lvn_count
int hvn_count
int drive_number
string setup_type
string result
float pnl_r
string created_at
}
KV_STORE {
string key PK
string value
string updated_at
}
TICKS ||--o{ POSITION_EVENTS : "referenced by event_time"
OPEN_POSITIONS ||--o{ POSITION_EVENTS : "referenced by position_id"
```

**Diagram sources**
- [database.py:24-176](file://backend/app/infrastructure/storage/database.py#L24-L176)

### Sample Data Examples
- Market State: VolumeProfile with val, poc, vah and computed_at
- Trading: Trade with EntrySignal, fills, and derived Position
- DTOs: AMTAnalysisDTO with marketState, profile, aggressivePrints, and sessionVwap
- Persistence: Trades with extra metadata, session_profiles with prior-day levels

**Section sources**
- [market_state.py:20-173](file://backend/app/domain/models/market_state.py#L20-L173)
- [trade_aggregate.py:293-795](file://backend/app/domain/trading/models/trade_aggregate.py#L293-L795)
- [schemas.py:91-163](file://backend/app/infrastructure/serialization/schemas.py#L91-L163)
- [database.py:35-176](file://backend/app/infrastructure/storage/database.py#L35-L176)

### Data Access Patterns
- Query ticks with symbol/time filters and limits
- Retrieve closed trades by date range
- Persist LLM decisions with known keys and extra metadata
- Save performance snapshots and fine-tuning features
- Manage open positions across restarts with replace-on-conflict

**Section sources**
- [database.py:485-764](file://backend/app/infrastructure/storage/database.py#L485-L764)

### Serialization Formats
- JSON payloads with camelCase aliases for frontend consumption
- Extra fields stored as JSON blobs for extensibility
- DTO converters ensure type-safe transformations

**Section sources**
- [schemas.py:367-667](file://backend/app/infrastructure/serialization/schemas.py#L367-L667)

### Security and Privacy
- Configuration secrets loaded from environment variables only
- Validation prevents unsafe configurations in live mode
- DTOs restrict unknown fields for safety

**Section sources**
- [loader.py:139-245](file://backend/app/config_models/loader.py#L139-L245)
- [validator.py:22-170](file://backend/app/config_models/validator.py#L22-L170)
- [schemas.py:230-231](file://backend/app/infrastructure/serialization/schemas.py#L230-L231)

### Migration and Version Management
- Schema upgrades performed via index replacement and deduplication
- Feature schema version tracked (fp-42-v1)
- Configuration hierarchy supports environment-specific overrides and strategy-driven tuning

**Section sources**
- [database.py:204-217](file://backend/app/infrastructure/storage/database.py#L204-L217)
- [features.py:18-71](file://backend/app/domain/probability/features.py#L18-L71)
- [loader.py:139-245](file://backend/app/config_models/loader.py#L139-L245)