# BackendV2 Target Runtime Architecture

> Ultra-low-latency deterministic trading runtime. No historic-mode reconstruction. Event-driven pipeline architecture with explicit ownership, bounded mutation, and live-only execution.

---

## Core Runtime Topology

```
                    ┌──────────────────────────────────────────────┐
                    │              Runtime Orchestrator             │
                    │  Session lifecycle | Symbol scheduling        │
                    │  Pipeline wiring | Health monitoring          │
                    └──────────┬───────────────────────────────────┘
                               │
   ┌─────────────┐
   │  Live Feed  │
   └──────┬──────┘
          │
                              │
                    ┌─────────▼─────────┐
                    │   Tick Sequencer   │
                    │   (deterministic)  │
                    └─────────┬─────────┘
                              │
                    ┌─────────▼─────────┐
                    │  Tick Normalizer   │
                    └─────────┬─────────┘
                              │
               ┌──────────────┼──────────────┐
               ▼              ▼              ▼
        ┌───────────┐  ┌────────────┐  ┌──────────────┐
        │  Candle    │  │  OrderFlow  │  │ Microstructure│
        │ Pipeline   │  │  Pipeline   │  │  Pipeline     │
        └─────┬─────┘  └──────┬─────┘  └──────┬───────┘
              │               │               │
              └───────────────┼───────────────┘
                              │
                    ┌─────────▼─────────┐
                    │  Feature Compute  │
                    └─────────┬─────────┘
                              │
                    ┌─────────▼─────────┐
                    │  Signal Pipeline   │
                    └─────────┬─────────┘
                              │
                    ┌─────────▼─────────┐
                    │  Gate Pipeline     │
                    └─────────┬─────────┘
                              │
                    ┌─────────▼─────────┐
                    │  Risk Pipeline     │
                    └─────────┬─────────┘
                              │
                    ┌─────────▼─────────┐
                    │  Execution Pipeline │
                    └─────────┬─────────┘
                              │
                    ┌─────────▼─────────┐
                    │  Broker Sync       │
                    └─────────┬─────────┘
                              │
                    ┌─────────▼─────────┐
                    │  Event Persistence │
                    └───────────────────┘
```

---

## Runtime Modules

### MarketDataIngestion

| Property | Specification |
|----------|--------------|
| **Responsibility** | Own feed connections. Normalize raw market data into internal Tick structs. No buffering. Push model. |
| **Inputs** | Raw exchange feed (Level 1 ticks, optional Level 2 depth) |
| **Outputs** | `Tick` struct → TickSequencer |
| **Owned State** | Feed connection handle. Symbol → exchange mapping. |
| **Mutation** | Stateless per tick. No cross-tick accumulation. |
| **Sync vs Async** | Async I/O boundary. Ingest thread → lock-free queue to sequencer. |
| **Hot Path** | Tick parse → struct fill → queue push. No allocations after warmup. |
| **Failure** | Feed disconnect → reconnect with exponential backoff. Lost ticks tolerated via gap fill on resume. |
| **Testing** | Mock feed → verify Tick struct fields. Inject bad data → verify error handling. |

### TickSequencer

| Property | Specification |
|----------|--------------|
| **Responsibility** | Assign monotonic sequence numbers. Maintain global tick order across symbols. Drop duplicate timestamps. |
| **Inputs** | Raw `Tick` from any feed source |
| **Outputs** | `SequencedTick` → next pipeline stage |
| **Owned State** | Atomic `sequence_counter: u64`. Last `(symbol, timestamp)` seen. |
| **Mutation** | Single-threaded consumer. Bounded ring buffer input. |
| **Sync vs Async** | Synchronous. Consumes from lock-free queue. |
| **Hot Path** | Sequence increment. Duplicate check (hash set per symbol, size=2). No heap alloc. |
| **Failure** | Counter overflow → runtime panic (unreachable in practice). Duplicate detected → drop silently. |
| **Testing** | Inject 100 ticks → verify monotonic sequence. Inject duplicate → verify drop. Mixed symbol order → verify global sequence. |

### TickNormalizer

