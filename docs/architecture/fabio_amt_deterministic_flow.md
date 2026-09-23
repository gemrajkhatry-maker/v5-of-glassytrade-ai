# Fabio AMT Deterministic Trading Flow — Canonical Architecture

> Single-source-of-truth document for the Fabio AMT trading system.
> Every component, responsibility, and data flow is mapped to concrete code.

## 1. End-to-End Execution Flow

```
Dhan WebSocket
      │
      ▼
MultiplexedMarketFeed          (quant/brokers/multiplexed_feed.py)
      │  one WS connection, fan-out per symbol via add_reader()
      ▼
LiveGateway                    (quant/brokers/live_gateway.py)
      │  per-symbol tick queue; subscribe()/next_tick()/try_next_tick()
      ▼
QuantCoordinator               (quant/multi_engine.py)
      │  owns one QuantEngine per scanned contract
      │  bounded ThreadPoolExecutor (max_workers = config n)
      │  shared PortfolioRiskAuthority + Portfolio (LiveOMS capital book)
      ▼
QuantEngine                    (quant/runtime.py)
      │  single-threaded deterministic event loop
      │
      ├── BarAggregator        (quant/aggregator.py)
      │     ticks → fixed-interval bars (default 60s)
      │
      ├── AMTEngine            (quant/amt_engine.py)
      │     bar → AMTAnalyzer.analyze() → AMTResult → amt_result_to_dto()
      │
      ├── DecisionService      (quant/decision/decision_service.py)
      │     AMT DTO + context → GatePipeline (4 gates) → SignalBuilder → QuantDecision
      │
      ├── PaperOMS / LiveOMS   (quant/execution/oms.py, live_oms.py)
      │     QuantDecision signal → submit()/close() → Position/Fill
      │
      ├── PositionManager      (quant/position_manager.py)
      │     manages exits (bar-based + tick-based), pyramids, stop trailing
      │
      ├── ExitEngine           (quant/execution/exits.py)
      │     evaluates SL/TP/structural exit conditions
      │
      ├── SessionRisk          (quant/execution/risk.py)
      │     session halt, sizing, cushion tiers, daily-loss limit
      │
      └── EventStore           (quant/event_store.py)
            append-only event log; SHA-256 checksum chain
            every event → _emit() → EventStore.append() + apply_event() → EngineState
```

### Post-Engine Flow (Frontend)

```
EventStore.fold()              → EngineState (frozen dataclass)
      │
      ▼
project_state(EngineState)     → ViewState        (quant/state.py)
      │
      ▼
view_state_to_ws(ViewState)    → dict             (quant/ws_adapter.py)
      │
      ▼
QuantCoordinator.snapshot()    merges fold-derived book
      │                        with StateProjector live cache
      ▼
WebSocket gameloop             (backend/app/api/websocket/gameloop.py)
      │  _coordinator_viewer_loop: 0.5s cadence, asyncio.to_thread
      ▼
Frontend (React)
```

## 2. State Ownership — Single Source of Truth

| State | Owner | Derived By | Notes |
|-------|-------|-----------|-------|
| **Positions** (open, pyramids) | `EventStore` | `fold()` → `EngineState.position` | `StateProjector` is NOT a position authority; it is a live cache for ticks/depth/AMT banner |
| **EngineState** | `EventStore` | `fold()` via `apply_event()` | Frozen dataclass; all transitions are pure (`with_bar`, `with_position`, `without_position`, `with_risk`) |
| **Risk state** | `EventStore` → `SessionRisk` | `fold()` for persisted; `SessionRisk` for live session tracking | `SessionRisk` is per-engine; `PortfolioRiskAuthority` is shared across engines |
| **AMT analysis** | `AMTEngine` (per-engine) | Computed per closed bar from `AMTAnalyzer` | Incremental: `IncrementalVolumeProfile`, `CVDTracker`, `Footprint` cache |
| **WS snapshot** | `QuantCoordinator.snapshot()` | Merges `project_state(fold())` + `StateProjector` live fields | Positions always from fold; ltp/oi/depth from projector |

### State Flow Invariants

