# Master Refactoring Plan — GlassyTrade v5

> **Date:** 2026-04-02  
> **Role:** Principal Engineer / Architect  
> **Scope:** SOLID, DDD, Event-Driven Architecture, Code Quality

---

## Phase 1: Immediate Wins — Quick Fixes (1-2 hours)

### 0.1 Fix broken test imports
- **Problem:** 18 tests fail at import time due to `ModuleNotFoundError`
- **Root cause:** Tests import modules that don't exist (planned features never implemented)
- **Fix:** Create stub modules that export the expected symbols, then mark tests with `@pytest.mark.skip(reason="Feature not yet implemented")`
- **Files to create:**
  - `app/infrastructure/adapters/data_generator.py` — synthetic market data
  - `app/domain/fabio_ai/strategy/__init__.py`, `protocols.py`, `setup_detector.py`
  - `app/domain/services/walk_forward_validator.py`
  - `app/domain/services/option_selection_engine.py`
  - `app/domain/services/scalp_gate_pipeline.py`
  - `app/domain/services/scalp_exit_rules.py`
  - `app/application/services/portfolio_coordinator.py`
  - `app/domain/services/capital_ladder.py`
  - `app/domain/services/fifteen_sec_trigger.py`

### 0.2 Fix conftest.py — remove over-eager mocking
- **Problem:** `tests/conftest.py` mocks `shared.entities` as `MagicMock`, conflicting with real import path
- **Fix:** Only add parent directory to `sys.path`, don't mock subpackages

### 0.3 Extract shared utilities
- **Problem:** IST timezone and `_depth_to_dto()` duplicated across 5+ files
- **Fix:** Create `app/shared/timezones.py` and `app/shared/utils.py`
- **Impact:** Eliminates 3+ instances of duplication

### 0.4 Establish test baseline
- Create `tests/baseline_test_results.json` capturing pass/fail/skip counts
- Install `import-linter` for architecture guardrails

### 0.5 Create dual-run comparison framework
- **File:** `tests/validation/comparison_engine.py`
- **Purpose:** Run old vs new codepath side-by-side and assert byte-identical state
- **Usage:** Required for every extraction in Phase 2 and 3

---

## Phase 2: Dead Code & Layer Inversion Cleanup (2-3 days)

### 1. Fix Layer Inversions (DIP violations)

**Current violations:**

| File | Imports | Should be |
|------|---------|-----------|
| `application/services/trading_session.py` | `from app.api.dependencies import get_service_graph` | Injected via constructor |
| `application/engine.py` | `from app.config import settings` | Injected via TradingEngineConfig |
| `domain/fabio_ai/services/option_scanner.py` | `from app.config import settings` | Constructor parameter |
| `domain/fabio_ai/services/vp_contract_selector.py` | `from app.config import settings` | Constructor parameter |

**Fix strategy for each:**
1. Add a typed dataclass as constructor parameter
2. Pass it from `ServiceGraph` (composition root)
3. Verify: `import-linter` no longer flags the violation
4. Run: full test suite, compare against baseline

### 2. Remove dead event bus

**Current state:**
- 13 domain events defined, 5 `.publish()` calls, **0 subscribers**
- The event bus is a facade masking synchronous method-call architecture

**Fix strategy:**
- Option A (recommended): Document that system is synchronous, remove dead `.publish()` calls, keep event types for future use
- Option B: Remove `EventBusPort` entirely, replace with direct method calls
- Decision: **Option A** — less risky, preserves optionality

**Files affected:**
- `application/services/entry_coordinator.py` — `_event_bus.publish(PositionOpened(...))` → direct call to `_event_logger.log_position_event()`
- `application/handlers/llm_entry_handler.py` — `_event_bus.publish(AIAnalysisCompleted(...))` → direct call
- `application/handlers/trade_lifecycle_handler.py` — event publish calls
- `api/dependencies.py` — remove `event_bus` from ServiceGraph
- `domain/ports/event_bus.py` — keep but mark as "optional future extension"