| Property | Specification |
|----------|--------------|
| **Responsibility** | Convert exchange-specific tick formats into canonical internal representation. Apply price/quantity normalization, decimal scaling, contract multiplier adjustments. |
| **Inputs** | `SequencedTick` from sequencer |
| **Outputs** | `NormalizedTick` → CandlePipeline and OrderFlowPipeline |
| **Owned State** | Symbol metadata cache (tick size, lot size, multiplier, decimal places) |
| **Mutation** | Read-only after initialization. Metadata loaded once per symbol on session start. |
| **Sync vs Async** | Synchronous |
| **Hot Path** | Multiply/divide by precomputed scalars. No branching per symbol (lookup table). |
| **Failure** | Unknown symbol → stall runtime (require metadata before first tick). Invalid price → log, skip tick. |
| **Testing** | NSE tick → verify multiplier applied. MCX tick → verify decimal shift. Unknown symbol → verify stall. |

### CandlePipeline

| Property | Specification |
|----------|--------------|
| **Responsibility** | Build 1-minute, 5-minute, 15-minute, hourly, daily OHLC candles from normalized ticks. Emit completed candle events. |
| **Inputs** | `NormalizedTick` |
| **Outputs** | `Candle` (open, high, low, close, volume, timestamp) |
| **Owned State** | Active candle per symbol per timeframe. Map: `(symbol, timeframe) → CandleBuilder`. |
| **Mutation** | In-place update of active candle H/L/C/Volume. Open set once on first tick of new period. |
| **Sync vs Async** | Synchronous |
| **Hot Path** | Compare tick price against current H/L. Increment volume. No heap. |
| **Failure** | Gap in ticks → candle still valid (open from first tick after gap, close from last). Partial candle emitted at session end. |
| **Testing** | Feed ordered ticks → verify all OHLC fields. Feed gap → verify candle covers available range. Verify all timeframes emit at correct boundaries. |

### OrderFlowPipeline

| Property | Specification |
|----------|--------------|
| **Responsibility** | Compute tick-level order flow metrics: bid/ask imbalance, cumulative delta, footprint, volume clusters, bid/ask volume ratio. |
| **Inputs** | `NormalizedTick` |
| **Outputs** | `OrderFlowMetrics` → FeatureComputation and SignalPipeline |
| **Owned State** | Rolling window of bid/ask volumes (size=100). CVD accumulator per symbol. |
| **Mutation** | Rolling window update (ring buffer). CVD += (bid_vol - ask_vol). |
| **Sync vs Async** | Synchronous |
| **Hot Path** | Two floating-point ops per tick (delta, accumulator). Array write to ring buffer. |
| **Failure** | Missing bid/ask → treat as zero delta. CVD overflow → renormalize. |
| **Testing** | Feed ticks with known delta → verify CVD matches. Verify window slides correctly. Verify metrics at tick n vs n+100. |

**Existing module mapping**:
- `cvd_tracker.py` → CVD accumulator sub-component
- `orderflow_detectors.py` → BigTrade, Bubble, OFI detection sub-components
- `absorption_detector` (inside orderflow_detectors.py) → OrderFlowPipeline

### MicrostructureAnalysis

| Property | Specification |
|----------|--------------|
| **Responsibility** | Compute Level 2 / depth-derived metrics: spread, order book imbalance, depth pressure, iceberg detection, stop-run detection. Operates on optional depth data. Degrades gracefully when only Level 1 available. |
| **Inputs** | Depth snapshots (optional), NormalizedTick |
| **Outputs** | `MicrostructureMetrics` → FeatureComputation and SignalPipeline |
| **Owned State** | Current order book state per symbol (bids sorted desc, asks sorted asc). |
| **Mutation** | Full replace on depth snapshot (exchange-driven). No cumulative state across snapshots. |
| **Sync vs Async** | Synchronous |
| **Hot Path** | Peek at top-of-book only (bid[0], ask[0]). Full depth only computed on demand or per second. |
| **Failure** | No depth data → all metrics set to NaN/None. Stale depth > 100ms → mark metrics stale. |
| **Testing** | Feed depth snapshots → verify spread, imbalance. Missing depth → verify graceful degradation. Iceberg order pattern → verify detection. |

### MarketStructureAnalysis

