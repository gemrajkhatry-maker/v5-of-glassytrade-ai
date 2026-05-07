# BrokersV2 Architecture & Execution Plan

## Executive Summary

**Current Status**: 102 tests passing, 8 failing (WebSocket tests need minor fixes)
**Code Base**: ~2,500 lines across 15 files
**Architecture**: Clean Architecture + DDD + Event-Driven + Hexagonal Ports/Adapters

---

## 1. CURRENT STATE ANALYSIS

### 1.1 What We Have ✅

#### **Phase 1: Core Domain Infrastructure** (100% Complete)
```
✅ InstrumentRegistry (299L, 14 tests)
   - O(1) lookups via hash maps
   - Security ID → Canonical mapping
   - Options chain queries
   - Expiry management
   
✅ InstrumentResolver (219L, 6 tests)
   - High-level symbol resolution
   - ATM/OTM/ITM strike calculations
   - Nearest expiry resolution
   
✅ Error Hierarchy (87L, 10 tests)
   - 8 custom exception types
   - Domain-specific errors
   
✅ CircuitBreaker (215L, 11 tests)
   - CLOSED → OPEN → HALF_OPEN state machine
   - Thread-safe with RLock
   - Configurable thresholds
```

#### **Phase 7: Broker Adapter Framework** (100% Complete)
```
✅ DhanBrokerAdapter (258L, 13 tests)
   - FULLY ASYNC (eliminated asyncio.run() anti-pattern)
   - Circuit breaker integration
   - DRY_RUN support
   - Rate limiter integration
   
✅ DhanWebSocketManager (239L)
   - Real-time tick streaming
   - Connection lifecycle management
   - Subscription tracking
```

#### **Phase 2: WebSocket Infrastructure** (80% Complete)
```
✅ ConnectionManager (491L)
   - Max 5 concurrent connections
   - Health-based allocation
   - Instrument sharding
   - Zombie detection
   
✅ ConnectionPool (210L)
   - Pool management
   - Health scoring
   - Auto-pruning
   
⚠️ Tests: 11/19 passing (8 need minor assertion fixes)
```

#### **Market Data Events** (Created, Not Tested)
```
✅ TickEvent, DepthEvent, QuoteEvent, CandleEvent
   - Immutable dataclasses (frozen=True)
   - msgspec codec for serialization
   - Calculated properties (spread, mid, imbalance)
```

### 1.2 What's Missing ❌

#### **Critical Gaps**
```
❌ Auth & Token Management
   - No TOTP generation
   - No token refresh logic
   - No OAuth flow

❌ OMS Infrastructure
   - No reconciliation engine
   - No fill processor
   - No audit trail
   - No idempotency protection

❌ Rate Limiter (Basic Only)
   - Token bucket exists
   - Missing: sliding window, leaky bucket
   - Missing: request scheduler
   - Missing: endpoint-specific buckets

❌ Market Data Pipeline
   - No depth processor
   - No VWAP engine
   - No candle builder
   - No replay infrastructure

❌ Risk Gateway (Basic Only)
   - Basic position checks exist
   - Missing: exposure tracking
   - Missing: P&L limits
   - Missing: kill switch integration

❌ Options Analytics
   - No option chain normalization
   - No Greeks calculation
   - No OI/PCR analytics

❌ Observability
   - No structured logging
   - No metrics collection
   - No health checks

❌ Integration Layer
   - No unified gateway
   - No factory pattern
   - No configuration management
```

### 1.3 Code Quality Issues ⚠️

```
⚠️ 8 failing WebSocket tests (assertion mismatches)
⚠️ msgspec dependency not in requirements.txt
⚠️ No __init__.py exports for new modules
⚠️ Some stub implementations (NotImplementedError)
⚠️ No type checking (mypy not configured)
⚠️ No linting (ruff not configured)
```

---

## 2. TARGET ARCHITECTURE

### 2.1 Architectural Principles

```
✅ Clean Architecture (Domain → Application → Infrastructure)
✅ Hexagonal Ports/Adapters (broker abstraction)
✅ Domain-Driven Design (aggregates, value objects)
✅ Event-Driven (async event bus, pub/sub)
✅ CQRS (commands vs queries separation)
✅ Dependency Injection (interfaces first)
✅ Immutability (frozen dataclasses for events)
✅ Type Safety (full typing, mypy strict)
```

