# Backend Code Audit — Complete Findings & Action Plan

**Date:** 2026-08-06  
**Branch:** stable_4  
**Scope:** Valentini Triple-A Strategy Implementation — Calculations, Data Pipeline, Architecture  
**Reference:** `amt_docs/Valentini_Scalper_Build_Guide_Layout.txt`

---

## Fix Status (Updated 2026-08-06)

### ✅ Fixed in Current Branch

| # | Fix | File | Commit |
|---|-----|------|--------|
| 1 | VP double-counting removed | `range_bar_builder.py:243-257` | ✅ |
| 2 | VWAP bands volume-weighted std | `amt_analyzer.py:684-708` | ✅ |
| 3 | VWAP std proportional clamp (0.1% floor, 3% cap) | `amt_analyzer.py:697-708` | ✅ |
| 4 | Persistent Triple-A state machine | `range_bar_builder.py:394-519` | ✅ |
| 5 | VWAP breakout detector | `vwap_breakout.py` (new) | ✅ |
| 6 | VWAP bands value object | `vwap_bands.py` (new) | ✅ |
| 7 | ATR True Range calculation | `amt_analyzer.py:483-500` | ✅ |
| 8 | Lee-Ready delta enabled | `engine.py:189-193` | ✅ |
| 9 | Volume spike cap clamps (not zero) | `candle_aggregator.py:172` | ✅ |
| 10 | Tests: volume profile, VWAP bands, VWAP breakout | `tests/unit/domain/` | ✅ |

### ❌ Remaining (Non-Critical)

| # | Issue | Priority | Effort |
|---|-------|----------|--------|
| 1 | AbsorptionValidator not wired into GatePipeline | P1 | 3 hr |
| 2 | Dynamic position sizing not connected | P1 | 1 hr |
| 3 | Dual VWAP state (VWAPService + AMTAnalyzer) | P2 | 2 hr |
| 4 | Dead code removal (RL, MLX, etc.) | P2 | 2 hr |
| 5 | Prior session POC/VAL persistence | P2 | 2 hr |
| 6 | Gate pipeline simplification (12 → 5 gates) | P2 | 2 hr |

---

## Executive Summary

The backend implements a sophisticated AMT (Auction Market Theory) trading system with 70+ service files. While individual calculation components are well-engineered, the Triple-A strategy pattern is **fragmented across multiple partially-implemented systems** with significant bugs and architectural issues preventing cohesive execution.

**Overall Strategy Score: 4/10** — Components exist, but the strategy loop is not closed.

---

## Part 1: Calculation Bugs

### Bug #1: Range Bar Volume Profile Double-Counting

**Severity:** CRITICAL  
**File:** `backend/app/application/range_bar_builder.py:229-251`

**Problem:** Each bar's volume is counted TWICE in the volume profile — once at mid-price, once distributed across the bar's range.

```python
# Line 232-234: First adds full volume to mid-price bucket
mid_price = (bar.high + bar.low) / 2.0
bucket = round(mid_price / step) * step
self._vp_levels[bucket] = self._vp_levels.get(bucket, 0.0) + bar.volume  # ← ADDED

# Line 239-251: THEN distributes same volume across bar range
price = bar.low
while price <= bar.high:
    bkt = round(price / step) * step
    self._vp_levels[bkt] = self._vp_levels.get(bkt, 0.0) + bar.volume / ...  # ← ADDED AGAIN
```

**Impact:** VP is inflated, POC/VAH/VAL are shifted, range bar signals are wrong.

**Fix:** Remove the mid-price bucket addition (lines 232-236). Only distribute volume across the bar's range.

---

### Bug #2: VWAP Bands Use Simple Std (Not Volume-Weighted)

**Severity:** CRITICAL  
**Files:** 
- `backend/app/domain/fabio_ai/services/vwap_service.py:174-183`
- `backend/app/domain/fabio_ai/services/amt_analyzer.py:669-714`

**Problem:** The VWAP standard deviation is calculated from a simple standard deviation of typical prices, NOT volume-weighted as required for VWAP bands.

```python
# vwap_service.py:174-183 — Current implementation (WRONG)
deviations = list(self._state.price_deviations)
mean_deviation = sum(deviations) / len(deviations)
variance = sum((d - mean_deviation) ** 2 for d in deviations) / len(deviations)
return math.sqrt(max(0.0, variance))
```

