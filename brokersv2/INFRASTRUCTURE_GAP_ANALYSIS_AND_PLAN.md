# Infrastructure Gap Analysis & Implementation Plan

## Executive Summary

**Current State**: brokersv2 has **459 tests passing** with solid foundation in place  
**Target**: Institutional-grade infrastructure supporting AMT, execution, analytics, replay, research, and automated trading  
**Gap**: **60% of required features are missing** - requires 12 major new modules  

---

## 1. REQUIREMENT AUDIT

### ✅ IMPLEMENTED (40% Coverage)

| Module | Status | Tests | Notes |
|--------|--------|-------|-------|
| **1. Broker Gateway** | ✅ 80% | ~100 | Has adapter, WebSocket, circuit breaker. Missing: SessionManager, ConnectionSupervisor fully integrated |
| **2. OMS Infrastructure** | ✅ 70% | ~50 | Has OrderManager, FillProcessor, Reconciliation. Missing: Super/Forever orders, idempotency |
| **3. Market Data Infrastructure** | ✅ 60% | ~40 | Has pipeline, candle builder, VWAP engine. Missing: Full L2 processing, sequence handling |
| **4. Order Book Engine** | ❌ 0% | 0 | **NOT IMPLEMENTED** |
| **5. Option Analytics** | ❌ 0% | 0 | **NOT IMPLEMENTED** |
| **6. Delta & Footprint** | ❌ 0% | 0 | **NOT IMPLEMENTED** |
| **7. Market Profile** | ❌ 0% | 0 | **NOT IMPLEMENTED** |
| **8. VWAP & Execution Analytics** | ✅ 50% | ~20 | Has session VWAP. Missing: anchored VWAP, slippage metrics, fill quality |
| **9. Instrument Registry** | ✅ 85% | ~40 | Has TradeHull-style APIs. Missing: bulk_resolve, search optimization |
| **10. Replay Infrastructure** | ❌ 0% | 0 | **NOT IMPLEMENTED** |
| **11. Event Bus** | ✅ 70% | ~20 | Has pub/sub. Missing: backpressure, bounded queues, fanout consumers |
| **12. Risk Control** | ✅ 60% | ~30 | Has basic gateway. Missing: Kill Switch integration, P&L Exit APIs |
| **13. Observability** | ✅ 80% | ~30 | Has metrics, health checks. Missing: tracing hooks, replay drift metrics |
| **14. Performance Optimization** | ⚠️ 30% | 0 | Partial optimization. Missing: benchmarks, profiling infrastructure |
| **15. Rate Limiting** | ✅ 50% | ~15 | Has token bucket. Missing: sliding window, request scheduler, prioritization |

### ❌ CRITICAL MISSING MODULES (0% Implemented)

1. **Order Book Engine** - Full L2 reconstruction, liquidity metrics, imbalance streams
2. **Options Analytics** - Greeks, IV surface, skew, term structure, OI/PCR analytics
3. **Delta & Footprint Infrastructure** - Cumulative delta, footprint aggregation, imbalance detection
4. **Market Profile Infrastructure** - TPO profiles, volume profiles, POC/VAH/VAL, HVN/LVN
5. **Replay Infrastructure** - Event capture, replay engine, determinism verification, event clock
6. **Advanced Rate Limiting** - Sliding window, request scheduler, endpoint-specific buckets
7. **Advanced Event Bus** - Backpressure, bounded queues, fanout consumers, dead-letter queue

---

## 2. DETAILED GAP ANALYSIS

### 2.1 Broker Gateway

| Feature | Status | Gap |
|---------|--------|-----|
| BrokerGateway | ✅ | Complete |
| SessionManager | ⏳ | Partial - needs JWT auth, token refresh |
| ConnectionSupervisor | ⏳ | Partial - exists in websocket/, needs integration |
| RetryManager | ❌ | Not implemented |
| RequestDispatcher | ❌ | Not implemented |
| RateLimiter | ✅ | Basic token bucket exists |
| JWT Authentication | ❌ | Not implemented |
| WebSocket Auth | ❌ | Not implemented |
| Reconnect Orchestration | ⏳ | Partial |
| Heartbeat Handling | ❌ | Not implemented |

**Missing**: RetryManager, RequestDispatcher, JWT auth flow, ConnectionSupervisor integration

