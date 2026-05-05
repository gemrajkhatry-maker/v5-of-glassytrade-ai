# Trading Session Shotgun Surgery Analysis

## Status: ✅ ARCHITECTURE REFACTORED

**Note:** This file documents the *previous* shotgun surgery pattern. The `trading_session.py` has been decomposed into focused services.

**Current Structure:**
- `trading_session.py` (863 lines) — thin coordinator, delegates to 18+ services
- `trading_session/` directory — focused modules

---

## Shotgun Surgery Pattern Analysis

### Pattern 1: Position Lifecycle Changes Require Multiple Edits

**Scenario:** Adding a new position lifecycle field (e.g., `trailing_amount`)

**Files Requiring Changes:**
1. `trading_session.py:601` - `_run_amt_analysis` (uses position state)
2. `trading_session.py:695` - `_resolve_entry_decision` (reads position fields)
3. `trading_session.py:1005` - `_execute_signal` (modifies positions)
4. `trading_session.py:1071` - `_build_state_snapshot` (serializes state)
5. `entities.py:Position` (entity definition)
6. `schemas.py` (DTO serialization)
7. `types.ts` (frontend types)

**Evidence:**
```python
# trading_session.py:695 - _resolve_entry_decision reads position fields
side=pos.side.value if hasattr(pos.side, "value") else str(pos.side),
# trading_session.py:1005 - _execute_signal modifies positions  
session.portfolio.close_position(pos.id, price, "SESSION_CLOSE")
# trading_session.py:1071 - _build_state_snapshot serializes
state["amt"] = serialize_amt(session.last_amt) if session.last_amt else None
```

---

### Pattern 2: AMT Analysis Changes Span Multiple Methods

**Scenario:** Adding new AMT metric (e.g., `liquidity_score`)

**Files Requiring Changes:**
1. `trading_session.py:601` - `_run_amt_analysis` (computes AMT)
2. `trading_session.py:747` - `_on_tick` (dispatches AMT result)
3. `trading_session.py:1071` - `_build_state_snapshot` (includes in state)
4. `event_store.py` (event schema if persisted)
5. `schemas.py` (DTO)
6. `types.ts` (frontend interface)

**Evidence:**
```python
# trading_session.py:601
def _run_amt_analysis(self, event: TickReceived, session, prior, cache: SessionCache) -> object:
    # Computes AMT - if new field added, must update here

# trading_session.py:747  
def _on_tick(self, event: TickReceived) -> None:
    # Dispatches result from _run_amt_analysis
    
# trading_session.py:1071
def _build_state_snapshot(self, session: SessionState) -> dict:
    # Serializes session.last_amt to state
```

---

### Pattern 3: Risk Management Changes Touched Across Layers

**Scenario:** Adding new risk check (e.g., `max_daily_drawdown_pct`)

**Files Requiring Changes:**
1. `trading_session.py:474` - `_session_phase_check`
2. `trading_session.py:601` - `_run_amt_analysis`
3. `session_risk_coordinator.py` - risk coordination
4. `domain/services/session_phase_gate.py` - phase gates
5. `entities.py:Position` - position validation
6. `schemas.py` - DTO updates
7. `types.ts` - frontend display

---

## Shotgun Surgery Matrix

| Change Type | trading_session.py | entities.py | schemas.py | types.ts | Other Files |
|------------|-------------------|-------------|------------|----------|-------------|
| New position field | 3 methods | ✓ | ✓ | ✓ | state_builder.py |
| AMT metric | 3 methods | - | ✓ | ✓ | amt_coordinator.py |
| Risk parameter | 2 methods | - | ✓ | ✓ | risk_sizing_engine.py |
| Signal attribute | 2 methods | ✓ | ✓ | ✓ | signal_coordinator.py |
| Session phase logic | 2 methods | - | ✓ | ✓ | phase_manager.py |

---

## Root Cause Analysis

### Violation: Single Responsibility Principle
```python
# One file doing 6+ things:
class TradingSession:  # 1,079 lines
    def process_tick(...)          # 1. Orchestration
    def _session_phase_check(...)  # 2. Session lifecycle
    def _run_amt_analysis(...)     # 3. AMT analysis
    def _resolve_entry_decision(...) # 4. Signal resolution
    def _on_tick(...)              # 5. Event handling
    def _execute_signal(...)       # 6. Execution
    def _build_state_snapshot(...) # 7. Presentation
```

### Violation: Feature Envy
Methods reach across too many concerns, creating coupling.

---

## Refactoring Recommendation

### Split trading_session.py into focused services:

```
trading_session.py (1,079 lines) →
├── session_orchestrator.py (200 lines)
│   - process_tick()
│   - _on_tick()
│   
├── amt_service.py (250 lines)
│   - _run_amt_analysis()
│   - AMT result handling
│
├── position_service.py (200 lines)
│   - _resolve_entry_decision()
│   - _execute_signal()
│   - _on_trade_closed()
│
├── phase_manager.py (180 lines)
│   - _session_phase_check()
│   - halt_trading(), resume_trading()
│
└── state_builder.py (150 lines)
    - _build_state_snapshot()
    - state serialization
```

### Benefits:
1. **Single Responsibility:** Each file has one reason to change
2. **Reduced Coupling:** Position changes only affect position_service.py
3. **Easier Testing:** Each service can be unit tested independently
4. **Clear Ownership:** Developer knows exactly where to make changes