### 3. Eliminate code duplication

**Duplicate instances found:**

| What | Copies | Solution |
|------|--------|----------|
| `_depth_to_dto()` | 3 (engine.py:42, gameloop.py:63, trading_session.py:~1200) | → `app/shared/converters.py` |
| `_camelcase_ai()` | 2 (trading_session.py, test files) | → `app/shared/converters.py` |
| IST timezone `timezone(timedelta(hours=5, minutes=30))` | 6+ files | → `app/shared/timezones.py` |
| R:R calculation `reward/risk if risk > 0 else 0` | 3+ locations | → `app/domain/services/risk_utils.py` |

### 4. Kill silent exception handlers

**Problem:** 12 instances of `except Exception: log.debug("Silent exception handled")`

**Fix:**
- Categorize each as either:
  - **Non-critical:** UI decoration, logging fallbacks → keep but use specific exception type
  - **Critical:** Trading decisions, position management → propagate to orchestrator level
- Example fix:
  ```python
  # Before  
  except Exception:
      log.debug("Silent exception handled", exc_info=True)
  
  # After — non-critical
  except (KeyError, TypeError):
      log.debug("AMT state missing field %s, using default", key)
  
  # After — critical
  except ValueError as e:
      raise TradingError(f"Invalid signal parameters: {e}") from e
  ```

### 5. Fix `SessionState.__import__` hacks

**Current:**
```python
portfolio: Portfolio = field(
    default_factory=lambda: __import__(
        "app.domain.trading.models.aggregates", fromlist=["Portfolio"]
    ).Portfolio.create_default()
)
```

**Fix:**
- Restructure imports so `SessionState` can use normal imports
- If circular dependency is the cause, use `TYPE_CHECKING` for type hints and lazy import for default
- Or use a factory pattern: `_portfolio_factory: Callable[[], Portfolio] = Portfolio.create_default`

---

## Phase 3: God Class Extraction — trading_session.py (4-5 days)

### Target: Split 1,326-line file into 6 focused orchestrators

**Current `TradingSessionService.process_tick()` responsibilities:**

```
process_tick() — ~900 lines
├── Session phase check + force-exit on session end (80 lines)
├── AMT analysis + footprint generation (120 lines)  
├── Initial Balance engine updates (60 lines)
├── IB breakout scalp evaluation (50 lines)
├── 1-min bar engine update (30 lines)
├── Pre-candle advisory trigger (30 lines)
├── Level approach tracking (20 lines)
├── Agent pipeline (features + probability) (80 lines)
├── Trade lifecycle exit checks (60 lines)
├── Overseer timing + decision save (40 lines)
├── Entry gate pipeline evaluation (120 lines)
├── Short signal gates (40 lines)
├── Signal construction + execution (80 lines)
├── Gate tracking + persistence (40 lines)
├── LLM trigger for UI (20 lines)
└── State snapshot building (40 lines)
```

**Extracted modules:**

```
TradingSessionService (facade, ~150 lines)
├── TickOrchestrator (~150 lines) — candle management, session phase, force-exit
├── AMTOrchestrator (~120 lines) — AMT analysis, IB engine, pre-candle, level tracking
├── AgentPipelineOrchestrator (~100 lines) — feature extraction, probability engine, decision
├── ExitOrchestrator (~100 lines) — trade lifecycle checks, position exits
├── EntryOrchestrator (~150 lines) — gate pipeline, signal construction, execution
└── StateOrchestrator (~80 lines) — state snapshot, DTO building
```

**Extraction methodology (Strangler Fig):**

For each orchestrator:
1. **Extract** code into new class
2. **Dual-run:** keep old code running, call new code silently, compare results
3. **Verify:** 10,000+ ticks produce byte-identical state
4. **Switch:** use new orchestrator output, keep old as assertion backup
5. **Delete:** remove old code path