1. **EventStore is append-only.** State is never mutated directly; it is derived by folding events.
2. **EngineState is immutable.** Every transition returns a new instance via `dataclasses.replace()`.
3. **`_emit()` is the central bus.** Every event goes through `_emit()` → `EventStore.append()` + `apply_event()` → cached `EngineState` update.
4. **StateProjector is a live cache only.** It holds per-tick data (ltp, oi, depth, forming candle, closed trades) that an event fold cannot know without retaining full history.
5. **No dual writes.** Position state lives in EventStore only. `PositionManager` operates through OMS and emits events; it does not maintain independent position state.

## 3. Decision Authority

```
DecisionService.evaluate(ctx)
      │
      ├── Risk halt check (if ctx.risk_halted and not allow_positioned)
      │     → HALTED
      │
      ├── GatePipeline.evaluate(ctx)
      │     ├── Gate 1: gate_session_phase     — session clock valid?
      │     ├── Gate 2: gate_position_cooldown  — no open position, cooldown elapsed?
      │     ├── Gate 3: gate_triple_a_edge      — absorption → accumulation → aggression?
      │     └── Gate 4: gate_risk_reward        — stop-cap gate? (R:R >= 1.5 in SignalBuilder)
      │
      ├── All gates pass → SignalBuilder.build_or_reason(ctx)
      │     → Triple-A or LVN_Sniper signal → APPROVED
      │
      ├── Gate 1 or 2 failed → GATE_REJECTED (hard reject, no fade)
      │
      └── Gate 3 or 4 failed → VA-fade fallback
            → detect_va_fade(ctx) → VA_FADE or NO_EDGE
```

**LLMAdvisor is advisory-only.** It consumes `DecisionContext` via `_advisor.on_context()` and emits `AgentDecisionProduced` events, but it **never gates an entry**. The 4-gate pipeline is 100% deterministic.

## 4. Multi-Symbol Orchestration

### QuantCoordinator Responsibilities

| Responsibility | Method | Frequency |
|---------------|--------|-----------|
| Engine lifecycle (start/stop/rescan) | `start()`, `rescan()`, `switch_symbol()`, `stop()` | On demand |
| EOD square-off | `eod_square_off()` | Every 30s via watchdog |
| Dynamic symbol rotation | `check_and_rotate_dead_symbols()` | Every 60s via watchdog |
| Broker-vs-engine reconciliation | `_intraday_reconcile()` | Every 60s via watchdog |
| State-vs-EventStore reconciliation | `_periodic_state_reconcile()` | Every 120s via watchdog |
| WS snapshot composition | `snapshot(symbol)` | Every 500ms via gameloop |

### Thread Model

- **Bounded `ThreadPoolExecutor`**: `max_workers = config.n` (default 8). Each running engine occupies one worker. Spawns beyond capacity are refused.
- **`_lifecycle_lock` (RLock)**: Serializes lifecycle transitions (start/rescan/switch/stop) to prevent duplicate engine spawns.
- **`_lock` (Lock)**: Protects `_engines` and `_gateways` dict access.
- **Watchdog thread**: Single daemon thread runs EOD square-off, rotation, and reconciliation loops.

### Shared Resources

| Resource | Scope | Access Pattern |
|----------|-------|---------------|
| `PortfolioRiskAuthority` | All engines | Thread-safe; every engine registers entries/exits against one authority |
| `Portfolio` (LiveOMS capital book) | All LiveOMS instances | Shared so aggregate sizing/exposure is consistent |
| `SessionLevelStore` | All engines | One file, one lock; deduplicates NPOC records per session |
| `MultiplexedMarketFeed` | All engines | One WS connection; per-symbol reader queues |

## 5. Event Sourcing & Persistence

### EventStore

- **Append-only log** with sequence numbers and SHA-256 HMAC checksum chain.
- **`fold()`** derives `EngineState` by replaying events through `apply_event()`. Incremental: only processes events since last fold.
- **`export()` / `export_to_jsonl()`**: Lazy streaming export. `export_to_jsonl()` writes one row at a time without retaining in memory.
- **`import_()`**: Validates contiguous sequence, enforces HMAC checksums, rebuilds atomically.
- **`prune(keep_last=k)`**: Re-roots checksum chain from GENESIS, resets fold cache. Bounds memory for long-running engines.
- **`verify_chain()`**: Validates entire HMAC chain. Used at startup for tamper detection.