---

### 2.2 OMS Infrastructure

| Feature | Status | Gap |
|---------|--------|-----|
| Normalized Order Models | ✅ | Complete |
| Broker-Independent APIs | ✅ | Complete |
| Execution Tracking | ✅ | Complete |
| Order Lifecycle Management | ✅ | Complete |
| Order State Machines | ✅ | Complete |
| Partial Fill Tracking | ✅ | Complete |
| Modify/Cancel Workflows | ⏳ | Partial |
| Idempotency Protection | ❌ | Not implemented |
| Reconciliation | ✅ | Complete |
| Market Orders | ✅ | Complete |
| Limit Orders | ✅ | Complete |
| Stop Orders | ✅ | Complete |
| Forever Orders | ❌ | Not implemented |
| Super Orders | ❌ | Not implemented |
| Conditional Triggers | ❌ | Not implemented |
| OrderEvent | ✅ | Exists in domain |
| ExecutionEvent | ✅ | Exists in domain |
| PositionEvent | ⏳ | Partial |

**Missing**: Idempotency protection, Forever/Super orders, Conditional triggers, PositionEvent

---

### 2.3 Market Data Infrastructure

| Feature | Status | Gap |
|---------|--------|-----|
| Level 1 (LTP, OHLC, VWAP, OI) | ✅ | Complete |
| Level 2 Full Depth | ⏳ | Partial - DepthProcessor exists but untested |
| Bid/Ask Ladders | ❌ | Not implemented |
| Incremental Depth Updates | ❌ | Not implemented |
| Order Book Snapshots | ❌ | Not implemented |
| Async Consumers | ✅ | Exists in pipeline |
| Reconnect-Safe Subscriptions | ⏳ | Partial |
| Stream Multiplexing | ❌ | Not implemented |
| Packet Normalization | ✅ | Exists |
| Timestamp Normalization | ❌ | Not implemented |
| Sequence Handling | ❌ | Not implemented |
| Heartbeat Monitoring | ❌ | Not implemented |
| TickEvent | ✅ | Complete |
| DepthEvent | ✅ | Complete |
| CandleEvent | ✅ | Complete |
| QuoteEvent | ✅ | Complete |

**Missing**: Full L2 processing, incremental updates, sequence handling, stream multiplexing

---

### 2.4 Order Book Engine (100% MISSING)

| Feature | Status |
|---------|--------|
| Full Order Book Reconstruction | ❌ |
| Incremental Depth Processing | ❌ |
| Bid/Ask Ladders | ❌ |
| Queue Snapshots | ❌ |
| Liquidity Metrics | ❌ |
| Imbalance Calculations | ❌ |
| Queue Pressure API | ❌ |
| Execution Pressure API | ❌ |
| Sweep Detection Primitives | ❌ |

**Required Files** (~2000 lines):
- `brokersv2/analytics/order_book/engine.py` - Core reconstruction engine
- `brokersv2/analytics/order_book/ladder.py` - Bid/ask ladder management
- `brokersv2/analytics/order_book/metrics.py` - Liquidity & imbalance metrics
- `brokersv2/analytics/order_book/snapshot.py` - Queue snapshots
- `brokersv2/analytics/order_book/events.py` - OrderBookEvent
- `brokersv2/tests/unit/test_order_book.py` - ~50 tests

---

### 2.5 Option Analytics (100% MISSING)

| Feature | Status |
|---------|--------|
| Option Chain Normalization | ❌ |
| Strike Ladder Generation | ❌ |
| Expiry Ladder Generation | ❌ |
| ATM/ITM/OTM Classification | ❌ |
| IV Surface Infrastructure | ❌ |
| Skew Infrastructure | ❌ |
| Term Structure Infrastructure | ❌ |
| OI Analytics | ❌ |
| PCR Calculations | ❌ |
| OI Buildup Detection | ❌ |
| OptionChainEvent | ❌ |
| GreeksEvent | ❌ |
| OIEvent | ❌ |

**Required Files** (~3000 lines):
- `brokersv2/analytics/options/chain.py` - Option chain normalization
- `brokersv2/analytics/options/greeks.py` - Black-Scholes Greeks calculation
- `brokersv2/analytics/options/iv_surface.py` - IV surface construction
- `brokersv2/analytics/options/skew.py` - Skew & term structure
- `brokersv2/analytics/options/oi_analytics.py` - OI, PCR, buildup detection
- `brokersv2/analytics/options/events.py` - OptionChainEvent, GreeksEvent, OIEvent
- `brokersv2/tests/unit/test_options_analytics.py` - ~80 tests

