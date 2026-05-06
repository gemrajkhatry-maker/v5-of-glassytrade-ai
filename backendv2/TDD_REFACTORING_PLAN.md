# TDD Refactoring Plan — BackendV2

> **Approach**: Vertical slices via tracer bullets. One test → one implementation → repeat.
> **Goal**: Fix architectural violations + complete pending items with full test suite
> **Timeline**: 6-8 weeks (4 phases)
> **Methodology**: Red-Green-Refactor cycle, behavior-driven tests, public interface focus

---

## Planning Summary

### Architectural Issues to Fix (from ARCHITECTURE_REVIEW.md)

**Critical (V1-V2)**:
1. Split `core_components.py` (5 responsibilities, global mutable state)
2. Unify dual event systems (domain events + pipeline events)

**High Priority (V3-V5)**:
3. Wire up DI container (currently unused)
4. Fix stage coupling in `SessionRuntime`
5. Move `ISignalService` to domain ports

**Medium Priority (V6-V8)**:
6. Split `IStorage` interface (15 methods violates ISP)
7. Establish error handling convention
8. Clarify orchestration model (pipeline vs handlers)

### Pending Implementation Items

**From VERIFIED_IMPLEMENTATION_STATUS.md**:
1. Dhan adapter parity (option chain, lot size, error recovery)
2. Risk sizing engine (dynamic P&L, compounding)
3. Trail engine enhancements (VWAP trail, CVD breakeven)
4. Trade journal (not yet implemented)
5. Missing tests for critical components

### Test Coverage Gaps

**Current**: ~60% (64 test files)
**Target**: 85%+

**Missing Tests For**:
- Exit engine (255L) ❌
- Exit rules (80L) ❌
- Risk manager (200L) ❌
- Circuit breakers (103L) ❌
- Self-healing (208L) ❌
- Position sizer (101L) ❌
- Pyramid manager (48L) ❌
- Structural stop engine (207L) ❌
- Loss tracker (247L) ❌

---

## Phase 1: Critical Architecture Fixes (Week 1-2)

**Focus**: Eliminate global mutable state, establish proper DI

### Task 1.1: Split `core_components.py` via TDD

**Behavior**: Each component should be independently instantiable, testable, and injectable.

#### Cycle 1.1.1: Metrics Registry
```
RED:   Test that MetricsRegistry can be instantiated and records metrics
GREEN: Extract MetricsRegistry to app/core/metrics.py
       Delete global _metrics instance
```

**Test File**: `tests/unit/core/test_metrics.py`

**Behaviors to Test**:
- [ ] Can record counters, gauges, histograms
- [ ] Snapshot returns all metrics
- [ ] Thread-safe operations (concurrent writes)
- [ ] Reset clears all metrics

**Implementation**:
```python
# app/core/metrics.py (extract from core_components.py)
class MetricsRegistry:
    def counter(self, name: str, value: float = 1.0) -> None: ...
    def gauge(self, name: str, value: float) -> None: ...
    def histogram(self, name: str, value: float) -> None: ...
    def snapshot(self) -> dict: ...
```

**Update**:
- `api/routers/metrics.py` — inject via constructor
- `api/routers/observability.py` — inject via constructor

---

#### Cycle 1.1.2: Circuit Breaker
```
RED:   Test that CircuitBreaker opens after failures, closes after successes
GREEN: Extract CircuitBreaker to app/core/circuit_breaker.py
       Delete global _circuit_breaker instance
```

**Test File**: `tests/unit/core/test_circuit_breaker.py`

**Behaviors to Test**:
- [ ] Starts CLOSED
- [ ] Opens after N consecutive failures
- [ ] Transitions to HALF_OPEN after timeout
- [ ] Closes after N successes in HALF_OPEN
- [ ] Decorator wraps async functions
- [ ] Raises RuntimeError when OPEN

**Implementation**:
```python
# app/core/circuit_breaker.py
class CircuitBreaker:
    def __init__(self, config: CircuitBreakerConfig): ...
    def record_success(self) -> None: ...
    def record_failure(self) -> None: ...
    @property
    def state(self) -> CircuitState: ...
    def __call__(self, func): ...
```