This calculates `σ(typical_price)` — a simple std of prices, not a volume-weighted std.

**Correct Formula:**
```
σ = sqrt(Σ(volume_i × (typical_price_i - VWAP)²) / Σ(volume_i))
```

The shifted variance accumulator (`cum_sq_vol`) already exists in `VWAPState` but is never used for the band calculation.

**Impact:** VWAP bands are incorrect — too wide or too narrow depending on volume distribution. Aggression scoring, signal entry, and stop-loss levels all depend on band accuracy.

**Fix:** Use the accumulated `cum_sq_vol` and `cum_vol` from `VWAPState`:
```python
variance = self._state.cum_sq_vol / self._state.cum_vol
std = math.sqrt(max(0.0, variance))
```

---

### Bug #3: Fake ATR Calculation

**Severity:** HIGH  
**File:** `backend/app/domain/fabio_ai/services/amt_analyzer.py:547-550`

**Problem:** The absorption detector uses a "fake ATR" that divides session range by 14, not True Range.

```python
atr = (max(d.high for d in recent_data[-14:]) - min(d.low for d in recent_data[-14:])) / max(len(recent_data[-14:]), 1)
```

This is `(session_high - session_low) / 14` — **not ATR**.

**Correct ATR Formula:**
```
TR = max(high - low, |high - prev_close|, |low - prev_close|)
ATR = SMA(TR, 14)  # or EMA(TR, 14)
```

**Impact:** Absorption detection uses wrong threshold. With `ABSORPTION_RANGE_ATR = 0.30`, a ₹24,000 NIFTY might get fake ATR of ₹300 instead of real ATR of ₹50, causing absorption signals to fire on normal candles.

**Fix:** Implement proper True Range calculation in a dedicated ATR service.

---

### Bug #4: VWAP Standard Deviation Clamping Inconsistency

**Severity:** MEDIUM  
**File:** `backend/app/domain/fabio_ai/services/vwap_service.py:185-201`

**Problem:** The std clamping bounds are inconsistent:
```python
MIN_VWAP_STD = 1.0          # Absolute minimum (in price units)
MAX_VWAP_STD = vwap * 0.10  # 10% of VWAP
```

For NIFTY options at ₹50-200 premium, `MIN_VWAP_STD = 1.0` means minimum band of ₹1 (2-4% of price — too wide). For NIFTY futures at ₹24,000, `MAX_VWAP_STD = ₹2,400` (10% — bands are useless).

**Fix:** Make min/max proportional to price:
```python
MIN_VWAP_STD_RATIO = 0.001  # 0.1% of VWAP minimum
MAX_VWAP_STD_RATIO = 0.03   # 3% of VWAP maximum
```

---

## Part 2: Input Data Pipeline Issues

### Issue #1: Lee-Ready Classifier Disabled

**Severity:** CRITICAL  
**Files:**
- `backend/app/application/candle_aggregator.py:82` — `_use_lee_ready = False`
- `backend/app/application/candle_aggregator.py:233` — dead code path
- `backend/app/application/engine.py` — `set_delta_mode(True)` never called

**Problem:** The L2 market depth data (best bid/ask) IS available in the live stream:
```python
# engine.py:364-365
best_bid = pkt_bids[0].get("price", 0) if pkt_bids else 0.0
best_ask = pkt_asks[0].get("price", 0) if pkt_asks else 0.0

# engine.py:436-437 — passed to aggregator
tick = self._candle_aggregator.aggregate(
    ..., best_bid=float(best_bid), best_ask=float(best_ask)
)
```

And the Lee-Ready classifier EXISTS and is correctly implemented in `tick_delta.py`:
```python
# tick_delta.py:41-169 — TickDeltaClassifier (Lee-Ready algorithm)
# Step 1: Quote Rule — price >= ask → buy, price <= bid → sell
# Step 2: Tick Rule — price > prev_price → buy, price < prev_price → sell
# Step 3: Update state
```

But `_use_lee_ready` is hardcoded to `False` and `set_delta_mode(True)` is never called.

**Impact:** Delta is always estimated from body proxy instead of classified from actual bid/ask. This affects:
- Absorption detection (side determination)
- CVD (Cumulative Volume Delta) accuracy
- Aggression scoring
- Signal direction
- All VP buy/sell splits