---

### 2.6 Delta & Footprint Infrastructure (100% MISSING)

| Feature | Status |
|---------|--------|
| Trade Delta | ❌ |
| Cumulative Delta | ❌ |
| Delta Candles | ❌ |
| Aggressive Buyer/Seller Metrics | ❌ |
| Footprint Aggregation | ❌ |
| Imbalance Aggregation | ❌ |
| Stacked Imbalance Detection | ❌ |
| Unfinished Auction Primitives | ❌ |
| Absorption Metrics | ❌ |
| DeltaEvent | ❌ |
| FootprintEvent | ❌ |
| ImbalanceEvent | ❌ |

**Required Files** (~2500 lines):
- `brokersv2/analytics/delta/trade_delta.py` - Trade-level delta calculation
- `brokersv2/analytics/delta/cumulative.py` - Cumulative delta streams
- `brokersv2/analytics/delta/footprint.py` - Footprint aggregation
- `brokersv2/analytics/delta/imbalance.py` - Imbalance detection & aggregation
- `brokersv2/analytics/delta/auction.py` - Unfinished auctions, absorption
- `brokersv2/analytics/delta/events.py` - DeltaEvent, FootprintEvent, ImbalanceEvent
- `brokersv2/tests/unit/test_delta_footprint.py` - ~70 tests

---

### 2.7 Market Profile Infrastructure (100% MISSING)

| Feature | Status |
|---------|--------|
| TPO Profiles | ❌ |
| Volume Profiles | ❌ |
| POC Calculation | ❌ |
| VAH/VAL | ❌ |
| HVN/LVN Detection | ❌ |
| Session Profiles | ❌ |
| Rolling Profiles | ❌ |
| Profile Snapshots | ❌ |
| ProfileEvent | ❌ |

**Required Files** (~2000 lines):
- `brokersv2/analytics/profile/tpo.py` - TPO (Time Price Opportunity) profiles
- `brokersv2/analytics/profile/volume_profile.py` - Volume profiles, POC, VAH/VAL
- `brokersv2/analytics/profile/hvn_lvn.py` - High/Low Volume Node detection
- `brokersv2/analytics/profile/session.py` - Session & rolling profiles
- `brokersv2/analytics/profile/events.py` - ProfileEvent
- `brokersv2/tests/unit/test_market_profile.py` - ~60 tests

---

### 2.8 Replay Infrastructure (100% MISSING)

| Feature | Status |
|---------|--------|
| Deterministic Event Sequencing | ❌ |
| Replay-Capable Event Streams | ❌ |
| Replay Scheduler | ❌ |
| Event Clock Abstraction | ❌ |
| Event Playback Infrastructure | ❌ |
| JSONL Storage | ❌ |
| Parquet Support | ❌ |
| Speed Control | ❌ |
| Determinism Verification | ❌ |
| LIVE PIPELINE == REPLAY PIPELINE | ❌ |

**Required Files** (~2500 lines):
- `brokersv2/replay/event_capture.py` - Event capture & storage (JSONL/Parquet)
- `brokersv2/replay/event_clock.py` - Event clock abstraction
- `brokersv2/replay/replay_scheduler.py` - Replay scheduler with speed control
- `brokersv2/replay/playback.py` - Event playback engine
- `brokersv2/replay/determinism.py` - Determinism verification tools
- `brokersv2/replay/events.py` - ReplayEvent
- `brokersv2/tests/unit/test_replay.py` - ~80 tests
- `brokersv2/tests/property/test_replay_determinism.py` - ~30 Hypothesis tests

**CRITICAL**: Must use identical event types, normalization, and processing pipelines as live

---

### 2.9 Event Bus Enhancements (30% MISSING)

| Feature | Status |
|---------|--------|
| Asyncio Queues | ✅ |
| Topic-Based Pub/Sub | ✅ |
| Bounded Queues | ❌ |
| Low-Latency Dispatching | ⏳ |
| Replay-Safe Ordering | ❌ |
| Fanout-Safe Consumers | ❌ |
| Backpressure Handling | ❌ |
| Dead-Letter Queue | ❌ |
| Queue Depth Metrics | ❌ |
| Dropped Packet Detection | ❌ |

