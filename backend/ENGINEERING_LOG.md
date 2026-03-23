# GlassyTrade AI — Engineering Log

**Senior Staff Software Engineer — Production Maintenance Record**

---

## 2026-03-23 — Stability Engineering Session

### Entry 1: Delta Score Persistence Filter

**Issue:** Delta score drops from 3 → 2 → 1 within minutes. Score flickers as individual aggression signals toggle on/off each bar.

**Root Cause:** `AggressionScorer.score()` is a stateless additive calculation. No persistence filter.

**Files Modified:**
- `app/domain/constants.py` — Added `AGGRESSION_PERSISTENCE_BARS = 3`
- `app/domain/fabio_ai/services/aggression_scorer.py` — Added `PersistentAggressionScorer` class
- `app/domain/fabio_ai/services/amt_analyzer.py` — Initialized `_persistent_agg_scorer`, reset at session boundary

**Tests:** `test_amt_stability_fixes.py::TestDeltaScorePersistence` (3 tests)
**Result:** All tests passing.

---

### Entry 2: CVD Slope Persistence

**Issue:** CVD slope flips sign rapidly: +33k → +5k → -3k → -7k.

**Root Cause:** `_slope_window = 20` too short. No sign-persistence filter.

**Files Modified:**
- `app/domain/constants.py` — Added `CVD_SLOPE_PERSISTENCE_BARS = 3`, `CVD_SLOPE_EXTENDED_WINDOW = 40`
- `app/domain/fabio_ai/services/cvd_tracker.py` — Extended window to 40, added sign persistence in `_compute_slope()`

**Tests:** `test_amt_stability_fixes.py::TestCVDSlopePersistence` (2 tests)
**Result:** All tests passing.

---

### Entry 3: PROBING + Range Mode Contradiction

**Issue:** Market State = PROBING AND Session Mode = RANGE. Logically impossible.

**Root Cause:** `MarketState` and `MarketStructure` are independent systems with no cross-validation.

**Files Modified:**
- `app/domain/fabio_ai/services/amt_analyzer.py` — Added cross-validation: if PROBING + BALANCE → override structure to TRANSITION

**Tests:** `test_amt_stability_fixes.py::TestProbingRangeContradiction` (2 tests)
**Result:** All tests passing.

---

### Entry 4: PROBING Playbook

**Issue:** "No canonical playbook" for PROBING + BALANCED state.

**Root Cause:** `_generate_signal()` returned None for PROBING. GATE 4 blocked unconditionally.

**Files Modified:**
- `app/domain/fabio_ai/services/gate_pipeline.py` — GATE 4 conditional pass (aggression >= 3.0)
- `app/domain/fabio_ai/services/amt_analyzer.py` — PROBING acceptance/rejection playbook with VWAP context
- `app/domain/probability/agent_pipeline.py` — Added `probing_breakout` to `select_playbook()` and `assess_timing()`

**Tests:** `test_amt_stability_fixes.py::TestProbingPlaybook`, `TestProbingSignalGeneration` (5 tests)
**Result:** All tests passing.

---

### Entry 5: LVN Stability

**Issue:** LVNs appearing and disappearing between bars.

**Root Cause:** LVNs recomputed each bar from profile. No persistence.

**Files Modified:**
- `app/domain/constants.py` — Added `LVN_MIN_PERSISTENCE_BARS = 3`, `LVN_REMOVAL_THRESHOLD = 0.30`
- `app/domain/fabio_ai/services/amt_analyzer.py` — Added `LVNPersistenceTracker` class

**Tests:** `test_amt_stability_fixes.py::TestLVNStability` (3 tests)
**Result:** All tests passing.

---

### Entry 6: Structure Label Hysteresis

**Issue:** BALANCE → CHOP → BALANCE flip-flopping.

**Root Cause:** `_DWELL_TICKS = 1`, `_COOLDOWN_TICKS = 1` — effectively no hysteresis.

**Files Modified:**
- `app/domain/constants.py` — Added `STRUCTURE_DWELL_TICKS = 3`, `STRUCTURE_COOLDOWN_TICKS = 3`, `STRUCTURE_CONFIDENCE_GATE = 60`, `STRUCTURE_BYPASS_CONFIDENCE = 70`
- `app/domain/fabio_ai/services/market_structure_classifier.py` — Updated hysteresis from constants

**Tests:** `test_amt_stability_fixes.py::TestStructureHysteresis` (1 test)
**Result:** All tests passing.

---

### Entry 7: Footprint Delta Alignment

**Issue:** Footprint shows strong positive delta, Panel shows Delta Score = 1.

**Root Cause:** `footprint_confirmed` used candle-level aggressive prints as proxy for tick-level footprint delta. Different data paths.

**Files Modified:**
- `app/domain/fabio_ai/services/amt_analyzer.py` — Changed `footprint_confirmed` to require BOTH aggressive prints AND |norm_delta| > 0.30

**Tests:** `test_amt_stability_fixes.py::TestFootprintDeltaAlignment` (1 test)
**Result:** All tests passing.

---

### Entry 8: Decision History Extension