| Metric | Body Proxy | Lee-Ready |
|--------|-----------|-----------|
| Delta accuracy | ~50-60% | ~85-95% |
| Absorption side | Guessed | Known |
| CVD reliability | Low | High |

**Fix:** Enable Lee-Ready at engine startup:
```python
# engine.py — after candle_aggregator init
self._candle_aggregator.set_delta_mode(True)
self._futures_aggregator.set_delta_mode(True)
```

Or use the existing feature flag `true_delta_lee_ready` from `config/base.yaml`.

---

### Issue #2: Historical Candles Missing `taker_buy_volume`

**Severity:** MEDIUM  
**File:** `backend/app/application/engine.py:158-165`

**Problem:** When loading historical candles for session warm-up, `taker_buy_volume` and `delta` are not set:

```python
candle = OHLC(
    time=timestamp.isoformat(),
    open=float(row.get("open", 0)),
    high=float(row.get("high", 0)),
    low=float(row.get("low", 0)),
    close=float(row.get("close", 0)),
    volume=int(row.get("volume", 0)),
    # ← taker_buy_volume NOT SET (defaults to 0)
    # ← delta NOT SET (defaults to 0)
)
```

**Impact:** Initial volume profile (first ~15 min of session) has no buy/sell split. All delta-dependent indicators use body proxy for warm-up period.

**Fix:** Use body proxy for historical candles (acceptable fallback), document the limitation.

---

### Issue #3: Delta Proxy Formula is Crude

**Severity:** MEDIUM  
**File:** `backend/app/domain/services/market_data_utils.py:11-17`

**Problem:** The delta estimation from candle body:
```python
body_ratio = (close - open_price) / spread
return body_ratio * volume
```

Limitations:
- A doji (open == close) gives delta = 0 — could have heavy two-sided trade
- A marubozu gives delta = ±volume — assumes ALL volume was one-sided
- No account of wick dynamics (absorption at highs, accumulation at lows)

**Impact:** When Lee-Ready is unavailable (historical data), delta is inaccurate.

**Fix:** Already addressed by enabling Lee-Ready for live data. Body proxy remains as fallback.

---

### Issue #4: Range Bar Backfill Uses Synthetic Ticks

**Severity:** MEDIUM  
**File:** `backend/app/application/services/tick_processor.py:221-239`

**Problem:** Historical candles are converted to synthetic range bar ticks with assumed path and equal volume:

```python
# Assumes path: open → low → high → close
ticks = [o]
if l < o: ticks.append(l)
if h > o: ticks.append(h)
ticks.append(c)

vol_per_tick = v / len(ticks)  # Equal volume per tick (wrong)
buy_per_tick = tb / len(ticks)  # Equal split (wrong)
```

**Impact:** Range bar VP built from backfill is distorted. The actual price path within each candle is unknown — could be open → high → low → close, or any permutation.

**Fix:** Accept the limitation for initial backfill. Once live streaming starts, real ticks produce accurate range bars. Consider marking backfill bars as `isWarmUp: true` in the frontend.

---

### Issue #5: Volume Spike Cap Drops Data

**Severity:** LOW  
**File:** `backend/app/application/candle_aggregator.py:164-174`

**Problem:** When a tick's volume exceeds 5% of cumulative volume, the volume is set to 0:
```python
if candle_vol > vol_cap:
    candle_vol = 0  # Drops the tick's volume entirely
```

**Impact:** During genuine volume spikes (news events, breakout bars), volume is lost entirely, affecting VP and all downstream calculations.

**Fix:** Clamp to cap instead of zeroing:
```python
if candle_vol > vol_cap:
    candle_vol = vol_cap  # Clamp instead of zero
```

---

### Issue #6: Dual VWAP State (Divergent Values)

**Severity:** MEDIUM  
**Files:**
- `backend/app/domain/fabio_ai/services/vwap_service.py` — standalone VWAP
- `backend/app/domain/fabio_ai/services/amt_analyzer.py:431-479` — inline VWAP

**Problem:** VWAP is calculated in TWO places with separate state accumulators:
1. `VWAPService.update()` — standalone service
2. `AMTAnalyzer._update_session_vwap()` — inline calculation in the analyzer

They don't share state. If both are instantiated, they'll produce different VWAP values.

**Impact:** Inconsistent VWAP across components. The gate pipeline might use one value while the signal generator uses another.

**Fix:** Consolidate into a single VWAP state holder (dependency injection).

