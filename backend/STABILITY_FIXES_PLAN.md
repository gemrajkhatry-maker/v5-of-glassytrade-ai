# GlassyTrade AI — Stability Engineering Plan

**Date:** 2026-03-23
**Status:** COMPLETE — All 8 issues fixed, 237 tests passing
**Author:** Senior Quant Developer / Market Microstructure Engineer

---

## Executive Summary

This document describes the root cause analysis, implementation plan, and validation of 8 critical stability issues in the GlassyTrade AI Auction Market Theory (AMT) decision engine. All fixes preserve architectural integrity, maintain backward compatibility, and pass comprehensive validation.

---

## Issue #1: Delta Score Instability

### Observed Behavior
Delta score drops from 3 → 2 → 1 within minutes. Score flickers as individual aggression signals toggle on/off each bar.

### Root Cause
`AggressionScorer.score()` is a **stateless** additive calculation. Each bar, the score is recomputed from scratch based on 7 independent binary signals. Any single signal flipping off causes the total to drop immediately. There was no persistence filter.

### Fix
- Created `PersistentAggressionScorer` class wrapping `AggressionScorer`
- Tracks `_confirmed_streak` (consecutive bars at/above MIN_AGGRESSION_SCORE)
- Tracks `_pyramid_streak` (consecutive bars at/above PYRAMID_AGGRESSION_SCORE)
- `confirmed=True` only after `AGGRESSION_PERSISTENCE_BARS` (3) consecutive bars
- Raw score always available for display; persistence filter gates trading signals only

### Files Changed
| File | Change |
|------|--------|
| `app/domain/constants.py` | Added `AGGRESSION_PERSISTENCE_BARS = 3` |
| `app/domain/fabio_ai/services/aggression_scorer.py` | Added `PersistentAggressionScorer` class (lines 155-252) |
| `app/domain/fabio_ai/services/amt_analyzer.py` | Initialize `_persistent_agg_scorer`, use instead of static `AggressionScorer.score()` |

### Why This Works
Persistence filter ensures the score represents **sustained aggression** over multiple bars, not momentary spikes. A single-bar dip doesn't reset the signal.

### Why Alternatives Were Rejected
- **EMA smoother**: Would blur real transitions and introduce lag
- **Hysteresis on individual signals**: Too complex, would require 7 separate state machines
- **Higher threshold**: Would reduce trade frequency without addressing flicker

---

## Issue #2: CVD Slope Instability

### Observed Behavior
CVD slope flips sign rapidly: +33k → +5k → -3k → -7k.

### Root Cause
- `_slope_window = 20` candles — too short for session-leg scale directional commitment
- No sign-persistence filter — slope can flip every bar

### Fix
- Extended default slope window from 20 to 40 candles (`CVD_SLOPE_EXTENDED_WINDOW = 40`)
- Added sign-persistence filter: slope sign must persist for 3 consecutive bars before emitted
- Raw slope always computed; emitted slope changes only after persistence

### Files Changed
| File | Change |
|------|--------|
| `app/domain/constants.py` | Added `CVD_SLOPE_PERSISTENCE_BARS = 3`, `CVD_SLOPE_EXTENDED_WINDOW = 40` |
| `app/domain/fabio_ai/services/cvd_tracker.py` | Extended default window, added `_slope_sign_history`, persistence logic in `_compute_slope()` |

### Why This Works
40-candle window smooths noise while maintaining responsiveness. Sign persistence prevents rapid flipping caused by single-bar CVD reversals.

---

## Issue #3: PROBING + Range Mode Contradiction

### Observed Behavior
Market State = PROBING (testing outside value) AND Session Mode = RANGE (rotation inside value). Logically impossible.

### Root Cause
`MarketState` (4-state from `market_state_engine.py`) and `MarketStructure` (5-state from `market_structure_classifier.py`) are **independent systems** with no cross-validation. Price can be outside VA (PROBING) while structure classifier sees tight range/overlap (BALANCE).

### Fix
Added cross-validation in `AMTAnalyzer.analyze()` after both are computed:
```python
if market_state == MarketState.PROBING and structure.state == "BALANCE":
    structure = MarketStructure(state="TRANSITION", ...)
```

### Files Changed
| File | Change |
|------|--------|
| `app/domain/fabio_ai/services/amt_analyzer.py` | Added cross-validation block (lines ~1586-1594) |

### Why This Works
If price is testing outside value (PROBING), the structure cannot be BALANCE — it's TRANSITION by definition. This aligns the two classification systems.

### Why Alternatives Were Rejected
- **Merging the two systems**: Violates separation of concerns
- **Making PROBING override to EXPANSION**: Too aggressive — PROBING is unconfirmed