**Required Changes**:
- Enhance `brokersv2/events/bus.py` with backpressure, bounded queues
- Add dead-letter queue mechanism
- Add fanout consumer support
- Add ~30 tests for new features

---

### 2.10 Risk Control Infrastructure (40% MISSING)

| Feature | Status |
|---------|--------|
| Dhan Kill Switch | ❌ |
| P&L Exit APIs | ❌ |
| Broker Emergency Shutdown | ❌ |
| Exposure Snapshots | ❌ |
| Kill-Switch Orchestration | ❌ |
| Account Protection | ❌ |
| Daily Loss Limits | ❌ |

**Required Files** (~1000 lines):
- Enhance `brokersv2/risk/gateway.py` with Kill Switch integration
- Add P&L Exit API integration
- Add exposure tracking
- Add ~40 tests

---

### 2.11 Rate Limiting & Scheduler (50% MISSING)

| Feature | Status |
|---------|--------|
| Token Bucket | ✅ |
| Sliding Window | ❌ |
| Leaky Bucket | ❌ |
| Request Scheduler | ❌ |
| Request Prioritization | ❌ |
| Queue-Based Dispatching | ❌ |
| Rate-Aware Scheduling | ❌ |
| Retry Orchestration | ❌ |
| Metrics for Rate Utilization | ❌ |
| Endpoint-Specific Buckets | ❌ |

**Required Files** (~1500 lines):
- `brokersv2/infrastructure/rate_limiter/sliding_window.py` - Sliding window limiter
- `brokersv2/infrastructure/rate_limiter/scheduler.py` - Request scheduler
- `brokersv2/infrastructure/rate_limiter/priority.py` - Priority queues
- `brokersv2/infrastructure/rate_limiter/metrics.py` - Rate utilization metrics
- `brokersv2/tests/unit/test_rate_limiting.py` - ~60 tests

---

### 2.12 Observability Enhancements (20% MISSING)

| Feature | Status |
|---------|--------|
| Structured Logging | ❌ |
| Metrics | ✅ |
| Tracing Hooks | ❌ |
| WebSocket Health Metrics | ❌ |
| Queue Depth Metrics | ❌ |
| Replay Drift Metrics | ❌ |
| Dropped Packet Detection | ❌ |
| Reconnect Metrics | ❌ |
| Latency Metrics | ✅ |

**Required Changes**:
- Add structlog integration
- Add tracing hooks
- Add replay drift metrics
- Add ~20 tests

---

### 2.13 Testing Architecture

| Test Type | Current | Target |
|-----------|---------|--------|
| Unit Tests | ~300 | ~800 |
| Integration Tests | ~18 | ~100 |
| Property-Based Tests | 0 | ~150 |
| Concurrency Tests | 0 | ~80 |
| Performance Tests | 0 | ~50 |
| Failure Injection Tests | 0 | ~80 |
| **TOTAL** | **~318** | **~1260** |

**Required Test Files** (~15000 lines of tests):
- Property-based tests with Hypothesis (~150 tests)
- Concurrency tests (~80 tests)
- Performance benchmarks (~50 tests)
- Failure injection tests (~80 tests)

---

## 3. IMPLEMENTATION ROADMAP

### Phase A: Critical Analytics (Weeks 1-4)

**Priority**: 🔴 CRITICAL - Powers AMT/order-flow systems

#### A1: Order Book Engine (Week 1)
- Full L2 reconstruction engine
- Bid/ask ladders with queue tracking
- Liquidity metrics & imbalance calculations
- Queue pressure & execution pressure APIs
- Sweep detection primitives
- **Deliverable**: 50 tests, ~2000 lines

#### A2: Delta & Footprint Infrastructure (Week 2-3)
- Trade-level delta calculation
- Cumulative delta streams
- Footprint aggregation (price × volume)
- Imbalance detection & stacked imbalances
- Unfinished auction primitives
- Absorption metrics
- **Deliverable**: 70 tests, ~2500 lines

