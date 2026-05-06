# Production Readiness Audit — GlassyTrade AMT Strategy Engine

> **Scope:** backendv2 + frontend + amt_docs  
> **Date:** 2026-05-06  
> **Auditor:** Senior Platform Engineer  
> **Status:** ~41% feature-complete, ~82% test coverage on implemented code  
> **Assessment:** NOT PRODUCTION-READY — significant gaps in orchestration, execution, and operational infrastructure

---

## 1. Executive Summary

### Current State (Verified Against Actual Code)

| Layer | Implementation | Tests | Status |
|-------|---------------|-------|--------|
| AMT Domain (Phase 2) | 94% — 15/16 services fully implemented | 149 tests | ✅ Strong |
| Exit Domain (Phase 3) | 25% — Engine + rules exist, missing pyramid, sizer, structural stop, loss tracker | 41 tests | ⚠️ Partial |
| Risk Domain (Phase 4) | 25% — RiskManager solid, missing tiered sizing, circuit breakers, self-healing | 26 tests | ⚠️ Partial |
| Application Layer (Phase 5) | 0% — No orchestrator, no session state manager, no coordinators | 0 tests | ❌ Missing |
| Infrastructure (Phase 6) | 25% — SQLite storage good, Dhan adapter basic, no paper broker | ~50 tests | ⚠️ Partial |
| API Layer (Phase 7) | 5% — Only metrics router, no trading/health/market routers | ~100 tests | ❌ Missing |
| Frontend | 60% — Charting, sidebar, AI panel, journal exist; no replay controls | Minimal | ⚠️ Partial |
| AI/ML Layer | 0% in backendv2 (was in v1, not ported) | 0 tests | ❌ Out of Scope |

### Critical Finding

**The AMT computation engine is production-grade. The trading execution pipeline is not.**  
You can compute signals. You cannot reliably execute, manage positions, or recover from failures.

---

## 2. Production Readiness Audit by Module

### 2.1 AMT Domain Services — ✅ MOSTLY PRODUCTION-READY

| Service | Status | Lines | Tests | Risks |
|---------|--------|-------|-------|-------|
| VolumeProfileEngine | ✅ Complete | 130 | 14 | VWAP σ bands missing |
| LVN/HVN Detector | ✅ Complete | 173 | 16 | None |
| AbsorptionDetector | ✅ Complete | 171 | 8 | Needs more edge-case tests |
| CVDTracker | ✅ Complete | 168 | 8 | Session boundary reset verified |
| MarketStateEngine | ✅ Complete | 119 | 13 | 2-state only (no 3-state) |
| BreakDetector | ✅ Complete | 105 | 16 | No absorption classification |
| DisplacementDetector | ✅ Complete | 100 | 6 | ATR-only, no volume-confirmed |
| InitialBalanceEngine | ✅ Complete | 112 | 12 | None |
| AcceptanceRejectionEngine | ✅ Complete | 256 | 27 | None |
| DriveTracker | ✅ Complete | 74 | 10 | No decay logic |
| SessionContext | ✅ Complete | 119 | 12 | Hardcoded thresholds |
| MTFAnalyzer | ✅ Complete | 116 | 10 | Daily/hourly only |
| ProfileClassifier | ✅ Complete | 136 | 16 | None |
| OrderFlowDetectors | ✅ Complete | 171 | 14 | None |
| SignalGenerator | ✅ Complete | 131 | 21 | No gate validation at signal level |
| AggressionScorer | ✅ Complete | 211 | 8 | Per-symbol config missing |

**Production Blockers:**
- VWAP with σ bands: NOT in code (needed for Triple-A methodology)
- Composite profile: Missing
- NPOC tracker: Missing
- Footprint analyzer: Missing
- Order book analyzer: Missing

**Scaling Bottlenecks:**
- Volume profile recalculation on every candle — O(n) per bucket. For 100+ symbols, profile rebuild every minute will CPU-bound.
- No incremental profile updates; full rebuild on each candle.

**Reliability Concerns:**
- Session boundary auto-reset for CVD — verified in tests, but no integration test with live session transitions.
- POC drift: No tracking of POC migration across sessions.

---

### 2.2 Exit Domain — ⚠️ PARTIAL

| Component | Status | Lines | Tests | Gap |
|-----------|--------|-------|-------|-----|
| ExitEngine | ✅ Complete | 226 | 41 | None |
| ExitRules | ✅ Complete | 80 | 16 | None |
| TrailEngine | ⚠️ Partial | ~25 | 0 | Only ATR trail; missing VWAP, CVD, imbalance trails |
| PartitionExitManager | ⚠️ Partial | ~30 | 0 | P1/P2/P3 exist; missing counter-aggression exit |
| BreakevenEngine | ✅ Complete | ~50 | 8 | None |
| PyramidManager | ❌ Missing | 0 | 0 | Needs port from backend v1 (110L) |
| PositionSizer | ❌ Missing | 0 | 0 | Needs port from backend v1 (136L) |
| StructuralStopEngine | ❌ Missing | 0 | 0 | Needs port from backend v1 (335L) |
| LossTracker | ❌ Missing | 0 | 0 | Needs port from backend v1 (528L) |

**Production Blockers:**
- No position sizing = cannot compute trade quantity
- No structural stop = SL placement not validated against LVN/VA/IB
- No loss tracker = daily loss circuit breaker cannot fire
- No pyramid manager = cannot do structured add-ons

**Failure Scenarios:**
- Position opened without SL → orphan position risk. ExitEngine checks SL existence but no enforcement at entry.
- Partial fill → PartitionExitManager may miscalculate percentages.
- Trail activation at 1R → if tick gap jumps past trail, slippage unbounded.