---

## Part 3: Strategy Architecture Issues

### Issue #1: Triple-A State Machine Not Persistent

**Severity:** CRITICAL  
**File:** `backend/app/application/range_bar_builder.py:124-127`

**Problem:** The `_triple_a_phase` field exists but is NEVER written:
```python
# Line 124: Field initialized
self._triple_a_phase: str = ""

# detect_triple_a() recomputes from scratch each call (line 404)
recent = self._bars[-10:]
```

Phase transitions are not tracked. Each call recomputes the entire pattern from the last 10 bars with no memory of prior state.

**Impact:** Triple-A pattern detection has no persistence. The state machine variables are dead code.

**Fix:** Implement persistent state transitions:
- Track `phase` across calls
- Record `absorption_bar_index` when absorption is detected
- Only progress to ACCUMULATION after 2+ bars near POC
- Only emit AGGRESSION when VWAP breakout occurs after accumulation

---

### Issue #2: Absorption Disconnected from Signal Flow

**Severity:** CRITICAL  
**File:** `backend/app/domain/fabio_ai/services/absorption_validator.py`

**Problem:** `AbsorptionValidator` exists as a standalone class but:
- Never wired into `RangeBarBuilder`
- Never consumed by `GatePipeline` or `SignalGenerator`
- The `absorption_detected` flag from `AggressionScorer` uses raw thresholds, not this validator

**Impact:** Absorption detection is computed but never used for signal decisions.

**Fix:** Wire absorption validation into the gate pipeline context.

---

### Issue #3: No VWAP Breakout Aggression Signal

**Severity:** CRITICAL  
**Problem:** The Triple-A strategy requires:
1. Absorption detected → record level
2. Accumulation near POC → confirm consolidation
3. **VWAP breakout with volume** → aggression entry

No service connects absorption → VWAP breakout as an aggression signal. The `AggressionScorer` scores aggression but doesn't require prior absorption context.

**Impact:** The core entry logic of the strategy is missing.

**Fix:** Implement VWAP breakout service that triggers when:
- Prior absorption is confirmed (within last N bars)
- Price breaks above VWAP + σ (for LONG) or below VWAP - σ (for SHORT)
- Volume > average × 1.2

---

### Issue #4: Signal Generator Ignores Triple-A

**Severity:** CRITICAL  
**File:** `backend/app/domain/services/signal_generator.py:26-124`

**Problem:** `SignalGenerator.generate()` uses `aggression` and `cvd_slope` for signal decisions but:
- Never queries Triple-A pattern state
- Doesn't check absorption → accumulation → aggression sequence
- Entry price defaults to POC (not a breakout price)
- No VWAP breakout confirmation

**Impact:** Signals are generated from generic aggression, not the Triple-A pattern.

**Fix:** Integrate Triple-A state into signal generation.

---

### Issue #5: Position Sizer Uses Fixed Risk

**Severity:** MEDIUM  
**File:** `backend/app/domain/fabio_ai/services/position_sizer.py:36-105`

**Problem:** `PositionSizer.calculate()` always uses fixed `RISK_PER_TRADE_PCT`. The dynamic cushion system from `LossTracker.compute_dynamic_risk()` exists but is never called.

**Impact:** No session-aware position sizing. After losses, the system doesn't reduce risk.

**Fix:** Connect `LossTracker.compute_dynamic_risk()` → `PositionSizer.calculate()`.

---

## Part 4: Dead Code / Unused Components

| Component | File | Evidence |
|-----------|------|----------|
| `RangeBarBuilder._triple_a_phase` | `range_bar_builder.py:124` | Field initialized, never written |
| `RL Trainer` | `rl/trainer.py:123-298` | No production caller |
| `RL Environment` | `rl/valentini_env.py:88-487` | Training-only, not in DI container |
| `ScalpGatePipeline` | `services/scalp_gate_pipeline.py` | Duplicates `fabio_ai` gate pipeline |
| `GenerativeAIService` | `services/generative_ai_service.py` | No references in production flow |
| `MLXCompute` | `services/mlx_compute.py` | Apple Silicon compute, unused |
| `PredictionEngine` | `services/prediction_engine.py` | Not wired to signal flow |
| `TradeManager` alias | `exit_engine.py:519` | Only tests use it |

---

## Part 5: What's Correctly Implemented