### 2.2 Module Dependency Graph

```
┌─────────────────────────────────────────────────┐
│                  Strategies                      │
│         (Future: AMT, Execution, Analytics)      │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│              Event Bus (Core)                    │
│    - Pub/Sub with backpressure                  │
│    - Dead-letter queue                          │
│    - Replay support                             │
└────────────────────┬────────────────────────────┘
                     │
        ┌────────────┼────────────┐
        ▼            ▼            ▼
┌──────────┐  ┌──────────┐  ┌──────────┐
│   OMS    │  │  Market  │  │   Risk   │
│          │  │   Data   │  │          │
└────┬─────┘  └────┬─────┘  └────┬─────┘
     │              │              │
     └──────────────┼──────────────┘
                    │
                    ▼
┌─────────────────────────────────────────────────┐
│          Instrument Registry (Core)              │
│    - Canonical ↔ Broker translation             │
│    - O(1) lookups                               │
│    - Options chain                              │
└────────────────────┬────────────────────────────┘
                     │
                     ▼
┌─────────────────────────────────────────────────┐
│          Broker Gateway (Infrastructure)         │
│    - DhanHQ v2 adapter                          │
│    - WebSocket manager                          │
│    - Rate limiter                               │
│    - Circuit breaker                            │
└─────────────────────────────────────────────────┘
```

### 2.3 Data Flow

#### **Live Market Data Pipeline**
```
DhanHQ WebSocket
    ↓
ConnectionSupervisor (reconnect logic)
    ↓
PacketDecoder (binary → dict)
    ↓
SymbolMapper (security_id → canonical)
    ↓
NormalizationLayer (dict → TickEvent/DepthEvent)
    ↓
EventBus (publish)
    ↓
Subscribers (strategies, analytics, UI)
```

#### **Order Execution Pipeline**
```
Strategy (signal)
    ↓
RiskGateway (validate)
    ↓
OMS (create order)
    ↓
OrderGateway (rate limit, circuit breaker)
    ↓
BrokerAdapter (place order)
    ↓
DhanHQ API
    ↓
OrderUpdate (WebSocket postback)
    ↓
OMS (update state)
    ↓
EventBus (publish OrderEvent)
```

#### **Replay Pipeline** (IDENTICAL to live)
```
ReplayStorage (JSONL/Parquet)
    ↓
ReplayScheduler (event clock)
    ↓
EventBus (publish)
    ↓
Subscribers (SAME as live!)
```

---

## 3. IMPLEMENTATION PLAN

### Phase 3: Market Data Core (Week 1-2)
**Priority**: 🔴 CRITICAL

#### Tasks:
```
3.1  Event Bus Enhancement
     - Backpressure handling
     - Bounded queues
     - Metrics collection
     - Tests: 15

3.2  Market Data Pipeline
     - DepthProcessor (L2/L3)
     - VWAP engine
     - Candle builder (1m, 5m, 15m, 1h)
     - Tests: 30

3.3  WebSocket Fixes
     - Fix 8 failing tests
     - Add __init__.py exports
     - Tests: 19/19 passing
```

**Deliverables**:
- Real-time tick/depth streaming
- VWAP calculation
- OHLC candle aggregation
- Event bus with backpressure

---

### Phase 4: Instrument Registry Enhancement (Week 2)
**Priority**: 🔴 CRITICAL

#### Tasks:
```
4.1  TradeHull-Style APIs
     - get_instrument()
     - resolve_security_id()
     - find_option()
     - option_chain()
     - nearest_expiry()
     - Tests: 20

4.2  Master Data Loader
     - CSV import
     - API sync
     - Caching
     - Tests: 15
```

**Deliverables**:
- Developer-friendly instrument APIs
- Automatic master data sync
- Options discovery

---

### Phase 5: OMS Infrastructure (Week 3)
**Priority**: 🟡 HIGH