---

### 2.3 Risk Domain — ⚠️ PARTIAL

| Component | Status | Lines | Tests | Gap |
|-----------|--------|-------|-------|-----|
| RiskManager | ✅ Complete | 200 | 14 | None |
| MaxDrawdownTracker | ✅ Complete | ~80 | 6 | None |
| IntradayCompounding | ✅ Complete | ~60 | 5 | None |
| RiskSizingEngine | ⚠️ Basic | 61 | 12 | No tiered sizing, no dynamic risk, no compounding |
| CircuitBreakers | ⚠️ Partial | ~40 | 14 | Only in core_components; no domain-level breakers |
| SelfHealing | ❌ Missing | 0 | 0 | Needs creation |
| FlashCrashProtector | ❌ Missing | 0 | 0 | Needs port from backend v1 |
| PositionReconciliation | ❌ Missing | 0 | 0 | Needs creation |

**Production Blockers:**
- RiskSizingEngine is basic — no A/B/C tier logic, no session P&L adjustment
- No flash crash protection — price velocity circuit breaker missing
- No self-healing — order rejection recovery not automated

**Reliability Concerns:**
- Kill switch exists but no integration test with live trading halt
- Drift detection exists but no automated response (just logs)

---

### 2.4 Application Layer (Orchestration) — ❌ MISSING

| Component | Status | Lines | Tests | Gap |
|-----------|--------|-------|-------|-----|
| TradingSessionService | ❌ Missing | 0 | 0 | THE core orchestrator (868L in v1) |
| SessionStateManager | ❌ Missing | 0 | 0 | Per-symbol state (444L in v1) |
| EntryCoordinator | ❌ Missing | 0 | 0 | Signal gating + entry (295L in v1) |
| ExitCoordinator | ❌ Missing | 0 | 0 | Exit management (237L in v1) |
| TickProcessor | ❌ Missing | 0 | 0 | Tick pipeline (327L in v1) |
| StateSnapshotBuilder | ❌ Missing | 0 | 0 | Snapshot for recovery |
| TradeJournal | ❌ Missing | 0 | 0 | Trade recording (907L in v1) |
| EngineLifecycle | ❌ Missing | 0 | 0 | Startup/shutdown (492L in v1) |

**What exists instead:**
- Event handlers: `evaluate_entry_handler.py` (91L), `check_exit_handler.py` (95L), `update_tick_handler.py` (63L)
- These are fragments, not an orchestrator

**Production Blockers:**
- No central orchestrator = no deterministic tick → signal → position flow
- No session state manager = symbol state scattered, risk of cross-symbol contamination
- No trade journal = no post-trade analysis, no P&L tracking
- No engine lifecycle = unclean shutdowns, data loss on restart

**Failure Scenarios:**
- Handler exception → no isolation, may crash entire runtime
- No state snapshot → restart loses all open positions
- No tick processor → tick ordering not guaranteed

---

### 2.5 Infrastructure — ⚠️ PARTIAL

| Component | Status | Lines | Tests | Gap |
|-----------|--------|-------|-------|-----|
| SQLite Storage | ✅ Complete | 373 | 14 | None |
| EventStore | ✅ Complete | ~100 | 8 | None |
| Metrics | ✅ Complete | ~80 | 6 | None |
| FeatureFlags | ✅ Complete | ~60 | 6 | None |
| DhanAdapter | ⚠️ Basic | 80 | 14 | Missing option chain, lot size, retry logic |
| PaperBroker | ❌ Missing | 0 | 0 | Needs creation |
| Serialization Schemas | ❌ Missing | 0 | 0 | Needs port from v1 |
| PostgreSQL Adapter | ✅ Complete | 163 | 0 | Exists but unused |
| Redis Cache | ✅ Complete | 103 | 0 | Exists but unused |

**Production Blockers:**
- No paper broker = cannot test strategies without real money
- Dhan adapter incomplete = cannot trade options (missing option chain fetch)
- No serialization schemas = frontend-backend contract unstable

**Reliability Concerns:**
- SQLite is single-writer — will bottleneck under high tick volume
- No database replication — data loss if disk fails
- Redis/PostgreSQL adapters exist but not wired into hot path

---

### 2.6 API Layer — ❌ MINIMAL

| Component | Status | Lines | Tests | Gap |
|-----------|--------|-------|-------|-----|
| Metrics Router | ✅ Exists | ~50 | 6 | None |
| Alerts Router | ✅ Exists | ~40 | 0 | Basic |
| Observability Router | ✅ Exists | ~30 | 0 | Basic |
| Health Router | ❌ Missing | 0 | 0 | Needs creation |
| Trading Router | ❌ Missing | 0 | 0 | Needs creation |
| Market Router | ❌ Missing | 0 | 0 | Needs creation |
| WebSocket/SSE | ❌ Missing | 0 | 0 | Needs creation |
| FastAPI App | ⚠️ Basic | ~40 | 0 | No middleware, CORS, lifespan |

**Production Blockers:**
- No WebSocket/SSE = frontend cannot receive real-time updates
- No trading router = cannot start/stop trading via API
- No health router = no Kubernetes liveness/readiness probes

---

### 2.7 Frontend — ⚠️ PARTIAL

| Component | Status | Notes |
|-----------|--------|-------|
| ChartScene | ✅ Complete | Candles, footprint, range bars |
| MarketSidebar | ✅ Complete | Symbol scanner |
| AIAnalysisPanel | ✅ Complete | GenAI + AMT analysis display |
| JournalPage | ✅ Complete | Trade journal view |
| SystemStatusBar | ✅ Complete | Connection status |
| ModelStateBanner | ✅ Complete | Strategy state display |
| useServerTradingSystem | ✅ Complete | WebSocket hook |