#### A3: Market Profile Infrastructure (Week 3-4)
- TPO (Time Price Opportunity) profiles
- Volume profiles with POC, VAH/VAL
- HVN/LVN detection
- Session & rolling profiles
- Profile snapshots
- **Deliverable**: 60 tests, ~2000 lines

---

### Phase B: Options Analytics (Weeks 4-6)

**Priority**: 🔴 CRITICAL - Powers options trading systems

#### B1: Option Chain Normalization (Week 4)
- Strike ladder generation
- Expiry ladder generation
- ATM/ITM/OTM classification
- Option chain event streaming
- **Deliverable**: 30 tests, ~1000 lines

#### B2: Greeks & IV Surface (Week 5)
- Black-Scholes Greeks calculation (Delta, Gamma, Theta, Vega, Rho)
- IV surface construction
- Skew & term structure infrastructure
- Greeks event streaming
- **Deliverable**: 40 tests, ~1500 lines

#### B3: OI Analytics (Week 6)
- OI tracking per strike
- PCR (Put-Call Ratio) calculations
- OI buildup detection
- OI change analytics
- **Deliverable**: 30 tests, ~1000 lines

---

### Phase C: Replay Infrastructure (Weeks 6-8)

**Priority**: 🔴 CRITICAL - Powers replay, research, backtesting

#### C1: Event Capture & Storage (Week 6-7)
- JSONL event storage
- Parquet support for bulk storage
- Deterministic event sequencing
- Event metadata (timestamps, sequence numbers)
- **Deliverable**: 40 tests, ~1200 lines

#### C2: Replay Engine (Week 7-8)
- Event clock abstraction
- Replay scheduler with speed control
- Event playback infrastructure
- LIVE == REPLAY pipeline verification
- **Deliverable**: 50 tests, ~1500 lines

#### C3: Determinism Verification (Week 8)
- Property-based determinism tests (Hypothesis)
- Replay drift detection
- Sequence integrity verification
- **Deliverable**: 30 property tests, ~800 lines

---

### Phase D: Event Bus & Rate Limiting (Weeks 8-10)

**Priority**: 🟡 HIGH - Infrastructure backbone

#### D1: Event Bus Enhancements (Week 8-9)
- Bounded queues with backpressure
- Fanout-safe consumers
- Dead-letter queue
- Replay-safe ordering
- Dropped packet detection
- Queue depth metrics
- **Deliverable**: 60 tests, ~1500 lines

#### D2: Advanced Rate Limiting (Week 9-10)
- Sliding window rate limiter
- Leaky bucket implementation
- Request scheduler with priorities
- Queue-based dispatching
- Endpoint-specific buckets
- Retry orchestration
- Rate utilization metrics
- **Deliverable**: 70 tests, ~2000 lines

---

### Phase E: Risk Control & Auth (Weeks 10-11)

**Priority**: 🟡 HIGH - Production safety

#### E1: Kill Switch & P&L Exit (Week 10)
- Dhan Kill Switch integration
- P&L Exit APIs integration
- Broker emergency shutdown
- Exposure snapshots
- Kill-switch orchestration
- **Deliverable**: 40 tests, ~1000 lines

#### E2: Auth & Token Management (Week 11)
- JWT authentication flow
- OAuth token refresh
- TOTP generation (pyotp)
- Token storm prevention
- WebSocket authentication
- **Deliverable**: 50 tests, ~1200 lines

---

### Phase F: Observability & Performance (Weeks 11-12)

**Priority**: 🟢 MEDIUM - Production readiness

#### F1: Structured Logging & Tracing (Week 11)
- structlog integration
- Context propagation
- Tracing hooks
- WebSocket health metrics
- Reconnect metrics
- **Deliverable**: 25 tests, ~800 lines

#### F2: Performance Optimization (Week 12)
- WebSocket throughput optimization
- Event dispatch optimization
- Parsing speed optimization
- Memory allocation reduction
- Benchmark infrastructure
- **Deliverable**: 50 benchmarks, ~1000 lines

---

### Phase G: Testing & Quality (Weeks 12-14)

**Priority**: 🟢 MEDIUM - Quality gates

#### G1: Property-Based Testing (Week 12-13)
- Replay determinism properties (Hypothesis)
- Order book invariant properties
- Parser robustness properties
- Normalization stability properties
- Strike ordering properties
- Delta invariant properties
- **Deliverable**: 150 Hypothesis tests