#### Tasks:
```
5.1  Order Gateway
     - Rate limit integration
     - Circuit breaker integration
     - DRY_RUN support
     - Tests: 15

5.2  Reconciliation Engine
     - Internal vs broker state
     - Auto-resolution
     - Conflict tracking
     - Tests: 15

5.3  Fill Processor
     - Partial fills
     - Average price calculation
     - Execution stats
     - Tests: 10

5.4  Audit Trail
     - Immutable records
     - Correlation ID tracking
     - Tests: 10
```

**Deliverables**:
- Full order lifecycle
- Reconciliation
- Fill tracking
- Audit trail

---

### Phase 6: Rate Limiter & Scheduler (Week 3-4)
**Priority**: 🟡 HIGH

#### Tasks:
```
6.1  Sliding Window Rate Limiter
     - Endpoint-specific buckets
     - Tests: 10

6.2  Request Scheduler
     - Priority queues
     - Retry-aware scheduling
     - Tests: 10

6.3  DhanHQ Rate Limits
     - Order APIs: 10/sec
     - Data APIs: 5/sec
     - Quote APIs: 1/sec
     - Tests: 15
```

**Deliverables**:
- Production-grade rate limiting
- Request prioritization
- Quota management

---

### Phase 7: Auth & Token Management (Week 4)
**Priority**: 🟡 HIGH

#### Tasks:
```
7.1  Token Manager
     - OAuth flow
     - Auto-refresh
     - Storm prevention
     - Tests: 15

7.2  TOTP Generator
     - PIN + TOTP flow
     - pyotp integration
     - Tests: 10
```

**Deliverables**:
- Automated token lifecycle
- TOTP authentication

---

### Phase 8: Risk Gateway (Week 4-5)
**Priority**: 🟡 HIGH

#### Tasks:
```
8.1  Exposure Tracker
     - Portfolio exposure
     - Instrument exposure
     - Tests: 10

8.2  P&L Limits
     - Daily loss limits
     - Kill switch integration
     - Tests: 10

8.3  Price Validation
     - Deviation checks
     - Freeze quantity
     - Tests: 10
```

**Deliverables**:
- Real-time risk monitoring
- Emergency shutdown

---

### Phase 9: Options Analytics (Week 5-6)
**Priority**: 🟢 MEDIUM

#### Tasks:
```
9.1  Option Chain Normalizer
     - Strike ladder
     - Expiry ladder
     - ATM/ITM/OTM
     - Tests: 15

9.2  OI Analytics
     - PCR calculation
     - OI buildup detection
     - Tests: 10

9.3  Greeks Infrastructure
     - Black-Scholes
     - IV surface
     - Tests: 15
```

**Deliverables**:
- Options chain APIs
- Greeks calculation
- OI analytics

---

### Phase 10: Replay Infrastructure (Week 6)
**Priority**: 🟢 MEDIUM

#### Tasks:
```
10.1 Event Capture
     - JSONL storage
     - Parquet support
     - Tests: 10

10.2 Replay Engine
     - Event clock
     - Speed control
     - Tests: 15

10.3 Determinism Verification
     - Property-based tests
     - Tests: 10
```

**Deliverables**:
- Replay-capable pipelines
- Backtesting support

---

### Phase 11: Observability (Week 6-7)
**Priority**: 🟢 MEDIUM

#### Tasks:
```
11.1 Structured Logging
     - structlog integration
     - Context propagation
     - Tests: 5

11.2 Metrics Collection
     - Request latency
     - Queue depth
     - Reconnect count
     - Tests: 10

11.3 Health Checks
     - Connection health
     - Token validity
     - DB writable
     - Tests: 10
```

**Deliverables**:
- Production observability
- Health monitoring

---

### Phase 12: Integration & Testing (Week 7-8)
**Priority**: 🟢 MEDIUM

#### Tasks:
```
12.1 Gateway Orchestration
     - Unified entry point
     - Factory pattern
     - Config management
     - Tests: 15

12.2 Integration Tests
     - End-to-end flows
     - Failure injection
     - Tests: 20

12.3 Performance Tests
     - Throughput benchmarks
     - Latency measurements
     - Tests: 10
```

**Deliverables**:
- Production-ready gateway
- Comprehensive test suite

---

## 4. TESTING STRATEGY

### 4.1 Test Pyramid

