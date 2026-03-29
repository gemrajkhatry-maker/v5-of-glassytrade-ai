# SOLID Refactoring Plan — Zero-Regression Approach

## Strategy: Extract → Test → Delete

Every refactoring follows this cycle:
1. **Extract** code to new service file (pure copy + import wrapper)
2. **Test** the extracted service independently
3. **Redirect** original code to use extracted service
4. **Delete** the original inline code
5. **Verify** full test suite passes

This ensures ZERO regressions — the original code is never modified until the replacement is proven working.

---

## Phase 1: Extract from amt_analyzer.py (1,279 → ≤200 lines)

### What's Still Inline (9 services to extract)

| # | Block | Lines | Target File |
|---|-------|-------|-------------|
| 1 | `IncrementalVolumeProfile` (class) | 144-310 (~166 lines) | `volume_profile.py` (already exists) |
| 2 | `find_lvns` + `LVNPersistenceTracker` (class) | 311-458 (~148 lines) | `lvn_detector.py` (already exists) |
| 3 | `find_hvns` | 460-490 (~31 lines) | `lvn_detector.py` (already exists) |
| 4 | `detect_displacement_leg` | 555-672 (~118 lines) | `displacement_detector.py` (NEW) |
| 5 | `detect_displacement` | 673-722 (~50 lines) | `displacement_detector.py` (NEW) |
| 6 | `detect_acceptance` | 723-739 (~17 lines) | `displacement_detector.py` (NEW) |
| 7 | `_generate_signal` | 1017-1195 (~179 lines) | `signal_generator.py` (NEW) |
| 8 | `compute_observation` | 1201-1279 (~79 lines) | `rl_observation.py` (NEW) |
| 9 | VWAP computation (inline) | 727-774 (~48 lines) | `vwap_tracker.py` (NEW) |

### Execution Order
1. Extract `displacement_detector.py` (185 lines) — self-contained, no dependencies
2. Extract `signal_generator.py` (179 lines) — depends on AMTConfig only
3. Extract `rl_observation.py` (79 lines) — pure data transformation
4. Extract `vwap_tracker.py` (48 lines) — simple accumulator
5. Redirect `IncrementalVolumeProfile` → `volume_profile.py` (already exists)
6. Redirect `find_lvns`/`find_hvns`/`LVNPersistenceTracker` → `lvn_detector.py` (already exists)
7. Delete all inline code
8. Final amt_analyzer.py ≈ 200 lines (analyze() orchestrator only)

---

## Phase 2: Extract from trading_session.py (1,191 → ≤200 lines)

### What's Still Inline (5 modules to extract)

| # | Block | Lines | Target File |
|---|-------|-------|-------------|
| 1 | Phase 5 force-exit + profile saving | 477-586 (~110 lines) | `session_phase_enforcer.py` (NEW) |
| 2 | Agent pipeline + probability features | 710-770 (~61 lines) | `agent_pipeline_runner.py` (NEW) |
| 3 | Entry decision + gate pipeline | 802-1059 (~258 lines) | `entry_orchestrator.py` (NEW) |
| 4 | Overseer coordination | 906-930 (~25 lines) | `overseer_coordinator.py` (NEW) |
| 5 | Signal execution + tracker | 1060-1140 (~81 lines) | `signal_executor.py` (NEW) |

### Execution Order
1. Extract `session_phase_enforcer.py` — self-contained, no state mutation
2. Extract `agent_pipeline_runner.py` — pure function, inputs → outputs
3. Extract `entry_orchestrator.py` — gate pipeline + decision logic
4. Extract `signal_executor.py` — signal build + execution
5. Extract `overseer_coordinator.py` — LLM coordination
6. Redirect trading_session.py to use extracted modules
7. Final trading_session.py ≈ 200 lines (wiring + thin orchestrator)

---

## Phase 3: Extract from engine.py (852 → ≤200 lines)

### What's Still Inline (3 modules to extract)

| # | Block | Lines | Target File |
|---|-------|-------|-------------|
| 1 | `_recover_open_positions` | 323-452 (~130 lines) | `position_recovery.py` (NEW) |
| 2 | Range bar building | 705-852 (~148 lines) | `range_bar_builder.py` (already exists — redirect) |
| 3 | Viewer notification | 788-804 (~17 lines) | `viewer_notifier.py` (NEW) |

### Execution Order
1. Extract `position_recovery.py` — self-contained DB logic
2. Redirect range bar → `range_bar_builder.py` (already exists)
3. Extract `viewer_notifier.py` — simple notification logic
4. Final engine.py ≈ 350 lines (tick loop + wiring)

---

## Phase 4: Fix SOLID Violations

### 4a. Open/Closed — Add `@abstractmethod` to `BrokerPort.execute_order()`

**File:** `backend/app/domain/ports/broker.py:14`
```python
# BEFORE
def execute_order(...):

# AFTER  
@abstractmethod
def execute_order(...):
```

### 4b. Dependency Inversion — Remove `settings` from adapters

**Files:**
- `backend/app/infrastructure/adapters/dhan_broker_adapter.py:40,149`
- `backend/app/infrastructure/adapters/mlx_inference_adapter.py:5`

**Fix:** Inject config via constructor instead of importing `settings` directly.

### 4c. Interface Segregation — Split `MarketDataPort`

**Split into:**
- `HistoricalDataPort` — `fetch_history`, `fetch_order_book`, `scan_candidates`
- `StreamingPort` — `stream_full`, `stream_depth_20`, `get_ltp`
- `OptionsPort` — `get_option_chain`

Consumers depend only on the ports they need.

---

## Safety Rules

1. **Never modify existing code** until new service is extracted and tested
2. **Run full test suite** after each extraction (1,089 tests must pass)
3. **Use backward-compatible wrappers** — keep original function signatures
4. **No changes to public API** — only internal code moves
5. **One file at a time** — never extract multiple files simultaneously