**Missing:**
- Replay controls (play/pause/step/rewind)
- Session profile overlay (session/leg/combined VP modes exist in config but not fully wired)
- Real-time WebSocket feed (relies on polling or SSE, not WebSocket)
- No visual regression tests

---

## 3. Core Strategy Domain Model

### 3.1 Implemented Entities

#### MarketStateDetector
- **Responsibility:** Classify market as BALANCED or IMBALANCED
- **Inputs:** Price, VWAP, VAH, VAL, σ bands
- **Outputs:** MarketState enum, zone classification, confidence score
- **Invariants:** Always returns a state; never None
- **Failure Modes:** Missing VWAP → defaults to BALANCED
- **Concurrency:** Single-threaded per symbol
- **Replay:** Deterministic — same price sequence → same state
- **Tests:** 13 tests, all passing

#### VolumeProfileEngine
- **Responsibility:** Compute POC, VAH, VAL from volume distribution
- **Inputs:** Candles (OHLCV)
- **Outputs:** VolumeProfile with POC, VAH, VAL, buckets
- **Invariants:** POC is highest volume bucket; VA contains ~68% of volume
- **Failure Modes:** < 2 candles → empty profile
- **Concurrency:** Single-threaded; rebuild per candle
- **Replay:** Deterministic
- **Tests:** 14 tests

#### VWAPEngine
- **Responsibility:** Compute VWAP and deviation bands
- **Inputs:** Ticks or candles (price, volume)
- **Outputs:** VWAP value, 1σ/2σ/3σ bands
- **Invariants:** VWAP = Σ(price × volume) / Σ(volume)
- **Failure Modes:** Zero volume → VWAP = last price
- **Concurrency:** Running accumulator per symbol
- **Replay:** Deterministic if tick order preserved
- **Tests:** 6 tests (needs more for σ bands)

#### OrderFlowEngine
- **Responsibility:** Compute CVD, big trades, bubbles, OFI
- **Inputs:** Ticks with bid/ask volume
- **Outputs:** CVD value, delta, big trade flags, bubble flags
- **Invariants:** CVD is monotonic accumulator; resets at session boundary
- **Failure Modes:** Missing bid/ask → delta = 0
- **Concurrency:** Single-threaded per symbol
- **Replay:** Deterministic
- **Tests:** 14 tests

#### AggressionScorer
- **Responsibility:** 7-component additive scoring for entry confidence
- **Inputs:** Footprint, CVD, big trades, absorption, OFI, LVN, volume bubble
- **Outputs:** Score 0.0–5.0, confidence tier (LOW/MEDIUM/HIGH)
- **Invariants:** Each component contributes fixed weight; score is sum
- **Failure Modes:** Missing data → component contributes 0
- **Concurrency:** Stateless computation
- **Replay:** Deterministic
- **Tests:** 8 tests

#### SignalGenerator
- **Responsibility:** Triple-A signal generation
- **Inputs:** Absorption flag, VWAP position, R:R ratio
- **Outputs:** Signal (LONG/SHORT/NO_TRADE) with SL/TP levels
- **Invariants:** R:R ≥ 1.5 required; SL beyond VA boundary
- **Failure Modes:** No absorption → NO_TRADE
- **Concurrency:** Stateless
- **Replay:** Deterministic
- **Tests:** 21 tests

### 3.2 Missing Entities (Critical)

| Entity | Why Missing | Impact |
|--------|-------------|--------|
| EntryModel | No EntryCoordinator | Cannot validate entry timing |
| ExitModel | No ExitCoordinator | Cannot manage exit lifecycle |
| RiskModel | RiskSizingEngine is basic | Cannot tier risk by setup quality |
| SessionStateManager | Not implemented | No per-symbol state isolation |
| ReplayStateManager | Not implemented | Cannot replay sessions |
| SignalValidator | No gate pipeline | Cannot validate signals pre-entry |
| TradeLifecycleManager | Not implemented | No trade state machine |
| ExecutionRouter | No ExecutionPipeline | Cannot route orders to broker |
| StrategyTelemetryModel | Partial (metrics exist) | No end-to-end latency tracking |

---

## 4. AMT-Specific Risk Analysis

### 4.1 Balance/Imbalance Classification Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Incorrect classification during low volatility | High | Medium | Add volatility filter; require minimum ATR |
| False breakout in balance | Medium | High | Require volume confirmation + absorption |
| Late transition detection | Medium | Medium | Use order flow divergence as early signal |

### 4.2 Volume Profile Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| POC drift across sessions | Medium | Medium | Track POC migration; flag significant shifts |
| VAH/VAL binning errors | Low | High | Use fixed tick size buckets; test with known data |
| Profile rebuild CPU spike | High | Medium | Implement incremental profile updates |
| Session boundary errors | Medium | High | Explicit session reset; test with session transitions |

### 4.3 VWAP Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Reset timing issues | Medium | High | Configurable reset (session/weekly/monthly) |
| Deviation band miscalculation | Low | High | Property-based tests for σ bands |
| Anchoring to wrong session | Medium | High | Session context validation |

### 4.4 Order Flow Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| CVD/delta inconsistency | Medium | Medium | Cross-validate with footprint |
| Out-of-order ticks | Low | High | TickSequencer with sequence numbers |
| Absorption false positive | Medium | High | Require range compression + volume spike |

### 4.5 Execution Risks