```
        ┌─────────┐
        │  E2E    │  ~20 tests (integration)
        ├─────────┤
        │ Integration│ ~50 tests
        ├─────────┤
        │  Unit   │ ~200 tests (target: 95% coverage)
        ├─────────┤
        │ Property│ ~30 tests (Hypothesis)
        └─────────┘
```

### 4.2 Test Categories

#### **Unit Tests** (Per Module)
- State transitions
- Calculations
- Error handling
- Edge cases

#### **Property-Based Tests** (Hypothesis)
- Replay determinism
- Order book invariants
- Parser robustness
- Normalization stability

#### **Concurrency Tests**
- WebSocket streams
- OMS updates
- Replay pipelines
- Cache reloads

#### **Failure Injection Tests**
- WebSocket disconnects
- Malformed packets
- Stale state
- Reconnect storms

#### **Performance Tests**
- Tick throughput: target 10k/sec
- Order latency: target <100ms
- Replay speed: target 100x real-time

---

## 5. QUALITY GATES

### 5.1 Code Quality
```
✅ 95%+ test coverage
✅ Zero mypy errors (strict mode)
✅ Zero ruff warnings
✅ No asyncio.run() anti-patterns
✅ No broker-specific identifiers leaking
✅ O(1) instrument lookups verified
```

### 5.2 Performance Targets
```
✅ Instrument lookup: <1μs
✅ Tick processing: <100μs
✅ Order placement: <100ms
✅ WebSocket reconnect: <2s
✅ Replay throughput: >10k events/sec
```

### 5.3 Reliability Targets
```
✅ WebSocket uptime: 99.9%
✅ Order delivery: 100% (with retries)
✅ No silent failures
✅ Graceful degradation
```

---

## 6. EXECUTION TRACKING

### 6.1 Current Status

| Phase | Status | Tests | Lines | Files |
|-------|--------|-------|-------|-------|
| 1: Core Domain | ✅ Complete | 40/40 | ~820 | 4 |
| 7: Broker Adapter | ✅ Complete | 13/13 | ~500 | 3 |
| 2: WebSocket | 🚧 80% | 11/19 | ~700 | 3 |
| 3: Market Data | ⏳ Pending | 0 | ~280 | 1 |
| 4: Instruments | ⏳ Pending | 0 | 0 | 0 |
| 5: OMS | ⏳ Pending | 0 | 0 | 0 |
| 6: Rate Limiter | ⏳ Pending | 0 | 0 | 0 |
| 8: Auth | ⏳ Pending | 0 | 0 | 0 |
| 9: Risk | ⏳ Pending | 0 | 0 | 0 |
| 10: Options | ⏳ Pending | 0 | 0 | 0 |
| 11: Replay | ⏳ Pending | 0 | 0 | 0 |
| 12: Observability | ⏳ Pending | 0 | 0 | 0 |

**Total**: 102 tests passing, ~2,300 lines, 11 files

### 6.2 Next Steps (Priority Order)

1. **Fix 8 WebSocket tests** (30 min)
2. **Install msgspec, test market events** (15 min)
3. **Enhance event bus** (2 hours)
4. **Build market data pipeline** (4 hours)
5. **Add __init__.py exports** (15 min)

---

## 7. ANTI-PATTERN PREVENTION

### 7.1 Duplication Prevention
```
✅ DRY: Extract common logic (rate limiter, circuit breaker)
✅ Single Source of Truth: CanonicalInstrument only
✅ No broker-specific code outside adapter layer
```

### 7.2 Code Smell Prevention
```
✅ Max class size: 300 lines (refactor if exceeded)
✅ Max function size: 50 lines
✅ No God classes (split by responsibility)
✅ No circular dependencies (enforce layering)
```

### 7.3 Shotgun Surgery Prevention
```
✅ Feature locality: Related code in same module
✅ Interface stability: Ports change rarely
✅ Dependency direction: Inner → Outer only
```

---

## 8. DECISIONS LOG

### 8.1 Architecture Decisions

| Decision | Rationale | Date |
|----------|-----------|------|
| msgspec over pydantic | 10x faster serialization | 2026-02-07 |
| asyncio over threading | Better scalability | 2026-02-07 |
| SQLite over PostgreSQL | Single-machine deployment | 2026-02-07 |
| Frozen dataclasses for events | Thread safety, immutability | 2026-02-07 |
| Token bucket rate limiter | Burst-friendly | 2026-02-07 |

