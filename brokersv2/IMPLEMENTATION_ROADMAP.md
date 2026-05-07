# Implementation Roadmap - Quick Reference

## Current Status
**Tests**: 459 passing / 1500 target (31%)  
**Modules**: 6/15 complete (40%)  
**Next Phase**: A1 - Order Book Engine  

---

## Build Order (Critical Path)

```
WEEK 1-4:    A1 → A2 → A3 (Analytics Core)
             ↓
WEEK 4-6:    B1 → B2 → B3 (Options Analytics)
             ↓
WEEK 6-8:    C1 → C2 → C3 (Replay Infrastructure)
             ↓
WEEK 8-10:   D1 → D2 (Event Bus + Rate Limiting)
             ↓
WEEK 10-11:  E1 → E2 (Risk + Auth)
             ↓
WEEK 11-12:  F1 → F2 (Observability + Performance)
             ↓
WEEK 12-14:  G1 → G2 → G3 (Testing Suite)
             ↓
WEEK 14-16:  H1 → H2 (Integration + Gateway)
```

---

## Phase A: Analytics Core (4 weeks)

### Week 1: Order Book Engine
**Files**: 6 | **Tests**: 50 | **Lines**: 2000

```
Day 1-2: Core engine (reconstruction, ladders)
Day 2-3: Liquidity metrics
Day 3-4: Imbalance calculations
Day 4-5: Sweep detection
Day 5-7: Integration + benchmarks
```

**Key Deliverables**:
- Full L2 order book reconstruction
- Bid/ask ladders with queue tracking
- Liquidity & imbalance metrics
- Sweep detection primitives

---

### Week 2-3: Delta & Footprint
**Files**: 7 | **Tests**: 70 | **Lines**: 2500

```
Day 1-2: Trade delta calculation
Day 2-4: Cumulative delta streams
Day 4-6: Footprint aggregation
Day 6-8: Imbalance detection
Day 8-10: Auction analysis
```

**Key Deliverables**:
- Trade-level & cumulative delta
- Footprint candles (price × volume)
- Stacked imbalance detection
- Unfinished auction primitives

---

### Week 3-4: Market Profile
**Files**: 6 | **Tests**: 60 | **Lines**: 2000

```
Day 1-2: TPO profiles
Day 2-4: Volume profiles (POC, VAH/VAL)
Day 4-5: HVN/LVN detection
Day 5-6: Session profiles
Day 6-7: Integration
```

**Key Deliverables**:
- TPO (Time Price Opportunity) profiles
- Volume profiles with POC, VAH/VAL
- High/Low Volume Node detection
- Session & rolling profiles

---

## Phase B: Options Analytics (3 weeks)

### Week 4: Option Chain
**Files**: 3 | **Tests**: 30 | **Lines**: 1000

- Strike & expiry ladder generation
- ATM/ITM/OTM classification
- Option chain normalization

### Week 5: Greeks & IV
**Files**: 3 | **Tests**: 40 | **Lines**: 1500

- Black-Scholes Greeks calculation
- IV surface construction
- Skew & term structure

### Week 6: OI Analytics
**Files**: 3 | **Tests**: 30 | **Lines**: 1000

- OI tracking per strike
- PCR calculations
- OI buildup detection

---

## Phase C: Replay Infrastructure (3 weeks)

### Week 6-7: Event Capture
**Files**: 3 | **Tests**: 40 | **Lines**: 1200

- JSONL & Parquet storage
- Deterministic sequencing
- Event metadata

### Week 7-8: Replay Engine
**Files**: 4 | **Tests**: 50 | **Lines**: 1500

- Event clock abstraction
- Replay scheduler (speed control)
- LIVE == REPLAY verification

### Week 8: Determinism
**Files**: 3 | **Tests**: 30 | **Lines**: 800

- Hypothesis property tests
- Replay drift detection
- Sequence integrity

---

## Phase D: Event Bus & Rate Limiting (3 weeks)

### Week 8-9: Event Bus
**Files**: 5 | **Tests**: 60 | **Lines**: 1500

- Bounded queues + backpressure
- Fanout consumers
- Dead-letter queue

### Week 9-10: Rate Limiting
**Files**: 5 | **Tests**: 70 | **Lines**: 2000