---

## Issue #4: Missing Playbook for PROBING + BALANCED

### Observed Behavior
"No canonical playbook" when market state is PROBING. This is a critical AMT state that should support both acceptance and rejection scenarios.

### Root Cause
- `_generate_signal()` returned `None` unconditionally for PROBING
- GATE 4 in gate pipeline blocked PROBING unconditionally
- No acceptance/rejection logic existed

### Fix
**GATE 4**: Changed from unconditional block to conditional pass (requires `aggression_score >= 3.0`)

**PROBING Playbook** in `_generate_signal()`:
- **Scenario A — Acceptance**: Aggression confirms break direction → continuation trade
- **Scenario B — Rejection**: Opposing aggression → fade back into value
- Both scenarios require `has_aggression=True` (persistence-filtered)

Added `aggression_direction` parameter to `_generate_signal()` to distinguish bullish/bearish.

### Files Changed
| File | Change |
|------|--------|
| `app/domain/fabio_ai/services/gate_pipeline.py` | GATE 4 conditional pass (lines 164-175) |
| `app/domain/fabio_ai/services/amt_analyzer.py` | PROBING playbook (lines ~1817-1871), `aggression_direction` parameter |

### Why This Works
PROBING is an unconfirmed break. With HIGH aggression confirming direction, it becomes a valid entry. With opposing aggression, the fade back into value is a mean-reversion opportunity.

---

## Issue #5: LVN Instability

### Observed Behavior
LVNs appearing and disappearing between bars.

### Root Cause
LVNs recomputed from volume profile each bar via `find_lvns()`. Small changes in smoothed histogram cause local minima to appear/disappear. No persistence mechanism.

### Fix
Created `LVNPersistenceTracker` class:
1. New LVNs enter as **candidates** with a birth bar index
2. Only **emitted** after surviving `LVN_MIN_PERSISTENCE_BARS` (3) consecutive bars
3. Once emitted, persists until volume at that level rises above `LVN_REMOVAL_THRESHOLD` (30% of mean)
4. Reset at session boundaries

### Files Changed
| File | Change |
|------|--------|
| `app/domain/constants.py` | Added `LVN_MIN_PERSISTENCE_BARS = 3`, `LVN_REMOVAL_THRESHOLD = 0.30` |
| `app/domain/fabio_ai/services/amt_analyzer.py` | Added `LVNPersistenceTracker` class (lines ~377-467), integrated in `analyze()` |

### Why This Works
Persistence filter ensures LVNs represent genuine structural gaps, not noise. Once formed, they remain stable unless the profile structure truly changes.

---

## Issue #6: Structure Label Instability

### Observed Behavior
BALANCE → CHOP → BALANCE flip-flopping.

### Root Cause
`MarketStructureClassifier` had `_DWELL_TICKS = 1` and `_COOLDOWN_TICKS = 1` — effectively no hysteresis. BALANCE and CHOP score similarly on overlapping features (high overlap, low VWAP slope), causing rapid alternation.

### Fix
Increased hysteresis parameters:
- `_DWELL_TICKS`: 1 → 3 (new state must persist 3 consecutive ticks)
- `_COOLDOWN_TICKS`: 1 → 3 (3-tick hold after state change)
- `_CONFIDENCE_GATE`: 60 (unchanged)
- `_BYPASS_CONFIDENCE`: 65 → 70 (higher bar for skipping TRANSITION buffer)

### Files Changed
| File | Change |
|------|--------|
| `app/domain/constants.py` | Added `STRUCTURE_DWELL_TICKS = 3`, `STRUCTURE_COOLDOWN_TICKS = 3`, `STRUCTURE_CONFIDENCE_GATE = 60`, `STRUCTURE_BYPASS_CONFIDENCE = 70` |
| `app/domain/fabio_ai/services/market_structure_classifier.py` | Updated constants import, replaced hardcoded values |

### Why This Works
Meaningful dwell/cooldown prevents noise-driven flipping while still allowing legitimate regime changes within ~3 bars.

---

## Issue #7: Footprint Delta vs Delta Score Mismatch

### Observed Behavior
Footprint shows strong positive delta, Panel shows Delta Score = 1.

### Root Cause
- Footprint delta: computed from tick-level buy/sell classification (tick rule)
- Aggression score: computed from candle-level multi-signal additive scoring
- `footprint_confirmed` signal used `len(agg_prints) >= 2` (aggressive volume prints) as proxy — completely different data path

### Fix
Changed `footprint_confirmed` to require **both** conditions:
```python
has_agg_prints = len(agg_prints) >= 2
has_strong_delta = abs(norm_delta) > 0.30
footprint_confirmed = has_agg_prints and has_strong_delta
```

