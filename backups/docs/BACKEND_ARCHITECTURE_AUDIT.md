# Senior Principal Engineer — Architecture Audit

**Date:** 2026-03-20
**Scope:** DRY violations, SOLID principles, code smells, event flow, LLM/ML integration
**Auditor:** Senior Principal Engineer

---

## 1. Executive Summary

The GlassyTrade AI backend is a **functionally complete trading system** with proper DDD layering, but has significant architectural debt that will impede maintainability and correctness as the system scales.

**Critical Findings:**
- **SOLID violations:** 5 major violations (SRP, OCP, DIP)
- **DRY violations:** 8 significant duplications
- **Code smells:** 12 identified patterns
- **Event flow issues:** 3 architectural anti-patterns

---

## 2. SOLID Violations

### 2.1 Single Responsibility Principle (SRP) — VIOLATED

**trading_session.py (1,200+ lines)**
The `TradingSessionService` class has **12+ responsibilities**:
1. Tick processing pipeline orchestration
2. Portfolio mutation (SL/TP exits)
3. AMT analysis dispatch
4. LLM entry decision dispatch
5. Overseer dispatch
6. Position consistency reconciliation
7. Session risk management
8. Playbook guard telemetry
9. Explainability monitoring
10. Session eviction (memory management)
11. Journal/audit logging
12. System risk state aggregation

**Impact:** This is a "God Class" anti-pattern. Any change to exit logic risks breaking entry logic.

**Recommendation:** Split into:
```
TickPipelineCoordinator (tick → analysis → signal → execute)
PositionLifecycleManager (open/close/partial/reconcile)
SessionTelemetryService (playbook guard, explainability, journal)
SystemRiskAggregator (risk state, halt management)
```

### 2.2 Open/Closed Principle (OCP) — VIOLATED

**llm_entry_handler.py**
The `_llm_worker_loop` method (500+ lines) has **hardcoded gate logic** that should be extensible:
- CVD hard gate (market-specific thresholds)
- Profile shape gate (hardcoded shape codes)
- Momentum fade gate
- Contested zone gate

Adding a new gate requires modifying the worker loop, not extending it.

**Recommendation:** Extract gates into a `GateChain` pattern:
```python
class EntryGate(ABC):
    @abstractmethod
    def evaluate(self, context: GateContext) -> GateResult: ...

class GateChain:
    def __init__(self, gates: list[EntryGate]): ...
    def evaluate(self, context: GateContext) -> GateResult:
        for gate in self._gates:
            result = gate.evaluate(context)
            if not result.passed:
                return result
        return GateResult(passed=True)
```

### 2.3 Dependency Inversion Principle (DIP) — VIOLATED

**llm_entry_handler.py** directly imports concrete implementations:
```python
from app.domain.fabio_ai.services.entry_gate import (
    build_entry_signal,
    check_momentum_fade,
    three_align_check,
)
```

Domain services should depend on abstractions (ports), not concrete implementations.

### 2.4 Interface Segregation Principle (ISP) — VIOLATED

**StoragePort** is a fat interface with 15+ methods. Most clients only need 2-3:
- `save_tick` — used by engine
- `save_trade` — used by lifecycle handler
- `load_open_positions` — used by recovery

**Recommendation:** Split into focused interfaces:
```python
class TickStoragePort: ...
class TradeStoragePort: ...
class PositionStoragePort: ...
class RiskStoragePort: ...
```

### 2.5 Liskov Substitution Principle (LSP) — PASS

No violations detected. Port implementations correctly fulfill their contracts.

---

## 3. DRY Violations

### 3.1 Market State Mapping (3 locations)

```
trading_session.py:    "Trending" if MarketStateCodec.is_imbalanced(...)
llm_entry_handler.py:  "Trending" if MarketStateCodec.is_imbalanced(...)
entry_gate.py:         market_state.upper() in ("IMBALANCED", "IMBALANCE")
```

**Fix:** Single `MarketState.display_name()` method.