**Update**:
- `api/routers/metrics.py` — inject via constructor
- `api/routers/observability.py` — inject via constructor

---

#### Cycle 1.1.3: Event Store
```
RED:   Test that EventStore appends and queries events immutably
GREEN: Extract EventStore to app/core/event_store.py
       Delete global _event_store instance
```

**Test File**: `tests/unit/core/test_event_store.py`

**Behaviors to Test**:
- [ ] Can append events
- [ ] Can query by event type
- [ ] Returns copy (immutable)
- [ ] Empty when initialized

**Implementation**:
```python
# app/core/event_store.py
@dataclass(frozen=True)
class Event:
    event_type: str
    timestamp: float
    data: dict

class EventStore:
    def append(self, event: Event) -> None: ...
    def get_events(self, event_type: str | None = None) -> list[Event]: ...
    def snapshot(self) -> list[Event]: ...
```

**Update**:
- `infrastructure/alerts/alert_manager.py` — inject via constructor

---

#### Cycle 1.1.4: Feature Flags
```
RED:   Test that FeatureFlags can enable/disable/query features
GREEN: Extract FeatureFlags to app/core/feature_flags.py
       Delete global _config instance
```

**Test File**: `tests/unit/core/test_feature_flags.py`

**Behaviors to Test**:
- [ ] Can enable features
- [ ] Can disable features
- [ ] Query returns False for unknown features
- [ ] Thread-safe operations

**Implementation**:
```python
# app/core/feature_flags.py
class Feature(str, Enum):
    TRADING_ENABLED = "trading_enabled"
    PAPER_TRADING = "paper_trading"
    RISK_MANAGEMENT = "risk_management"
    AI_ANALYSIS = "ai_analysis"

class FeatureFlags:
    def is_enabled(self, feature: Feature) -> bool: ...
    def enable(self, feature: Feature) -> None: ...
    def disable(self, feature: Feature) -> None: ...
```

**Update**:
- `api/routers/alerts.py` — inject via constructor

---

#### Cycle 1.1.5: Delete `core_components.py`
```
RED:   Test that app starts without core_components.py imports
GREEN: Delete core_components.py
       Verify all imports updated
       Run full test suite
```

**Verification**:
```bash
grep -r "from app.core.core_components" app/
# Should return 0 matches
```

---

### Task 1.2: Wire Up DI Container

**Behavior**: Dependencies should be injected via constructor, not manually instantiated.

#### Cycle 1.2.1: Container Registration
```
RED:   Test that container can register and resolve dependencies
GREEN: Update api/main.py lifespan to wire container
```

**Test File**: `tests/unit/application/test_di_container_integration.py`

**Behaviors to Test**:
- [ ] Container resolves singletons
- [ ] Container resolves factories
- [ ] Container resolves lazy dependencies
- [ ] Missing registration raises KeyError

**Implementation**:
```python
# api/main.py (lifespan function)
@asynccontextmanager
async def lifespan(application: FastAPI):
    container = Container()
    
    # Register infrastructure
    container.register(IStorage, SQLiteStorageAdapter(settings.db_path))
    container.register(IBroker, PaperBrokerAdapter(...))
    container.register(IMarketData, DhanAdapter(...))
    
    # Register core components
    container.register(MetricsRegistry, MetricsRegistry())
    container.register(CircuitBreaker, CircuitBreaker(...))
    
    # Register application services
    container.register_factory(RuntimeOrchestrator, lambda c: 
        RuntimeOrchestrator(storage=c.resolve(IStorage))
    )
    
    # Store container
    application.state.container = container
```

**Update**:
- All routers — resolve dependencies from container
- All handlers — resolve dependencies from container

---

### Task 1.3: Fix Stage Coupling

**Behavior**: Pipeline stages should not access other stages' private state.

#### Cycle 1.3.1: Decouple MarketStructureAnalysis
```
RED:   Test that MarketStructureAnalysis receives storage via constructor
GREEN: Update SessionRuntime to inject storage directly
       Remove self._persistence._storage access
```