| Property | Specification |
|----------|--------------|
| **Responsibility** | Compute market structure from candles and order flow: volume profile (POC, VAH, VAL), LVN/HVN, market state (balanced/imbalanced), acceptance/rejection, displacement, initial balance, session context, break detection, profile classification. |
| **Inputs** | Completed `Candle` events, `OrderFlowMetrics` |
| **Outputs** | `MarketStructureResult` → FeatureComputation |
| **Owned State** | Volume profile builder per symbol. Session context per symbol. LVN/HVN registry. |
| **Mutation** | Candle-driven. Accumulate volume in profile buckets. Update session state at candle close. |
| **Sync vs Async** | Synchronous |
| **Hot Path** | Bucket index calculation (price → bucket). Volume add. No allocation. |
| **Failure** | Partial session data → emit with degraded confidence. |
| **Testing** | Feed 390 minutes of candles → verify POC at expected bucket. Verify VA expansion to 68%. Verify LVN below 15% mean threshold. |

**Existing module mapping**:
- `volume_profile.py` → VolumeProfile sub-component
- `lvn_detector.py` → LVN/HVN sub-component
- `market_state_engine.py` → MarketState sub-component
- `acceptance_rejection.py` → Acceptance/Rejection sub-component
- `break_detector.py` → BreakDetection sub-component
- `displacement_detector.py` → Displacement sub-component
- `initial_balance_engine.py` → InitialBalance sub-component
- `session_context.py` → SessionContext sub-component
- `profile_classifier.py` → ProfileClassification sub-component
- `drive_tracker.py` → DriveTracking sub-component
- `mtf_analyzer.py` → MultiTimeframe sub-component

### FeatureComputation

| Property | Specification |
|----------|--------------|
| **Responsibility** | Compute derived features for signal generation: VWAP + σ bands, RSI, ATR, rolling correlations, normalized feature vectors. All features are pure functions of windowed input data. |
| **Inputs** | `Candle`, `OrderFlowMetrics`, `MarketStructureResult`, `MicrostructureMetrics` |
| **Outputs** | `FeatureVector` → SignalPipeline |
| **Owned State** | Rolling windows per symbol per feature. Window sizes: 20, 50, 200 bars. |
| **Mutation** | Ring buffer append on new candle. Read-only for feature computation. |
| **Sync vs Async** | Synchronous |
| **Hot Path** | VWAP: running sum of (price * volume) / running sum of volume. No heap. |
| **Failure** | Insufficient data → features return NaN. Downstream handles NaN via graceful degradation. |
| **Testing** | Feed known price/volume sequence → verify VWAP matches manual calculation. Verify σ bands at correct stddev multiple. |

**Existing module mapping**:
- `VWAP` computation → sub-component (currently missing, needs creation)
- `AggressionScorer` → consumes features (currently in aggression_scorer.py)

### SignalGeneration

| Property | Specification |
|----------|--------------|
| **Responsibility** | Generate trade signals from feature vector + market structure. Triple-A methodology: BUY absorption + above VWAP = LONG, SELL absorption + below VWAP = SHORT. No state. Pure function. |
| **Inputs** | `FeatureVector`, `MarketStructureResult`, `OrderFlowMetrics` |
| **Outputs** | `Signal` → GatePipeline |
| **Owned State** | None. Stateless computation. |
| **Mutation** | None. |
| **Sync vs Async** | Synchronous |
| **Hot Path** | Compare. Branch. No heap. |
| **Failure** | Invalid input → NO_TRADE signal. Missing features → NO_TRADE. |
| **Testing** | Known absorption + VWAP → verify LONG/SHORT. Missing absorption → verify NO_TRADE. R:R < 1.5 → verify NO_TRADE. |

**Existing module mapping**:
- `signal_generator.py` → SignalGeneration module (rename from generator to pipeline)

### GateEvaluation

| Property | Specification |
|----------|--------------|
| **Responsibility** | Evaluate signal against configurable gate pipeline: aggression score, confidence threshold, session phase filter, playbook guard, gate rejection tracker, LLM overseer (optional). Each gate is an independent evaluator. |
| **Inputs** | `Signal`, `MarketStructureResult`, `OrderFlowMetrics`, `FeatureVector` |
| **Outputs** | `GateResult` (approved/rejected + reason) → RiskPipeline |
| **Owned State** | Gate configuration per symbol. AggressionScorer with persistence history. Gate rejection counters. |
| **Mutation** | Update persistence history per gate evaluation. Increment rejection counters. |
| **Sync vs Async** | Synchronous for gate rules. Async-callable for LLM overseer (optional, non-blocking). |
| **Hot Path** | Aggression score: 7-component additive scoring. All integer arithmetic. No heap. |
| **Failure** | Any gate fails → signal rejected with rejection reason. LLM overseer timeout → fall through with reduced confidence. |
| **Testing** | Generate signal with high aggression → verify gate passes. Low aggression → verify gate rejects. Verify persistence bars requirement. |