### 3.2 Side Normalization (5 locations)

```python
pos.side.value if hasattr(pos.side, 'value') else str(pos.side)
```

Repeated in:
- `trading_session.py` (3×)
- `trade_lifecycle_handler.py` (2×)
- `llm_entry_handler.py` (1×)

**Fix:** Create `Side.normalize(side) -> str` utility.

### 3.3 Decimal-to-Float Conversion (4 locations)

```python
float(position.entry_price) if hasattr(position.entry_price, '__float__') else position.entry_price
```

**Fix:** Centralize in `ValueObjectSerializer.to_float()`.

### 3.4 VWAP Bias Check (duplicated)

`check_vwap_bias()` is defined in `entry_gate.py` AND referenced in `llm_entry_handler.py` with inline logic.

### 3.5 CVD Threshold Calculation (2 locations)

```python
cvd_thresh = 5000 if settings.SCANNER_MODE in ("nse", "nse_options") else 50
```

**Fix:** Move to `constants.py` as `CVD_BLOCK_THRESHOLD_NSE` / `CVD_BLOCK_THRESHOLD_MCX`.

### 3.6 Session Info Retrieval (3 locations)

```python
_market = Settings().DEFAULT_EXCHANGE
if _market in ("NFO", "BSE"): _market = "NSE"
session_info = get_session_info(timestamp=tick.time, market=_market)
```

**Fix:** Create `SessionContextFactory.from_tick(tick)`.

### 3.7 Position Recovery Logic (duplicated)

Both `trading_session.py` AND `engine.py` have position recovery code with slightly different logic.

### 3.8 Aggression Score Display Formatting

```python
f"Aggression Score: {amt_result.aggression:.2f}"
```

Appears in both `llm_entry_handler.py` and `prompt_builder.py`.

---

## 4. Code Smells

### 4.1 Long Method (Critical)

| File | Method | Lines |
|------|--------|-------|
| `trading_session.py` | `_on_tick` | ~400 |
| `llm_entry_handler.py` | `_llm_worker_loop` | ~500 |
| `trading_session.py` | `_execute_signal` | ~150 |

### 4.2 Feature Envy

`llm_entry_handler.py` extensively reads `session._last_fp_domain`, `session._prior_profile`, `session._ib_high` — these are internal state that should be exposed via a proper query interface.

### 4.3 Data Clumps

`(amt_result, tick, order_book, session_info)` appears as a parameter group in 8+ method signatures. Should be a `TradingContext` dataclass.

### 4.4 Primitive Obsession

`market_state_str: str` is passed everywhere instead of a proper `MarketState` enum with behavior.

### 4.5 Temporal Coupling

```python
# In llm_entry_handler.py
with session._lock:
    session._last_ai_time = time.time()
    session._ai_running = True
# ... 500 lines later ...
with session._lock:
    session._ai_running = False
```

Lock acquisition/release spans 500 lines — any exception in between leaves the lock inconsistent.

### 4.6 Inappropriate Intimacy

`TradingSessionService` reaches into `session._agent_decision`, `session._last_fp_domain`, `session._prior_profile` — these are implementation details of `SessionState`.

### 4.7 Message Chains

```python
self._lifecycle_handler._trade_manager.get_position_metrics(pos.id)
```

Three levels of indirection — violates Law of Demeter.

### 4.8 Switch Statements (type codes)

```python
if exit_sig.reason == ExitReason.PARTIAL_TAKE_PROFIT:
    # partial close
else:
    # full close
```

Should use polymorphism: `ExitStrategy.execute(portfolio, position)`.

### 4.9 Dead Code

- `SessionState._last_candle_time` — set but never read
- `SessionState._cached_profile` / `_cached_leg_profile` — set in AMT handler but session state has its own copy

### 4.10 Magic Numbers

```python
if time.time() - enqueue_time > 30.0:  # staleness
if elapsed < 10:  # cooldown
if len(self._cache) > self._CACHE_SIZE:  # cache
if grade_score < -5:  # extreme grade
if signal_age > 600:  # signal TTL
```

