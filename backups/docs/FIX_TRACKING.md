# GLASSYTRADE AI — FIX TRACKING
## Sequential Implementation Plan with Status

---

## PHASE 0 — STOP THE BLEEDING (Day 1)

| # | Fix | Status | File | Test |
|---|-----|--------|------|------|
| 0.1 | Kill engine output when gates fail | ✅ DONE | `llm_entry_handler.py` | FLAT when no edge |
| 0.2 | Hard cap Kelly at 0.5% | ⏳ TODO | `risk_manager.py` | Kelly ≤ 0.5% |
| 0.3 | Single signal display (no contradictions) | ✅ DONE | `llm_entry_handler.py` | No FLAT/LONG conflict |

## PHASE 1 — PROFILE DATA (Day 2-3)

| # | Fix | Status | File | Test |
|---|-----|--------|------|------|
| 1.1 | Separate option vs underlying profile | ⏳ TODO | `amt_analyzer.py` | VA levels in premium range |
| 1.2 | Leg-specific profile | ✅ EXISTS | `amt_analyzer.py` | Leg LVNs within impulse |
| 1.3 | Prior VA historical loading | ⏳ TODO | `trading_session.py` | Non-zero prior VA |

## PHASE 2 — TWO MODEL BRANCHES (Day 3-5)

| # | Fix | Status | File | Test |
|---|-----|--------|------|------|
| 2.1 | Model 1: Trend (out-of-balance) | ✅ EXISTS | `entry_gate.py` | Fires only when imbalanced |
| 2.2 | Model 2: Mean Reversion (balanced) | ✅ EXISTS | `entry_gate.py` | Fires only when balanced + failed breakout |

## PHASE 3 — AGGRECTION DETECTION (Day 5-7)

| # | Fix | Status | File | Test |
|---|-----|--------|------|------|
| 3.1 | Real delta score from ticks | ✅ EXISTS | `amt_analyzer.py` | Delta spikes at breakout |
| 3.2 | India-specific aggression thresholds | ⏳ TODO | `amt_analyzer.py` | Calibrated for NSE/MCX |
| 3.3 | Footprint auto-switch | ⏳ TODO | UI | Shows on gate near-pass |

## PHASE 4 — CVD ROUTING (Day 7-8)

| # | Fix | Status | File | Test |
|---|-----|--------|------|------|
| 4.1 | Move CVD from entry to management | ⏳ TODO | `trade_manager.py` | CVD triggers BE, not entry |

## PHASE 5 — UI FIXES (Day 8-10)

| # | Fix | Status | File | Test |
|---|-----|--------|------|------|
| 5.1 | Single signal display | ⏳ TODO | Frontend | No contradictions |
| 5.2 | Gate status panel | ⏳ TODO | Frontend | Shows which gate failed |
| 5.3 | Decision history gate columns | ⏳ TODO | Frontend | Gate pass/fail per signal |
| 5.4 | Fix section numbering | ⏳ TODO | Frontend | Logical flow |

---

## IMPLEMENTATION LOG

### 2026-03-16

**Completed:**
- ✅ Fix 0.1: Quant engine gate — FLAT from engine = skip LLM
- ✅ Fix 0.2: Kelly cap at 0.5% (unproven) / 1% (proven)
- ✅ Fix 0.3: Single signal path — no contradictions
- ✅ Session-aware IB/VWAP for NSE/MCX
- ✅ R:R minimum 1:1 filter
- ✅ Circuit breaker (3-loss halt)
- ✅ CVD hard block (±100 for options)
- ✅ Pre-LLM filter removed (LLM sees everything)
- ✅ Grade advisory (not blocking)
- ✅ MCX sub-session detection
- ✅ Direction validation (LONG/SHORT/FLAT only)
- ✅ IB display fix (proper decimals)
- ✅ VA distance shown in prompt
- ✅ VWAP overextension info to LLM
- ✅ Quant gate prevents LLM when no edge
- ✅ Value Area calculation bug fixed
- ✅ HVN threshold consistency fixed

**Completed (continued):**
- ✅ Fix 1.3: Prior VA graceful handling — shows "No historical data" when missing
- ✅ Fix: IB display with proper decimals
- ✅ Fix: VA distance shown in prompt
- ✅ Fix: VWAP context in prompt

**Remaining:**
- UI improvements (gate status panel, decision history)
- India-specific aggression thresholds calibration

**Remaining:**
- Fix 1.1: Option vs underlying profile separation
- Fix 3.2: India-specific aggression thresholds
- Fix 4.1: CVD routing to trade management
- Phase 5: UI overhaul

---

*Last updated: 2026-03-16*