**Existing module mapping**:
- `aggression_scorer.py` → AggressionGate sub-component
- Gate pipeline (currently missing) → create GateEvaluation module
- Entry gates (currently missing) → create gate evaluators

### RiskEvaluation

| Property | Specification |
|----------|--------------|
| **Responsibility** | Pre-trade and intra-trade risk validation. Daily drawdown check (2% from peak). Consecutive losses check (3 max). Position limits (concurrent 5). Portfolio notional (60%). Per-symbol notional (20%). Kill switch. Circuit breakers (price velocity, volume spike). |
| **Inputs** | Approved `Signal`, `Portfolio`, current market state |
| **Outputs** | `RiskResult` (approved/rejected + reason) → ExecutionPipeline |
| **Owned State** | `DailyRiskState` per trading day. `KillSwitch` state. Circuit breaker thresholds. |
| **Mutation** | Update risk state on trade open/close. Check thresholds synchronously. |
| **Sync vs Async** | Synchronous |
| **Hot Path** | Compare P&L against peak. Compare position count against limit. All integer. |
| **Failure** | Threshold breached → reject + halt. Kill switch → reject all. |
| **Testing** | Simulate 2% drawdown → verify halt. 3 consecutive losses → verify pause. Kill switch active → verify all rejected. |

**Existing module mapping**:
- `risk_manager.py` → RiskEvaluation module (already exists, needs pipeline integration)
- Circuit breakers (missing) → create sub-component
- Self-healing (missing) → create sub-component

### PositionLifecycle

| Property | Specification |
|----------|--------------|
| **Responsibility** | Track open positions, manage SL/TP, trail stops, partition exits (P1/P2/P3), pyramid adds, position sizing. Stateful per symbol. |
| **Inputs** | Approved `Signal` (open), `Tick` (update), `ExitDecision` (close) |
| **Outputs** | `PositionEvent` (opened, updated, closed) → ExecutionPipeline, EventPersistence |
| **Owned State** | Active `Position` per symbol. `ExitEngine` per position. `TrailEngine` per position. `PartitionExitManager` per position. `PyramidManager` per symbol. |
| **Mutation** | Position open → add to active map. Tick → update SL/TP, check exits. Close → remove from active, archive. |
| **Sync vs Async** | Synchronous |
| **Hot Path** | Compare tick price against SL/TP. Compare profit against trail activation threshold. |
| **Failure** | Duplicate open for same symbol → reject. Orphan position (no SL) → flat check on disconnect. |
| **Testing** | Open LONG → verify SL/TP set. Tick hits SL → verify exit reason STOP_LOSS. Profit > 1R → verify trail activated. P1 → verify 30% exit. |

**Existing module mapping**:
- `exit_engine.py` → ExitEngine sub-component
- `exit_rules.py` → ExitRules sub-component
- `TrailEngine` (inside exit_engine.py) → extracted as independent sub-component
- `PartitionExitManager` (inside exit_engine.py) → extracted as independent sub-component
- `PyramidManager` (missing) → create
- `PositionSizer` (missing) → create
- `StructuralStopEngine` (missing) → create
- `LossTracker` (missing) → create (or fold into RiskEvaluation)

### ExecutionPipeline

| Property | Specification |
|----------|--------------|
| **Responsibility** | Submit orders to broker adapter. Track order lifecycle (pending, filled, partial, cancelled, rejected). Report fills back to PositionLifecycle. |
| **Inputs** | `OrderRequest` from PositionLifecycle, `FillEvent` from broker |
| **Outputs** | `OrderStatusEvent` → PositionLifecycle, BrokerSynchronization |
| **Owned State** | Order state machine per order ID. |
| **Mutation** | Order submission → state = PENDING. Fill → update state and remaining qty. Reject → state = REJECTED. |
| **Sync vs Async** | Synchronous order submission. Async fill callback from broker adapter. |
| **Hot Path** | Submit order → no wait. Fill callback → match against open order map. |
| **Failure** | Order reject → notify PositionLifecycle. Broker disconnect → queue orders and recover on reconnect. |
| **Testing** | Submit buy → verify PENDING. Fill 50% → verify PARTIAL. Fill remaining → verify FILLED. |