**Test File**: `tests/unit/runtime/pipeline/test_market_structure_decoupled.py`

**Behaviors to Test**:
- [ ] MarketStructureAnalysis initializes with storage
- [ ] Does not depend on other stages
- [ ] Can be tested in isolation

**Implementation**:
```python
# runtime/orchestrator/session.py (line 51)
# BEFORE:
self._market_structure = MarketStructureAnalysis(
    storage=self._persistence._storage  # ❌
)

# AFTER:
self._market_structure = MarketStructureAnalysis(
    storage=storage  # ✅ Injected from constructor
)
```

---

## Phase 2: Complete Untested Components (Week 3-4)

**Focus**: Full test coverage for exit, risk, and trade management domains

### Task 2.1: Exit Engine Tests

**Test File**: `tests/unit/domain/exit/test_exit_engine.py`

#### Cycle 2.1.1: SL/TP Execution
```
RED:   Test that ExitEngine closes position when SL hit
GREEN: Verify ExitEngine.evaluate() returns ExitDecision
```

**Behaviors to Test**:
- [ ] LONG position: SL hit when tick_low <= stop_loss
- [ ] LONG position: TP hit when tick_high >= take_profit
- [ ] SHORT position: SL hit when tick_high >= stop_loss
- [ ] SHORT position: TP hit when tick_low <= take_profit
- [ ] Uses wick extremes (not close price)
- [ ] Returns None for closed positions
- [ ] Returns ExitReason.STOP_LOSS or ExitReason.TAKE_PROFIT

---

#### Cycle 2.1.2: Time Stop
```
RED:   Test that ExitEngine triggers time stop
GREEN: Verify time stop logic delegates to exit_rules
```

**Behaviors to Test**:
- [ ] Time stop triggered after max_hold_seconds
- [ ] Time stop varies by session phase
- [ ] Time stop varies by market state
- [ ] Time stop can be disabled

---

#### Cycle 2.1.3: Trailing Stop
```
RED:   Test that ExitEngine trails stop after 1R profit
GREEN: Verify TrailEngine.apply_atr_trail()
```

**Behaviors to Test**:
- [ ] ATR trail activates after 1R profit
- [ ] Trail follows price at ATR step
- [ ] Trail only moves in favorable direction
- [ ] Returns None if not activated

---

#### Cycle 2.1.4: Partition Exits
```
RED:   Test that ExitEngine executes P1/P2/P3 partitions
GREEN: Verify PartitionExitManager.check()
```

**Behaviors to Test**:
- [ ] P1 exit at 1R (30% size)
- [ ] P2 exit at 2R (40% size)
- [ ] P3 trails remaining 30%
- [ ] Breakeven at 1R
- [ ] State tracked per position

---

### Task 2.2: Risk Domain Tests

#### Cycle 2.2.1: Risk Manager
**Test File**: `tests/unit/domain/risk/test_risk_manager.py`

**Behaviors to Test**:
- [ ] Halts on 2% daily drawdown
- [ ] Pauses on 3 consecutive losses
- [ ] Rejects if max concurrent positions (5) exceeded
- [ ] Rejects if portfolio notional > 60% equity
- [ ] Rejects if per-symbol notional > 20% equity
- [ ] Kill switch halts immediately
- [ ] Drift detection from baseline win rate

---

#### Cycle 2.2.2: Circuit Breakers
**Test File**: `tests/unit/domain/risk/test_circuit_breakers.py`

**Behaviors to Test**:
- [ ] Locks on N consecutive losses
- [ ] Locks on daily drawdown %
- [ ] Unlocks on profit target hit
- [ ] Locks on absolute account loss
- [ ] Returns BreakerResult with reason
- [ ] Non-overridable (hard stops)

---

#### Cycle 2.2.3: Self-Healing
**Test File**: `tests/unit/domain/risk/test_self_healing.py`

**Behaviors to Test**:
- [ ] Entry rejection: no retry
- [ ] SL rejection: retry once
- [ ] Exit rejection: retry 3x then escalate
- [ ] Exponential backoff on retries
- [ ] Sync/async callable handling
- [ ] Circuit breaker integration