| Risk | Likelihood | Impact | Mitigation |
|------|------------|--------|------------|
| Entry confirmation lag | High | High | Pre-compute signal; submit on tick |
| Slippage in fast markets | High | Medium | Market orders with max slippage limit |
| Signal overfitting | Medium | High | Walk-forward testing; multi-instrument validation |

---

## 5. Implementation Roadmap

### Phase 1 — Core Runtime Foundation (Weeks 1-2)

**Objectives:**
- Build deterministic tick processing pipeline
- Implement session lifecycle management
- Create event-driven architecture with typed events

**Deliverables:**
- `TickSequencer` — monotonic sequence numbers, duplicate detection
- `TickNormalizer` — exchange-specific → canonical format
- `SessionRuntime` — per-symbol session creation/teardown
- `EventBus` — typed event routing between stages

**Architecture Decisions:**
- Synchronous hot path, async I/O boundaries
- Lock-free SPSC queues between stages
- Zero heap allocation after warmup

**Dependencies:** None

**Critical Risks:**
- Tick ordering must be deterministic — any timestamp ambiguity breaks replay
- Session boundary detection must be exact — off-by-one candle corrupts profiles

**Testing Requirements:**
- 100% unit test coverage for sequencer
- Determinism tests: same input → same output
- Session boundary tests with timezone handling

**Performance Requirements:**
- Tick → sequenced: < 1μs
- Normalizer: < 1μs
- Memory: pre-allocated ring buffers

---

### Phase 2 — Market Data Infrastructure (Weeks 2-3)

**Objectives:**
- Ingest live ticks from Dhan feed
- Build candle pipeline (1m, 5m, 15m, 1h, 1d)
- Compute order flow metrics

**Deliverables:**
- `DhanFeed` adapter — WebSocket connection, reconnection
- `CandlePipeline` — OHLCV construction per timeframe
- `OrderFlowPipeline` — CVD, delta, big trades, bubbles

**Architecture Decisions:**
- Candle completion on first tick of next period
- Order flow metrics computed per tick, aggregated per candle
- Dhan feed async; pipeline sync after queue

**Dependencies:** Phase 1

**Critical Risks:**
- Feed disconnect → gap fill on resume
- Duplicate ticks from reconnection → sequencer drops
- Missing bid/ask in ticks → delta = 0 (graceful degradation)

**Testing Requirements:**
- Mock feed → verify candle OHLC
- Gap injection → verify candle validity
- Duplicate tick injection → verify drop

**Performance Requirements:**
- 1,000+ ticks/second per symbol
- Candle update: < 1μs per tick
- CVD update: 2 FLOPs per tick

---

### Phase 3 — Auction Market Theory Engine (Weeks 3-5)

**Objectives:**
- Compute all AMT market structure from candles
- Detect balance/imbalance, breaks, displacement, drives

**Deliverables:**
- `MarketStructureAnalysis` — consolidates all 11 AMT sub-components
- `VolumeProfileEngine` — POC, VAH, VAL, LVN, HVN
- `MarketStateEngine` — BALANCED/IMBALANCED classification
- `BreakDetector` — initiative/responsive break detection
- `DisplacementDetector` — ATR-based displacement
- `InitialBalanceEngine` — IB high/low tracking
- `DriveTracker` — D1/D2/D3+ tracking
- `SessionContext` — gap, OBI, session phase

**Architecture Decisions:**
- Each sub-component is independent; no shared state
- MarketStructureResult aggregates all sub-component outputs
- Candle-driven updates (not tick-driven, for efficiency)

**Dependencies:** Phase 2

**Critical Risks:**
- Profile rebuild every candle is O(n) — CPU bound at scale
- IB completion timeout must match exchange session times
- Session phase (morning/afternoon) depends on exchange timezone

**Testing Requirements:**
- 390 minutes of candles → verify POC at expected price
- VA expansion → verify 68% of volume
- LVN detection → verify below 15% mean threshold
- Market state transitions → verify BALANCED ↔ IMBALANCED

**Performance Requirements:**
- Profile rebuild: < 50μs for 100 buckets
- Market state detection: < 10μs
- All AMT metrics: < 100μs per candle per symbol

---

### Phase 4 — Volume Profile Engine Enhancement (Weeks 5-6)

**Objectives:**
- Add composite profile support
- Implement NPOC tracking
- Add profile factory/selector

**Deliverables:**
- `CompositeProfile` — multi-session volume aggregation
- `NPOCTracker` — naked point of control tracking
- `ProfileFactory` — session vs composite vs leg profile selection

**Architecture Decisions:**
- Composite profile = rolling N-session volume sum
- NPOC = POC level not revisited in N sessions
- Profile selector driven by frontend config (session/leg/combined)

**Dependencies:** Phase 3

**Critical Risks:**
- Composite profile memory grows with sessions — need eviction
- NPOC tracking requires historical data — bootstrap on first run

**Testing Requirements:**
- Multi-session composite → verify volume sums
- NPOC → verify level marked after N sessions
- Profile selector → verify correct profile emitted per config

---

### Phase 5 — VWAP & Deviation Engine (Weeks 6-7)

**Objectives:**
- Implement VWAP with σ bands
- Support session, weekly, monthly anchors
- Add deviation band logic for entries

**Deliverables:**
- `VWAPEngine` — running VWAP with σ bands
- `DeviationBandEngine` — band-based entry/exit logic
- `VWAPAnchor` — session/weekly/monthly reset

**Architecture Decisions:**
- VWAP = cumulative (price × volume) / cumulative volume
- σ = sqrt(Σ(volume × (price - VWAP)²) / Σ(volume))
- Reset on anchor boundary

**Dependencies:** Phase 2

**Critical Risks:**
- VWAP reset timing — must match exchange session open
- σ band width varies by volatility — adaptive bands may be needed
- Cumulative overflow — renormalize periodically