### BrokerSynchronization

| Property | Specification |
|----------|--------------|
| **Responsibility** | Reconcile local position state with broker. On startup: fetch open positions from broker → verify match. On disconnect: reconnect → reconcile. Handle partial fills, slip-page, commissions. |
| **Inputs** | `FillEvent` from broker, `PositionEvent` from PositionLifecycle |
| **Outputs** | `ReconciliationEvent` (match, mismatch, resolved) |
| **Owned State** | Last known broker position state per symbol. |
| **Mutation** | Compare broker state vs local state. Log mismatch. Auto-resolve known cases (partial fill timing). |
| **Sync vs Async** | Async polling on timer (every 10 seconds). Sync compare on each fill. |
| **Hot Path** | Fill match → no-op. Disconnect → reconciliation only on reconnect. |
| **Failure** | Mismatch → alert, pause trading for symbol. Unresolvable → manual intervention required. |
| **Testing** | Simulate partial fill → verify local state updated. Simulate reconnect → verify reconciliation runs. Mismatch → verify alert. |

### SessionRuntime

| Property | Specification |
|----------|--------------|
| **Responsibility** | Manage session lifecycle per symbol. Create state on first tick. Handle multi-symbol scheduling. |
| **Inputs** | Runtime lifecycle events (start, stop, pause, resume) |
| **Outputs** | Runtime session events and persistence events |
| **Owned State** | Session context per symbol. Warm/cold state. Active symbols set. |
| **Mutation** | On first tick → create session. On stop → teardown and flush. |
| **Sync vs Async** | Thread-safe. Session map accessed by tick thread (read) and orchestration thread (create/evict). |
| **Hot Path** | Read session from map on each tick. Map lookup. |
| **Failure** | Session eviction during active trading → prevent (evict only idle). I/O persistence failure → isolate and continue. |
| **Testing** | Start session → verify state created. Idle timeout → verify eviction. Stop → verify teardown and flush. |

**Existing module mapping**:
- Session state (currently split across handlers) → consolidate into SessionRuntime
- Session state manager (missing) → create
- Trading session service (missing) → create as orchestrator

### EventPersistence

| Property | Specification |
|----------|--------------|
| **Responsibility** | Persist tick, candle, signal, trade, and position events to storage. Batched writes for ticks (every 50 ticks or 5 seconds). Immediate writes for trades and signals. |
| **Inputs** | Events from all upstream pipelines |
| **Outputs** | Storage write acknowledgments |
| **Owned State** | Write buffer for ticks. Pending write count. |
| **Mutation** | Buffer append. Flush on batch limit or timer. |
| **Sync vs Async** | Async writes. Submission queue to storage thread. |
| **Hot Path** | Tick write → buffer append. No I/O. |
| **Failure** | Storage down → buffer in memory (configurable max size), flush on restoration of storage. Buffer overflow → drop oldest ticks. |
| **Testing** | Feed 100 ticks → verify 2 batched writes (50 per batch). Feed trade → verify immediate write. Storage failure → verify buffered. |

**Existing module mapping**:
- `database.py` → SQLite storage adapter

### TelemetryPipeline

| Property | Specification |
|----------|--------------|
| **Responsibility** | Collect latency metrics, throughput counters, error rates, and system health. No impact on hot path. Non-blocking submission. |
| **Inputs** | Latency measurements (timestamps at pipeline stage boundaries). Pipeline event counters. |
| **Outputs** | Metrics to stdout (human-readable), metrics endpoint (JSON), log file. |
| **Owned State** | Counter map. Latency histogram per stage. |
| **Mutation** | Atomic counter increment. Lock-free histogram update. |
| **Sync vs Async** | Async submission. Hot path writes to lock-free metric buffer. Consumer thread reads and reports. |
| **Hot Path** | One atomic increment. One timestamp read (optional, can be disabled). |
| **Failure** | Metric buffer full → drop metrics. No system impact. |
| **Testing** | Feed 1000 ticks → verify counter at 1000. Measure stage delay → verify in histogram. |

### StrategyRuntime