### 8.2 Deferred Decisions

| Decision | Deferred Until | Reason |
|----------|---------------|--------|
| Multi-broker support | Phase 12 | DhanHQ first |
| PostgreSQL migration | Phase 12 | Scale when needed |
| Kubernetes deployment | Phase 12 | Single-machine OK |
| Redis event bus | Phase 12 | In-memory sufficient |

---

## 9. RISK MITIGATION

| Risk | Impact | Mitigation |
|------|--------|------------|
| DhanHQ API changes | HIGH | Adapter pattern isolates changes |
| WebSocket reliability | HIGH | Connection supervisor, auto-reconnect |
| Rate limit violations | MEDIUM | Token bucket + scheduler |
| Token expiry | MEDIUM | Auto-refresh before expiry |
| Silent failures | CRITICAL | No broad except Exception, structured logging |
| Performance bottlenecks | MEDIUM | Load testing, profiling |

---

## 10. SUCCESS CRITERIA

### MVP (Week 4)
```
✅ Live market data streaming
✅ Order placement & tracking
✅ Rate limiting operational
✅ Token management automated
✅ Risk checks enforced
✅ 150+ tests passing
```

### Production Ready (Week 8)
```
✅ All 12 phases complete
✅ 300+ tests passing
✅ 95%+ code coverage
✅ Performance targets met
✅ Observability operational
✅ Replay infrastructure working
```

---

## APPENDIX A: File Structure

```
brokersv2/
├── core/
│   ├── ports.py              # Interfaces (124L) ✅
│   ├── types.py              # Type definitions ✅
│   ├── events.py             # Base events ✅
│   ├── errors.py             # Error hierarchy (87L) ✅
│   └── resilience.py         # CircuitBreaker (215L) ✅
├── domain/
│   ├── instrument/
│   │   ├── models.py         # CanonicalInstrument ✅
│   │   ├── registry.py       # InstrumentRegistry (299L) ✅
│   │   ├── resolver.py       # InstrumentResolver (219L) ✅
│   │   └── parser.py         # Symbol parsing ✅
│   ├── order/
│   │   └── models.py         # Order + StateMachine (164L) ✅
│   ├── market/
│   │   ├── models.py         # Tick, Quote, Depth ✅
│   │   └── events.py         # Immutable events (279L) ⚠️
│   └── risk/
│       └── models.py         # Risk models ✅
├── infrastructure/
│   ├── dhan_adapter/
│   │   ├── adapter.py        # DhanBrokerAdapter (258L) ✅
│   │   ├── client.py         # HTTP client ✅
│   │   ├── mapper.py         # InstrumentMapper ✅
│   │   ├── factory.py        # Factory pattern ✅
│   │   └── websocket.py      # WebSocket manager (239L) ✅
│   ├── rate_limiter/
│   │   └── token_bucket.py   # TokenBucket ✅
│   ├── auth/                 # ❌ NOT IMPLEMENTED
│   └── paper_adapter/        # ❌ NOT IMPLEMENTED
├── marketdata/
│   ├── pipeline.py           # MarketDataPipeline ✅
│   └── gateway.py            # ❌ NOT IMPLEMENTED
├── oms/
│   ├── order_manager.py      # OrderManager ✅
│   └── gateway.py            # ❌ NOT IMPLEMENTED
├── risk/
│   └── gateway.py            # RiskGateway ✅
├── websocket/
│   ├── manager.py            # WebSocketManager ✅
│   ├── supervisor.py         # ConnectionSupervisor ✅
│   ├── subscription.py       # SubscriptionManager ✅
│   └── connection/
│       ├── manager.py        # ConnectionManager (491L) ⚠️
│       └── pool.py           # ConnectionPool (210L) ⚠️
├── events/
│   └── bus.py                # EventBus ✅
├── tests/
│   ├── unit/                 # Unit tests (102 passing)
│   └── integration/          # ❌ NOT IMPLEMENTED
└── docs/                     # DhanHQ v2 docs ✅
```

**Legend**: ✅ Complete, ⚠️ Needs work, ❌ Not implemented