**QA per extraction:**
```python
comparer = DualRunComparer(tolerance=1e-9)
for tick in simulated_10000_ticks():
    old_state = old_process_tick(tick)
    new_state = orchestrator.process(tick)  
    comparer.compare(old_state, new_state)
    assert comparer.is_clean(), comparer.summary()
```

---

## Phase 4: Dual Position State Unification (2-3 days)

### Problem: Two position registries requiring reconciliation

**Current architecture flaw:**

```
Portfolio.positions     → tracks positions for P&L (aggregates.py)
TradeManager._positions → tracks positions for exit logic (trade_manager.py)
```

These two registries drift independently, requiring `_record_position_consistency()` and `reconcile_portfolio()` to sync them — a clear signal the design is wrong.

**Target: Portfolio is single source of truth**

```
Before:
  Portfolio.positions        [positions for P&L]
  TradeManager._positions    [positions for exits]
  → reconciliation needed

After:
  Portfolio.positions        [single source]
  TradeManager queries Portfolio for position state
  → no reconciliation needed
```

**Migration steps:**
1. Add `Portfolio.get_position(id)`, `Portfolio.get_managed_positions(symbol)` 
2. Change `TradeManager` to query `Portfolio` instead of maintaining own registry
3. Keep `TradeManager.register_position()` but have it add metadata to `Portfolio` position
4. Remove `TradeManager._positions` dict
5. Delete `_record_position_consistency()` and all reconciliation code
6. Dual-run validation: 50,000 ticks, position counts must match at every tick

**QA — critical edge cases:**
- Position opened and immediately hit SL on same tick
- Position with scale-in, then partial exit
- TradeManager trails SL → Portfolio must see the change
- Mid-trade recovery: restart engine, recover from DB
- Concurrent opens on different symbols

---

## Phase 5: Event Bus Cleanup (1-2 days)

### Problem: Dead event bus with zero subscribers

**Evidence:**
- 13 domain events defined in `events.py`
- 5 `.publish()` calls across codebase
- **0 `.subscribe()` calls anywhere**

**Fix options:**
- **A:** Remove event bus entirely (cleanest, but largest diff)
- **B:** Add real subscribers to existing events (turn facade into working pattern)
- **C:** Remove publish calls, keep events for future use (safer, minimal diff)

**Recommendation: C** — document system architecture as synchronous method-call, remove dead publishes, keep event types as documentation of what events exist conceptually.

---

## Phase 6: Entry Gate Refactoring (2 days)

### Problem: `entry_gate.py` is 1,108 lines with mixed concerns

**Current structure:**
```
entry_gate.py
├── Three-Align Gate (150 lines)
├── Confirmation Bundle (Vol+Delta+Spread) (80 lines)
├── Momentum Fade Filter (60 lines)
├── ATR computation (30 lines)
├── Signal construction (SL/TP calc) (200 lines)
├── VWAP bias check (50 lines)
├── Grade scoring (A/B/C setup) (100 lines)
├── Stacked imbalance alignment (40 lines)
├── Option Execution Gates (50 lines)
├── Gate Pipeline integration (60 lines)
└── Position sizing (30 lines)
```

**Target:**
```
app/domain/fabio_ai/services/gates/
├── __init__.py
├── three_align.py          # Market State + Location + Confirmation
├── confirmation_bundle.py  # Volume/Delta/Spread (2/3 rule)
├── momentum_fade.py        # Freight train detection
├── signal_builder.py       # SL/TP construction
├── vwap_bias.py           # VWAP bands check
├── grade_scorer.py        # A/B/C setup classification
└── position_sizing.py     # Lot size calculation
```

These are **pure quant functions** — stateless, no side effects, trivially testable.

---

## Phase 7: Engine Cleanup (2 days)

### Problem: `engine.py` is 940 lines with mixed concerns