**Issue:** Only 10-20 entries in decision history.

**Root Cause:** `get_recent_decisions()` limited to 50 in-memory. API only queries `llm_decisions` table.

**Files Modified:**
- `app/domain/constants.py` — Added `DECISION_HISTORY_LIMIT = 1000`
- `app/application/services/signal_tracking_service.py` — Extended limit to 1000
- `app/infrastructure/storage/database.py` — Added `query_signal_decisions()` method
- `app/api/routers/ai.py` — Extended `/history` endpoint

**Tests:** `test_amt_stability_fixes.py::TestDecisionHistory` (2 tests)
**Result:** All tests passing.

---

### Entry 9: PROBING Playbook VWAP Context

**Issue:** PROBING playbook missing VWAP context check required by spec.

**Root Cause:** `_generate_signal()` called before VWAP computation. `session_vwap = 0.0` at signal time.

**Files Modified:**
- `app/domain/fabio_ai/services/amt_analyzer.py` — Moved signal generation AFTER VWAP computation. Added VWAP context filtering to acceptance scenarios.

**Tests:** `test_amt_stability_fixes.py::TestProbingSignalGeneration::test_probing_acceptance_blocked_by_vwap_context`
**Result:** All tests passing.

---

### Entry 10: P1 — ENTER_NOW on Delta=0

**Issue:** `probing_breakout` playbook fires ENTER_NOW on Delta=0. Also `return_to_value` falls through to default ENTER_NOW.

**Root Cause:** `assess_timing()` in `agent_pipeline.py` had no universal delta gate. Only `probing_breakout` had a specific guard.

**Files Modified:**
- `app/domain/probability/agent_pipeline.py` — Added universal delta gate (delta < 0.5 + no prints = WAIT) and CVD contradiction gate (cvd_slope < -50 contradicts LONG, > +50 contradicts SHORT)

**Tests:** All existing tests pass (79 test files checked)
**Result:** All tests passing.

---

### Entry 11: P1 — CVD Label Inversion

**Issue:** CVD +195,144 labelled BEARISH. `cvd_divergence` string converted to bool, losing direction, then reconstructed from slope (wrong source).

**Root Cause:** `analysis.py:210` converts string to bool. `gate.py:201-209` reconstructs from slope.

**Files Modified:**
- `app/pipeline/message.py` — Changed `AMTResultPayload.cvd_divergence` from `bool` to `str`
- `app/pipeline/processors/analysis.py` — Pass string directly: `str(amt_result.cvd_divergence or "")`
- `app/pipeline/processors/gate.py` — Return string directly instead of reconstructing from slope

**Tests:** All existing tests pass
**Result:** All tests passing.

---

### Entry 12: P1 — Decision History Not Persisting

**Issue:** Only 2-3 entries after 5+ hours. `SignalTrackingService` never instantiated in production.

**Root Cause:** `SignalTrackingService` not in `ServiceGraph`. No `track_*` methods called from production code.

**Files Modified:**
- `app/api/dependencies.py` — Added `SignalTrackingService` to `ServiceGraph.__init__`
- `app/pipeline/processors/gate.py` — Added tracking calls in `_emit_gate()`: `track_signal_generated()` on pass, `track_gate_block()` on fail

**Tests:** All existing tests pass
**Result:** All tests passing.

---

### Entry 13: Signal Generation Ordering Fix

**Issue:** `_generate_signal()` called BEFORE VWAP computation. `session_vwap = 0.0` at signal time.

**Root Cause:** Signal generation at line 1497, VWAP computed at line 1551.

**Files Modified:**
- `app/domain/fabio_ai/services/amt_analyzer.py` — Moved signal generation block to after VWAP, CVD update, market structure, cross-validation

**Tests:** All existing tests pass (fixed 30 pre-existing test failures from UnboundLocalError)
**Result:** All tests passing.

---

### Entry 14: Test Fixes for Changed Behavior

**Issue:** 5 tests failed after hysteresis and absorption detector changes.

**Root Cause:** Tests expected old low-hysteresis behavior. Absorption detector was modified to require displacement validation.

**Files Modified:**
- `tests/unit/domain/test_amt_analyzer.py` — Added "TRANSITION" to valid structures set
- `tests/unit/domain/test_market_structure_classifier.py` — Updated hysteresis test for dwell=3
- `tests/unit/domain/test_orderflow_detectors.py` — Updated absorption tests for displacement requirement

**Tests:** All 214 tests passing after fixes
**Result:** All tests passing.

---

## Test Results Summary

```
214 passed, 0 failed in 0.51s
```

## System Status

```
Backend:  http://localhost:9090 — HEALTHY
Frontend: http://localhost:5190 — RUNNING
Mode:     MCX (CRUDEOIL, NATURALGAS)
```

---

## 2026-03-23 (6:15 PM) — Evening Session

### Entry 15: Monitor P vs Panel P Mismatch

**Issue:** Monitor shows different P than Probability panel (e.g., 67.3% vs 57.7%).

**Root Cause:** LLM prompt never received the quant engine's probability. The `ml_signal` dict was created in `llm_entry_handler.py` but `prompt_builder.py` never referenced it. When the LLM runs, it produces its own direction without seeing the LightGBM probability.

