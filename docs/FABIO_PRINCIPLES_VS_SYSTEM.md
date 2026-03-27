# Fabio Valentini's Interrogation — Core Principles vs System Reality

### GlassyTrade AI v2.0 | 2026-03-27
### Source: Fabio Valentini's AMT Methodology — Live Trading Transcript

---

> "My model has only TWO states — BALANCED and IMBALANCED. That is it. The entire trade decision lives or dies on this one classification."

---

## The Two Core Market States — Is the Detection Real?

**"My model has only TWO states — BALANCED and IMBALANCED. That is it. The entire trade decision lives or dies on this one classification. Tell me exactly:**

- When your engine says BALANCED for CRUDEOIL 8850 PE, what calculation produces this? Is it based on the price staying within the Value Area (70% rule), or is it a time-based consolidation detection from the profile shape, or something else?
- Because I see CVD Slope at -54.5 BEARISH and you are calling BALANCED. In my model, CVD is a LEADING indicator — it tells me what is happening BEFORE price moves. A -54.5 slope means aggressive sellers are dominating. A truly BALANCED market has CVD near zero, oscillating around a mean. So is your BALANCED detection completely disconnected from CVD? Because if yes, the foundation of the engine is broken.

**Finding:** The system has FOUR states (NO_TRADE, BALANCED, IMBALANCED, PROBING) instead of Fabio's TWO. BALANCED is computed purely from price position relative to VA — completely disconnected from CVD. A BALANCED market with CVD slope -54.5 is a contradiction that Fabio would call a "distribution within balance" — a high-probability SHORT setup, not FLAT.

---

## LVNs at 743, 756, 788 — This Profile is Wrong

**"Low Volume Nodes are the only objective refinement level I use. I don't use arbitrary support/resistance. I use LVN because at LVN the market moves fast — low volume means no friction. Now your LVNs are at 743, 756, 788. The current price is 640-644. This means ALL your LVNs are 100 to 160 points ABOVE price. Tell me:**

- What time window is this profile built from? Because if price is 640 and LVNs are 743+, you either have a multi-day composite profile where yesterday price was at 750-800, or your profile calculation is pulling incorrect data.
- In my model, I use LVN from the current developing profile OR the most recent compression zone — not a historical composite that has no relevance to today's price location.
- Are LVNs dynamically recalculated as the session develops, or are they fixed at session open? Because an LVN from 9:00 AM at 743 is completely useless at 11:00 PM when price is 100 points lower.

**Finding:** The volume profile is built on **OPTION PREMIUM** (CRUDEOIL 8850 PE at ₹640), not on the **UNDERLYING CRUDEOIL FUTURES** (₹8,878). The LVNs at 743, 756, 788 are from earlier in the session when the option premium was higher. This is architecturally wrong — AMT profiles must be built on the underlying instrument, not on derivatives.

---

## IB Range 643.30–644.80 = 1.5 Points — Fatal Error

**"The Initial Balance is the foundation of everything. Without a correct IB, I cannot define premium/discount. I cannot define where the market is trying to go. A 1.5 point IB on CRUDEOIL options is statistically impossible in normal conditions. Tell me:**

- Is the IB being calculated on the OPTION PREMIUM of CRUDEOIL 8850 PE, or on the underlying CRUDEOIL FUTURES price? This is the most critical question. In AMT, IB must ALWAYS be on the underlying — never on the derivative.
- If you are calculating IB on the option LTP, you are building your entire location framework on a decaying instrument whose price reflects time value, not just directional movement. This will give you a completely wrong picture.
- What is the IB window — first 30 minutes from 9:00 AM MCX? Because at 11 PM, this IB is 14 hours old. Does the system recalculate IB for specific legs or sessions, or is one IB held for the entire day?

**Finding:** IB is calculated on **option premium** (1.5 point range on a ₹640 option). The IB window is correctly set to first 30 minutes of MCX session, but on the wrong instrument. IB must track underlying futures (which would have a 5-15 point range in the first 30 minutes).

---

## Prior POC and Prior VA — The Most Critical Reference

**"In my model, when I look for targets, I go to the PRIOR POC. When I look for rejection, I check if price is accepting or rejecting the prior VA boundaries. Prior session data is not optional — it is the TARGET. Your Prior POC shows 699.68, which is fine. But Prior VA is 0.00 — 0.00. Tell me:**