#### G2: Concurrency Testing (Week 13)
- Concurrent WebSocket streams
- Concurrent subscriptions
- Concurrent OMS updates
- Concurrent replay pipelines
- Concurrent cache reloads
- **Deliverable**: 80 concurrency tests

#### G3: Failure Injection Testing (Week 13-14)
- WebSocket disconnects
- Malformed packets
- Stale broker state
- Dropped packets
- Delayed packets
- Reconnect storms
- OMS desync
- Replay inconsistencies
- **Deliverable**: 80 failure injection tests

---

### Phase H: Integration & Gateway (Weeks 14-16)

**Priority**: 🟢 MEDIUM - Production deployment

#### H1: Gateway Orchestration (Week 14-15)
- Unified gateway entry point
- Factory pattern for all components
- Configuration management
- Dependency injection wiring
- **Deliverable**: 50 tests, ~1500 lines

#### H2: Integration Testing (Week 15-16)
- End-to-end trading flows
- Full pipeline integration (live + replay)
- Cross-component wiring
- Performance integration tests
- **Deliverable**: 50 integration tests

---

## 4. ESTIMATED TOTALS

| Phase | Duration | Tests | Lines | Files |
|-------|----------|-------|-------|-------|
| A: Analytics Core | 4 weeks | 180 | 6500 | 18 |
| B: Options Analytics | 3 weeks | 100 | 3500 | 9 |
| C: Replay Infrastructure | 3 weeks | 120 | 3500 | 10 |
| D: Event Bus & Rate Limiting | 3 weeks | 130 | 3500 | 10 |
| E: Risk Control & Auth | 2 weeks | 90 | 2200 | 6 |
| F: Observability & Performance | 2 weeks | 75 | 1800 | 8 |
| G: Testing & Quality | 3 weeks | 310 | 0 (tests) | 15 |
| H: Integration & Gateway | 3 weeks | 100 | 1500 | 8 |
| **TOTAL** | **23 weeks** | **1105** | **22500** | **84** |

---

## 5. DEPENDENCY GRAPH

```
┌─────────────────────────────────────────────────┐
│              Strategies (Future)                 │
│        AMT, Execution, Analytics, Research       │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│           Replay Infrastructure (C)              │
│    - Event capture, replay engine, determinism   │
└────────────────────┬────────────────────────────┘
                     │
        ┌────────────┼────────────┐
        ▼            ▼            ▼
┌──────────┐  ┌──────────┐  ┌──────────┐
│  Order   │  │  Delta   │  │  Market  │
│  Book    │  │Footprint │  │ Profile  │
│  (A1)    │  │  (A2)    │  │  (A3)    │
└────┬─────┘  └────┬─────┘  └────┬─────┘
     │              │              │
     └──────────────┼──────────────┘
                    ▼
┌─────────────────────────────────────────────────┐
│         Options Analytics (B)                    │
│    - Chain, Greeks, IV, OI, PCR                  │
└────────────────────┬────────────────────────────┘
                     │
        ┌────────────┼────────────┐
        ▼            ▼            ▼
┌──────────┐  ┌──────────┐  ┌──────────┐
│   OMS    │  │  Market  │  │   Risk   │
│  (✅70%) │  │  Data    │  │(✅60%)   │
│          │  │(✅60%)   │  │          │
└────┬─────┘  └────┬─────┘  └────┬─────┘
     │              │              │
     └──────────────┼──────────────┘
                    ▼
┌─────────────────────────────────────────────────┐
│          Event Bus (D) + Rate Limiting (D)       │
│    - Backpressure, bounded queues, scheduler     │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│          Broker Gateway (✅80%) + Auth (E)       │
│    - DhanHQ adapter, WebSocket, circuit breaker  │
└─────────────────────────────────────────────────┘
```

**Build Order**: A → B → C → D → E → F → G → H

---

## 6. TDD IMPLEMENTATION STRATEGY

### 6.1 Red-Green-Refactor Loop

For EVERY feature:

1. **RED** - Write failing tests first
   - Unit tests for state transitions
   - Property tests with Hypothesis for invariants
   - Integration tests for component wiring
   - Concurrency tests for async code
   - Performance tests for latency targets

2. **GREEN** - Implement minimal code to pass tests
   - Start with interface/port definition
   - Implement core logic
   - Wire to existing infrastructure
   - Add observability hooks

