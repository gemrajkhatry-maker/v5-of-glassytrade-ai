# Runtime Ownership Matrix

## Purpose

This file is the **canonical, runtime-owned state map** for the backendv2 runtime.
It defines:

- Which component owns each mutable state slice.
- Exactly which methods are allowed to mutate that state.
- Which states must be immutable to all other components.
- The canonical event edges through which ownership is crossed.

Any direct cross-component state access that bypasses a stage's event contract should be treated as a contract violation.

## Runtime stages and ownership

All stages are listed from feed ingestion to egress.

### TickSequencer (tick sequencing)

- Stage owner: `backendv2/app/runtime/pipeline/sequencer.py:TickSequencer`
- Owned state:
  - `_counter`
  - `_last_seen`
  - `_out_of_order_count`
  - `_order_violation_count`
  - `_symbol_stall_count`
  - `_drop_count`
  - `_max_sequence`
  - `_max_symbols`
- Valid mutation points:
  - `process()`
  - `restore()`
  - `warmup()`
  - `reset()`
  - `snapshot()` (read-only serialization)
- Contract:
  - Owns sequence/tick-order discipline.
  - Mutates its own counters only.
  - Emits `SequencedTick` for downstream stages.

### TickNormalizer (symbol profiles / normalization contract)

- Stage owner: `backendv2/app/runtime/pipeline/normalizer.py:TickNormalizer`
- Owned state:
  - `_profiles`
  - `_allowed_symbols`
  - `_strict_symbol_mode`
- Valid mutation points:
  - `process()`
  - `register_symbol()`
  - `register_symbols()`
  - `unregister_symbol()`
  - `set_allowed_symbols()`
  - `restore()`
  - `warmup()`
  - `reset()`
  - `snapshot()` (read-only serialization)
- Contract:
  - Owns tick-to-canonical conversion rules.
  - Emits `NormalizedTick`.

### CandlePipeline (candle builders)

- Stage owner: `backendv2/app/runtime/pipeline/candle_builder.py:CandlePipeline`
- Owned state:
  - `_active`
  - `_timeframes`
- Valid mutation points:
  - `process()`
  - `build_candles()`
  - `restore()`
  - `warmup()`
  - `teardown()`
  - `reset()`
  - `snapshot()` (read-only serialization)
- Contract:
  - Owns completed and in-flight candle builders.
  - Emits `Candle`.

### OrderFlowPipeline

- Stage owner: `backendv2/app/runtime/pipeline/orderflow.py:OrderFlowPipeline`
- Owned state:
  - `_states`
  - `_window`
  - `_tick_index`
- Valid mutation points:
  - `process()`
  - `restore()`
  - `warmup()`
  - `teardown()`
  - `reset()`
  - `snapshot()`
- Contract:
  - Owns CVD / micro-order flow accumulators.
  - Emits `OrderFlowMetrics`.

### MicrostructureAnalysis

- Stage owner: `backendv2/app/runtime/pipeline/microstructure.py:MicrostructureAnalysis`
- Owned state:
  - `_state`
  - `_last_tick_ts`
- Valid mutation points:
  - `process()`
  - `restore()`
  - `warmup()`
  - `teardown()`
  - `reset()`
  - `snapshot()`
- Contract:
  - Owns top-of-book / depth pressure transitions.
  - Emits `MicrostructureMetrics`.

### MarketStructureAnalysis

- Stage owner: `backendv2/app/runtime/pipeline/market_structure.py:MarketStructureAnalysis`
- Owned state:
  - `_states`
- Valid mutation points:
  - `process()`
  - `process_symbol()`
  - `restore()`
  - `warmup()`
  - `teardown()`
  - `reset()`
  - `snapshot()` (read-only)
- Contract:
  - Owns AMT sub-analyzers and per-symbol bar history.
  - Emits `MarketStructureResult`.

### FeatureComputation

- Stage owner: `backendv2/app/runtime/pipeline/features.py:FeatureComputation`
- Owned state:
  - `_candles`
  - `_orderflow`
  - `_micro`
  - `_market`
  - `_max_candles`
- Valid mutation points:
  - `process()`
  - `ingest_orderflow()`
  - `ingest_microstructure()`
  - `ingest_market_structure()`
  - `restore()`
  - `warmup()`
  - `teardown()`
  - `reset()`
  - `snapshot()`
- Contract:
  - Owns derived feature buffers and latest context by symbol.
  - Emits `FeatureVector`.

### SignalGeneration

- Stage owner: `backendv2/app/runtime/pipeline/signal.py:SignalGeneration`
- Owned state:
  - `_last_feature`
  - `_last_orderflow`
  - `_last_micro`
  - `_last_market`
  - `_bars`
- Valid mutation points:
  - `process()`
  - `ingest()`
  - `ingest_orderflow()`
  - `ingest_microstructure()`
  - `ingest_market_structure()`
  - `restore()`
  - `warmup()`
  - `teardown()`
  - `reset()`
  - `snapshot()`
- Contract:
  - Owns signal-generation input rolling state.
  - Emits `Signal` only through process output.

### GateEvaluation

- Stage owner: `backendv2/app/runtime/pipeline/gates.py:GateEvaluation`
- Owned state:
  - `_seen`
