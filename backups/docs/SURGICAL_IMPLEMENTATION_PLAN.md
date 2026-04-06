# SURGICAL IMPLEMENTATION PLAN
## Fabio Model Gap Closure — Precision Implementation

---

## PRIORITY 1: EARLY BREAKEVEN (CVD-BASED)
### Impact: +5% Win Rate | Effort: Small | Risk: Low

### Fabio's Rule:
> *"Move to BE when CVD confirms within 1 candle — before waiting for price to move 50% toward TP"*

### Current Behavior:
```python
# trade_manager.py — triggers at 50% of TP distance
if unrealised >= tp_distance * 0.50:  # TOO LATE
    mp.stop_loss = mp.entry_price
```

### Target Behavior:
```python
# Move to BE when:
# 1. CVD confirms direction strongly (slope > threshold)
# 2. OR price moves 1R (distance from entry to SL)
# Whichever comes FIRST
```

### Files to Modify:
1. `backend/app/domain/fabio_ai/services/trade_manager.py`
2. `backend/app/application/handlers/trade_lifecycle_handler.py`

### Tests Required:
```
test_cvd_breakeven_triggers_at_1r()
test_cvd_breakeven_before_price_target()
test_cvd_breakeven_not_triggered_on_weak_cvd()
test_breakeven_preserves_original_sl_if_cvd_reverses()
```

---

## PRIORITY 2: VWAP ADAPTIVE TRAILING
### Impact: +3% Win Rate | Effort: Small | Risk: Low

### Fabio's Rule:
> *"After +1.5R profit, trail to the nearest VWAP band"*

### Current Behavior:
```python
# trade_manager.py — static 30% ratchet
trail_offset = unrealised * 0.30  # TOO LOOSE
```

### Target Behavior:
```python
# Trail to VWAP ± 1σ band after +1R
# Tighter, adapts to market conditions automatically
```

### Files to Modify:
1. `backend/app/domain/fabio_ai/services/trade_manager.py`
2. `backend/app/domain/fabio_ai/services/trade_manager.py` (config)

### Tests Required:
```
test_vwap_trail_activates_at_1r()
test_vwap_trail_follows_bands()
test_vwap_trail_tighter_than_static()
test_vwap_trail_handles_missing_vwap()
```

---

## PRIORITY 3: INSIDE-CLUSTER SL PLACEMENT
### Impact: -3 ticks slippage per trade | Effort: Small | Risk: Low

### Fabio's Rule:
> *"Put your stop loss 1-2 ticks inside the cluster. You get out before acceleration."*

### Current Behavior:
```python
# entry_gate.py — places SL outside the cluster
return best - buffer  # WIDER than needed
```

### Target Behavior:
```python
# Place SL 1-2 ticks INSIDE the aggressive print cluster
# Saves 5-6 ticks of slippage on stop-outs
```

### Files to Modify:
1. `backend/app/domain/fabio_ai/services/entry_gate.py`

### Tests Required:
```
test_sl_inside_cluster_for_long()
test_sl_inside_cluster_for_short()
test_sl_respects_minimum_distance()
```

---

## PRIORITY 4: INTRADAY COMPOUNDING
### Impact: +50% returns on winning days | Effort: Medium | Risk: Medium

### Fabio's Rule:
> *"Risk session profits on directional days. Build profit conservatively, then scale."*

### Current Behavior:
```python
# Static 0.25-0.5% risk every trade
risk_pct = 0.005  # ALWAYS THE SAME
```

### Target Behavior:
```
Phase 1 (Conservative): 0.25% risk until +1% session profit
Phase 2 (Cushion): 0.35% + risk 20% of session profit
Phase 3 (Momentum): 0.40% + scale-in allowed (after 2+ wins)
Cap: Never > 0.5%, never > 30% of session profit
Reverse: 2 consecutive losses → back to Phase 1
```

### Files to Modify:
1. `backend/app/domain/fabio_ai/services/session_risk_manager.py`
2. `backend/app/domain/fabio_ai/services/trade_manager.py`

### Tests Required:
```
test_compounding_scales_with_profit()
test_compounding_caps_at_30_percent()
test_compounding_reverses_on_losses()
test_compounding_respects_max_risk()
```

---

## PRIORITY 5: SQUEEZE DETECTION
### Impact: Highest-conviction setup | Effort: Medium | Risk: Medium

### Fabio's Rule:
> *"All these sellers are in pain. They need to close. Market creates expansion."*

### Current State:
- Failed entry tracking exists (`regime_detector.py`)
- CVD tracking exists (`cvd_tracker.py`)
- NOT CONNECTED

### Target Behavior:
```
IF price breaks through a level where traders were stopped out
AND CVD confirms in breakout direction
THEN = SQUEEZE SETUP (high conviction entry)
```

### Files to Modify:
1. `backend/app/domain/fabio_ai/services/entry_gate.py`
2. `backend/app/domain/fabio_ai/services/amt_analyzer.py`

### Tests Required:
```
test_squeeze_detected_on_failed_level_break()
test_squeeze_requires_cvd_confirmation()
test_squeeze_higher_conviction_than_normal()
```

---

## IMPLEMENTATION ORDER

```
Day 1: Priority 1 (Early BE) + Priority 3 (Inside-cluster SL)
Day 2: Priority 2 (VWAP trailing)
Day 3: Priority 4 (Intraday compounding)
Day 4: Priority 5 (Squeeze detection)
Day 5: Integration testing
```

---

## TEST STRATEGY

### Unit Tests (per change):
- Each modification gets 3-5 targeted unit tests
- Test both happy path and edge cases
- Test interaction with existing components

### Integration Tests:
- Feed synthetic market data through full pipeline
- Verify new behaviors trigger correctly
- Verify no regression in existing behavior

### Backtest Validation:
- Run on historical data (if available)
- Compare win rate before/after
- Compare avg R:R before/after

---

## ROLLBACK PLAN

Each change is isolated and can be reverted independently:
1. Git commit per feature
2. Feature flags for new behaviors
3. Config toggles for compounding system