- Has Prior VA EVER shown a non-zero value in this system? If no, this means your session boundary logic is broken — the system never snapshots VA at session close and carries it forward.
- Prior POC is 699.68, which is 60 points above current price. Is this prior POC being used as an active TARGET in your probability model? Or is it just a display number that has no input into the direction probability output?
- In my model, when price is deeply below prior POC, it tells me the market has REJECTED value — and a mean reversion back to prior POC is a high-probability target. Is your system using prior POC as a target reference in the P(target) calculation?

**Finding:** Prior VA = 0.00 is because no previous session exists in the database for this symbol (first run). The system does snapshot VA at session close via `_maybe_reset_symbol_state()`, but the session boundary detection may not be working correctly for MCX (which runs across midnight). Prior POC is computed but NOT wired into the probability model as a target.

---

## Aggression Detection — The Trigger That Makes Everything Work

**"The trigger for every trade in my model is AGGRESSION — specifically, large executed orders at a key location. I filter for 20–30 contracts on NASDAQ on a 1-minute chart. Without aggression, I don't take the trade even if location and market state are perfect. Tell me:**

- How does your system detect aggression? Is it actual order size filtering (e.g., trades above X lots at a price level), or is it just the Delta Score derived from bid-ask imbalance?
- The Delta Score showing 0.50 — what does this mean? Is it normalized between -1 and +1? A 0.50 positive delta with CVD Slope -54.5 negative is a contradiction. Which is more current — Delta is tick-level, CVD is bar-level?
- In my model, I specifically watch for a 'big red ball' or 'big green ball' at the LVN — the visible bubble in footprint. Your footprint tab exists in the UI. Is it actually computing delta per price level within each bar, or is it a visual placeholder with no live data feeding it?

**Finding:** Aggression is detected via a 7-signal additive scoring system (footprint, CVD, big trade, absorption, OFI, confluence, bubble). The "big red/green ball" — Fabio's signature visual — is implemented as `AggressivePrintRegistry` with sigma-based detection. The contradiction between Delta Score (+0.50) and CVD Slope (-54.5) is because Delta is tick-level (current bar) while CVD is bar-level (rolling 20-bar window). Both are valid — they measure different timeframes.

---

## Failed Auction — The Best Setup in My Model

**"The failed auction is arguably my highest win-rate setup. Price breaks out of balance, looks like a breakout, then fails to follow through and snaps back inside. This is where trapped traders close their positions and accelerate the move back to POC. Your system shows 'No acceptance/rejection signals' in section 03C. Tell me:**

- Is failed auction detection implemented at all? This requires: (1) detecting a break above/below a structural level, (2) monitoring follow-through volume within N bars, (3) flagging when follow-through is absent.
- What defines 'acceptance' in your system — is it N consecutive closes above/below a level, or time-at-price above a threshold, or volume-at-price confirmation?
- A failed auction at IB High/Low or VA High/Low is the core of my mean reversion model. If this is not implemented, the system is completely missing the setups that have the highest probability and best risk-to-reward.

**Finding:** `AcceptanceRejectionEngine` IS implemented with:
- **Acceptance:** Price closes above VAH for 120+ seconds with volume > 1.2× baseline
- **Rejection:** Wick > body at VA edge + volume spike > 1.5× baseline
- **Liquidity Sweep:** Pierce level + close back inside + long wick

However, the engine can't fire because it's monitoring the **option premium** profile. With VAH at ₹804 and price at ₹642, the price is nowhere near the VA edges. The implementation is correct but applied to the wrong instrument.

---

## Second Drive Rule — Don't Take the First

**"I never take the first drive out of balance. I wait for the retest — the second drive. Because the first drive can be a fake-out, especially in London session. The second drive with confirmed aggression is the real move. Tell me:**

- Does your system have any 'second drive' or 'retest confirmation' logic? Meaning: does it wait for price to break a level, pull back to test it, and THEN look for aggression before generating a signal?
- Or does your engine fire a signal the moment CVD spikes or Delta Score crosses a threshold, which would be exactly the 'first drive' mistake I warn against?
- Because if you are taking first drives, your win rate on trend-following signals will be low — maybe 30–40%. You will take many small losses and miss the big confirmation moves.

**Finding:** The system HAS second drive logic — `DriveTracker` with 4 drives (D1, D2, D3, D4). Gate G7 specifically blocks D1 (first drive) and only allows D2+ (second drive) or D3+ with confirmation. The `is_second_drive` flag is required for the aggression scoring to reach "confirmed" status. This matches Fabio's principle exactly.

---