- Valid mutation points:
  - `process()`
  - `restore()`
  - `warmup()`
  - `teardown()`
  - `reset()`
  - `snapshot()`
- Contract:
  - Owns idempotency-safe gate dedupe key set.
  - Emits `GateResult`.

### RiskEvaluation

- Stage owner: `backendv2/app/runtime/pipeline/risk.py:RiskEvaluation`
- Owned state:
  - `_state` (per-symbol `kill_switch`, `risk_manager`, `portfolio`)
- Valid mutation points:
  - `process()`
  - `sync_position_event()`
  - `retract_position()`
  - `notify_trade_closed()`
  - `restore()`
  - `warmup()`
  - `teardown()`
  - `reset()`
  - `snapshot()`
- Contract:
  - Owns risk policy and portfolio risk view.
  - Emits `RiskResult`.
  - Must only apply fill close accounting through `sync_position_event()`.
  - Must only remove pre-fill rejects through `retract_position()`.

### PositionLifecycle

- Stage owner: `backendv2/app/runtime/pipeline/position.py:PositionLifecycle`
- Owned state:
  - `_portfolio`
  - `_metrics`
- Valid mutation points:
  - `process()` (delegates to `_handle_signal`, `_handle_fill`, `_handle_order_status`, etc.)
  - `process_exit_signal()`
  - `restore()`
  - `warmup()`
  - `teardown()`
  - `reset()`
  - `snapshot()`
- Contract:
  - Owns runtime position books for open lifecycle.
  - Emits `PositionEvent`.
  - Pre-fill broker failures map to rejection/cancel closed lifecycle only via `ORDER_STATUS`.

### ExecutionPipeline

- Stage owner: `backendv2/app/runtime/pipeline/execution.py:ExecutionPipeline`
- Owned state:
  - `_broker`
- Valid mutation points:
  - `__init__()`
  - `process()`
  - `restore()`
  - `warmup()`
  - `teardown()`
  - `reset()`
- Contract:
  - Owns broker binding selection only.
  - Emits `OrderStatusEvent`.

### BrokerSynchronization

- Stage owner: `backendv2/app/runtime/pipeline/broker_sync.py:BrokerSynchronization`
- Owned state:
  - `_open_orders`
- Valid mutation points:
  - `process()`
  - `restore()`
  - `warmup()`
  - `teardown()`
  - `reset()`
  - `snapshot()`
- Contract:
  - Owns in-flight order status map.
  - Emits `FillEvent` for FILLED statuses.
  - Never mutates position state directly.

### EventPersistence

- Stage owner: `backendv2/app/runtime/pipeline/persistence.py:EventPersistence`
- Owned state:
  - `_buffer`
  - `_dropped_events`
  - `_flush_count`
  - `_flush_failures`
  - `_last_flush_ns`
  - `_last_tick_written_ns`
  - `_flush_interval_ns`
  - `_last_tick_written_ns`
- Valid mutation points:
  - `process()`
  - `flush()`
  - `restore()`
  - `warmup()`
  - `teardown()`
  - `reset()`
  - `snapshot()`
- Contract:
  - Owns bounded persistence ring state and flush accounting.
  - Should never own or mutate runtime domain state (portfolio, risk, symbols, candles).

### TelemetryPipeline

- Stage owner: `backendv2/app/runtime/pipeline/telemetry.py:TelemetryPipeline`
- Owned state:
  - `_counters`
  - `_latencies_ns`
  - `_started_ns`
  - `_metrics`
- Valid mutation points:
  - `start_span()`
  - `end_span()`
  - `restore()`
  - `warmup()`
  - `teardown()`
  - `reset()`
  - `snapshot()`
- Contract:
  - Owns only observability state.
  - Must not alter trading state.

### StrategyRuntime

- Stage owner: `backendv2/app/runtime/pipeline/strategy.py:StrategyRuntime`
- Owned state:
  - `_strategies`
  - `_register_counter`
  - `_metrics`
- Valid mutation points:
  - `register()`
  - `unregister()`
  - `clear()`
  - `process()`
  - `restore()`
  - `warmup()`
  - `teardown()`
  - `reset()`
  - `snapshot()`
- Contract:
  - Owns strategy registration metadata and deterministic dispatch order.
  - Emits `StrategyEvent` envelopes.

## Orchestration boundary

- Owner: `backendv2/app/runtime/orchestrator/session.py:SessionRuntime`
- Owned state:
  - `_event_count`
  - `_running`
  - staged stage instances (`_sequencer`, `_normalizer`, ...).
- Valid mutation points:
  - `start()`, `stop()`, `run_once()`, `_process_tick()`, `_run_signal_flow()`, `warmup()`, `teardown()`, `register_strategy()`, `unregister_strategy()`
- Contract:
  - Owns orchestration flow and lifecycle control only.
  - Stage state mutation must flow via explicit stage APIs, never by direct state assignment to stage internals.

## Orchestrator boundary

- Owner: `backendv2/app/runtime/orchestrator/registry.py:RuntimeOrchestrator`
- Owned state:
  - `_sessions`
- Valid mutation points:
  - `create_live_session()`
  - `get_session()`
  - `start()`, `stop()`, `run_once()`
  - `teardown_all()`
- Contract:
  - Owns session map and per-session lifecycle.
  - Live-only orchestration only; no checkpoint/restart contract is exposed at session/orchestrator level.