The normalized delta check (`|delta/volume| > 0.30`) aligns the aggression signal with the directional bias shown in the footprint.

### Files Changed
| File | Change |
|------|--------|
| `app/domain/fabio_ai/services/amt_analyzer.py` | Updated `footprint_confirmed` calculation (lines ~1439-1442) |

---

## Issue #8: Decision History Too Short

### Observed Behavior
Only 10–20 entries in decision history.

### Root Cause
- `SignalTrackingService.get_recent_decisions()` had `limit=50` (in-memory only)
- API endpoint `/history` only queried `llm_decisions` table (LLM decisions only)
- Signal decisions (GENERATED/BLOCKED/WAITING/COOLDOWN) stored via `save_position_event()` but never queried back

### Fix
- Extended `get_recent_decisions()` default limit from 50 to 1000
- Added `query_signal_decisions()` method to database adapter
- Updated `/history` API endpoint to return both `decisions` (LLM) and `signal_decisions`

### Files Changed
| File | Change |
|------|--------|
| `app/domain/constants.py` | Added `DECISION_HISTORY_LIMIT = 1000` |
| `app/application/services/signal_tracking_service.py` | Extended default limit to 1000 |
| `app/infrastructure/storage/database.py` | Added `query_signal_decisions()` method |
| `app/api/routers/ai.py` | Extended `/history` endpoint to return both decision types |

---

## Validation

### Test Results
```
237 passed, 0 failed in 0.52s
```

### Test Coverage
| Fix | Tests |
|-----|-------|
| #1 Delta Score Persistence | 3 tests: persistence, streak reset, raw score availability |
| #2 CVD Slope Persistence | 2 tests: sign persistence, session reset |
| #3 PROBING+Range | 2 tests: override to TRANSITION, preserve BALANCE when valid |
| #4 PROBING Playbook | 5 tests: gate blocking/allowing, acceptance/rejection signals |
| #5 LVN Stability | 3 tests: persistence requirement, survival, removal on volume rise |
| #6 Structure Hysteresis | 1 test: parameter verification |
| #7 Footprint Alignment | 1 test: dual-condition requirement |
| #8 Decision History | 2 tests: extended limit, limit respect |

### Regression Tests
All existing tests pass:
- `test_aggression_scorer.py` — 18 tests
- `test_market_state_engine.py` — 10 tests
- `test_gate_pipeline.py` — 18 tests
- `test_amt_analyzer.py` — updated valid structures
- `test_market_structure_classifier.py` — updated hysteresis test
- `test_orderflow_detectors.py` — updated absorption tests
- `test_entry_gate.py` — 34 tests
- `test_drive_tracker.py` — 14 tests

---

## Architecture Impact

- **No breaking changes**: All existing interfaces preserved
- **New classes**: `PersistentAggressionScorer`, `LVNPersistenceTracker` — internal to AMTAnalyzer
- **Backward compatible**: GATE 4 default behavior (aggression=0) still blocks PROBING
- **No schema changes**: Database methods are additive

---

## Remaining Risks

| Risk | Mitigation |
|------|-----------|
| CVD slope lag (40-candle window) | Acceptable — prioritizes directional commitment over responsiveness |
| LVN staleness during news events | Conservative removal threshold (30% of mean) prevents premature removal |
| PROBING aggression threshold (3.0) | Intentionally high to prevent false entries during unconfirmed breaks |
| Decimal/float type mismatches (~100 LSP warnings) | Pre-existing — separate type-safety refactor needed |

---

## Constants Reference

| Constant | Value | Purpose |
|----------|-------|---------|
| `AGGRESSION_PERSISTENCE_BARS` | 3 | Bars required for aggression confirmation |
| `CVD_SLOPE_PERSISTENCE_BARS` | 3 | Bars for CVD slope sign stability |
| `CVD_SLOPE_EXTENDED_WINDOW` | 40 | Candles for session-leg slope |
| `LVN_MIN_PERSISTENCE_BARS` | 3 | Bars before LVN is emitted |
| `LVN_REMOVAL_THRESHOLD` | 0.30 | Volume ratio for LVN removal |
| `STRUCTURE_DWELL_TICKS` | 3 | State persistence requirement |
| `STRUCTURE_COOLDOWN_TICKS` | 3 | Hold after state change |
| `STRUCTURE_CONFIDENCE_GATE` | 60 | Min confidence for state change |
| `STRUCTURE_BYPASS_CONFIDENCE` | 70 | Confidence to skip TRANSITION buffer |
| `DECISION_HISTORY_LIMIT` | 1000 | Max decisions returned from API |