---

#### Cycle 2.2.4: Position Reconciliation
**Test File**: `tests/unit/domain/risk/test_position_reconciliation.py`

**Behaviors to Test**:
- [ ] Detects mismatch between local and broker positions
- [ ] Reconciles on startup
- [ ] Alerts on unrecoverable mismatch
- [ ] Handles broker downtime gracefully

---

### Task 2.3: Trade Management Tests

#### Cycle 2.3.1: Position Sizer
**Test File**: `tests/unit/domain/exit/test_position_sizer.py`

**Behaviors to Test**:
- [ ] Calculates lots from risk % (0.5% default)
- [ ] Respects hard ceiling (1% equity)
- [ ] Rejects zero equity
- [ ] Rejects zero stop distance
- [ ] Rejects zero point value
- [ ] Returns PositionSize value object

---

#### Cycle 2.3.2: Pyramid Manager
**Test File**: `tests/unit/domain/exit/test_pyramid_manager.py`

**Behaviors to Test**:
- [ ] Requires profit (price > entry for LONG)
- [ ] Requires aggression score >= 3.0
- [ ] Max 2 adds (3 total entries)
- [ ] Add1 = 100% base, Add2 = 50% base
- [ ] Rejects if same LVN (< 0.3% separation)
- [ ] Returns PyramidSignal or None

---

#### Cycle 2.3.3: Structural Stop Engine
**Test File**: `tests/unit/domain/exit/test_structural_stop_engine.py`

**Behaviors to Test**:
- [ ] FAILED_AUCTION: stop beyond probe extreme
- [ ] AAA/MEAN_REVERSION: stop beyond nearest LVN
- [ ] MOMENTUM: stop beyond IB or VA
- [ ] Default: stop beyond nearest level
- [ ] ATR cap (2× ATR)
- [ ] Fallback if no levels available
- [ ] Returns StructuralStop with StopReason

---

#### Cycle 2.3.4: Loss Tracker
**Test File**: `tests/unit/domain/exit/test_loss_tracker.py`

**Behaviors to Test**:
- [ ] Accumulates daily losses
- [ ] Triggers circuit breaker at max daily losses (3)
- [ ] Resets on new day
- [ ] Persists to KV storage
- [ ] Thread-safe with RLock
- [ ] Tracks consecutive losses

---

### Task 2.4: Additional Missing Tests

#### Cycle 2.4.1: Exit Rules
**Test File**: `tests/unit/domain/exit/test_exit_rules.py`

**Behaviors to Test**:
- [ ] `classify_exit()` returns correct ExitReason
- [ ] `check_time_stop()` varies by phase/state
- [ ] `check_spread_blowout()` triggers on threshold

---

#### Cycle 2.4.2: Risk Sizing Engine
**Test File**: `tests/unit/domain/risk/test_risk_sizing_engine.py`

**Behaviors to Test**:
- [ ] Base sizing from equity %
- [ ] Adjusts for setup tier (A/B/C)
- [ ] Adjusts for session P&L (if implemented)
- [ ] Compounding logic (if implemented)

---

#### Cycle 2.4.3: Risk Tier Engine
**Test File**: `tests/unit/domain/risk/test_risk_tier_engine.py`

**Behaviors to Test**:
- [ ] Classifies setup as Tier A/B/C
- [ ] Tier A: highest risk allocation
- [ ] Tier C: lowest risk allocation
- [ ] Uses multiple criteria (aggression, confluence, etc.)

---

## Phase 3: Complete Pending Features (Week 5-6)

**Focus**: Implement missing functionality with TDD

### Task 3.1: Dhan Adapter Parity