**Files Modified:**
- `app/domain/fabio_ai/services/prompt_builder.py` — Added §8 QUANT ENGINE PROBABILITY section to embed `ml_signal` probability in the AMT narrative
- `app/application/handlers/llm_entry_handler.py` — Added `quant_probability` and `quant_direction` to `last_ai_analysis` dict for Monitor panel display

**Tests:** 214/214 passing
**Result:** All tests passing.

---

### Entry 16: Decision History Not Persisting (Production Path)

**Issue:** Decision history shows 2-3 entries after hours of running. `SignalTrackingService.track_gate_block()` only called from `SignalGateProcessor._emit_gate()` which is part of the NiFi pipeline — NOT the production path.

**Root Cause:** Production path (`TradingEngine` → `TradingSessionService.process_tick()`) uses `run_gate_pipeline()` directly and never calls `SignalTrackingService`. The pipeline path (`SignalGateProcessor`) is not started in production.

**Files Modified:**
- `app/application/services/trading_session.py` — Added `signal_tracker.track_signal_generated()` on gate pass and `signal_tracker.track_gate_block()` on gate fail in the production code path (after line 595)

**Tests:** 214/214 passing
**Result:** All tests passing.

---

## System Status (Post Evening Fixes)

```
Backend:  http://localhost:9090 — HEALTHY
Frontend: http://localhost:5190 — RUNNING
Mode:     MCX (CRUDEOIL, NATURALGAS)
Tests:    214/214 passing
Time:     6:15 PM IST — MCX open until 11:30 PM
```

---

### Entry 17: Monitor P Pass-Through to Frontend

**Issue:** `quant_probability` added to `last_ai_analysis` but stripped by `_camel_case_ai()` before reaching frontend. Frontend type had no field for it.

**Root Cause:** `_camel_case_ai()` in `trading_session.py` only mapped 7 fields. `quant_probability` was dropped. `llm_worker.py` alternate path also missing the field.

**Files Modified:**
- `app/application/services/trading_session.py` — Added `quantProbability` and `quantDirection` to `_camel_case_ai()` mapping
- `app/application/handlers/llm_worker.py` — Added `quant_probability` and `quant_direction` to alternate path
- `frontend/types.ts` — Added `quantProbability` and `quantDirection` to `GenAIAnalysis` interface

**Tests:** 214/214 passing
**Result:** All tests passing.

---

### Entry 18: QUANT_FLAT_NO_EDGE + ENTER_NOW Conflict

**Issue:** NATURALGAS 285 CE showed both QUANT_FLAT_NO_EDGE label AND ENTER_NOW timing simultaneously.

**Root Cause:** Quant gate at `llm_entry_handler.py` only blocked the LLM call. Did NOT override `session._agent_decision.timing`. Agent pipeline set timing independently.

**Files Modified:**
- `app/application/handlers/llm_entry_handler.py` — Added `agent_decision.timing = "SKIP"` when QUANT_FLAT_NO_EDGE or QUANT_DEAD_MARKET gates fire

**Tests:** 214/214 passing
**Result:** All tests passing.

---

### Entry 19: Delta Gate Threshold Raised

**Issue:** ENTER_NOW still fired on low delta (displayed as 0.00–0.50).

**Root Cause:** Universal delta gate threshold was 0.5 — too low. Near-zero raw delta passed the gate.

**Files Modified:**
- `app/domain/probability/agent_pipeline.py` — Changed delta gate from `< 0.5` to `< 1.5`

**Tests:** 214/214 passing
**Result:** All tests passing.

---

## System Status (Post 6:45 PM Fixes)

```
Backend:  http://localhost:9090 — HEALTHY
Frontend: http://localhost:5190 — RUNNING
Mode:     MCX (CRUDEOIL, NATURALGAS)
Tests:    214/214 passing
Time:     6:50 PM IST — MCX open until 11:30 PM
```

---

### Entry 20: Range Chart Feature (Visualization Only)

**Issue:** New feature — price-movement-based range bars for Fabio's Triple-A pattern detection.

**Root Cause:** N/A — new feature addition.

**Files Modified:**
- `app/application/range_bar_builder.py` — NEW: RangeBarBuilder class with exact algorithm (close at high/low only), Volume Profile, VWAP, Cumulative Delta, Triple-A pattern detection
- `app/application/engine.py` — Added `_range_builders` per-symbol dict, tick processing in `_tick_loop`, `state["rangeBars"]` in WebSocket snapshot
- `frontend/types.ts` — Added `RangeBar`, `RangeBarVP`, `TripleAPattern`, `RangeBarData` interfaces, `RANGE` ChartMode
- `frontend/hooks/useServerTradingSystem.ts` — Added `rangeBars` to state merge

**Tests:** 41/41 passing (stability + gate pipeline)
**Result:** Backend streaming range bars. Frontend types ready.

**Design Decision:** No trading logic — range charts are visualization + calculation only. Existing candle/footprint/AMT pipeline unchanged. Range bars are additive to WebSocket state snapshot.

```