**Extractions:**
- `_seed_history()` (60 lines) → `HistorySeeder`
- `_seed_mtf_history()` (50 lines) → `MTFHistorySeeder`  
- `_recover_open_positions()` (80 lines) → `PositionRecovery` (already partially in `startup_reconciliation.py`)
- `_load_candles_from_db()` (40 lines) → `CandleRepository`
- `_backfill_range_bars()` (50 lines) → `RangeBarBackfiller`

**Target `TradingEngine` after extraction:**
```python
class TradingEngine:
    def __init__(self, graph): ...
    async def start(self): ...
    async def stop(self): ...
    async def _tick_loop(self): ...  # 100-150 lines, delegates to modules
    def get_latest_state(self, symbol): ...
    def get_history(self, symbol): ...
```

---

## Phase 8: Final Cleanup & Polish (1-2 days)

### Remaining items:

1. **Unused imports** — run `pycln` or `autoflake` across codebase
2. **Magic numbers** — extract constants:
   - `0.55` (probability threshold) — appears in trading_session.py, entry_gate.py
   - `0.5` (500ms tick throttle) — engine.py
   - `60` (trade cooldown seconds) — trading_session.py
   - `600` (signal age TTL) — trading_session.py
3. **Inconsistent logging** — standardize log message format
4. **Remove commented-out code** blocks
5. **Type hint coverage audit** — identify functions missing annotations

---

## QA Strategy — Every Phase

Each phase follows this sequence:

```
1. Unit tests for extracted/new code
   → pytest path/to/new_module -v
   
2. Architecture validation
   → lint-imports (verify no new layer violations)
   → python -c "import app.main" (verify startup)
   
3. Dual-run comparison (for extractions)
   → 5,000+ ticks, old vs new codepath
   → byte-identical state comparison
   
4. Integration tests
   → Full pipeline test (tick → signal → position → exit)
   → WS viewer: connect, receive state, delta updates
   
5. Regression suite
   → Full test suite: pytest -x tests/
   → Must equal or exceed baseline pass rate (currently 1,440/1,712 = 84.1%)
   
6. Smoke test
   → Start backend, connect frontend, stream data 5 minutes
   → No errors in backend.log
```

---

## Risk Matrix

| Phase | Risk | Impact | Mitigation |
|-------|------|--------|------------|
| 1: Layer inversions | Low | Low | Each change is isolated, easily reversible |
| 2: Dead code removal | Medium | Low | Dual-run validation before deletion |
| 3: God class extraction | High | High | Strangler fig pattern, 10K tick dual-run |
| 4: Position state unification | Critical | Critical | This is money — need 50K tick stress test |
| 5: Event bus cleanup | Low | Low | Dead code, removal has no behavioral impact |
| 6: Entry gate split | Low | Low | Pure functions, trivially testable |
| 7: Engine cleanup | Medium | Medium | Same strangler fig pattern as Phase 3 |
| 8: Final cleanup | Low | Low | Cosmetic only, no behavioral changes |

---

## Phase Ordering Rationale

**Why this order?**

1. **Phase 1 (Layer inversions)** first because they're low risk, fix violations of core principles, and the rest of the cleanup benefits from correct boundaries
2. **Phase 2 (Dead code)** second because it reduces complexity before extraction work begins  
3. **Phase 3 (God class)** third because it's the highest-impact improvement — the code becomes readable and maintainable
4. **Phase 4 (Position state)** fourth because the dual position registry is the source of many subtle bugs
5. **Phases 5-7** in order of risk (lowest first: dead event bus → entry gates → engine)
6. **Phase 8 (Polish)** last because it's cosmetic

**What NOT to do:**
- ❌ Don't do Phase 4 before Phase 3 (the position registry bug is hard to fix in the God class)
- ❌ Don't do Phase 5 before Phase 1 (event bus removal is meaningless while layer inversions exist)
- ❌ Don't merge multiple phases in one PR (each must be independently deployable)