| Component | File | Notes |
|-----------|------|-------|
| Volume Profile (CME Two-Row Pairs) | `volume_profile.py:69-148` | Textbook-correct |
| POC with VWAP tie-break | `volume_profile.py:41-66` | Correct |
| Value Area 70% | `constants.py:49` | CME standard |
| LVN/HVN thresholds | `constants.py:47-48` | Fabio spec-compliant |
| Session VWAP with shifted variance | `vwap_service.py:68-231` | Numerically stable |
| Session 5-phase structure | `session_context.py:90-125` | Correct mapping |
| Structural Stop Engine | `structural_stop_engine.py:47-335` | Correct |
| Drive Tracker (D1/D2/D3+) | `drive_tracker.py:52-314` | Correct |
| AbsorptionValidator | `absorption_validator.py:35-146` | Correct (but disconnected) |
| AggressionScorer | `aggression_scorer.py:60-153` | Correct |
| PositionSizer (fixed fractional) | `position_sizer.py:32-136` | Correct |
| RiskManager | `risk_manager.py:53-258` | Correct |
| TickDeltaClassifier (Lee-Ready) | `tick_delta.py:41-169` | Correct (but disabled) |
| PersistentAggressionScorer | `aggression_scorer.py:165-281` | Correct |

---

## Part 6: Data Pipeline Architecture

### Current Flow

```
Exchange (Dhan)
    ↓
dhan_adapter.py
    ├── tick stream: LTP, volume, OI, cum_buy, cum_sell
    └── L2 depth: 20 levels (NSE) / 5 levels (MCX)
         ↓
engine.py:364-365
    ├── best_bid = depth_bids[0].price
    └── best_ask = depth_asks[0].price
         ↓
    ┌─────────────────────┐    ┌──────────────────────────┐
    │ candle_aggregator   │    │ tick_processor            │
    │ .aggregate()        │    │ .update_range_bar()       │
    │                     │    │                          │
    │ ❌ Lee-Ready = False │    │ ✅ Uses taker_buy_volume │
    │ ⚠ Falls back to     │    │ ❌ VP double-count       │
    │   body proxy        │    │ ❌ Synthetic backfill    │
    │ ✅ Has best_bid/ask │    └──────────────────────────┘
    └─────────────────────┘              ↓
              ↓                    range_bar_builder.py
    amt_analyzer.py                    ↓
    ├── VP (CME Two-RP) ✅         gate_pipeline.py
    ├── VWAP bands ❌               ↓
    ├── Absorption ⚠️           signal_generator.py
    ├── Aggression ✅                  ↓
    ├── Gate Pipeline ⚠️         entry_coordinator.py
    └── Signal (deprecated)           ↓
                                  trade_execution
```

### Required Flow

```
Exchange (Dhan)
    ↓
dhan_adapter.py
    ├── tick stream + L2 depth
         ↓
    ┌─────────────────────────────┐
    │ Lee-Ready Delta Classifier  │
    │ ✅ USE best_bid/best_ask    │
    │ ✅ Classify each trade      │
    │ ✅ Accurate delta           │
    └─────────────────────────────┘
              ↓
    ┌─────────────────────────────┐
    │ Triple-A State Machine      │
    │ Phase 1: Absorption detect  │
    │ Phase 2: Accumulation track │
    │ Phase 3: VWAP breakout      │
    └─────────────────────────────┘
              ↓
    ┌─────────────────────────────┐
    │ Signal Generator            │
    │ entry = breakout price      │
    │ SL = absorption level ± step│
    │ TP = entry + (entry-SL) × 2 │
    └─────────────────────────────┘
              ↓
    ┌─────────────────────────────┐
    │ Risk + Position Sizing      │
    │ dynamic risk from PnL       │
    │ gate validation             │
    └─────────────────────────────┘
              ↓
         trade_execution
```

---

## Part 7: Priority Action Plan

### P0 — Critical (Strategy Doesn't Work As-Designed)

| # | Fix | File | Effort |
|---|-----|------|--------|
| 1 | Enable Lee-Ready delta | `engine.py` + `candle_aggregator.py` | 30 min |
| 2 | Remove VP double-counting | `range_bar_builder.py:232-236` | 15 min |
| 3 | Fix VWAP bands to volume-weighted | `vwap_service.py:174-183` | 1 hr |
| 4 | Implement persistent Triple-A state machine | `range_bar_builder.py` + new service | 4 hr |
| 5 | Wire AbsorptionValidator → GatePipeline → Signal | `gate_pipeline.py` + `signal_generator.py` | 3 hr |
| 6 | Implement VWAP breakout aggression | New service | 3 hr |