- Sliding window + leaky bucket
- Request scheduler (priorities)
- Endpoint-specific buckets

---

## Phase E: Risk Control & Auth (2 weeks)

### Week 10: Kill Switch
**Files**: 3 | **Tests**: 40 | **Lines**: 1000

- Dhan Kill Switch integration
- P&L Exit APIs
- Emergency shutdown

### Week 11: Auth
**Files**: 3 | **Tests**: 50 | **Lines**: 1200

- JWT + OAuth flow
- TOTP generation (pyotp)
- Token refresh

---

## Phase F: Observability & Performance (2 weeks)

### Week 11: Logging & Tracing
**Files**: 4 | **Tests**: 25 | **Lines**: 800

- structlog integration
- Tracing hooks
- Health metrics

### Week 12: Performance
**Files**: 4 | **Tests**: 50 | **Lines**: 1000

- WebSocket optimization
- Parsing speed optimization
- Benchmark infrastructure

---

## Phase G: Testing Suite (3 weeks)

### Week 12-13: Property Tests
**Files**: 5 | **Tests**: 150 (Hypothesis)

- Replay determinism
- Order book invariants
- Parser robustness

### Week 13: Concurrency Tests
**Files**: 4 | **Tests**: 80

- Concurrent streams
- Concurrent subscriptions
- Concurrent replay

### Week 13-14: Failure Injection
**Files**: 6 | **Tests**: 80

- WebSocket disconnects
- Malformed packets
- Reconnect storms

---

## Phase H: Integration & Gateway (3 weeks)

### Week 14-15: Gateway
**Files**: 4 | **Tests**: 50 | **Lines**: 1500

- Unified entry point
- Factory pattern
- Config management

### Week 15-16: Integration
**Files**: 4 | **Tests**: 50

- End-to-end flows
- Live + replay pipeline
- Cross-component wiring

---

## Total Deliverables

| Category | Count |
|----------|-------|
| **New Files** | 84 |
| **New Tests** | 1,105 |
| **New Code** | 22,500 lines |
| **Total Tests** | 1,564 (459 existing + 1,105 new) |
| **Total Code** | 37,500 lines (15,000 existing + 22,500 new) |

---

## Quality Gates (Per Phase)

✅ 100% tests passing  
✅ 95%+ code coverage  
✅ Zero mypy errors (strict)  
✅ Zero ruff warnings  
✅ All Hypothesis tests passing  
✅ Performance targets met  
✅ Documentation updated  

---

## Start Here: Phase A1 (Week 1, Day 1)

### Step 1: Create Structure
```bash
mkdir -p brokersv2/analytics/order_book
touch brokersv2/analytics/order_book/__init__.py
touch brokersv2/analytics/order_book/engine.py
touch brokersv2/analytics/order_book/ladder.py
touch brokersv2/analytics/order_book/metrics.py
touch brokersv2/analytics/order_book/snapshot.py
touch brokersv2/analytics/order_book/events.py
touch brokersv2/tests/unit/test_order_book.py
```

### Step 2: Write First Failing Tests
```python
# brokersv2/tests/unit/test_order_book.py
def test_order_book_starts_empty():
    """Test new order book has no levels."""
    book = OrderBook("NSE:RELIANCE")
    assert book.bid_levels == 0
    assert book.ask_levels == 0
```

### Step 3: Implement Minimal Code
```python
# brokersv2/analytics/order_book/engine.py
class OrderBook:
    def __init__(self, symbol: str):
        self.symbol = symbol
        self.bids = {}
        self.asks = {}
    
    @property
    def bid_levels(self) -> int:
        return len(self.bids)
    
    @property
    def ask_levels(self) -> int:
        return len(self.asks)
```

### Step 4: Run Tests (GREEN)
```bash
pytest brokersv2/tests/unit/test_order_book.py -v
```

### Step 5: Refactor
- Improve type hints
- Add docstrings
- Extract common patterns

**Repeat RED-GREEN-REFACTOR for all 50 tests!**

---

## Daily Workflow

1. **Morning**: Review PROGRESS.md, update status
2. **RED**: Write 5-10 failing tests
3. **GREEN**: Implement minimal code to pass
4. **REFACTOR**: Improve code quality
5. **Evening**: Update PROGRESS.md checklist, commit

---

**Ready to start Phase A1?** 🚀