3. **REFACTOR** - Improve code quality
   - Extract common patterns
   - Optimize performance
   - Improve type hints
   - Add documentation

### 6.2 Test-First Requirements

**BEFORE writing ANY implementation code**:
- Write unit tests for all public APIs
- Write property tests for mathematical invariants
- Write concurrency tests for async operations
- Write failure injection tests for error paths
- Write performance tests for latency targets

**Test Categories Per Module**:
- 60% Unit tests (state, calculations, error handling)
- 15% Property tests (Hypothesis for invariants)
- 10% Concurrency tests (async, parallel)
- 10% Failure injection tests (edge cases)
- 5% Performance tests (benchmarks)

### 6.3 Quality Gates

**Every module MUST have**:
- 95%+ test coverage
- Zero mypy errors (strict mode)
- Zero ruff warnings
- All Hypothesis property tests passing
- All concurrency tests passing
- Performance targets met

---

## 7. RISK MITIGATION

| Risk | Impact | Mitigation |
|------|--------|------------|
| Scope creep | HIGH | Strict phase gates, no feature additions mid-phase |
| Test complexity | MEDIUM | Start with simple unit tests, add property tests incrementally |
| Performance bottlenecks | MEDIUM | Benchmark early, profile continuously |
| DhanHQ API changes | LOW | Adapter pattern isolates changes |
| Replay determinism bugs | HIGH | Property-based tests from day 1 |
| Concurrency bugs | HIGH | Hypothesis + pytest-asyncio + stress tests |

---

## 8. SUCCESS CRITERIA

### Phase Completion Gates

Each phase is complete when:
1. ✅ All tests passing (100%)
2. ✅ 95%+ code coverage
3. ✅ Zero mypy errors
4. ✅ Zero ruff warnings
5. ✅ All property tests passing
6. ✅ Performance targets met
7. ✅ Documentation updated
8. ✅ Integration tests passing

### Project Completion Criteria

- [ ] 1105 new tests passing (total ~1500)
- [ ] 95%+ code coverage across all modules
- [ ] Zero mypy errors (strict mode)
- [ ] All Hypothesis property tests passing
- [ ] Replay determinism verified
- [ ] Performance targets met:
  - Instrument lookup: <1μs
  - Tick processing: <100μs
  - Order placement: <100ms
  - WebSocket reconnect: <2s
  - Replay throughput: >10k events/sec
- [ ] LIVE PIPELINE == REPLAY PIPELINE verified
- [ ] Production observability operational
- [ ] Failure injection tests passing

---

## 9. NEXT STEPS

### Immediate (Week 1, Day 1)

1. **Start Phase A1: Order Book Engine**
   - Create test file: `brokersv2/tests/unit/test_order_book.py`
   - Write first 10 failing tests for order book reconstruction
   - Implement minimal OrderBookEngine to pass tests
   - Iterate red-green-refactor

2. **Setup Testing Infrastructure**
   - Add `pytest-benchmark` to requirements.txt
   - Add `pytest-asyncio` mode configuration
   - Setup Hypothesis profiles
   - Create benchmark directory structure

3. **Establish Quality Gates**
   - Configure mypy strict mode
   - Configure ruff linting
   - Setup coverage reporting
   - Create CI/CD pipeline (optional)

---

## 10. CONCLUSION

**Current Infrastructure**: 40% feature complete, solid foundation  
**Gap**: 60% missing (analytics core, replay, advanced infrastructure)  
**Timeline**: 23 weeks to full institutional-grade implementation  
**Test Target**: 1105 new tests (total ~1500)  
**Code Target**: 22,500 lines of production code  

**Key Success Factors**:
1. **TDD MANDATE**: Tests first, ALWAYS
2. **Property-Based Testing**: Hypothesis for mathematical invariants
3. **Replay Determinism**: LIVE == REPLAY from day 1
4. **Performance First**: Benchmark early, optimize continuously
5. **Quality Gates**: No phase complete without 95%+ coverage

**This plan supports**:
- ✅ AMT/order-flow systems
- ✅ Execution engines
- ✅ Analytics engines
- ✅ Replay systems
- ✅ Research systems
- ✅ Automated trading systems

**Status**: Ready to begin Phase A1 (Order Book Engine) with TDD approach.