### Restart & Recovery

0. Coordinator loads SQLite open-position rows → `row_to_position(row)` → `restore_position(...)` (cross-restart durable source; JSONL journal is write-only and not replayed).
1. `restore_position(position)` — Seeds `EventStore` with a baseline `PositionOpened` event and rehydrates `PositionManager`.
2. `startup_reconcile()` — Verifies checksum chain, folds `EventStore`, reconciles against `PositionManager` book (book wins if fold empty).
3. `periodic_reconcile()` — Compares cached `EngineState` against fresh fold; detects drift.

Covering tests: `tests/quant/persistence/test_restart_contract.py::test_restart_restores_position_from_sqlite_row_then_startup_reconcile`, `tests/quant/test_partial_fold_reconcile.py::TestStartupReconcileRestore`.

## 6. Responsibility Ownership Map

| Responsibility | Module | Class/Function |
|---------------|--------|---------------|
| Tick ingestion | `quant/brokers/` | `MultiplexedMarketFeed`, `LiveGateway` |
| Bar aggregation | `quant/aggregator.py` | `BarAggregator` |
| AMT analysis | `quant/amt/analyzer.py` | `AMTAnalyzer` |
| AMT engine (per-symbol) | `quant/amt_engine.py` | `AMTEngine` |
| Decision gates | `quant/decision/pipeline.py` | `GatePipeline` |
| Decision evaluation | `quant/decision/decision_service.py` | `DecisionService` |
| Signal construction | `quant/decision/signal_builder.py` | `SignalBuilder` |
| Order management (paper) | `quant/execution/oms.py` | `PaperOMS` |
| Order management (live) | `quant/execution/live_oms.py` | `LiveOMS` |
| Position exits | `quant/execution/exits.py` | `ExitEngine` |
| Position management | `quant/position_manager.py` | `PositionManager` |
| Session risk | `quant/execution/risk.py` | `SessionRisk` |
| Portfolio risk (cross-engine) | `quant/execution/portfolio_risk.py` | `PortfolioRiskAuthority` |
| Event sourcing | `quant/event_store.py` | `EventStore` |
| State machine | `quant/state_machine.py` | `EngineState` |
| State projection | `quant/state.py` | `project_state()`, `StateProjector` |
| WS adapter | `quant/ws_adapter.py` | `view_state_to_ws()` |
| Multi-engine orchestration | `quant/multi_engine.py` | `QuantCoordinator` |
| Engine runtime | `quant/runtime.py` | `QuantEngine` |
| LLM advisor (advisory-only) | `quant/llm/advisor.py` | `LLMAdvisor` |
| Advisor factory | `quant/wiring_advisor.py` | `build_live_advisor()` |

## 7. Key Design Decisions

1. **Deterministic by construction.** `QuantEngine` is single-threaded. Given the same tick sequence, it always produces the same event trace. No LLM inference in the decision path.
2. **Event-sourced state.** `EventStore` is the single source of truth. `EngineState` is derived, never mutated directly. This enables replay, restart recovery, and audit.
3. **One engine per symbol.** Each `QuantEngine` is fully isolated. Cross-engine coordination happens only through `PortfolioRiskAuthority` (risk ceiling) and shared `Portfolio` (LiveOMS capital).
4. **Advisor is advisory.** `LLMAdvisor` consumes context and emits narrative events but never gates trading decisions. It can be disabled entirely without affecting trading behavior.
5. **Bounded concurrency.** The coordinator uses a bounded thread pool. Engine spawns beyond capacity are refused. Lifecycle operations are serialized.
6. **Incremental AMT.** `AMTAnalyzer` uses incremental trackers (`IncrementalVolumeProfile`, `CVDTracker`, `Footprint` cache) to avoid recomputing from scratch on every bar.