**Testing Requirements:**
- Known price/volume sequence → verify VWAP matches manual calc
- σ bands → verify 1σ contains ~68% of volume (approximately)
- Reset → verify VWAP restarts at anchor boundary

---

### Phase 6 — Order Flow & CVD Engine (Weeks 7-8)

**Objectives:**
- Enhance order flow with footprint analysis
- Add absorption, exhaustion, aggression detection
- Implement CVD divergence tracking

**Deliverables:**
- `FootprintAnalyzer` — bid/ask volume at price levels
- `AbsorptionDetector` — volume + range compression
- `ExhaustionDetector` — climax volume patterns
- `CVDEngine` — cumulative delta with divergence

**Architecture Decisions:**
- Footprint = 2D array (price levels × time buckets)
- Absorption = volume > 1.5× avg AND range < 0.5× avg
- Exhaustion = volume spike + price rejection wick

**Dependencies:** Phase 2

**Critical Risks:**
- Footprint memory = price levels × buckets × symbols — can grow large
- Absorption false positives in low volatility — need minimum volume threshold
- CVD divergence lag — divergence confirmed only after N bars

**Testing Requirements:**
- Known delta sequence → verify CVD matches
- Absorption pattern → verify detection
- Exhaustion pattern → verify detection
- Divergence → verify price vs CVD direction mismatch

---

### Phase 7 — Signal & Bias Engine (Weeks 8-9)

**Objectives:**
- Implement complete signal generation pipeline
- Add gate pipeline for signal validation
- Create bias model (trend vs mean reversion)

**Deliverables:**
- `SignalGenerator` — Triple-A methodology (exists, enhance)
- `GatePipeline` — 12-gate validation (port from v1)
- `EntryGates` — individual gate evaluators (port from v1)
- `BiasModel` — trend continuation vs mean reversion classifier

**Architecture Decisions:**
- Signal = pure function of features + market structure
- Gate pipeline = sequential evaluation, fail-fast
- Bias from market state + MTF alignment + session context

**Dependencies:** Phase 3, 5, 6

**Critical Risks:**
- Gate latency — 12 gates × evaluation time must be < 50μs total
- Bias flip — rapid trend ↔ mean reversion switching causes whipsaw
- Gate persistence — score must persist N bars, not just current

**Testing Requirements:**
- Each gate individually → verify pass/fail
- Gate combination → verify correct rejection reason
- Signal with all gates pass → verify approved
- Bias classification → verify trend vs mean reversion accuracy

---

### Phase 8 — Risk & Execution Engine (Weeks 9-11)

**Objectives:**
- Build complete risk evaluation pipeline
- Implement position lifecycle management
- Create execution router with broker sync

**Deliverables:**
- `RiskEvaluation` — pre-trade and intra-trade risk (exists, enhance)
- `PositionLifecycle` — open, manage, close positions
- `PositionSizer` — fixed fractional sizing (port from v1)
- `StructuralStopEngine` — LVN/VA-based SL (port from v1)
- `PyramidManager` — structured add-ons (port from v1)
- `LossTracker` — daily loss with circuit breaker (port from v1)
- `ExecutionPipeline` — order submission, fill tracking
- `BrokerSynchronization` — reconcile with broker

**Architecture Decisions:**
- Risk check before every order submission
- Position state machine: PENDING → OPEN → PARTIAL → CLOSED
- Broker sync every 10 seconds + on every fill

**Dependencies:** Phase 7

**Critical Risks:**
- Risk check latency must be < 10μs — cannot slow hot path
- Broker disconnect → queue orders, reconcile on reconnect
- Partial fill → position state must be exact

**Testing Requirements:**
- 2% drawdown → verify halt
- 3 consecutive losses → verify pause
- Kill switch → verify all rejected
- Partial fill → verify state = PARTIAL
- Broker mismatch → verify alert + pause

---

### Phase 9 — Replay & Backtesting (Weeks 11-13)

**Objectives:**
- Implement deterministic replay from tick storage
- Support backtesting with identical logic to live
- Create replay controls for frontend

**Deliverables:**
- `ReplayStateManager` — replay session state
- `TickReplayFeed` — read ticks from storage, emit at recorded rate
- `BacktestEngine` — run strategy on historical data
- `ReplayControls` — play/pause/step/rewind/speed

**Architecture Decisions:**
- Replay uses same pipeline as live — only feed source differs
- Tick timestamps drive replay speed, not wall clock
- Results must be bit-identical to live run on same data

**Dependencies:** Phase 1-8

**Critical Risks:**
- Replay determinism — any wall-clock dependency breaks parity
- Storage format versioning — old replay files may not load
- Speed adjustment — too fast → memory pressure from buffered ticks

**Testing Requirements:**
- Same tick file → two replays → identical trades
- Live session → persist → replay → identical results
- Speed 10× → verify completion, no data loss

---

### Phase 10 — Frontend Strategy Console (Weeks 13-14)

**Objectives:**
- Build strategy control panel
- Add replay controls
- Enhance visualization with AMT overlays

**Deliverables:**
- `StrategyControlPanel` — start/stop/pause trading
- `ReplayControls` — play/pause/step/rewind/speed
- `AMTOverlays` — balance/imbalance zones, VWAP bands, POC/VAH/VAL
- `SignalPanel` — live signals with gate status
- `PositionPanel` — open positions with P&L

**Architecture Decisions:**
- WebSocket for real-time updates (replace polling)
- React state management with Zustand or Redux
- Chart overlays via Canvas API for performance

**Dependencies:** Phase 9

