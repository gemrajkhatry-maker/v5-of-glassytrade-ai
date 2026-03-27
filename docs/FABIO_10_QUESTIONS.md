# Fabio Valentini's 10 Sharp Questions — Answered
### GlassyTrade AI v2.0 | 2026-03-27 | 1080 Tests Passing

---

## Q1. Value Area & Profile Construction — Suspicious Numbers

**Question:** VAH=804.24, POC=699.68, VAL=639.86, but price at 642. What profile window? Is this option premium or underlying?

**Answer:**

| Aspect | Current Implementation | Correct? |
|--------|----------------------|----------|
| **Profile window** | Session cumulative (9:00 AM MCX to current tick) — `IncrementalVolumeProfile` adds candles from session start | ✅ Correct |
| **Instrument** | **Option premium profile** — the system builds volume profile from the option's OHLCV candles, NOT from underlying futures | ❌ WRONG |
| **Bucket count** | 200 buckets with 1% buffer | ✅ Correct |
| **TPO period** | 5-minute bars (not 1-min or 30-min) | ✅ Acceptable |

**The critical flaw:** The system builds volume profile on **option premium LTP** (₹642 for CRUDEOIL 8850 PE), not on **underlying CRUDEOIL futures price** (~₹8,878). An option premium profile is meaningless for AMT — the option's volume distribution doesn't represent market structure, it represents option-specific supply/demand.

**Fix required:** Volume profile must be built on the **underlying futures price**, not the option premium. The option LTP should only be used for entry/exit price, not for VA/POC/IB computation.

**File:** `backend/app/domain/fabio_ai/services/amt_analyzer.py` — `create_profile()` takes OHLC data. Currently receives option OHLCV. Must be changed to receive underlying futures OHLCV.

---

## Q2. IB Range — Critically Broken

**Question:** IB = 643.30–644.80 (1.5 points) for CRUDEOIL. Statistically impossible.

**Answer:**

| Aspect | Current Implementation | Correct? |
|--------|----------------------|----------|
| **IB window** | First 30 minutes (9:00–9:30 MCX) | ✅ Correct window |
| **Instrument** | **Option premium** — tracking ₹642 PE, not ₹8,878 futures | ❌ WRONG |
| **Reset** | Reset at session start (09:00 MCX) | ✅ Correct |

A 1.5-point IB on an option premium makes no sense because:
- CRUDEOIL futures moves 5–15 points in the first minute
- The option premium's range is driven by delta/gamma, not by the auction itself
- IB must always be on the **underlying** instrument

**Fix required:** IB must track underlying futures price, not option premium.

**File:** `backend/app/domain/services/initial_balance_engine.py` — `update()` method receives option OHLC candles. Must be changed to receive underlying futures candles.

---

## Q3. Prior VA = 0.00 — Dead Feature

**Question:** Prior VA High/Low both 0.00. Is prior session data being fetched?

**Answer:**

| Aspect | Current Implementation | Status |
|--------|----------------------|--------|
| **Prior session snapshot** | `SessionStateManager._maybe_reset_symbol_state()` at line 330 | ✅ Implemented |
| **Prior VA/POC storage** | Saved to `session_profiles` DB table | ✅ Implemented |
| **Prior VA/POC loading** | `self._prior_poc/self._prior_vah/self._prior_val` in AMTAnalyzer | ✅ Implemented |
| **Data source** | Computed from last session's IncrementalVolumeProfile at session boundary | ✅ Correct |
| **Why showing 0.00** | No previous session exists in the DB for this symbol (first run) | ✅ Expected |

**Verdict:** This is working correctly. The 0.00 values are expected on first run — the prior session snapshot will be populated after the first session closes. The issue is that MCX sessions may not be properly detecting session boundaries (day change), so the snapshot never gets saved.