### 4.11 Duplicate Conditional Logic

The VWAP overextension check appears 3 times:
1. `_evaluate_candidate()` — blocks entry
2. `_llm_worker_loop()` — advisory warning
3. `entry_gate.py` — grade adjustment

### 4.12 Speculative Generality

`SessionState._playbook_guard_rejections`, `_explainability_entries`, `_aggression_explained_entries` — telemetry fields that add complexity but unclear business value.

---

## 5. Event Flow Analysis

### 5.1 Current Flow (Anti-Pattern: Hybrid Sync/Async)

```
Tick → process_tick() → event_bus.publish(TickReceived)
    ├── _on_tick() [SYNC handler]
    │   ├── amt_handler.analyze() [SYNC]
    │   ├── probability_engine [SYNC, <1ms]
    │   ├── lifecycle_handler.check_exits() [SYNC]
    │   ├── llm_handler.run_entry() [ASYNC via ThreadPool]
    │   │   └── _llm_worker_loop() [background thread]
    │   │       └── session._pending_signal = signal
    │   └── process_tick() drains _pending_signal [next tick]
    └── return state snapshot
```

**Problem:** The event bus is synchronous but LLM inference is async. The `_pending_signal` hack bridges them, creating temporal coupling.

### 5.2 Signal Processing Flow

```
LLM Decision → _pending_signal → drain on next tick → _execute_signal()
    ├── Risk validation
    ├── Option enrichment
    ├── Broker.execute_order()
    ├── TradeManager.register_position()
    └── Journal.log_entry()
```

**Problem:** Signal generation and execution happen on different ticks. A 5-minute candle means the signal could be 0-5 minutes stale when executed.

### 5.3 LLM/ML Information Flow

```
AMT Analyzer → amt_result (domain object)
    ├── amt_dto (frontend serialization)
    ├── footprint_dto (frontend serialization)
    ├── agent_decision (probability engine)
    ├── market_data_ai (LLM prompt input)
    └── session.last_amt (cached for UI)
```

**Assessment:** ✅ LLM/ML components receive correct information. The `market_data_ai` dict contains:
- Price/volume/delta (tick data)
- VAH/VAL/POC (profile data)
- CVD slope/divergence (order flow)
- VWAP bands (reference)
- LVN/HVN levels (structural)
- Aggression score (confirmation)
- Profile shape (distribution type)
- Episodic memory (trade history)

**Issue:** The LLM prompt is built in `llm_entry_handler.py` (500 lines) instead of a dedicated prompt engineering module. This makes prompt iteration difficult.

### 5.4 Trade Execution Flow

```
Signal → _execute_signal()
    ├── Trade thesis validation
    ├── Idempotency check (signal_id)
    ├── Risk manager validation
    ├── Option strike selection
    ├── Broker.execute_order() → Position
    ├── TradeManager.register_position()
    ├── Portfolio mutation (under lock)
    └── Journal + Storage persistence
```

**Assessment:** ✅ Trade execution is correct. The idempotency guard prevents duplicate entries. The lock prevents race conditions.

**Issue:** Portfolio mutation and TradeManager registration are separate operations. If registration fails after portfolio mutation, the position exists but has no exit monitoring.

---

## 6. Event-Driven Architecture Assessment

### 6.1 Is the System Fully Event-Driven?

**NO.** The system is **hybrid synchronous/reactive**:

| Component | Pattern | Assessment |
|-----------|---------|------------|
| Tick processing | Synchronous handler | ❌ Not event-driven |
| AMT analysis | Synchronous call | ❌ Not event-driven |
| LLM inference | Thread pool + pending signal | ⚠️ Half-event-driven |
| Position exits | Synchronous call | ❌ Not event-driven |
| Risk events | Event bus publish | ✅ Event-driven |
| Journal logging | Synchronous call | ❌ Not event-driven |

