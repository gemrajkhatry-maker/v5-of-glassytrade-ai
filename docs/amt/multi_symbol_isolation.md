# Multi-Symbol Isolation Contract

> Defines the per-symbol state ownership, shared resource semantics,
> and invariants that must hold when multiple QuantEngine instances
> run concurrently under one QuantCoordinator.

## Architecture

```
QuantCoordinator
      │
      ├── QuantEngine(symbol=A)     ← isolated state, own EventStore
      ├── QuantEngine(symbol=B)     ← isolated state, own EventStore
      └── QuantEngine(symbol=C)     ← isolated state, own EventStore
              │
              ├── own EventStore
              ├── own EngineState
              ├── own PositionManager
              ├── own SessionRisk
              ├── own AMTEngine
              ├── own DecisionService
              ├── own StateProjector
              │
              └── shared PortfolioRiskAuthority  (cross-engine risk ceiling)
              └── shared Portfolio               (LiveOMS capital book)
              └── shared SessionLevelStore       (NPOC dedup per session)
              └── shared MultiplexedMarketFeed   (one WS connection)
```

## Per-Symbol Isolated State

Each `QuantEngine` owns ALL of the following exclusively for its symbol:

| State | Owner | Isolation Guarantee |
|-------|-------|-------------------|
| `EventStore` | `QuantEngine.event_store` | Separate instance per engine; events from symbol A never enter symbol B's store |
| `EngineState` | `QuantEngine.state` | Frozen dataclass derived from own EventStore fold |
| `PositionManager` | `QuantEngine._get_position_manager()` | Separate instance; manages exits/pyramids for own symbol only |
| `SessionRisk` | `QuantEngine._risk` | Per-symbol session halt, sizing, and daily-loss tracking |
| `AMTEngine` | `QuantEngine._amt_engine` | Per-symbol AMT analysis with own incremental trackers |
| `DecisionService` | `QuantEngine._decision` | Stateless evaluator; receives symbol-specific `DecisionContext` |
| `StateProjector` | `QuantEngine.projector` | Per-symbol live cache (ltp, oi, depth, closed trades) |
| `BarAggregator` | `QuantEngine._aggregator` | Per-symbol tick → bar aggregation |
| Bar history / tick trace | `QuantEngine._trace`, deques | Per-symbol bounded deques |

### Isolation Invariants

1. **No cross-engine state mutation.** Engine A's event emission (`_emit()`) only modifies engine A's `EventStore`, `EngineState`, and `StateProjector`. There are no direct references between engines.
2. **No shared mutable state in the decision path.** `DecisionService` is stateless. `GatePipeline` operates on a per-call `DecisionContext`. `AMTEngine.analyze()` uses only per-engine state.
3. **Position state is per-engine.** `EventStore.fold()` for engine A produces positions for symbol A only. `PositionManager` for engine A manages symbol A's exits and pyramids only.

## Shared Resources

### PortfolioRiskAuthority

**File**: `quant/execution/portfolio_risk.py`

**Scope**: Shared across ALL engines under one coordinator.

**Purpose**: Aggregate risk ceiling — prevents N engines from simultaneously risking more than the portfolio limit.

**Access pattern**:
- Each engine calls `portfolio_risk.request_entry(risk_amount)` before opening a position
- Each engine calls `portfolio_risk.record_exit(pnl)` when closing a position
- Thread-safe: uses internal locking

**Invariant**: The sum of all engines' open risk must not exceed the portfolio ceiling. This is the ONLY cross-engine coupling in the decision path.

### Portfolio (LiveOMS Capital Book)

**File**: `quant/contracts/aggregates.py` → `Portfolio`

**Scope**: Shared by all `LiveOMS` instances under one coordinator.

**Purpose**: Single capital book so aggregate sizing/exposure is consistent. Without sharing, each engine's Portfolio would report the full account balance independently.

**Access pattern**: Only used when `live_oms_enabled=True` and `broker` is wired. `PaperOMS` does not use this.

### SessionLevelStore

**File**: `quant/session_levels.py` → `SessionLevelStore`

**Scope**: One file, one lock, shared by all engines.

**Purpose**: Deduplicates NPOC (Native POC) records per session across symbols. Prevents duplicate level detection when multiple symbols share similar price zones.

### MultiplexedMarketFeed

**File**: `quant/brokers/multiplexed_feed.py`

**Scope**: One WebSocket connection for all symbols.

**Purpose**: Fan-out tick delivery via per-symbol reader queues. Each engine's `LiveGateway` reads from its own queue.

**Isolation**: Per-symbol reader queues ensure ticks for symbol A are delivered only to engine A.

## Coordinator Operations

### EOD Square-Off (`eod_square_off()`)

- Iterates all engines; force-closes positions for engines whose market has passed the square-off deadline
- **Isolation**: Each engine's `force_close_position()` operates on that engine's own `PositionManager` and `EventStore` only
- No cross-engine side effects

### Dynamic Symbol Rotation (`check_and_rotate_dead_symbols()`)

- Detects dead/expired option symbols and rotates to active ATM contracts
- **Isolation**: `switch_symbol(old, new)` stops the old engine and spawns a new one. The old engine's state is discarded; the new engine starts fresh
- Uses `_lifecycle_lock` to prevent concurrent rotation of the same symbol

### Intraday Reconciliation (`_intraday_reconcile()`)

- Compares broker positions against each engine's position
- **Isolation**: Read-only comparison per engine. Detect-and-alert only — no auto-action
- Returns drift descriptions; does not modify engine state

### Periodic State Reconciliation (`_periodic_state_reconcile()`)

- Delegates to each engine's `periodic_reconcile()`
- **Isolation**: Each engine compares its own cached `EngineState` against its own `EventStore.fold()`. No cross-engine comparison

### Snapshot (`snapshot(symbol)`)

- Composes WS snapshot for one symbol
- **Isolation**: Reads only the specified engine's `EventStore.fold()`, `EngineState`, and `StateProjector`

## Thread Safety Model

| Resource | Lock | Scope |
|----------|------|-------|
| `_engines` dict | `_lock` (Lock) | Dict-level read/write protection |
| Lifecycle operations | `_lifecycle_lock` (RLock) | Serializes start/rescan/switch/stop |
| `PortfolioRiskAuthority` | Internal locking | Cross-engine risk requests |
| `SessionLevelStore` | File lock | Cross-engine NPOC dedup |
| Engine internals | None (single-threaded) | Each engine runs on one pool worker; no concurrent access to own state |

### Key Guarantee

Each `QuantEngine` runs its entire `_run_inner()` loop on a single `ThreadPoolExecutor` worker. Within that loop, there are no concurrent mutations to the engine's state. The only cross-engine calls (PortfolioRiskAuthority) are thread-safe by design.

## Testing Requirements

To verify multi-symbol isolation, tests must assert:

1. **State independence**: Engine A's EventStore contains only symbol A events; engine B's contains only symbol B events
2. **Decision independence**: A position opened on symbol A does not affect symbol B's decision pipeline
3. **Risk aggregation correctness**: PortfolioRiskAuthority correctly aggregates risk across engines without double-counting
4. **No cross-contamination on operations**: EOD square-off on symbol A does not modify symbol B's state
5. **Determinism**: Two runs with the same per-symbol tick streams produce identical event traces per symbol
