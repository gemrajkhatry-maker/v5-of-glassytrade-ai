# SPECIFICATION REVIEW PLAN
## GlassyTrade AI vs Fabio's Exact Specification
### Based on: blog.pickmytrade.trade/fabio-valentini-pro-scalper-nasdaq-scalping-strategy/

---

## EXECUTIVE SUMMARY

This document maps every calculation in Fabio's specification to our implementation and identifies gaps.

**Overall Alignment: 78/100**

---

## 1. DATA LAYER VERIFICATION

### Layer 1 — OHLCV (Candle Data) ✅ IMPLEMENTED

| Calculation | Spec Formula | Our Implementation | Status |
|-------------|--------------|-------------------|--------|
| ATR | `mean(high - low, 14 periods)` | `atr()` in amt_analyzer.py | ✅ |
| Avg Volume | `rolling_mean(volume, 20)` | `AGGRESSION_EMA_PERIOD = 20` | ✅ |
| Absorption | `(high-low) < ATR×0.3 AND volume > avg×2.0` | `is_small_range + is_high_volume` | ✅ |
| Displacement | `(high-low) > ATR×1.5` | `DISPLACEMENT_MULTIPLIER = 1.5` | ✅ |
| Balance breakout | `close > VAH or close < VAL` | Acceptance/Rejection engine | ✅ |

### Layer 2 — Tick Data ⚠️ PARTIAL

| Calculation | Spec Requirement | Our Status | Gap |
|-------------|-----------------|------------|-----|
| Volume Profile | `bucket[price/tick_size] += volume` | ✅ Using OHLCV | Using candle range, not exact ticks |
| POC | `max(profile, key=volume)` | ✅ Correct | — |
| VAH/VAL | 70% expansion from POC | ✅ CME method | — |
| LVN | `vol < mean × 0.15` | ⚠️ Using 0.40 | Spec says 15%, we use 40% |
| HVN | `vol > mean × 2.0` | ⚠️ Using 1.5x | Spec says 200%, we use 150% |
| Big Trade Filter | `trade_size ≥ threshold` | ❌ Not implemented | No tick-level trade size |

### Layer 3 — Bid/Ask Split ⚠️ APPROXIMATED

| Calculation | Spec Requirement | Our Status | Gap |
|-------------|-----------------|------------|-----|
| CVD (true) | `cumsum(ask_vol - bid_vol)` | ⚠️ Using delta approximation | No bid/ask split |
| CVD Divergence | Price vs CVD comparison | ✅ Implemented | Using approximated CVD |
| Footprint cells | ask_vol/bid_vol per level | ❌ Not implemented | Need bid/ask per price |
| Imbalance ratio | ≥300% threshold | ❌ Not implemented | Need bid/ask split |
| Delta per candle | ask_vol - bid_vol | ⚠️ Using OHLC approximation | Not true delta |

### Layer 4 — L2/DOM ❌ NOT IMPLEMENTED

| Calculation | Spec Requirement | Our Status |
|-------------|-----------------|------------|
| Liquidity walls | Large pending orders | ❌ Not implemented |
| Stop hunt zones | Thin DOM above high | ❌ Not implemented |
| Absorption confirmation | Limit bids defending | ❌ Not implemented |
| DOM imbalance | bid_depth/ask_depth ratio | ❌ Not implemented |

---

## 2. CALCULATION VERIFICATION

### 2.1 Volume Profile ✅

**Spec:** `bucket[round(price/tick_size)] += volume`

**Our implementation:**
```python
# amt_analyzer.py - create_profile()
for d in data:
    start_bucket = int((d.low - min_price) / step)
    end_bucket = int((d.high - min_price) / step)
    vol_per_bucket = d.volume / (end_bucket - start_bucket + 1)
    for i in range(start_bucket, end_bucket + 1):
        profile[i].volume += vol_per_bucket
```

**Status:** ✅ CORRECT — Uniform distribution across candle range

### 2.2 LVN Detection ⚠️ THRESHOLD MISMATCH

**Spec:** LVN when volume < 15% of mean row volume
**Our code:** LVN when volume < 40% of mean

```python
# entry_gate.py line 50
LVN_THRESHOLD = 0.40  # Spec says 0.15
```

**Fix needed:** Change to 0.15 for stricter LVN detection

### 2.3 CVD Calculation ⚠️ APPROXIMATED