| Property | Specification |
|----------|--------------|
| **Responsibility** | Host strategy logic that consumes computed features and produces signals. Supports multiple strategies running concurrently on different symbols. Each strategy has isolated state. |
| **Inputs** | `FeatureVector`, `MarketStructureResult`, `Portfolio` |
| **Outputs** | `StrategySignal` → SignalPipeline (merges with pipeline signals) |
| **Owned State** | Strategy-specific state (e.g., ML model weights, RL policy, custom indicator state). |
| **Mutation** | Strategy-defined. Must declare mutation boundaries in registration. |
| **Sync vs Async** | Synchronous for rule-based. Async-capable for ML inference (non-blocking submit, callback on result). |
| **Hot Path** | Rule-based strategies: no alloc, no branching beyond decision tree. ML strategies: inference cost depends on model complexity. |
| **Failure** | Strategy exception → strategy paused, other strategies continue. ML inference timeout → skip signal for this tick. |
| **Testing** | Register test strategy → verify signal received. Inject exception → verify only that strategy paused. |

---

## Pipeline Execution Model

### Tick Lifecycle (Live)

```
[MarketDataIngestion]
    async: receive raw tick → parse → push to ring buffer
    ↓
[TickSequencer]
    sync: read from ring buffer → assign seq → push to next
    ↓
[TickNormalizer]
    sync: read sequenced tick → normalize → push to next
    ↓
[CandlePipeline]  ─── sync: update active candle → emit completed → push candle
    ↓
[OrderFlowPipeline] ─ sync: update CVD, detect big trades, compute OFI
    ↓
[Microstructure] ─── sync: update book (if depth available)
    ↓
[FeatureCompute] ─── sync: compute VWAP, ATR (only on candle emit)
    ↓
[MarketStructure] ── sync: detect break, displacement, LVN (only on candle emit)
    ↓
[SignalGenerate] ─── sync: evaluate Triple-A
    ↓
[GateEval] ───────── sync: aggression score, confidence check
    ↓
[RiskEval] ───────── sync: drawdown, position limits
    ↓
[PositionLifecycle] ─ sync: check SL/TP, update trail, check partition exit
    ↓
[ExecutionPipeline] ─ sync: submit order if signal approved
    ↓
[EventPersistence] ─ async: batch write ticks, immediate write trades
```

### Candle Lifecycle

1. First tick of new period → set Candle.open = tick.price
2. Each tick → update Candle.high, Candle.low, Candle.close, Candle.volume
3. First tick of next period → emit completed Candle → trigger downstream subscribers
4. Downstream reactions on candle emit:
   - FeatureComputation: update VWAP, ATR, RSI
   - MarketStructureAnalysis: update volume profile, detect LVN, compute market state
   - SignalGeneration: re-evaluate (if gate pending or position open)
   - PositionLifecycle: structural stop adjustment (per-candle check)

### Order Flow Lifecycle

1. Each tick → update CVD accumulator (CVD += bid_vol - ask_vol)
2. Each tick → evaluate big trade detection (print_vol > 5x avg_within_window)
3. Each tick → compute OFI = (bid_vol - ask_vol) / (bid_vol + ask_vol)
4. Each tick → update rolling window for volume averages
5. Each 100 ticks → re-evaluate absorption patterns
6. Only on candle emit → aggregate order flow metrics for signal consumption

### Signal Lifecycle

1. Tick or candle event → collect current FeatureVector
2. Apply Triple-A logic: absorption detected? → check VWAP → check R:R → emit Signal
3. Signal → GatePipeline: evaluate each gate sequentially
4. Failed at any gate → NO_TRADE with rejection reason
5. Passed all gates → approved Signal → RiskPipeline
6. RiskPipeline evaluates pre-trade checks
7. Failed risk → NO_TRADE
8. Passed risk → ORDER_REQUEST

### Gate Lifecycle

1. AggressionScorer gate: compute 7-component score against threshold
   - Score ≥ 3.0 → HIGH confidence (pyramid eligible)
   - Score ≥ 2.0 → MEDIUM confidence (minimum for trade)
   - Score < 2.0 → LOW (reject)
2. Persistence gate: score must persist N consecutive evaluations
3. Session phase gate: reject if session phase is wrong for direction
4. Playbook gate: prevent rapid confidence flips
5. LLM overseer gate (optional, async): submit context, wait for validation