### 6.2 Recommended Event-Driven Architecture

```
Tick → EventBus.publish(TickReceived)
    ├── AMTAnalysisHandler [async]
    │   └── EventBus.publish(AMTAnalyzed)
    ├── ProbabilityHandler [async]
    │   └── EventBus.publish(ProbabilityComputed)
    ├── ExitEvaluationHandler [async]
    │   └── EventBus.publish(ExitEvaluated)
    └── LLMAnalysisHandler [async]
        └── EventBus.publish(LLMAnalyzed)

EventBus.publish(AMTAnalyzed + ProbabilityComputed + LLMAnalyzed)
    → SignalDecisionHandler [sync]
        └── EventBus.publish(SignalGenerated)

EventBus.publish(SignalGenerated)
    → ExecutionHandler [sync]
        └── EventBus.publish(PositionOpened)

EventBus.publish(PositionOpened)
    → JournalHandler [async]
    → NotificationHandler [async]
    → PersistenceHandler [async]
```

---

## 7. Key Recommendations

### Priority 1 (Immediate — 2 weeks)

1. **Extract `TradingContext` dataclass** to eliminate parameter clumps
2. **Create `Side.normalize()` utility** to eliminate DRY violation
3. **Split `StoragePort`** into focused interfaces (ISP)
4. **Extract gates into `GateChain`** for extensibility (OCP)
5. **Add signal staleness validation** before execution

### Priority 2 (Short-term — 4 weeks)

6. **Split `TradingSessionService`** into 4 focused services (SRP)
7. **Extract `_llm_worker_loop`** into `LLMWorker` class with gate chain
8. **Create `TradingContextFactory`** for session info retrieval
9. **Unify position recovery** into single service
10. **Add circuit breaker** for LLM inference timeouts

### Priority 3 (Medium-term — 8 weeks)

11. **Migrate to async event bus** for true event-driven architecture
12. **Extract prompt engineering** into dedicated `PromptEngineeringService`
13. **Add event sourcing** for position lifecycle (audit trail)
14. **Implement CQRS** for read/write separation (state snapshots vs mutations)

---

## 8. LLM/ML Decision Quality Assessment

### 8.1 Information Completeness: ✅ GOOD

The LLM receives comprehensive market context:
- Full AMT analysis (POC, VAH, VAL, LVN, HVN, profile shape)
- Order flow metrics (CVD, aggression, absorption, bubbles)
- VWAP bands and bias
- Session context (phase, opening relation, gap type)
- Episodic memory (recent trade outcomes)
- Gate warnings (informational, not blocking)

### 8.2 Decision Flow: ⚠️ NEEDS IMPROVEMENT

**Current:** LLM → gates → grade → confidence → signal → execute

**Issue:** The LLM is supposed to be the "READER" but gates can override its decision. This creates confusion about who is the authority.

**Recommendation:** Clarify the authority chain:
```
LLM (READER) → conviction assessment → signal generation
GATES (SAFETY NET) → disaster prevention only (circuit breaker, extreme CVD)
GRADE (ADVISORY) → confidence adjustment, not blocking
```

### 8.3 Trade Execution: ✅ CORRECT

- Idempotency guard prevents duplicates
- Lock prevents race conditions
- Journal provides full audit trail
- Crash recovery restores open positions

---

## 9. Summary

| Category | Score | Status |
|----------|-------|--------|
| SOLID Compliance | 2/5 | ❌ Needs work |
| DRY Compliance | 4/10 | ⚠️ Significant duplication |
| Code Quality | 5/10 | ⚠️ Technical debt |
| Event-Driven | 3/10 | ❌ Hybrid anti-pattern |
| LLM Integration | 7/10 | ✅ Good information flow |
| Trade Execution | 8/10 | ✅ Correct and safe |

**Overall Architecture Maturity: 65%**

The system is **functionally complete** but has significant architectural debt that will impede maintainability. The recommended refactoring should be prioritized to prevent further accumulation of technical debt.