**Current**: 80L (basic orders)
**Target**: 300L+ (full parity with backend's 507L)

#### Cycle 3.1.1: Option Chain Fetch
```
RED:   Test that DhanAdapter.fetch_option_chain() returns contracts
GREEN: Implement option chain API call with caching
```

**Test File**: `tests/unit/infrastructure/test_dhan_option_chain.py`

**Behaviors to Test**:
- [ ] Fetches option chain for underlying
- [ ] Filters by expiry
- [ ] Returns list of OptionContract
- [ ] Caches result (TTL 60s)
- [ ] Handles API errors gracefully
- [ ] Rate limiting respected

---

#### Cycle 3.1.2: Lot Size Query
```
RED:   Test that DhanAdapter.get_lot_size() returns correct lot size
GREEN: Implement lot size lookup
```

**Test File**: `tests/unit/infrastructure/test_dhan_lot_size.py`

**Behaviors to Test**:
- [ ] Returns lot size for symbol
- [ ] Caches result
- [ ] Returns None for unknown symbol
- [ ] Handles API errors

---

#### Cycle 3.1.3: Error Recovery / Retry
```
RED:   Test that DhanAdapter retries on transient failures
GREEN: Implement retry logic with exponential backoff
```

**Test File**: `tests/unit/infrastructure/test_dhan_retry.py`

**Behaviors to Test**:
- [ ] Retries on 5xx errors (3 attempts)
- [ ] Does not retry on 4xx errors
- [ ] Exponential backoff (1s, 2s, 4s)
- [ ] Circuit breaker integration
- [ ] Logs retry attempts

---

### Task 3.2: Risk Sizing Engine Enhancements

#### Cycle 3.2.1: Dynamic Risk from Session P&L
```
RED:   Test that risk % adjusts based on session P&L
GREEN: Implement dynamic risk calculation
```

**Test File**: `tests/unit/domain/risk/test_dynamic_risk_sizing.py`

**Behaviors to Test**:
- [ ] Risk increases when session profitable
- [ ] Risk decreases when session losing
- [ ] Floor at 0.25% risk
- [ ] Ceiling at 1.0% risk
- [ ] Smooth adjustment (no jumps)

---

#### Cycle 3.2.2: Compounding Logic
```
RED:   Test that position size compounds from equity growth
GREEN: Implement compounding calculation
```

**Behaviors to Test**:
- [ ] Position size grows with equity
- [ ] Position size shrinks with equity loss
- [ ] Recalculates on each trade
- [ ] Respects max position size cap

---

### Task 3.3: Trail Engine Enhancements

#### Cycle 3.3.1: VWAP-Based Trailing Stop
```
RED:   Test that TrailEngine trails to VWAP
GREEN: Implement VWAP trailing logic
```

**Test File**: `tests/unit/domain/exit/test_vwap_trail.py`

**Behaviors to Test**:
- [ ] Trails to VWAP + offset for LONG
- [ ] Trails to VWAP - offset for SHORT
- [ ] Only moves in favorable direction
- [ ] Activates after 1R profit

---

#### Cycle 3.3.2: CVD Breakeven
```
RED:   Test that TrailEngine moves to breakeven on CVD confirmation
GREEN: Implement CVD-based breakeven logic
```

**Test File**: `tests/unit/domain/exit/test_cvd_breakeven.py`

**Behaviors to Test**:
- [ ] Moves SL to breakeven when CVD confirms direction
- [ ] CVD slope threshold for confirmation
- [ ] Only applies after 0.5R profit
- [ ] Does not move against position

---

### Task 3.4: Trade Journal

**Behavior**: Persist trade history with annotations for post-trade analysis.

#### Cycle 3.4.1: Trade Record Creation
```
RED:   Test that TradeJournal persists completed trades
GREEN: Implement TradeJournal with SQLite storage
```

**Test File**: `tests/unit/domain/trading/test_trade_journal.py`

**Behaviors to Test**:
- [ ] Records entry/exit details
- [ ] Records AMT context (market state, profile shape, etc.)
- [ ] Records exit reason
- [ ] Records P&L
- [ ] Queryable by date/symbol/setup

---

#### Cycle 3.4.2: Post-Trade Analysis
```
RED:   Test that TradeJournal generates analysis reports
GREEN: Implement analysis methods
```

**Behaviors to Test**:
- [ ] Win rate by setup type
- [ ] Average R:R by setup
- [ ] Best/worst session phases
- [ ] Performance by market state
- [ ] Export to CSV/JSON

---

## Phase 4: Medium Priority Fixes (Week 7-8)

**Focus**: Refine architecture, improve consistency

### Task 4.1: Unify Event Systems

**Problem**: Domain events and pipeline events exist separately.

#### Cycle 4.1.1: Event Adapter
```
RED:   Test that domain events can be translated to pipeline events
GREEN: Implement EventAdapter
```

**Test File**: `tests/unit/domain/test_event_adapter.py`

**Behaviors to Test**:
- [ ] TickReceived → Tick
- [ ] SignalGenerated → Signal
- [ ] PositionClosed → PositionEvent
- [ ] Preserves all data
- [ ] Bidirectional translation

---

### Task 4.2: Split IStorage Interface

**Problem**: IStorage has 15 methods (violates ISP).

#### Cycle 4.2.1: Granular Interfaces
```
RED:   Test that consumers only depend on needed interfaces
GREEN: Refactor to inject specific interfaces
```

**Test File**: `tests/unit/infrastructure/test_storage_interfaces.py`

**Behaviors to Test**:
- [ ] TickProcessor only needs ITickStorage
- [ ] TradeJournal only needs ITradeStorage
- [ ] SessionStateManager only needs IOpenPositionStorage
- [ ] SQLiteStorageAdapter implements all interfaces
- [ ] Mock storage for testing (implement only needed interface)

---

### Task 4.3: Error Handling Convention

**Problem**: Inconsistent error handling (silent returns, exceptions, logging).

#### Cycle 4.3.1: Establish Convention
```
RED:   N/A (documentation + refactoring)
GREEN: Document convention, refactor inconsistent code
```

**Documentation**: `docs/ERROR_HANDLING.md`

**Convention**:
- **Domain**: Raise exceptions (let application handle)
- **Application**: Log and return error responses
- **Infrastructure**: Log, wrap in domain exceptions, re-raise
- **API**: Return HTTP error responses

**Refactor Candidates**:
- `application/handlers/evaluate_entry_handler.py` — silent returns
- `domain/exit/service/exit_engine.py` — NotImplementedError (good)
- `infrastructure/adapters/dhan_adapter.py` — inconsistent

---

### Task 4.4: Clarify Orchestration Model

**Problem**: Pipeline stages and command handlers both exist.

#### Cycle 4.4.1: Document Relationship
```
RED:   N/A (documentation)
GREEN: Document architecture decision
```

**Documentation**: `docs/ARCHITECTURE_DECISIONS.md`

**Decision**:
- **Pipeline**: Primary tick processing path (deterministic, testable)
- **Handlers**: API command processing (explicit, auditable)
- **Integration**: Handlers submit commands to pipeline, pipeline publishes domain events

---

## Test Suite Structure

```
tests/
├── unit/
│   ├── core/                    ← NEW: Core components
│   │   ├── test_metrics.py
│   │   ├── test_circuit_breaker.py
│   │   ├── test_event_store.py
│   │   └── test_feature_flags.py
│   │
│   ├── domain/
│   │   ├── exit/                ← NEW: Exit domain tests
│   │   │   ├── test_exit_engine.py
│   │   │   ├── test_exit_rules.py
│   │   │   ├── test_position_sizer.py
│   │   │   ├── test_pyramid_manager.py
│   │   │   ├── test_structural_stop_engine.py
│   │   │   ├── test_loss_tracker.py
│   │   │   ├── test_vwap_trail.py
│   │   │   └── test_cvd_breakeven.py
│   │   │
│   │   ├── risk/                ← NEW: Risk domain tests
│   │   │   ├── test_risk_manager.py
│   │   │   ├── test_circuit_breakers.py
│   │   │   ├── test_self_healing.py
│   │   │   ├── test_position_reconciliation.py
│   │   │   ├── test_risk_sizing_engine.py
│   │   │   ├── test_risk_tier_engine.py
│   │   │   └── test_dynamic_risk_sizing.py
│   │   │
│   │   └── trading/             ← NEW: Trading domain tests
│   │       └── test_trade_journal.py
│   │
│   ├── application/
│   │   └── test_di_container_integration.py
│   │
│   ├── infrastructure/
│   │   ├── test_dhan_option_chain.py
│   │   ├── test_dhan_lot_size.py
│   │   ├── test_dhan_retry.py
│   │   └── test_storage_interfaces.py
│   │
│   └── runtime/
│       └── pipeline/
│           └── test_market_structure_decoupled.py
│
├── integration/
│   ├── test_full_pipeline_flow.py
│   └── test_trade_lifecycle.py
│
└── e2e/
    └── test_paper_trading_e2e.py
```

**Expected Test Count**: 64 → 120+ test files
**Expected Coverage**: 60% → 85%+

---

## Execution Order

### Week 1-2: Phase 1 (Critical)
1. Task 1.1: Split `core_components.py` (5 cycles)
2. Task 1.2: Wire up DI container (1 cycle)
3. Task 1.3: Fix stage coupling (1 cycle)

**Deliverable**: No global mutable state, proper DI, decoupled stages

---

### Week 3-4: Phase 2 (Test Coverage)
1. Task 2.1: Exit engine tests (4 cycles)
2. Task 2.2: Risk domain tests (4 cycles)
3. Task 2.3: Trade management tests (4 cycles)
4. Task 2.4: Additional tests (3 cycles)

**Deliverable**: 85%+ test coverage for critical paths

---

### Week 5-6: Phase 3 (Features)
1. Task 3.1: Dhan adapter parity (3 cycles)
2. Task 3.2: Risk sizing enhancements (2 cycles)
3. Task 3.3: Trail engine enhancements (2 cycles)
4. Task 3.4: Trade journal (2 cycles)

**Deliverable**: Full feature parity, enhanced capabilities

---

### Week 7-8: Phase 4 (Refinement)
1. Task 4.1: Unify event systems (1 cycle)
2. Task 4.2: Split IStorage interface (1 cycle)
3. Task 4.3: Error handling convention (1 cycle)
4. Task 4.4: Clarify orchestration (documentation)

**Deliverable**: Cleaner architecture, documented conventions

---

## Success Metrics

### Architecture
- [ ] Zero global mutable state (verified via grep)
- [ ] DI container wired in `api/main.py`
- [ ] No stage coupling (verified via code review)
- [ ] Domain layer isolation maintained (0 imports from infra/api)

### Test Coverage
- [ ] 85%+ line coverage (measure with `pytest --cov`)
- [ ] 100% branch coverage for critical paths (exit, risk)
- [ ] All tests pass (`pytest` exits 0)
- [ ] No test warnings or deprecations

### Feature Completeness
- [ ] Dhan adapter: option chain, lot size, retry
- [ ] Risk sizing: dynamic P&L, compounding
- [ ] Trail engine: VWAP trail, CVD breakeven
- [ ] Trade journal: full implementation

### Code Quality
- [ ] No linting errors (`ruff check`)
- [ ] No type errors (`mypy`)
- [ ] All public APIs documented
- [ ] Architecture decisions documented (ADRs)

---

## Risk Mitigation

### Risk 1: Breaking Existing Functionality
**Mitigation**: 
- Run full test suite after each cycle
- Manual testing with paper trading after each phase
- Feature flags for new functionality

### Risk 2: Scope Creep
**Mitigation**:
- Strict adherence to TDD (one test at a time)
- No speculative features
- Document out-of-scope items for future phases

### Risk 3: Time Overruns
**Mitigation**:
- Prioritize critical phases (1-2) first
- Phase 3-4 can be deferred if needed
- Weekly progress reviews

---

## Next Steps

1. **User Approval**: Review this plan, confirm priorities
2. **Environment Setup**: Ensure test environment ready (`pytest`, `coverage`, `ruff`)
3. **Start Phase 1, Task 1.1, Cycle 1.1.1**: First RED cycle (MetricsRegistry test)
4. **Iterate**: Continue RED→GREEN→REFACTOR cycle for each task

**Question for User**: Should we start with Phase 1 (architecture fixes) or Phase 2 (test coverage)? My recommendation is Phase 1 to establish solid foundation before adding tests.