### Execution Lifecycle

1. Approved order → PositionSizer computes quantity
2. Order → ExecutionPipeline → broker adapter
3. Broker adapter → submit to exchange
4. Fill callback → update PositionLifecycle
5. Reject callback → log, notify
6. Partial fill → update PositionLifecycle with filled quantity
7. Each subsequent tick → ExitEngine evaluates (SL/TP/time/trail/partition)
8. Exit decision → ExecutionPipeline → broker adapter
9. Position closed → archive to trade journal

### Recovery Lifecycle

1. Runtime start → SessionRuntime checks for persisted state
2. If persisted state found → hydrate open positions from EventPersistence
3. Run BrokerSynchronization → reconcile open positions with broker
4. Irreconcilable positions → alert, pause, require manual resolution
5. Resume tick processing from current market time
6. Backfill missing candles from persistence for warm indicators

---

## Ownership Model

### Runtime Ownership

```
RuntimeOrchestrator
 |-- owns: SessionRuntime
 |-- owns: SymbolScheduler
 |-- owns: PipelineRegistry
 |-- owns: HealthMonitor
```

### Pipeline Ownership

Each pipeline stage owns its input queue and output event. No shared mutable state between stages. Stages communicate through lock-free single-producer single-consumer queues.

```
Stage N                     Stage N+1
[owned state]  →  [queue]  →  [owned state]
                    SPSC      (no shared state)
                 lock-free
```

### State Ownership

| State | Owner | Access Pattern |
|-------|-------|----------------|
| Tick sequence counter | TickSequencer | Write: self. Read: none external |
| Active candle | CandlePipeline | Write: self. Read: candle event consumers |
| CVD accumulator | OrderFlowPipeline | Write: self. Read: FeatureComputation (via event) |
| Volume profile | MarketStructureAnalysis | Write: self (candle-driven). Read: SignalPipeline (via event) |
| LVN/HVN registry | MarketStructureAnalysis | Write: self. Read: SignalPipeline (via event) |
| Active position | PositionLifecycle | Write: self. Read: RiskEvaluation, Telemetry |
| Daily risk state | RiskEvaluation | Write: self. Read: PositionLifecycle (via result) |
| Order state | ExecutionPipeline | Write: self. Read: BrokerSynchronization |
| Session state | SessionRuntime | Write: self. Read: all stages (via context token) |
| Feature windows | FeatureComputation | Write: self. Read: SignalGeneration (via event) |
| Gate persistence | GateEvaluation | Write: self. Read: self (persistence check) |

---

## Latency Optimization

### Hot Path Rules

1. No heap allocation after warmup. All tick processing uses pre-allocated structs.
2. No virtual dispatch in hot path. Stage interfaces are concrete types or trait objects resolved at composition time.
3. No I/O in hot path. Writes are buffered. Reads are from pre-loaded cache.
4. No synchronization beyond atomic operations in hot path. SPSC queues are lock-free.
5. Branch predictor friendly: per-symbol lookup tables instead of conditionals.
6. Cache line aligned: hot structs aligned to 64 bytes. False sharing prevention.

### Allocation Profile

| Operation | Allocations |
|-----------|-------------|
| Tick receive | 0 (reuse pre-allocated struct) |
| Sequence + normalize | 0 |
| Candle update | 0 (in-place) |
| CVD update | 0 |
| Signal evaluation | 0 |
| Gate evaluation | 0 |
| Risk evaluation | 0 |
| SL/TP check | 0 |
| Order submission | 1 (OrderRequest struct) |
| Event persistence | 0 (buffer append) |

### Throughput Targets

| Metric | Target |
|--------|--------|
| Ticks per second (single symbol) | 1,000,000+ |
| Signals evaluated per second | 100,000+ |
| Gate evaluations per second | 100,000+ |
| Risk evaluations per second | 100,000+ |
| End-to-end tick → persisted (p99) | < 10μs |
| Candle emit → signal (p99) | < 50μs |
| Signal → order submitted (p99) | < 100μs |
| Deterministic live tick fixture | 10,000,000+ |

---

## Testing Architecture

### Test Categories