### P1 — High (Architecture Cleanup)

| # | Fix | File | Effort |
|---|-----|------|--------|
| 7 | Fix ATR calculation (True Range) | New `atr_service.py` | 2 hr |
| 8 | Fix VWAP std clamping bounds | `vwap_service.py:185-201` | 30 min |
| 9 | Fix volume spike cap (clamp, don't zero) | `candle_aggregator.py:164-174` | 15 min |
| 10 | Consolidate dual VWAP state | `vwap_service.py` + `amt_analyzer.py` | 2 hr |
| 11 | Connect dynamic position sizing | `position_sizer.py` + `loss_tracker.py` | 1 hr |
| 12 | Remove dead code (RL, MLX, etc.) | Multiple files | 2 hr |

### P2 — Medium (Completeness)

| # | Fix | File | Effort |
|---|-----|------|--------|
| 13 | Persist prior session POC/VAH/VAL | `session_context.py` + storage | 2 hr |
| 14 | Reduce gate pipeline from 12 → 5 gates | `gate_pipeline.py` | 2 hr |
| 15 | Mark range bar backfill as warmup | `tick_processor.py` | 30 min |
| 16 | Unify market state classification | `market_state_engine.py` + `market_structure_classifier.py` | 3 hr |

### P3 — Low (Documentation/Testing)

| # | Fix | File | Effort |
|---|-----|------|--------|
| 17 | Add test: VP POC calculation | `tests/` | 2 hr |
| 18 | Add test: Lee-Ready classification | `tests/` | 2 hr |
| 19 | Add test: Triple-A state transitions | `tests/` | 3 hr |
| 20 | Add test: VWAP bands correctness | `tests/` | 2 hr |

---

## Part 8: Parameter Reference

### Current Parameters (from `config/base.yaml` + `constants.py`)

| Parameter | Value | Used In | Correct? |
|-----------|-------|---------|----------|
| `VALUE_AREA_PCT` | 0.70 | VP value area | ✅ CME standard |
| `LVN_THRESHOLD` | 0.15 | LVN detection | ✅ < 15% of mean |
| `HVN_THRESHOLD` | 2.00 | HVN detection | ✅ > 200% of mean |
| `ABSORPTION_RANGE_ATR` | 0.30 | Absorption detection | ⚠️ Fake ATR |
| `ABSORPTION_VOL_MULT` | 2.0 | Absorption detection | ✅ Volume > 2x avg |
| `AGGRESSION_FOOTPRINT` | 1.0 | Aggression scoring | ✅ Fabio spec |
| `AGGRESSION_CVD` | 1.0 | Aggression scoring | ✅ Fabio spec |
| `AGGRESSION_BIG_TRADE` | 1.0 | Aggression scoring | ✅ Fabio spec |
| `AGGRESSION_ABSORPTION` | 0.5 | Aggression scoring | ✅ Fabio spec |
| `AGGRESSION_OFI` | 0.5 | Aggression scoring | ✅ Fabio spec |
| `AGGRESSION_CONFLUENCE` | 0.5 | Aggression scoring | ✅ Fabio spec |
| `AGGRESSION_BUBBLE` | 0.5 | Aggression scoring | ✅ Fabio spec |
| `MIN_AGGRESSION_SCORE` | 2.0 | Trade threshold | ✅ Fabio spec |
| `PYRAMID_AGGRESSION_SCORE` | 3.0 | Pyramid threshold | ✅ Fabio spec |
| `MIN_RR_RATIO` | 1.5 | Signal filter | ✅ Triple-A spec |
| `RISK_PER_TRADE_PCT` | 0.005 (0.5%) | Position sizing | ✅ Conservative |
| `MAX_DAILY_LOSS_PCT` | 0.02 (2%) | Risk limit | ✅ Standard |
| `MAX_CONSECUTIVE_LOSSES` | 3 | Circuit breaker | ✅ Standard |
| `WARM_UP_MINUTES_NSE` | 15 | Session warmup | ✅ Adequate |
| `FOOTPRINT_IMBALANCE_RATIO` | 3.0 | Footprint detection | ✅ 3:1 ratio |
| `FOOTPRINT_IMBALANCE_PCT` | 0.40 | Footprint detection | ✅ 40% threshold |
| `BIG_TRADE_MULTIPLIER` | 5.0 | Big trade detection | ✅ 5x average |
| `CVD_SLOPE_WINDOW` | 20 | CVD slope | ✅ Standard |
| `BALANCE_RATIO_THRESHOLD` | 0.55/0.70 | Balance detection | ✅ Fabio spec |
| `DISPLACEMENT_MULTIPLIER` | 1.5 | Displacement detection | ✅ Standard |

### New Parameters Needed

| Parameter | Suggested Value | Purpose |
|-----------|----------------|---------|
| `VWAP_MIN_STD_RATIO` | 0.001 | Minimum VWAP band width |
| `VWAP_MAX_STD_RATIO` | 0.03 | Maximum VWAP band width |
| `TRIPLE_A_MAX_BARS` | 5 | Max bars for Triple-A detection window |
| `TRIPLE_A_MIN_ACCUMULATION` | 2 | Min accumulation bars |
| `TRIPLE_A_VWAP_SIGMA` | 1.0 | VWAP breakout threshold (σ) |

---

## Part 9: Data Limitations (NSE-Specific)

| Limitation | Impact | Mitigation |
|------------|--------|------------|
| No `taker_buy_volume` in historical data | Initial VP has no buy/sell split | Use body proxy for warmup, Lee-Ready for live |
| No tick-level bid/ask for history | Lee-Ready unavailable for initial candles | Body proxy fallback, document uncertainty |
| 1-minute candles minimum | Intra-candle range bar path unknown | Synthetic backfill (marked as warmup) |
| 20-level depth (NSE) | Sufficient for Lee-Ready classification | ✅ Adequate |
| 5-level depth (MCX) | Sufficient for Lee-Ready classification | ✅ Adequate |

---

## Appendix: File-by-File Audit Summary

### `backend/app/application/range_bar_builder.py`
- **574 lines** — Range bar construction + VP + VWAP + Triple-A
- **Bugs:** VP double-count (lines 232-236), Triple-A state not persisted (line 124)
- **Status:** Needs refactoring

### `backend/app/domain/services/volume_profile.py`
- **488 lines** — VP histogram, POC/VAH/VAL, incremental updates
- **Bugs:** None (CME method correct)
- **Status:** Keep, consolidate with fabio_ai VP service

### `backend/app/domain/fabio_ai/services/vwap_service.py`
- **231 lines** — Session VWAP + bands
- **Bugs:** Simple std instead of volume-weighted (line 174)
- **Status:** Fix std calculation

### `backend/app/domain/fabio_ai/services/absorption_validator.py`
- **146 lines** — Forward-looking displacement validation
- **Bugs:** None, but disconnected from pipeline
- **Status:** Wire into gate pipeline

### `backend/app/domain/fabio_ai/services/aggression_scorer.py`
- **281 lines** — Multi-signal additive scoring
- **Bugs:** None
- **Status:** Keep as-is

### `backend/app/domain/fabio_ai/services/gate_pipeline.py`
- **430 lines** — 12-gate validation
- **Bugs:** Over-engineered, missing Triple-A context
- **Status:** Simplify, add Triple-A fields

### `backend/app/domain/constants.py`
- **195 lines** — Config-driven constants
- **Bugs:** None
- **Status:** Add new VWAP/TRIPLE_A params

### `backend/app/application/candle_aggregator.py`
- **330 lines** — Tick-to-candle aggregation
- **Bugs:** Lee-Ready disabled (line 82), volume spike drops data (line 170)
- **Status:** Enable Lee-Ready, fix spike cap

### `backend/app/domain/services/tick_delta.py`
- **194 lines** — Lee-Ready classifier + body proxy
- **Bugs:** None (correct implementation, just disabled)
- **Status:** Enable via set_delta_mode(True)

### `backend/app/domain/services/signal_generator.py`
- **~124 lines** — Signal generation
- **Bugs:** Ignores Triple-A, entry defaults to POC
- **Status:** Refactor to use Triple-A state

---

*End of audit document. Total findings: 4 calculation bugs, 6 data pipeline issues, 5 architecture issues, 8 dead code components. Priority actions: 6 critical, 6 high, 4 medium, 4 low.*