## CVD — Is It Leading or Lagging in This System?

**"CVD is the only leading indicator I trust for intraday scalping. When CVD is rising and price hasn't moved yet, I know buyers are aggressive. I can put the trade to break-even earlier because I see the pressure building before price confirms. Tell me:**

- Is your CVD calculated from session open (cumulative from 9:00 AM), or is it a rolling window CVD over the last N bars? Because a rolling CVD loses its context — it doesn't tell you what the auction has been doing all session.
- CVD Slope of -54.5 — over how many bars is this slope calculated? 5 bars? 10 bars? Because on 1-minute bars at 11 PM with almost no volume, a single large sell order can create a -54 slope that is statistically meaningless.
- Most importantly: is CVD a direct INPUT to the direction probability model, or is it only displayed in 03B as a reference metric? Because CVD must be a primary input — not decoration.

**Finding:** CVD is computed as **rolling 20-bar CVD** (not session cumulative). The slope is calculated via linear regression over 20 bars. CVD IS a direct input to the probability model — it's one of the features in the LightGBM feature vector. However, the rolling window approach means it loses session-level context. Fabio's approach of session-cumulative CVD would be more aligned with his methodology.

---

## DEAD Market Logic — Should It Kill Everything?

**"When I am in a DEAD market — low volume, no aggression, no clear auction — I stay out. That is correct behavior. But I stay out of NEW TRADES. I don't delete my existing analysis. Tell me:**

- When DEAD state is active, does it only suppress new trade signals, or does it also wipe out your structural analysis — VA, POC, LVN, IB? Because these structures remain valid even when volume is low.
- The 5% of average volume threshold — is this calculated against the full session average, or against this specific time-of-day historical average? At 11 PM MCX, volume is always low compared to the 9 AM opening. Your system might be calling DEAD every evening because it is comparing against a session-wide average.
- Should there be a specific MCX evening session profile — where the 'average' is calculated only from historical 10 PM–11:30 PM data — so the DEAD threshold is appropriate for end-of-session conditions?

**Finding:** DEAD state only suppresses **new trade signals** (Gate G0 blocks). The structural analysis (VA, POC, LVN, IB) continues to update. The volume baseline is a rolling 50-candle average — NOT time-of-day adjusted. This means at 11 PM, the threshold compares against the high-volume 17:00–21:00 window, which is too aggressive for end-of-session.

---

## Summary — Fabio's 10 Core Principles vs System Reality

| # | Fabio's Principle | System Status | Fix Required |
|---|------------------|---------------|-------------|
| 1 | TWO states: BALANCED / IMBALANCED | System has 4 states (NO_TRADE, BALANCED, IMBALANCED, PROBING) | Merge NO_TRADE into BALANCED, rename PROBING to BALANCED |
| 2 | LVN from current session profile | LVNs are correct BUT from wrong instrument (option premium) | Build profile on underlying futures |
| 3 | IB on underlying only | IB is on option premium (1.5 pts vs expected 5-15 pts) | Build IB on underlying futures |
| 4 | Prior POC/VA as targets | Prior VA = 0.00 (broken session boundary), Prior POC not wired to model | Fix session boundary, wire Prior POC to probability model |
| 5 | Aggression = large orders at LVN | 7-signal scoring system — matches Fabio's "big ball" concept | ✅ Correct |
| 6 | Failed auction = highest win-rate | AcceptanceRejectionEngine implemented but on wrong instrument | Move to underlying profile |
| 7 | Second drive only (no first drive) | Gate G7 blocks D1, allows D2+ | ✅ Matches Fabio exactly |
| 8 | CVD = leading indicator (session cumulative) | CVD is rolling 20-bar (loses session context) | Change to session-cumulative CVD |
| 9 | DEAD = suppress new trades only | ✅ Only suppresses signals, not analysis | ✅ Correct behavior |
| 10 | DEAD threshold = time-of-day adjusted | Threshold is rolling 50-candle average (not time-adjusted) | Add TWAP-adjusted volume baseline |

### Critical Fix: Build Everything on Underlying Futures

Fix #2, #3, and #6 all resolve to ONE root cause: the system builds volume profile, IB, and LVN on **option premium** instead of **underlying futures price**. This single fix resolves:
- LVN accuracy (LVNs will be at meaningful price levels)
- IB accuracy (15-30 point range instead of 1.5)
- Acceptance/Rejection firing (price will be near VA edges)
- Failed auction detection (price will interact with structural levels)