| Category | Tests | Purpose |
|----------|-------|---------|
| Unit | Per module, per sub-component | Verify logic correctness |
| Pipeline | Stage → stage event flow | Verify event ordering, no data loss |
| Integration | Full pipeline live | Verify end-to-end tick → trade |
| Live data | Deterministic in-memory feed payloads | Verify deterministic behavior |
| Determinism | Same input twice | Verify identical output |
| Latency | Timestamp at each stage | Verify latency targets |
| Throughput | Max sustained tick rate | Verify throughput targets |
| Recovery | Simulate failures | Verify graceful degradation |

### Parity Verification

Every live session must produce identical output when run twice:
1. Same trade sequence
2. Same entry/exit prices
3. Same P&L
4. Same order of events
5. Same timestamps (relative to tick time, not wall clock)

Any live deterministic run that fails parity is a bug.

---

## Incremental Migration

### Step 1: Pipeline Skeleton (Current step)
- Create `pipeline/` directory structure
- Define `PipelineStage` trait/interface
- Define `SequencedTick`, `Candle`, `OrderFlowMetrics`, `Signal`, `GateResult`, `RiskResult`, `PositionEvent` event types
- Build `Sequencer` stage
- Wire existing `tick → candle` flow

### Step 2: Market Data Pipeline
- Migrate MarketDataIngestion → feed abstraction
- Migrate TickSequencer → sequencing
- Migrate TickNormalizer → normalization
- Wire: Feed → Sequencer → Normalizer → CandlePipeline

### Step 3: Order Flow Pipeline
- Migrate CVDTracker → OrderFlowPipeline
- Migrate OrderFlowDetectors → OrderFlowPipeline
- Wire: Normalizer → OrderFlowPipeline

### Step 4: Market Structure Pipeline
- Migrate all 11 AMT services → MarketStructureAnalysis
- Each service becomes a sub-component
- Wire: CandlePipeline → MarketStructureAnalysis

### Step 5: Signal + Gate Pipeline
- Migrate SignalGenerator → SignalGeneration
- Migrate AggressionScorer → GateEvaluation
- Create remaining gates
- Wire: MarketStructureAnalysis → SignalGeneration → GateEvaluation

### Step 6: Risk + Position Pipeline
- Migrate RiskManager → RiskEvaluation
- Create PositionSizer, PyramidManager, StructuralStopEngine, LossTracker
- Migrate ExitEngine → PositionLifecycle
- Wire: GateEvaluation → RiskEvaluation → PositionLifecycle

### Step 7: Execution + Broker Sync
- Create ExecutionPipeline
- Migrate DhanAdapter → broker adapter plugin
- Create PaperBroker
- Create BrokerSynchronization
- Wire: PositionLifecycle → ExecutionPipeline → BrokerSynchronization

### Step 8: Persistence + Telemetry
- Migrate SQLite storage → EventPersistence
- Create TelemetryPipeline
- Wire: all stages → EventPersistence (event bus pattern)

### Step 9: Session + Orchestrator
- Create SessionRuntime
- Create RuntimeOrchestrator
- Wire orchestration lifecycle

### Step 10: Production Hardening
- Remove startup-mode branching from orchestration
- Enforce live-only startup contracts
- Add observability for live-only runtime lifecycle

---

## Non-Negotiable Invariants

1. **No historic-mode reconstruction anywhere in execution path.** The pipeline runs the same code for all live sessions. The only difference is the feed source.
2. **Deterministic pipelines.** Same input → same output. Always. No wall-clock dependency. No random seeds. No hash map iteration order.
3. **Bounded mutation.** Each pipeline stage owns its state. No stage mutates another stage's state. Events carry copies.
4. **Hot path is allocation-free.** Zero heap allocations in tick processing. Pre-allocate everything at init.
5. **Synchronous hot path.** No async, no threads, no locks in tick processing. Async only at I/O boundaries (feed, broker, persistence).
6. **Explicit stage boundaries.** Pipeline stages communicate through typed events. No shared memory. No implicit coupling.
7. **Fail isolated.** One symbol's error does not crash another. One stage's exception does not crash the pipeline (stage pauses, events buffer).
8. **Teardown completeness.** Runtime shutdown flushes all buffers, persists all state, closes all connections. No data loss.
9. **No orphan positions.** Every open position has an SL. Every tick checks SL/TP. Disconnect → reconnect → verify.
10. **Live determinism.** The exact same code path executes per live run, regardless of invocation context.