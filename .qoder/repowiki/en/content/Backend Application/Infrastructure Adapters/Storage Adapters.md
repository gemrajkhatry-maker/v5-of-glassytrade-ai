# Storage Adapters

<cite>
**Referenced Files in This Document**
- [database.py](file://backend/app/infrastructure/storage/database.py)
- [async_persistence.py](file://backend/app/infrastructure/async_persistence.py)
- [metrics.py](file://backend/app/infrastructure/metrics.py)
- [storage.py](file://backend/app/domain/ports/storage.py)
- [dependencies.py](file://backend/app/api/dependencies.py)
- [main.py](file://backend/app/main.py)
- [metrics.py](file://backend/app/api/routers/metrics.py)
- [health.py](file://backend/app/api/routers/health.py)
- [trading.py](file://backend/app/application/services/trading_session.py)
- [engine.py](file://backend/app/application/engine.py)
- [signal_tracking_service.py](file://backend/app/application/services/signal_tracking_service.py)
- [ai.py](file://backend/app/api/routers/ai.py)
- [run_backtest.py](file://backend/scripts/run_backtest.py)
- [collect_training_data.py](file://backend/scripts/collect_training_data.py)
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
This document describes the GlassyTrade AI storage adapters layer, focusing on:
- Database storage adapter implementation for persistent data management
- AsyncPersistence layer for non-blocking I/O
- Metrics service for observability and performance tracking
- Storage interfaces, data models, indexing strategies, and query optimization
- Practical patterns for persistence, backup, recovery, and integration with the trading pipeline

The storage layer persists ticks, trades, LLM decisions, session profiles, open positions, position events, and performance snapshots. It is designed for production-grade throughput and reliability, with explicit separation of concerns between synchronous domain interfaces and asynchronous persistence.

## Project Structure
The storage adapters reside in the infrastructure layer and integrate with the domain via a unified StoragePort interface. The AsyncPersistenceBus wraps the storage adapter to offload writes to a background thread, ensuring the trading hot path remains latency-insensitive. Metrics are collected centrally and exposed via API endpoints.

```mermaid
graph TB
subgraph "Domain"
SP["StoragePort<br/>Interfaces"]
end
subgraph "Infrastructure"
SA["SQLiteStorageAdapter<br/>Persistent Storage"]
AP["AsyncPersistenceBus<br/>Background Queue"]
MC["MetricsCollector<br/>Observability"]
end
subgraph "Application"
TS["TradingSessionService"]
ENG["TradingEngine"]
SIG["SignalTrackingService"]
end
subgraph "API"
HR["Health Router"]
MR["Metrics Router"]
end
SP --> SA
SA --> AP
AP --> TS
AP --> ENG
AP --> SIG
HR --> MC
MR --> MC
```

**Diagram sources**
- [storage.py:54-121](file://backend/app/domain/ports/storage.py#L54-L121)
- [database.py:183-861](file://backend/app/infrastructure/storage/database.py#L183-L861)
- [async_persistence.py:24-277](file://backend/app/infrastructure/async_persistence.py#L24-L277)
- [metrics.py:14-98](file://backend/app/infrastructure/metrics.py#L14-L98)
- [dependencies.py:106-112](file://backend/app/api/dependencies.py#L106-L112)
- [health.py:81-84](file://backend/app/api/routers/health.py#L81-L84)
- [metrics.py:30-56](file://backend/app/api/routers/metrics.py#L30-L56)

**Section sources**
- [dependencies.py:106-112](file://backend/app/api/dependencies.py#L106-L112)
- [main.py:139-148](file://backend/app/main.py#L139-L148)

## Core Components
- StoragePort interface defines the contract for ticks, trades, decisions, open positions, and position events persistence and queries.
- SQLiteStorageAdapter implements StoragePort with WAL mode, indexing, and batched writes for ticks.
- AsyncPersistenceBus queues writes and executes them in a background thread, prioritizing critical writes (trade/position).
- MetricsCollector aggregates latency, signals, PnL, cache hits/misses, regime changes, and tick counts.

Key responsibilities:
- Data serialization: JSON serialization for “extra” fields and float conversions for numeric fields.
- Transaction handling: Explicit commits per operation with rollback on errors; periodic flush for tick batches.
- Indexing: Unique index on ticks (symbol, time), plus indexes for trades, decisions, snapshots, session profiles, position events, and fine-tuning features.
- Query optimization: Parameterized queries with optional filters and limits; defensive deduplication upgrade for ticks.

**Section sources**
- [storage.py:54-121](file://backend/app/domain/ports/storage.py#L54-L121)
- [database.py:183-861](file://backend/app/infrastructure/storage/database.py#L183-L861)
- [async_persistence.py:24-277](file://backend/app/infrastructure/async_persistence.py#L24-L277)
- [metrics.py:14-98](file://backend/app/infrastructure/metrics.py#L14-L98)

## Architecture Overview
The storage adapters layer sits between the trading pipeline and the persistence backend. Writes from the trading session and handlers are queued asynchronously, while reads remain synchronous to ensure consistency. Metrics are recorded centrally and exposed via health and metrics endpoints.

```mermaid
sequenceDiagram
participant TS as "TradingSessionService"
participant BUS as "AsyncPersistenceBus"
participant SA as "SQLiteStorageAdapter"
participant DB as "SQLite Database"
TS->>BUS : save_tick/save_trade/save_llm_decision...
BUS->>BUS : enqueue(write)
Note over BUS : Background thread drains queue<br/>and executes writes
BUS->>SA : save_* (via dynamic method dispatch)
SA->>DB : INSERT/UPDATE/COMMIT
DB-->>SA : OK
SA-->>BUS : OK
BUS-->>TS : returns immediately
```

**Diagram sources**
- [async_persistence.py:24-277](file://backend/app/infrastructure/async_persistence.py#L24-L277)
- [database.py:183-861](file://backend/app/infrastructure/storage/database.py#L183-L861)
- [trading.py:288-390](file://backend/app/application/services/trading_session.py#L288-L390)

**Section sources**
- [dependencies.py:106-112](file://backend/app/api/dependencies.py#L106-L112)
- [async_persistence.py:24-277](file://backend/app/infrastructure/async_persistence.py#L24-L277)
- [database.py:183-861](file://backend/app/infrastructure/storage/database.py#L183-L861)

## Detailed Component Analysis

### Database Storage Adapter (SQLiteStorageAdapter)
- Purpose: Persistent storage for ticks, trades, LLM decisions, performance snapshots, session profiles, open positions, position events, fine-tuning features, and a key-value store.
- Connection and concurrency:
  - Single persistent connection with row_factory for dict-like access.
  - Threading lock protects all writes; tick flush timer ensures bounded latency.
- Batched writes:
  - Tick buffer flushed when size threshold or interval elapses.
  - Flush occurs inside a lock; batch insert uses executemany with “INSERT OR REPLACE” for deduplication.
- Transactions:
  - Per-operation commits; rollback on exceptions; explicit flush() for batched commits.
- Indexing and schema:
  - Unique index on (symbol, time) for ticks; additional indexes for efficient queries.
  - Schema upgrades handle deduplication and index recreation safely.
- Data serialization:
  - Extra fields serialized as JSON; numeric fields converted via shared utilities.
- Query APIs:
  - Parameterized queries with optional start/end filters and limits.
  - Helpers for recent trades, session profiles, position events, and composite profiles.

```mermaid
classDiagram
class StoragePort {
<<interface>>
+save_tick(symbol, data)
+save_trade(data)
+save_llm_decision(data)
+save_performance_snapshot(snapshot)
+query_ticks(symbol, start, end, limit)
+query_trades(start, end)
+query_llm_decisions(start, end, symbols, limit)
+save_session_profile(profile_data)
+get_previous_session_profile(symbol, market)
+get_recent_trades(limit)
+save_position_event(event)
+query_position_events(position_id, symbol)
}
class SQLiteStorageAdapter {
-_db_path : string
-_lock : Lock
-_conn : Connection
-_tick_buffer : list
-_last_flush_time : float
-_flush_timer : Timer
+save_tick(symbol, tick_data)
+save_trade(trade_data, auto_commit)
+save_llm_decision(decision_data, auto_commit)
+save_performance_snapshot(snapshot)
+save_session_profile(profile_data)
+save_open_position(position)
+delete_open_position(position_id)
+load_open_positions()
+save_position_event(event)
+query_ticks(symbol, start, end, limit)
+query_trades(start, end)
+query_llm_decisions(start, end, symbols, limit)
+query_position_events(position_id, symbol)
+get_recent_trades(limit)
+get_previous_session_profile(symbol, market)
+kv_set(key, value)
+kv_get(key)
+save_npoc(underlying, session_date, poc_price)
+mark_npoc_filled(underlying, session_date, filled_at)
+get_active_npocs(underlying)
+load_composite_profiles(symbol, market, limit)
+flush()
}
StoragePort <|.. SQLiteStorageAdapter
```

**Diagram sources**
- [storage.py:54-121](file://backend/app/domain/ports/storage.py#L54-L121)
- [database.py:183-861](file://backend/app/infrastructure/storage/database.py#L183-L861)

**Section sources**
- [database.py:183-861](file://backend/app/infrastructure/storage/database.py#L183-L861)

### AsyncPersistence Layer (AsyncPersistenceBus)
- Purpose: Offload storage writes to a background thread to avoid blocking the trading hot path.
- Queues:
  - Main queue for non-critical writes (e.g., ticks, LLM decisions).
  - Critical queue for trade/position persistence; always drained first.
- Backpressure and drop handling:
  - Drops writes when queues are full; logs critical drops separately.
- Lifecycle:
  - start(): spawns background thread.
  - stop(timeout): flushes pending writes, drains critical queue, and joins thread.
- Read passthrough:
  - All read APIs are forwarded synchronously to the underlying storage.

```mermaid
flowchart TD
Start([Start]) --> Init["Initialize queues and thread"]
Init --> Loop{"Running?"}
Loop --> |Yes| DrainCritical["Drain critical queue (non-blocking)"]
DrainCritical --> WaitMain["Wait for main queue item (timeout)"]
WaitMain --> DrainMain["Drain up to N items from main queue"]
DrainMain --> ExecBatch["Execute batch against storage"]
ExecBatch --> ClearBatch["Clear batch"]
ClearBatch --> Loop
Loop --> |No and queues not empty| FlushRemainder["Drain critical and execute"]
FlushRemainder --> Stop([Stop])
Loop --> |No and queues empty| Stop
```

**Diagram sources**
- [async_persistence.py:24-277](file://backend/app/infrastructure/async_persistence.py#L24-L277)

**Section sources**
- [async_persistence.py:24-277](file://backend/app/infrastructure/async_persistence.py#L24-L277)

### Metrics Service (MetricsCollector)
- Purpose: Centralized metrics collection for inference latency, signal counts, PnL, cache hits/misses, regime changes, and ticks processed.
- Snapshot:
  - Returns uptime, counts, latency percentiles (p50/p95), signal totals, total PnL, cache hit rate, and regime change count.
- Thread-safe:
  - Uses a lock to protect internal counters and buffers.

```mermaid
classDiagram
class MetricsCollector {
-_inference_latencies : list
-_signal_counts : map
-_total_pnl : float
-_cache_hits : int
-_cache_misses : int
-_regime_changes : int
-_ticks_processed : int
-_start_time : float
+record_inference_latency(latency)
+record_signal(direction)
+record_pnl(pnl)
+record_cache_hit()
+record_cache_miss()
+record_regime_change()
+record_tick()
+snapshot() dict
}
```

**Diagram sources**
- [metrics.py:14-98](file://backend/app/infrastructure/metrics.py#L14-L98)

**Section sources**
- [metrics.py:14-98](file://backend/app/infrastructure/metrics.py#L14-L98)

### Storage Interfaces and Data Models
- StoragePort consolidates sub-ports for ticks, trades, decisions, open positions, and position events.
- Data models:
  - Ticks: symbol, time, OHLCV, delta, and extra JSON.
  - Trades: position metadata, prices, size, PnL, source/reason, timestamps, and extra JSON.
  - LLM decisions: symbol, direction/confidence, rationale, prompt, raw output, market state/aggression, price/volume/profile metrics, and extra JSON.
  - Performance snapshots: symbol, equity/balance/open PnL, open positions, total trades, win rate, and extra JSON.
  - Session profiles: symbol, market, session date, VAH/VAL/POC, shape, total volume, and extra JSON.
  - Open positions: id, symbol, side, entry/size/SL/TP, source, opened_at, and extra JSON.
  - Position events: position_id, symbol, event_type/time, and extra JSON.
  - Fine-tuning features: trade_id and derived features for ML training.
  - KV store: key/value with updated timestamp.

Indexing strategies:
- Ticks: unique index on (symbol, time); deduplication performed during schema upgrade.
- Trades: index on closed_at for closed trade queries.
- Decisions/Snapshots: index on created_at for time-series queries.
- Session profiles: composite index on (symbol, market, session_date).
- Position events: indexes on (position_id, created_at) and (symbol, created_at).
- Fine-tuning features: indexes on (symbol, created_at) and result.

**Section sources**
- [storage.py:13-121](file://backend/app/domain/ports/storage.py#L13-L121)
- [database.py:24-176](file://backend/app/infrastructure/storage/database.py#L24-L176)
- [database.py:178-181](file://backend/app/infrastructure/storage/database.py#L178-L181)

### Integration with the Trading Pipeline
- TradingSessionService uses the async storage bus for:
  - Persisting ticks (non-blocking)
  - Saving trades and performance snapshots
  - Recording position events and session profiles
- TradingEngine loads open positions at startup and queries ticks for backtesting.
- SignalTrackingService persists gate decisions as position events.
- Health and metrics endpoints expose system health and runtime metrics.

```mermaid
sequenceDiagram
participant TS as "TradingSessionService"
participant BUS as "AsyncPersistenceBus"
participant SA as "SQLiteStorageAdapter"
participant ENG as "TradingEngine"
participant SIG as "SignalTrackingService"
TS->>BUS : save_tick/save_trade/save_llm_decision
BUS->>SA : save_* (queued)
ENG->>SA : load_open_positions()
ENG->>SA : query_ticks(symbol, limit)
SIG->>SA : save_position_event(...)
Note over TS,BUS : Reads are synchronous passthrough
```

**Diagram sources**
- [trading.py:288-607](file://backend/app/application/services/trading_session.py#L288-L607)
- [engine.py:446-588](file://backend/app/application/engine.py#L446-L588)
- [signal_tracking_service.py:277-277](file://backend/app/application/services/signal_tracking_service.py#L277-L277)
- [async_persistence.py:81-107](file://backend/app/infrastructure/async_persistence.py#L81-L107)

**Section sources**
- [trading.py:288-607](file://backend/app/application/services/trading_session.py#L288-L607)
- [engine.py:446-588](file://backend/app/application/engine.py#L446-L588)
- [signal_tracking_service.py:277-277](file://backend/app/application/services/signal_tracking_service.py#L277-L277)

### Practical Patterns and Procedures

#### Data Persistence Patterns
- Asynchronous writes: Use the async bus for non-critical writes (ticks, LLM decisions) to keep the hot path responsive.
- Critical writes: Trade and position persistence are prioritized and less likely to drop under load.
- Explicit flush: Call flush() after processing a batch to ensure durability.

#### Backup and Recovery
- Database backup: Use SQLite’s built-in file-level backup or WAL replay to maintain consistency.
- Recovery: On startup, TradingEngine reloads open positions from storage; TradingSessionService queries recent trades and ticks for continuity.
- Health check: The health endpoint validates database availability via a key-value write.

#### Query Optimization
- Prefer indexed columns in WHERE clauses (e.g., closed_at for trades, created_at for decisions/snapshots).
- Use parameterized queries and limits to constrain result sets.
- For ticks, leverage the unique index on (symbol, time) and flush buffers before queries to ensure visibility.

#### Observability and Monitoring
- Metrics endpoint: Expose latency percentiles, signal counts, PnL, cache hit rate, and regime changes.
- Health endpoint: Reports database readiness and other subsystem statuses.

**Section sources**
- [async_persistence.py:133-159](file://backend/app/infrastructure/async_persistence.py#L133-L159)
- [engine.py:446-446](file://backend/app/application/engine.py#L446-L446)
- [health.py:26-78](file://backend/app/api/routers/health.py#L26-L78)
- [metrics.py:30-56](file://backend/app/api/routers/metrics.py#L30-L56)

## Dependency Analysis
- Domain depends on StoragePort; infrastructure implements it.
- Application services depend on StoragePort for persistence.
- AsyncPersistenceBus depends on any StoragePort implementation.
- MetricsCollector is independent and exposed via routers.

```mermaid
graph LR
SP["StoragePort"] --> SA["SQLiteStorageAdapter"]
SA --> AP["AsyncPersistenceBus"]
AP --> TS["TradingSessionService"]
AP --> ENG["TradingEngine"]
AP --> SIG["SignalTrackingService"]
MC["MetricsCollector"] --> HR["Health Router"]
MC --> MR["Metrics Router"]
```

**Diagram sources**
- [storage.py:54-121](file://backend/app/domain/ports/storage.py#L54-L121)
- [database.py:183-861](file://backend/app/infrastructure/storage/database.py#L183-L861)
- [async_persistence.py:24-277](file://backend/app/infrastructure/async_persistence.py#L24-L277)
- [metrics.py:14-98](file://backend/app/infrastructure/metrics.py#L14-L98)
- [health.py:81-84](file://backend/app/api/routers/health.py#L81-L84)
- [metrics.py:30-56](file://backend/app/api/routers/metrics.py#L30-L56)

**Section sources**
- [dependencies.py:106-112](file://backend/app/api/dependencies.py#L106-L112)

## Performance Considerations
- Write throughput:
  - Tick batching reduces write frequency; adjust batch size and flush interval based on workload.
  - Critical queue prioritization prevents starvation of trade/position writes.
- Concurrency:
  - Single connection with a lock; consider connection pooling if scaling horizontally.
- Indexing:
  - Ensure appropriate indexes exist for frequent queries; monitor query plans.
- Serialization overhead:
  - JSON serialization of extra fields adds CPU cost; minimize unnecessary fields.
- Memory footprint:
  - Metrics buffers cap at a fixed size; consider downsampling for long-running sessions.

[No sources needed since this section provides general guidance]

## Troubleshooting Guide
- Database errors:
  - Look for rollback and commit failures; inspect logs around storage operations.
- Queue drops:
  - Monitor dropped_count and critical pending counts; increase queue sizes if needed.
- Health check failures:
  - Verify database connectivity and permissions; confirm WAL mode and schema initialization.
- Metrics anomalies:
  - Check latency percentiles and cache hit rates; investigate spikes in ticks processed.

**Section sources**
- [database.py:232-248](file://backend/app/infrastructure/storage/database.py#L232-L248)
- [async_persistence.py:150-159](file://backend/app/infrastructure/async_persistence.py#L150-L159)
- [health.py:37-44](file://backend/app/api/routers/health.py#L37-L44)

## Conclusion
The storage adapters layer provides a robust, production-ready foundation for GlassyTrade AI:
- SQLiteStorageAdapter offers durable, indexed persistence with batched writes and explicit transactions.
- AsyncPersistenceBus decouples the trading hot path from I/O latency.
- MetricsCollector enables continuous monitoring of pipeline health and performance.
- The unified StoragePort interface cleanly separates domain logic from infrastructure concerns.

[No sources needed since this section summarizes without analyzing specific files]

## Appendices

### API Usage Examples
- Retrieve recent LLM decisions and signal decisions via API routers using the storage adapter.
- Query position events for a given position or symbol.

**Section sources**
- [ai.py:151-165](file://backend/app/api/routers/ai.py#L151-L165)
- [trading.py:82-95](file://backend/app/api/routers/trading.py#L82-L95)

### Scripts Integration
- Backtest runner and training data collector instantiate the storage adapter directly for offline operations.

**Section sources**
- [run_backtest.py:13-26](file://backend/scripts/run_backtest.py#L13-L26)
- [collect_training_data.py:21-23](file://backend/scripts/collect_training_data.py#L21-L23)