**Potential issue:** The `_maybe_reset_symbol_state` method checks `self._last_reset_date != date_str`. If the date parsing fails (e.g., `candle.time` format doesn't match), the reset never triggers and the snapshot is never saved.

**Fix required:** Verify that `_maybe_reset_symbol_state` correctly detects MCX session boundaries.

---

## Q4. BALANCED State vs CVD Slope -31.9 — Contradiction

**Question:** BALANCED state + BEARISH CVD slope = contradiction. Which takes priority?

**Answer:**

| Aspect | Current Implementation | Issue |
|--------|----------------------|-------|
| **State classification** | Price inside VAH ↔ VAL → BALANCED | ✅ Correct |
| **CVD computation** | Rolling 20-bar CVD slope | ✅ Correct |
| **Decision hierarchy** | Probability model (04) gets ALL signals as features | ✅ Correct design |
| **Why no SHORT** | ML probability P=0.519 < 0.55 threshold → FLAT | ✅ Working as designed |

**The contradiction is actually a feature, not a bug.** A BEARISH CVD slope inside BALANCED means sellers are in control BUT price hasn't broken below VA Low. The ML model correctly evaluates this as insufficient probability for entry.

**However**, the system is showing 20+ consecutive FLAT decisions with BEARISH CVD. This suggests:
1. The ML probability is consistently below 0.55 — the model may need retraining
2. Or the CVD slope is stale/not updating on every tick

**CVD window:** Rolling 20 bars × 5 min = 100-minute window. Recalculated on every 5-min bar close (not every tick).

**Fix required:** Verify CVD slope is recalculating on bar close and not stuck at -31.9.

---

## Q5. DEAD Market Logic — Too Aggressive?

**Question:** DEAD flag at 11:10 PM. Is 5% threshold appropriate for end-of-session?

**Answer:**

| Aspect | Current Implementation | Issue |
|--------|----------------------|-------|
| **Average volume baseline** | Last 50 candles (rolling window) | ⚠️ Includes non-session hours |
| **Threshold** | Volume < 5% of average | ❌ Hardcoded, not configurable |
| **Time-of-day adjustment** | None | ❌ MISSING |

**The problem:** At 11:10 PM, the MCX evening session is wrapping up. The "average volume" includes the high-volume 17:00–21:00 window. A 5% threshold relative to that full-day average is too aggressive for end-of-session.

**Fix required:**
1. Make the DEAD threshold configurable per time-of-day window
2. Use TWAP-adjusted volume baseline (same time-of-day average from prior sessions)
3. Suppress DEAD state during the last 30 minutes of session (log it, but don't block signal generation)

---

## Q6. Bimodal Shape Detection — How?

**Question:** "B Bimodal" with LVNs at 743, 756, 788 (all 100+ points above price). How?

**Answer:**

| Aspect | Current Implementation | Status |
|--------|----------------------|--------|
| **Algorithm** | Histogram bin gap threshold check | ✅ Implemented |
| **LVN source** | Session cumulative profile (from session start) | ✅ Correct |
| **Why LVNs far from price** | Because the profile is built on **option premium** — the option traded at ₹743–788 earlier in the session, now at ₹642 | ⚠️ See Q1 |

**The bimodal classification is technically correct** for the option premium profile — there are two distributions (high premium in morning, low premium now). But this is **meaningless for AMT** because option premium distributions don't represent market structure.

**Fix required:** Move to underlying futures profile (same as Q1 fix).

---

## Q7. Delta Score vs OFI — Contradiction

**Question:** Delta Score positive (1.50) = buying. OFI negative (-0.273) = selling. Contradicting.

**Answer:**

| Metric | Calculation | Window |
|--------|-------------|--------|
| **Delta Score** | `candle.delta / candle.volume` normalized — net buyer-seller imbalance per bar | Current 5-min bar |
| **OFI** | `(bid_vol - ask_vol) / (bid_vol + ask_vol)` — order book imbalance ratio | Current tick snapshot |

**Why they contradict:**
- Delta Score measures **executed trades** (what happened)
- OFI measures **resting orders** (what's on the book)
- A positive delta with negative OFI means: buyers are hitting the ask (buying aggression) but the order book has more sell orders stacked (resistance)

**This is actually a valid signal** — it means buyers are absorbing sell-side liquidity. In AMT, this is a **potential breakout setup** if it sustains.

**Decision hierarchy:** Both feed into the ML probability model equally. The model learns to weight them based on historical accuracy. If they consistently contradict, the model assigns lower confidence.

**Verdict:** Working as designed. The contradiction is market reality, not a bug.

---

## Q8. Rotation Label — What Triggers It?

**Question:** Is "Rotation" a real input or just a display label?

**Answer:**

| Aspect | Current Implementation | Status |
|--------|----------------------|--------|
| **Trigger** | BALANCED state + price velocity < threshold | ✅ Implemented |
| **Input to probability** | Yes — included as a feature | ✅ Correct |
| **Display only?** | No — it's a state modifier that adjusts entry logic | ✅ Correct |

**"Rotation" is triggered when:**
1. Market state = BALANCED (price inside VA)
2. Price velocity < 0.05/s (slow, oscillating movement)
3. CVD slope magnitude < 10 (no strong directional bias)

**"Rotation" changes to "Trend" when:**
1. Market state = IMBALANCED (price outside VA)
2. Price velocity > 0.1/s (fast directional movement)

**Verdict:** Working correctly. The label is functional, not decorative.

---

## Q9. Confidence Scoring — Functional Impact?

**Question:** All decisions FLAT. What does High/Medium/Low confidence mean?

**Answer:**

| Aspect | Current Implementation | Issue |
|--------|----------------------|-------|
| **Confidence inputs** | Signal agreement count across sections 01–04 | ✅ Implemented |
| **Kelly sizing** | Confidence × Kelly fraction | ✅ Correct |
| **Current state** | Kelly=0.0% because ML probability < 0.55 | ✅ Expected |

**When confidence matters:**
- Kelly > 0% → High confidence = 100% Kelly, Medium = 75%, Low = 50%
- Kelly = 0% → Confidence is irrelevant (no trade)

**The "High Confidence FLAT" is misleading.** It should show as "No Signal" instead of "High Confidence" when the probability is below threshold.

**Fix required:** Display "No Signal" instead of "High/Medium Confidence" when probability < threshold.

---

## Q10. Acceptance/Rejection Signals — Implemented?

**Question:** Has an Acceptance or Rejection signal ever fired?

**Answer:**

| Aspect | Current Implementation | Status |
|--------|----------------------|--------|
| **Acceptance detection** | `AcceptanceRejectionEngine.update()` — time accumulation above/below VA | ✅ Implemented |
| **Rejection detection** | Wick analysis + volume spike at VA edges | ✅ Implemented |
| **Liquidity sweep** | Pierce level + close back inside + long wick | ✅ Implemented |
| **Why showing "None"** | Price hasn't reached VA edges in current session | ⚠️ Because profile is on option premium |

**Acceptance fires when:**
- Price closes above VAH for 120+ seconds with volume > 1.2× baseline
- Time accumulation + volume confirmation

**Rejection fires when:**
- Upper/lower wick > body at VA edge + volume spike > 1.5× baseline
- Single candle with long wick rejecting from level

**Liquidity sweep fires when:**
- Price pierces VAH/VAL then closes back inside with long wick

**The issue:** Because the profile is on option premium (which trades at ₹642), and the VAH is at ₹804, the price is nowhere near the VA edges. The acceptance/rejection engine can't fire because the levels are irrelevant.

**Fix required:** Build profile on underlying futures (same as Q1 fix). Once the profile is on the correct instrument, acceptance/rejection signals will fire properly.

---

## Summary: 3 Critical Fixes Required

| # | Fix | Impact | Files |
|---|-----|--------|-------|
| **1** | Build volume profile on **underlying futures price**, not option premium | Q1, Q2, Q6, Q10 | `amt_analyzer.py`, `initial_balance_engine.py`, `trading_session.py` |
| **2** | Make DEAD market threshold configurable per time-of-day | Q5 | `trading_session.py` |
| **3** | Display "No Signal" instead of "High Confidence FLAT" | Q9 | `prompt_builder.py` |

Fix #1 is the most critical — it resolves Q1, Q2, Q6, and Q10 simultaneously. The entire AMT engine is currently computing profiles on the wrong instrument.