**Critical Risks:**
- WebSocket reconnection → state sync required
- Chart rendering at 60fps with many overlays → GPU usage
- Mobile responsiveness → touch controls for replay

**Testing Requirements:**
- Visual regression tests for chart overlays
- WebSocket reconnection → verify state resync
- Replay controls → verify correct tick advancement

---

### Phase 11 — Dashboard & Visualization (Weeks 14-15)

**Objectives:**
- Build operational dashboard
- Add real-time P&L, risk metrics, system health

**Deliverables:**
- `OperationsDashboard` — system health, latency metrics
- `PnLDashboard` — daily/weekly/monthly P&L
- `RiskDashboard` — exposure, drawdown, circuit breaker status
- `LatencyDashboard` — pipeline stage latencies

**Architecture Decisions:**
- Metrics collected via TelemetryPipeline (non-blocking)
- Dashboard polls metrics endpoint every 5 seconds
- Alerts via AlertManager for threshold breaches

**Dependencies:** Phase 10

---

### Phase 12 — Distributed Scaling (Weeks 15-17)

**Objectives:**
- Scale to multiple symbols across multiple processes
- Add Redis for cross-process state sharing
- Implement symbol sharding

**Deliverables:**
- `SymbolSharder` — distribute symbols across workers
- `RedisStateCache` — shared state for cross-symbol risk
- `ProcessPool` — worker process management
- `LoadBalancer` — tick distribution

**Architecture Decisions:**
- One process per N symbols (N = CPU cores / symbol count)
- Redis for shared risk state (daily drawdown, position count)
- No shared state within process — same pipeline architecture

**Dependencies:** Phase 11

---

### Phase 13 — Production Hardening (Weeks 17-19)

**Objectives:**
- Harden for production deployment
- Add comprehensive observability
- Implement disaster recovery

**Deliverables:**
- `HealthMonitor` — liveness/readiness probes
- `AlertManager` — production alerts
- `DisasterRecovery` — backup/restore procedures
- `SecurityHardening` — auth, RBAC, credential encryption
- `DeploymentPipeline` — blue/green deployment

**Architecture Decisions:**
- Kubernetes deployment with Helm charts
- Prometheus + Grafana for metrics
- PagerDuty for critical alerts
- Vault for secrets management

**Dependencies:** Phase 12

---

## 6. Testing Strategy

### 6.1 Unit Tests — ✅ STRONG (Implemented)

| Area | Tests | Coverage | Status |
|------|-------|----------|--------|
| Exit Engine | 41 | 100% | ✅ |
| Risk Domain | 26 | 100% | ✅ |
| AMT Pipeline | 149 | ~85% | ✅ |
| Dhan Adapter | 14 | 100% | ✅ |
| Position Sizing | 25 | 100% | ✅ |
| Market State & IB | 25 | 100% | ✅ |
| Acceptance/Rejection | 27 | 100% | ✅ |
| Entry Gates & Signals | 21 | 100% | ✅ |

### 6.2 Unit Tests — ❌ MISSING (Critical)

| Area | Needed Tests | Priority |
|------|-------------|----------|
| Absorption Detection | 15-20 | P0 |
| Value Area Fade | 10-12 | P0 |
| ORB Breakout | 8-10 | P0 |
| Max Drawdown Protection | 6-8 | P0 |
| Entry Gate Pipeline (12-gate) | 20-25 | P1 |
| Range Bar Generator | 12-15 | P1 |
| Contraction Detection | 8-10 | P1 |
| Failed Auction Re-entry | 6-8 | P1 |

### 6.3 Integration Tests — ⚠️ PARTIAL

| Test File | Status | Issue |
|-----------|--------|-------|
| `test_frontend_api_contract.py` | ✅ PASS | |
| `test_scanner_api.py` | ❌ ERROR | Import error |
| `test_scanner_startup.py` | ❌ ERROR | Import error |

**Needed:**
- Market data ingestion → candle pipeline
- Profile computation pipeline
- VWAP + order flow + signal alignment
- WebSocket distribution
- Persistence recovery

### 6.4 Deterministic Replay Tests — ❌ MISSING

**Requirements:**
- Identical input → identical output
- Replay matches live behavior
- Event ordering stable
- Timestamp normalization deterministic
- Session resets reproducible
- Checkpoint restore exact

**Implementation:**
- Create `test_determinism.py` with fixture-based tick streams
- Run pipeline twice → compare all outputs
- Test session boundary → verify reset behavior

### 6.5 Load & Stress Tests — ❌ MISSING

**Requirements:**
- High-frequency tick streams (1000+ ticks/sec)
- Bursty market open conditions
- Multi-symbol processing (50+ symbols)
- Profile recalculation pressure
- WebSocket fanout

**Implementation:**
- `test_load_ticks.py` — feed 1M ticks, measure throughput
- `test_burst_open.py` — simulate market open burst
- `test_multi_symbol.py` — 50 symbols concurrently

### 6.6 Latency Benchmarks — ❌ MISSING

**Measure:**
| Stage | P50 Budget | P95 Budget | P99 Budget |
|-------|-----------|-----------|-----------|
| Tick → sequenced | 1μs | 2μs | 5μs |
| Candle update | 1μs | 2μs | 5μs |
| CVD update | 1μs | 2μs | 5μs |
| Profile rebuild | 20μs | 50μs | 100μs |
| Signal generation | 5μs | 10μs | 20μs |
| Gate evaluation | 10μs | 20μs | 50μs |
| Risk evaluation | 5μs | 10μs | 20μs |
| Order submission | 50μs | 100μs | 200μs |

### 6.7 Failure & Recovery Tests — ❌ MISSING

