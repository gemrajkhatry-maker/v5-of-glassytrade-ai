# REFACTORING PLAN — Reduce Complexity
## Post-Deployment Cleanup

---

## CURRENT STATE (Problems)

```
trading_session.py:     1,683 lines, 36 methods, 7 dependencies
llm_entry_handler.py:   1,245 lines, duplicate logic
TOTAL:                  ~2,928 lines in hot path
```

### Key Issues:
1. `_on_tick()` is **318 lines** — handles everything
2. `_execute_unified_entry()` is **152 lines** — too complex
3. Storage calls scattered throughout
4. LLM handler duplicates gate logic

---

## TARGET STATE (After Refactoring)

```
trading_session.py:     ~400 lines (orchestration only)
signal_coordinator.py:  ~300 lines (entry decisions)
position_manager.py:    ~300 lines (exit decisions)
TOTAL:                  ~1,000 lines (56% reduction)
```

---

## REFACTORING STEPS (Non-Breaking)

### Phase 1: Extract SignalCoordinator (2 hours)

Create `app/domain/fabio_ai/services/signal_coordinator.py`:

```python
class SignalCoordinator:
    """Handles entry signal generation and validation."""
    
    def evaluate_entry(self, tick, amt_result, agent_decision, session):
        """Single method for all entry evaluation."""
        # 1. Check basic conditions
        # 2. Run three_align_check
        # 3. Check conviction level
        # 4. Check VWAP
        # 5. Build signal
        # Return: Signal or None
```

Move from `trading_session.py`:
- `_execute_unified_entry()` → `SignalCoordinator.evaluate_entry()`
- `_build_state_snapshot()` → `SignalCoordinator.build_context()`

### Phase 2: Extract PositionManager (2 hours)

Create `app/domain/fabio_ai/services/position_manager.py`:

```python
class PositionManager:
    """Handles all position lifecycle decisions."""
    
    def check_exits(self, position, tick, amt_result):
        """Single method for all exit decisions."""
        # SL check
        # TP check  
        # Trail check
        # Time stop
        # CVD kill signal
        # Return: ExitSignal or None
```

Move from `trading_session.py`:
- `_on_position_closed()` → `PositionManager.handle_close()`
- `check_exits()` → `PositionManager.check_exits()`
- `_on_partial_exit()` → `PositionManager.handle_partial()`

### Phase 3: Extract StorageDecorator (1 hour)

Create `app/infrastructure/decorators/storage_decorator.py`:

```python
class StorageDecorator:
    """Wraps storage calls for clean separation."""
    
    def on_session_start(self, session): ...
    def on_session_end(self, session): ...
    def on_position_change(self, position): ...
    def on_signal_generated(self, signal): ...
```

Remove all `self._storage.save_*` calls from `trading_session.py`.

---

## DEAD CODE TO DELETE

```
backend/app/domain/fabio_ai/services/learning_engine.py     (100 lines)
backend/app/domain/fabio_ai/services/prediction_engine.py   (209 lines) 
backend/app/domain/fabio_ai/services/oi_analyzer.py         (279 lines)
backend/app/domain/fabio_ai/rl/                             (924 lines)
────────────────────────────────────────────────────────────────
TOTAL: ~1,600 lines of dead code
```

---

## IMPLEMENTATION ORDER

1. **Week 1**: Extract `SignalCoordinator` from `trading_session.py`
2. **Week 2**: Extract `PositionManager` from `trading_session.py`
3. **Week 3**: Extract `StorageDecorator`, remove storage calls
4. **Week 4**: Delete dead code, archive pipeline/

---

## SUCCESS METRICS

- `trading_session.py` < 500 lines
- No method > 100 lines
- No file has > 5 direct dependencies
- All storage calls go through one interface
- LLM orchestration in single place

---

*Refactoring should be done AFTER paper trading validates the system works.*