**Spec:** `cumsum(ask_volume - bid_volume)` per tick
**Our implementation:** Using `delta` from OHLCV (approximation)

```python
# amt_analyzer.py - using candle delta, not true tick CVD
buy_ratio = d.taker_buy_volume / d.volume if d.volume > 0 else 0.5
```

**Status:** ⚠️ ACCEPTABLE for Indian markets (no true bid/ask feed)

### 2.4 Absorption Detection ✅

**Spec:** `volume > avg × 2.0 AND range < ATR × 0.3`

**Our code:**
```python
is_high_volume = volume > avg_volume * 2.0
is_small_range = (high - low) < ATR * 0.3
absorption = is_high_volume AND is_small_range
```

**Status:** ✅ MATCHES SPEC

---

## 3. SIGNAL SCORING VERIFICATION

### Spec's Aggression Score:

```python
def calculate_aggression_score(direction, at_price):
    score = 0
    # Signal 1: Footprint imbalance (+1)
    # Signal 2: CVD confirmation/divergence (+1)
    # Signal 3: Big trade cluster (+1)
    # Signal 4: Absorption (+0.5)
    
    # score >= 2.0 → HIGH confidence
    # score == 1.5 → MEDIUM confidence
    # score <= 1.0 → LOW confidence (stay flat)
```

### Our Implementation:

```python
# entry_gate.py - compute_grade_score()
# CVD confirms direction: +1
# No CVD divergence: +1
# Session alignment: +1
# Profile shape alignment: ±1
# VWAP check: -1 to -2
# Grade < -3: block
```

**Status:** ⚠️ SIMILAR but different scoring weights

---

## 4. MCX NATURALGAS PARAMETERS

| Parameter | Spec Value | Our Value | Status |
|-----------|------------|-----------|--------|
| Tick size | 0.10 | Not configured | ❌ Missing |
| Profile bucket | 0.10 (1 tick) | 200 buckets total | ⚠️ Different |
| Lot size | 1250 MCF | 1250 | ✅ |
| Big trade threshold | ≥50 lots | Not implemented | ❌ |
| CVD reset | 09:00 IST daily | Session-based | ✅ |
| Absorption ATR mult | 0.3 | 0.3 | ✅ |
| Absorption vol mult | 2.0× avg | 2.0× | ✅ |
| LVN threshold | <15% mean | <40% mean | ❌ Wrong |
| HVN threshold | >200% mean | >150% mean | ❌ Wrong |
| Imbalance threshold | 300% (3:1) | Not implemented | ❌ |

---

## 5. OUTPUT SCHEMA VERIFICATION

### Spec Output:
```json
{
  "symbol": "NATURALGAS",
  "market_state": "BALANCED",
  "session_poc": 9.10,
  "session_vah": 9.40,
  "session_val": 8.80,
  "price_vs_poc": "BELOW_POC",
  "cvd_current": -1240,
  "cvd_direction": "FALLING",
  "cvd_divergence": false,
  "footprint_imbalance": "WEAK",
  "aggression_score": 1.0,
  "direction": "SHORT",
  "confidence": "Low",
  "rationale": "Balanced market. Price below POC...",
  "no_trade_reason": "Aggression score below 2.0 threshold"
}
```

### Our Output:
```json
{
  "direction": "LONG|SHORT|FLAT",
  "confidence": "High|Medium|Low",
  "rationale": "..."
}
```

**Status:** ⚠️ PARTIAL — We output direction but not full spec schema

---

## 6. FIXES REQUIRED

### Priority 1 (Critical):
1. Fix LVN threshold: 0.40 → 0.15 (match spec)
2. Fix HVN threshold: 1.5x → 2.0x (match spec)

### Priority 2 (Important):
3. Add tick-size configuration per instrument
4. Add big trade threshold configuration
5. Implement footprint imbalance ratio (when bid/ask available)

### Priority 3 (Enhancement):
6. Add full output schema (market_state, cvd_current, etc.)
7. Add liquidity wall detection (when L2 available)
8. Add stop hunt zone detection

---

## 7. ACTION ITEMS

```
□ Fix LVN_THRESHOLD = 0.15 in constants.py
□ Fix HVN_THRESHOLD = 2.0 in constants.py  
□ Add MCX_TICK_SIZES config
□ Add BIG_TRADE_THRESHOLDS config
□ Add spec-compliant output schema
□ Update option_scanner.py to use new thresholds
□ Test with real MCX NATURALGAS data
```