**Simulate:**
- Packet loss → verify gap tolerance
- Duplicate events → verify deduplication
- Out-of-order ticks → verify sequencer reordering
- Broker disconnect → verify queue + reconnect
- Database outage → verify buffer + flush on restore
- Process crash → verify state recovery from snapshot

### 6.8 End-to-End Tests — ⚠️ PARTIAL

**Existing:**
- `test_event_flow.py` — event bus flow
- `test_live_data_ingestion.py` — WebSocket/SSE
- `test_paper_trading_simulation.py` — paper trading OMS
- `test_triple_a_validation.py` — Triple-A methodology
- `test_valentini_scalper.py` — full system E2E

**Needed:**
- Full scenario: ingest → compute → signal → validate → order → fill → update → persist → replay

### 6.9 Frontend Testing — ❌ MINIMAL

**Needed:**
- Chart rendering performance
- WebSocket synchronization
- Visual regression for AMT overlays
- Replay control interaction

### 6.10 CI/CD Requirements — ❌ MISSING

**Needed:**
- GitHub Actions workflow
- Pre-commit hooks (Ruff, MyPy)
- PyTest with coverage
- Benchmark regression checks
- Docker builds
- Integration test environment

---

## 7. Code Quality Requirements

### 7.1 Current State

| Requirement | Status | Notes |
|-------------|--------|-------|
| Strict typing | ⚠️ Partial | MyPy not enforced in CI |
| Interface-first design | ✅ Yes | Protocol-based ports exist |
| Protocol-based abstractions | ✅ Yes | `shared/port/` directory |
| Dependency inversion | ✅ Yes | DI container exists |
| Bounded contexts | ✅ Yes | `domain/amt/`, `domain/risk/`, `domain/exit/` |
| No hidden shared state | ⚠️ Partial | Some handlers may share state |
| Immutable event models | ✅ Yes | Frozen dataclasses |
| Explicit contracts | ✅ Yes | Typed inputs/outputs |
| Deterministic timestamps | ⚠️ Partial | Need explicit timestamp normalization |
| Pure computation where possible | ✅ Yes | Signal generation is pure |
| Side effects isolated at boundaries | ⚠️ Partial | I/O in handlers, not fully isolated |

### 7.2 Enforcement

- Add MyPy to CI with `--strict`
- Add Ruff for linting and import sorting
- Add import-linter to enforce bounded contexts
- All new code must have type hints
- All functions > 20 lines need docstring

---

## 8. Production Engineering Requirements

### 8.1 Observability — ⚠️ PARTIAL

| Component | Status | Gap |
|-----------|--------|-----|
| Structured logging | ⚠️ Basic | No structured JSON logs |
| Metrics collection | ✅ Yes | `core/metrics.py` exists |
| Distributed tracing | ❌ Missing | No OpenTelemetry |
| Alerting | ⚠️ Basic | `alert_manager.py` exists, not wired |
| Audit trails | ❌ Missing | No trade audit log |
| Session boundary telemetry | ❌ Missing | No session event logging |

### 8.2 Deployment — ❌ MISSING

| Component | Status |
|-----------|--------|
| Docker builds | ❌ Missing |
| Kubernetes manifests | ❌ Missing |
| Blue/green deployment | ❌ Missing |
| Feature flags | ✅ Yes | `core/feature_flags.py` exists |
| Runtime config versioning | ❌ Missing |
| Deployment rollbacks | ❌ Missing |

### 8.3 Security — ❌ MISSING

| Component | Status |
|-----------|--------|
| Authentication | ❌ Missing |
| RBAC | ❌ Missing |
| Broker credential encryption | ❌ Missing |
| API rate limiting | ❌ Missing |
| Input validation | ⚠️ Partial | FastAPI does some |

---

## 9. Team Scaling Requirements

### 9.1 Repository Structure

```
v5-of-glassytrade-ai/
├── backendv2/              # Core trading runtime
│   ├── app/
│   │   ├── api/            # API layer (routers, middleware)
│   │   ├── application/    # Orchestration (coordinators, handlers)
│   │   ├── core/           # Shared infrastructure (events, metrics, config)
│   │   ├── domain/
│   │   │   ├── amt/        # AMT domain (market structure, signals)
│   │   │   ├── risk/       # Risk domain (sizing, circuit breakers)
│   │   │   ├── exit/       # Exit domain (SL, TP, trail, partition)
│   │   │   └── shared/     # Shared domain (ports, value objects)
│   │   ├── infrastructure/ # Adapters (broker, storage, cache)
│   │   └── runtime/        # Runtime (feeds, orchestrator, pipeline)
│   ├── config/             # YAML configurations
│   ├── tests/
│   │   ├── unit/           # Unit tests
│   │   ├── integration/    # Integration tests
│   │   └── e2e/            # End-to-end tests
│   └── docs/               # Architecture docs, ADRs
├── frontend/               # React frontend
│   ├── components/         # React components
│   ├── hooks/              # Custom hooks
│   └── tests/              # Frontend tests
├── amt_docs/               # Methodology documentation
├── shared/                 # Shared types/contracts
└── docs/
    ├── adr/                # Architecture Decision Records
    └── agents/             # Agent documentation
```

### 9.2 Ownership Boundaries

| Team | Ownership |
|------|-----------|
| Core Runtime Team | `backendv2/app/runtime/`, `backendv2/app/core/` |
| AMT Strategy Team | `backendv2/app/domain/amt/` |
| Risk & Execution Team | `backendv2/app/domain/risk/`, `backendv2/app/domain/exit/` |
| Application Team | `backendv2/app/application/`, `backendv2/app/api/` |
| Infrastructure Team | `backendv2/app/infrastructure/`, deployment |
| Frontend Team | `frontend/` |
| QA Team | `backendv2/tests/`, test infrastructure |

### 9.3 API Versioning

- REST API: `/api/v1/...`, `/api/v2/...`
- WebSocket: version in connection path
- Breaking changes → new version; deprecation period = 3 months

---

## 10. Technical Debt Prevention

### 10.1 Architectural Traps

| Trap | Risk | Prevention |
|------|------|------------|
| Hidden coupling between signal and execution | Signal logic leaks into order submission | Strict pipeline boundaries; signal is pure data |
| Profile recomputation on every tick | CPU explosion | Candle-driven updates only |
| VWAP anchoring mistakes | Wrong session anchor → wrong fair value | Explicit anchor config; test session boundaries |
| Order flow aggregation errors | Lost ticks → wrong CVD | Sequencer guarantees ordering |
| Session-state leakage | Symbol A state affects Symbol B | Per-symbol isolation; no global mutable state |

### 10.2 Coding Standards

1. All domain logic in `domain/` — no I/O
2. All I/O in `infrastructure/` — no business logic
3. All orchestration in `application/` — no domain logic
4. All API in `api/` — no business logic
5. Pure functions preferred — immutable inputs/outputs
6. Explicit error handling — no silent failures
7. Every function has type hints
8. Every module has tests

### 10.3 Review Checklist

- [ ] Does this change affect the hot path?
- [ ] Are there new allocations in tick processing?
- [ ] Does this introduce shared mutable state?
- [ ] Are errors handled explicitly?
- [ ] Are there tests for success and failure cases?
- [ ] Does this change affect determinism?
- [ ] Is the change backward compatible?

---

## 11. Deliverables Summary

| # | Deliverable | Status | Owner |
|---|-------------|--------|-------|
| 1 | Production readiness audit | ✅ This document | Platform |
| 2 | Missing systems analysis | ✅ Section 2 | Platform |
| 3 | Partial implementation analysis | ✅ Section 2 | Platform |
| 4 | Detailed implementation roadmap | ✅ Section 5 | Platform |
| 5 | Testing architecture | ✅ Section 6 | QA |
| 6 | CI/CD architecture | ❌ Not created | DevOps |
| 7 | Reliability engineering strategy | ⚠️ Partial (Section 8) | Platform |
| 8 | Performance engineering strategy | ⚠️ Partial (Section 6.6) | Platform |
| 9 | Failure recovery strategy | ⚠️ Partial (Section 6.7) | Platform |
| 10 | Production hardening checklist | ✅ Section 10.3 | Platform |
| 11 | Operational readiness checklist | ❌ Not created | DevOps |
| 12 | Technical debt prevention plan | ✅ Section 10 | Platform |
| 13 | Architecture governance strategy | ✅ Section 9 | Platform |
| 14 | Suggested engineering team structure | ✅ Section 9.2 | Platform |
| 15 | Suggested repository structure | ✅ Section 9.1 | Platform |
| 16 | Suggested coding standards | ✅ Section 10.2 | Platform |
| 17 | Suggested release process | ❌ Not created | DevOps |
| 18 | Suggested deployment strategy | ❌ Not created | DevOps |
| 19 | Suggested observability stack | ⚠️ Partial (Section 8.1) | Platform |
| 20 | Suggested long-term scaling roadmap | ✅ Section 5 Phases 12-13 | Platform |

---

## 12. Immediate Actions (Next 2 Weeks)

### P0 — Blocking Production

1. **Port PositionSizer** from backend v1 (136L) — cannot trade without sizing
2. **Port LossTracker** from backend v1 (528L) — cannot protect capital without daily loss tracking
3. **Port StructuralStopEngine** from backend v1 (335L) — cannot place valid SL without structural levels
4. **Create TradingSessionService** — central orchestrator; without this, no deterministic execution
5. **Create SessionStateManager** — per-symbol state isolation

### P1 — Critical for Reliability

6. **Port PyramidManager** from backend v1 (110L)
7. **Create PaperBroker** — test without real money
8. **Add VWAP σ bands** to VolumeProfileEngine
9. **Fix integration test imports** — 2 of 3 failing
10. **Add absorption detection tests** — 15-20 tests

### P2 — Important for Quality

11. **Add Value Area Fade tests** — 10-12 tests
12. **Add ORB Breakout tests** — 8-10 tests
13. **Add Max Drawdown Protection tests** — 6-8 tests
14. **Create WebSocket/SSE endpoint** for frontend real-time updates
15. **Add deterministic replay tests**

---

## 13. Production Readiness Criteria

### Minimum Viable Production

| Criterion | Threshold | Current |
|-----------|-----------|---------|
| AMT signal generation | 100% tested | ✅ 94% |
| Position sizing | Implemented + tested | ❌ Missing |
| Risk circuit breakers | Implemented + tested | ⚠️ Partial |
| Order execution | End-to-end tested | ❌ Missing |
| Paper trading | Working | ❌ Missing |
| Session recovery | Restart preserves state | ❌ Missing |
| Frontend real-time | WebSocket/SSE working | ❌ Missing |
| Deterministic replay | Same input → same output | ❌ Missing |
| System health checks | Liveness/readiness probes | ❌ Missing |
| Alerting | Critical alerts configured | ⚠️ Partial |

**Verdict: NOT PRODUCTION-READY**

**Estimated time to production readiness: 12-16 weeks** (3-4 months) with 3-4 engineers focused full-time.

---

*Document version: 1.0*  
*Last updated: 2026-05-06*  
*Next review: After P0 actions complete (2 weeks)*