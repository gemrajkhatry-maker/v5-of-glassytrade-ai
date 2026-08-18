# AMT Engine — Implementation Master Plan
### Combined Spec Compliance Review + Pipeline Ordering Audit

**Spec Reference:** [AMT_INSTITUTIONAL_SCALPER_ALGORITHM.md](file:///Users/apple/Documents/v5-of-glassytrade-ai/amt_docs/AMT_INSTITUTIONAL_SCALPER_ALGORITHM.md)  
**Engine Root:** [quant/](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/)  
**Date:** 2026-08-18  
**Overall Score: 71 / 100**

---

## Part 1 — The Correct Execution Pipeline (Ground Truth)

Before reviewing what exists, this is the **exact ordered sequence** the spec demands, from raw tick to realized PnL. Every component must run in this order and feed the next one.

```
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 1 ► TICK INGESTION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Input: { price, qty, buy_vol, sell_vol, depth[20] }
  Gateway → feeds both aggregators

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 2 ► RANGE BAR GENERATOR  (spec §4)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  H_range = ATR(14) × scale → quantized to {5,10,25,50,100,200} ticks
  Bar closes when High - Low >= H_range
  Output: RangeBar { O, H, L, C, vol, buy_vol, sell_vol, delta, cvd }

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 3 ► UNIFIED ORDER-FLOW ANALYTICS ENGINE  (spec §5, §6)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  ONE engine, ONE output, feeds everything downstream.

  3a. Layer 1 — Macro Session Profile
        Accumulated from session open. Rolling histogram.
        Outputs: POC, VAH, VAL, LVN list, HVN list
        Algorithm: CME Two-Row Pairs (expand from POC until 68.2% vol)

  3b. Layer 2 — Compression Box Profile
        Anchored inside the 15-30 min tight range before current move.
        Outputs: Box_High, Box_Low (breakout confirmation boundary)

  3c. Layer 3 — Impulse Leg Profile  (THE SNIPER ENGINE)
        Anchored from Point A (swing low) to Point B (swing high) of
        the most recent directional impulse.
        Outputs: Leg_LVN (the void mid-leg = retest entry zone)
        SL for pyramid: 2 ticks behind Leg_LVN shelf

  3d. Anchored Session VWAP + Bands
        VWAP_t = sum(TP_i * Vol_i) / sum(Vol_i),  TP = (H+L+C)/3
        sigma_t = sqrt(sum((TP_i - VWAP_t)^2 * Vol_i) / sum(Vol_i))
        Upper_1 = VWAP + 1*sigma,  Lower_1 = VWAP - 1*sigma
        Upper_2 = VWAP + 2*sigma,  Lower_2 = VWAP - 2*sigma

  3e. CVD + Acceleration
        Delta_t = buy_vol_t - sell_vol_t
        CVD_t = cumulative sum of Delta
        CVD_velocity = EMA3(CVD) - EMA9(CVD)
        Divergence:
          BULLISH = price makes LL but CVD makes HL  (sellers absorbed)
          BEARISH = price makes HH but CVD makes LH  (buyers drying up)

  3f. Volume Bubble / Absorption Detector
        Bubble threshold: vol_bar >= 1.5 * V_avg20  AND  bar_range <= 0.5 * H_range
        Directional:
          BUY absorption: V_sell >= 0.60 * vol  AND  Close >= Low + 0.5*(H-L)
          SELL absorption: V_buy >= 0.60 * vol  AND  Close <= High - 0.5*(H-L)
        Size flag: print >= 30 lots → institutional bubble (London: 20-30)
        Output: Absorption { side, price, cluster_high, cluster_low, strength }

  3g. Order Book Imbalance (OBI)
        OBI = (Bid_qty - Ask_qty) / (Bid_qty + Ask_qty)  in [-1, +1]

  3h. Profile Classifier
        D-shape (balanced), P-shape (top-heavy), b-shape (bottom-heavy), B-shape (bimodal)
        POC Migration: RISING / FALLING / STABLE

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 4 ► TRIPLE-A STATE MACHINE  (spec §8)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Inputs: absorption (step 3f), profile POC (step 3a), VWAP (step 3d)
  MUST run AFTER step 3 completes. Never before.

  WAITING → ABSORBING:
    Trigger: absorption detected (bar_age == 0, fresh this bar)

  ABSORBING → ACCUMULATING:
    Condition: 2+ bars elapsed since absorption AND price within 2 steps of POC
    (Anti-whipsaw: never trade the first bar of absorption)

  ACCUMULATING → AGGRESSION:
    BOTH conditions required simultaneously:
    (a) Full 1-min candle CLOSES strictly beyond the absorption cluster
        LONG: bar.close > absorption.cluster_high
        SHORT: bar.close < absorption.cluster_low
    (b) CVD velocity expanding in the trade direction

  Output: phase in { WAITING, ABSORBING, ACCUMULATING, AGGRESSION }

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 5 ► GATE PIPELINE  (spec §9, §10)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Short-circuits: if any gate fails, stop immediately, do not enter.

  Gate 1 — SESSION PHASE
    Allow entry only in trading hours (NSE: 09:30-15:15, MCX: 09:00-23:00)
    Block: pre-market window (opening noise window)

  Gate 2 — COOLDOWN
    Minimum 5 bars elapsed since last trade close

  Gate 3 — TRIPLE-A EDGE  (entry trigger)
    Four valid paths, checked in priority order:
    Path A: state.phase == AGGRESSION (full 3-step confirmed)  ← PRIMARY
    Path B: IB Second Drive reclaim (D1 rejected + D2 re-approach)
    Path C: Price at Impulse Leg LVN + fresh absorption (Playbook C sniper)
    Path D: OBI >= 0.20 + close beyond VWAP band (depth aggression, fallback)
    
    NOTE: Fresh absorption alone + VWAP break WITHOUT AGGRESSION phase
    is NOT a valid standalone path — it bypasses the Accumulation phase
    (the "first raw spike" Fabio says never to trade).

  Gate 4 — RISK-REWARD
    R:R = |TP - entry| / |entry - SL| >= 1.5

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 6 ► SIGNAL BUILDER  (spec §11)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  LONG:
    Entry = bar.close (candle-close confirmation, never mid-bar)
    SL = absorption.cluster_low - 2 * tick_size  (behind the bubble cluster)
    TP priority: nearest NPOC above > prior session POC > entry + 2R

  SHORT:
    Entry = bar.close
    SL = absorption.cluster_high + 2 * tick_size
    TP priority: nearest NPOC below > prior session POC > entry - 2R

  Playbook B (VA Fade):
    Entry: 1m candle closes back INSIDE value area after failed auction
    SL: 1 tick beyond the failed auction wick
    TP: Session POC (100% exit)

  Playbook C (LVN Sniper):
    Entry: price retests Leg_LVN band (±2 ticks) + fresh absorption
    SL: 2 ticks behind the Leg_LVN shelf
    TP: beyond Point B, R:R >= 3.0

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 7 ► CUSHION RISK SIZING  (spec §12)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Cushion_t = sum of realized PnL this session
  MDL = E0 * 0.02  (max daily loss = 2% of starting equity)

  if Cushion_t <= 0:
    RiskDollars = min(E0 * 0.0025,  MDL - abs(Cushion_t))
  else:
    RiskDollars = (E0 * 0.0025) + (0.40 * Cushion_t)   [40% of earned cushion]

  Position size = floor(RiskDollars / abs(entry - SL))
  Lot snap: round to nearest lot multiple (min 1 lot)

  Circuit breakers (block if triggered):
    3 consecutive losses → hard stop for day
    Cushion_t <= -MDL → hard stop for day
    trades_today >= 6 → hard stop for day

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 8 ► OMS SUBMISSION
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Submit: { symbol, direction, entry, SL, TP, size, timestamp }
  Register fill: entry_price, entry_bar_index, pyramid_level=0

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 9 ► EXIT MANAGEMENT  (spec §13.1, §13.3)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Checked every bar close while position is open. In this order:

  9a. SPREAD BLOWOUT — bid-ask spread > 3% → exit at mid, immediately
  9b. STOP-LOSS HIT — bar.low <= SL (LONG) / bar.high >= SL (SHORT)
  9c. INSTANT RISK-ZERO (Breakeven):
        Trigger A: CVD velocity confirms direction (slope > threshold)
        Trigger B: profit >= 0.8R (NOT 1.0R — see Bug Q3)
        Action: SL_new = entry_price (downside risk = $0)
  9d. TAKE-PROFIT — MULTI-TIER:
        TP1 = 50% at +2R / first overhead LVN (banks daily cushion)
        TP2 = 25% at macro VA extreme / CVD divergence exhaustion
        TP3 = 25% Runner, trailed until session close
  9e. TRAILING STOP (after +1R profit):
        Trail_stop = close - 0.20 * unrealized_profit (LONG)
        Monotonic ratchet: trail only moves in profit direction
  9f. TIME STOP (session-phase aware):
        Phase 4: max 30 min hold | Phase 3: max 60 min hold
        Expiry day: force exit MCX@21:30, NSE@15:15
  9g. SESSION FORCE-EXIT — Phase 5: exit 100% immediately

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 10 ► PYRAMIDING  (spec §13.2)
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Runs AFTER exit check (only if position survives this bar).

  Authorization: base trade must be is_risk_free == True
  (SL already moved to breakeven or better)

  Pyramid 1 trigger:
    Price at Leg_LVN band (±2 ticks of Layer 3 LVN)
    Fresh absorption cluster at the LVN (bar_age == 0)
    1m candle closes IN the trade direction
    → Add 50% of base size
    → Move combined SL to Leg_LVN - 2 ticks (LONG)

  Pyramid 2 trigger:
    Price at second structural LVN
    Same absorption + close confirmation
    → Add 25% of base size
    → Move combined SL to second LVN - 2 ticks

  Max pyramid depth: 2 add-ons (base + P1 + P2)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 11 ► TRADE RECORD + RISK UPDATE
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  On fill close:
    Cushion_t += realized_PnL
    E_current = E0 + Cushion_t
    consecutive_losses / wins updated → check circuit breakers
    Persist to session store (survives restart)

━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
STEP 12 ► SESSION END
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
  Save session POC / VAH / VAL → prior session levels store
  Track naked POCs (unvisited = future targets)
  Reset: Cushion = $0, consecutive_losses = 0, trades_today = 0
  Core equity E0 = E0 + Cushion_t (gains compound into base)
```

---

## Part 2 — Implementation Scorecard (71 / 100)

| Component | Spec Section | File | Status | Score |
|---|---|---|---|---|
| Range Bar Generator | §4 | `quant/aggregator.py` | ❌ Time-bars only | 0/8 |
| Layer 1 Session Profile | §5.1 | [`amt/profile/volume_profile.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/amt/profile/volume_profile.py) | ✅ CME Two-Row exact | 10/10 |
| Layer 2 Compression Box | §5.2 | — | ❌ Not built | 0/5 |
| Layer 3 Impulse Leg LVN | §5, §9.3 | [`analyzer.detect_displacement_leg()`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/amt/analyzer.py#L322) | ⚠️ Computed, not wired to gates | 3/10 |
| Session VWAP + σ Bands | §6.1 | [`quant/vwap.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/vwap.py) | ⚠️ Two independent accumulators | 5/8 |
| CVD + Velocity | §6.2 | [`amt/orderflow/cvd.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/amt/orderflow/cvd.py) | ⚠️ LR slope not EMA3-EMA9 | 5/7 |
| CVD Divergence | §6.2 | [`amt/orderflow/cvd.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/amt/orderflow/cvd.py) | ✅ Bull/Bear detected | 5/5 |
| Volume Bubble / Absorption | §7.2 | [`quant/absorption.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/absorption.py) | ⚠️ 0.55 threshold (spec=0.60), missing close check | 4/7 |
| Big Trade Detector | §7.1 | [`amt/orderflow/detectors.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/amt/orderflow/detectors.py) | ⚠️ Candle-level proxy (Dhan ceiling) | 3/5 |
| Triple-A State Machine | §8 | [`quant/triple_a.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/triple_a.py) | ⚠️ Aggression = VWAP proxy, not cluster-close | 7/10 |
| Playbook A: Breakout Squeeze | §9.1 | `decision/` pipeline | ✅ Wired | 7/8 |
| Playbook B: VA Fade | §9.2 | [`decision/va_fade.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/decision/va_fade.py) | ✅ Wired | 7/8 |
| Playbook C: LVN Sniper Entry | §9.3 | — | ❌ Not wired to gates | 0/5 |
| Session Gates (NSE + MCX) | §10 | [`runtime._session_allow_entry()`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/runtime.py#L519) | ✅ Phase table, expiry, pre-market | 9/9 |
| Anti-Whipsaw Rule | §9.1 | [`gates_edge.py:46`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/decision/gates_edge.py#L46) | ❌ Bypass route skips Accumulation | 0/4 |
| SL Behind Cluster (1-2 ticks) | §11 | [`decision/signal_builder.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/decision/signal_builder.py) | ✅ `sl = anchor - 2*tick` | 5/5 |
| Structural TP (NPOC/priorPOC) | §9.1 | [`decision/signal_builder.py:155`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/decision/signal_builder.py#L155) | ✅ NPOC + prior POC candidates | 5/5 |
| Cushion Formula (40% of PnL) | §12.2 | [`execution/risk.py:166`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/execution/risk.py#L166) | ⚠️ Uses 20% + tier abstraction (spec=40%) | 5/7 |
| Circuit Breakers | §12 | [`execution/risk.py:104`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/execution/risk.py#L104) | ✅ 3-loss, 2% daily, 6-trade cap | 8/8 |
| Instant Risk-Zero (Breakeven) | §13.1 | [`execution/exits.py:135`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/execution/exits.py#L135) | ⚠️ Triggers at 1.0R (spec=0.8R) | 4/5 |
| Multi-Tier Partial Exits TP1/TP2/Runner | §13.3 | `execution/exits.py` | ❌ Single-exit only (100%) | 0/5 |
| Pyramiding OMS | §13.2 | [`execution/oms.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/execution/oms.py) | ❌ Single-position only | 0/8 |
| Aggression Scorer (FR-06, 7-factor) | §9 | [`amt/orderflow/aggression.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/amt/orderflow/aggression.py) | ✅ Excellent — beyond spec | 8/8 |
| Drive Tracker (D1/D2 rule) | §9 | [`amt/orderflow/drive.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/amt/orderflow/drive.py) | ✅ D1-rejected → D2 valid | 7/8 |
| Profile Shape Classifier | — | [`amt/profile/classifier.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/amt/profile/classifier.py) | ✅ Bonus — D/P/b/B + POC migration | +3 |
| Footprint Analyzer | — | [`amt/orderflow/footprint.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/amt/orderflow/footprint.py) | ✅ Bonus — gaussian model | +2 |
| Session Level Persistence (NPOC) | §12 reset | `amt/session/npoc.py` | ✅ Prior POC, naked POC tracked | 5/5 |
| VWAP Bias Filter | §9.1 | [`runtime._decide():363`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/runtime.py#L363) | ✅ Rejects LONG below VWAP | 4/4 |
| Post-Trade Cooldown | §10 | [`runtime._decide():314`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/runtime.py#L314) | ✅ 5-bar cooldown | 3/3 |
| **TOTAL** | | | | **71 / 100** |

---

## Part 3 — Pipeline Ordering Bugs

### The Core Architecture Problem

The engine runs **two completely independent analytics pipelines** that never share state:

```
Bar Close
   │
   ├─► Pipeline A — AuctionCoordinator          FEEDS THE GATES & SIGNAL BUILDER
   │     quant/vwap.py          (basic VWAP accumulator)
   │     quant/volume_profile.py (simple bucketed profile)
   │     quant/absorption.py    (0.55 threshold, no close check)
   │     quant/order_flow.py    (basic CVD slope)
   │     TripleAStateMachine    (VWAP±1σ proxy for aggression)
   │     → AuctionState
   │
   └─► Pipeline B — AMTAnalyzer                  FEEDS UI / ADVISORY DTO ONLY
         analyzer._update_session_vwap()  (separate accumulator, shifted variance)
         amt/profile/volume_profile.py    (incremental, more accurate)
         amt/orderflow/cvd.py             (full EMA divergence + persistence)
         amt/profile/lvn.py               (persistence-tracked LVNs)
         analyzer.detect_displacement_leg() (Impulse Leg LVN = Layer 3)
         amt/orderflow/aggression.py      (7-factor scorer)
         amt/orderflow/drive.py           (D1/D2 tracker)
         → AMTResult → DTO dict
```

**Consequence:** Decisions use Pipeline A's simpler data. Richer Pipeline B data (LVN persistence, true CVD divergence, 7-factor aggression score, Impulse Leg LVN) is shown in the UI but **never gates a trade**. The two VWAPs accumulate independently and drift intraday. SL/TP anchors come from Pipeline B's profile while the entry trigger comes from Pipeline A's VWAP — these are not the same profile.

---

### Bug 1 — Gate 3 Bypass Skips Accumulation (Anti-Whipsaw Violation)

**File:** [`quant/decision/gates_edge.py:46-54`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/decision/gates_edge.py#L46)

**Current code (Priority 2 path):**
```python
if state.absorption is not None and state.absorption.bar_age <= 5:
    if state.absorption.side == "BUY" and state.close > state.vwap.upper_1:
        return GateResult(3, True)   # ← NO accumulation wait!
```

**Spec rule (§9.1):** "Never enter on the 1st raw intra-bar spike. Wait for the candle close or 2nd drive."

The `TripleAStateMachine` correctly enforces `absorb_bars >= 2` before progressing. But Priority 2 allows entry the moment absorption appears + VWAP band breaches — exactly the first raw spike Fabio warns against.

**Required fix:**
```python
# Remove Priority 2 entirely. Valid Gate 3 paths:
# Path A: Full Triple-A AGGRESSION (3-step + 2-bar accumulation enforced by machine)
if state.triple_a_phase == "AGGRESSION" and state.triple_a_signal is not None:
    if state.triple_a_signal != ctx.agent_direction:
        return GateResult(3, False, "Triple-A direction conflict")
    return GateResult(3, True, "Triple-A AGGRESSION confirmed")

# Path B: IB Second Drive (D1 rejected, D2 re-approach — valid standalone)
if ctx.drive_entry_valid:
    return GateResult(3, True, "IB Second Drive")

# Path C: Impulse Leg LVN retest (Playbook C sniper — NEW)
if ctx.leg_lvn > 0 and abs(float(state.close) - ctx.leg_lvn) <= 2 * ctx.tick_size:
    if state.absorption is not None and state.absorption.bar_age == 0:
        return GateResult(3, True, f"LVN Sniper @ {ctx.leg_lvn:.2f}")

# Path D: OBI depth aggression (valid standalone — live book confirms)
if ctx.obi >= 0.20 and state.close > state.vwap.upper_1:
    return GateResult(3, True, "OBI aggression LONG")
if ctx.obi <= -0.20 and state.close < state.vwap.lower_1:
    return GateResult(3, True, "OBI aggression SHORT")

return GateResult(3, False, "No Triple-A edge")
```

---

### Bug 2 — Impulse Leg LVN Computed But Never Reaches Decisions

**Where computed:** [`analyzer.detect_displacement_leg():374`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/amt/analyzer.py#L374) → `AMTResult` → `_last_amt_dto`

**Where it's missing:** [`quant/decision/context.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/decision/context.py) has no `leg_lvn` field. Gate 3 Path C cannot fire. Playbook C is invisible to the trade engine.

**Fix — 3 files:**

1. **`context.py`** — add field:
```python
leg_lvn: float = 0.0  # Primary LVN from Impulse Leg Profile (Layer 3)
```

2. **`runtime._decide()`** — extract from DTO:
```python
leg_lvn = float(amt_dto.get("legLvn") or 0.0)
# Pass into DecisionContext: leg_lvn=leg_lvn
```

3. **`gates_edge.py`** — add Path C (shown in Bug 1 fix above)

---

### Bug 3 — No Pyramid Hook in `_manage_exit`

**File:** [`quant/runtime.py:611`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/runtime.py#L611)

`_manage_exit` only evaluates exits. There is no branch for pyramid add-ons. Even once the OMS is built, there is no place to call it.

**Required sequence:**
```python
def _manage_exit(self, state, bar) -> None:
    exit_dec = self._exits.evaluate(...)   # 1. Exit check always first
    if exit_dec.should_exit:
        # close + record + emit
        return
    # 2. Only if position survives: check pyramid
    if self._position is not None and self._exits.is_risk_free(self._position):
        self._check_pyramid(state, bar)
```

---

### Bug 4 — `_last_amt_dto` Write Without Lock

**File:** [`quant/runtime.py:884`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/runtime.py#L884)

`_last_amt_dto` is written by the main bar-close thread and can be read by `_decide` during startup while the seed thread is also writing. No lock guards the assignment.

**Fix:**
```python
with self._amt_lock:   # same lock that guards _amt_candles
    self._last_amt_dto = dto
```

---

### Bug 5 — GatePipeline Runs All 4 Gates Even After Gate 1 Fails

**File:** [`quant/decision/pipeline.py:29-33`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/decision/pipeline.py#L29)

All 4 gates run regardless. Gate 3 runs CVD, OBI, and absorption checks even if the session is closed. Minor wasted compute, not a logic error.

**Fix:** `break` after first failure:
```python
for gate_no, run in steps:
    result = run()
    results.append(result)
    if not result.passed:
        break   # short-circuit
```

---

## Part 4 — Complete Prioritized Fix List

### Phase 1 — Quick Wins (1 day, zero regression risk)

| # | Fix | File | Lines |
|---|---|---|---|
| Q1 | Absorption: 0.55 → **0.60** threshold + add close-position guard | [`quant/absorption.py:78`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/absorption.py#L78) | 6 |
| Q2 | Cushion: exact **40%** of PnL dollars (not 20% tier) | [`execution/risk.py:166`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/execution/risk.py#L166) | 15 |
| Q3 | Breakeven: **0.8R** trigger (not 1.0R) | [`execution/exits.py:135`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/execution/exits.py#L135) | 1 |
| Q4 | Lock `_last_amt_dto` write under `_amt_lock` | [`runtime.py:884`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/runtime.py#L884) | 3 |
| Q5 | GatePipeline: short-circuit on first gate failure | [`decision/pipeline.py:29`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/decision/pipeline.py#L29) | 5 |

### Phase 2 — Entry Logic Fixes (2-3 days)

| # | Fix | File | Lines |
|---|---|---|---|
| C1 | Remove Gate 3 Priority 2 bypass | [`decision/gates_edge.py:46`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/decision/gates_edge.py#L46) | 8 |
| C2 | Triple-A aggression: use cluster-high close (not VWAP proxy) | [`quant/triple_a.py:82`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/triple_a.py#L82) | 8 |
| C3 | Wire Impulse Leg LVN → `DecisionContext` → Gate 3 Path C | `context.py` + `runtime.py` + `gates_edge.py` | 20 |

### Phase 3 — Multi-Position Architecture (3-5 days)

| # | Fix | File | Lines |
|---|---|---|---|
| C4 | `PaperOMS.add_pyramid()` + multi-position tracking | [`execution/oms.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/execution/oms.py) | 40 |
| C5 | Multi-tier TP (TP1=50%, TP2=25%, Runner=25%) | `execution/exits.py` + `execution/oms.py` | 60 |
| C6 | `_check_pyramid()` + hook in `_manage_exit` | [`runtime.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/runtime.py) | 40 |

### Phase 4 — Pipeline Unification (3-5 days)

| # | Fix | Action |
|---|---|---|
| A1 | Merge Pipeline A + B | `AuctionCoordinator` consumes `IncrementalVolumeProfile` + `CVDTracker` from `amt/profile/`. Replace `VolumeProfileBuilder` + `OrderFlowBuilder` with unified output. |

### Phase 5 — Deferred Infrastructure

| # | Fix | Why Deferred |
|---|---|---|
| D1 | Range Bar Generator (ATR-dynamic) | Major infrastructure change; time bars are adequate proxy |
| D2 | Layer 2 Compression Box Profile | VAH/VAL gates proxy adequately |

---

## Part 5 — What Is Correct and Must Not Be Changed

| Module | Why It's Correct |
|---|---|
| [`amt/profile/volume_profile.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/amt/profile/volume_profile.py) | CME Two-Row Pairs, VWAP tie-break, session-scoped — exact spec |
| [`amt/profile/lvn.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/amt/profile/lvn.py) | Percentile filter + cluster dedup + strength score — excellent |
| [`amt/profile/classifier.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/amt/profile/classifier.py) | D/P/b/B shape + POC migration — beyond spec |
| [`amt/orderflow/aggression.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/amt/orderflow/aggression.py) | 7-factor FR-06 scoring (FOOTPRINT, CVD, BIG_TRADE, ABSORPTION, OFI, CONFLUENCE, BUBBLE) |
| [`amt/orderflow/drive.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/amt/orderflow/drive.py) | D1/D2/D3+ with rejection + momentum fade — correct |
| [`amt/orderflow/cvd.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/amt/orderflow/cvd.py) | Divergence detection (bull/bear), sign persistence — correct |
| [`amt/session/context.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/amt/session/context.py) | NSE/MCX phase tables, expiry, pre-market — exact |
| [`amt/session/npoc.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/amt/session/npoc.py) | Naked POC tracking across sessions — correct |
| [`execution/risk.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/execution/risk.py) — circuit breakers | 3-loss, 2% daily, 6-trade cap — exact spec |
| [`execution/exits.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/execution/exits.py) — CVD-kill | CVD slope threshold + CVD-driven early breakeven — correct |
| [`execution/exits.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/execution/exits.py) — trailing | 20% giveback, monotonic, breakeven floor — correct |
| [`execution/exits.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/execution/exits.py) — time stop | Session-phase-aware with expiry handling — correct |
| [`decision/signal_builder.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/decision/signal_builder.py) — SL | SL = anchor ± 2×tick (1-2 ticks inside structural level) — exact |
| [`decision/signal_builder.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/decision/signal_builder.py) — TP | NPOC > prior POC > fixed R:R fallback — correct |
| [`decision/va_fade.py`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/decision/va_fade.py) | Playbook B: VA fade with POC target — correct |
| [`runtime._session_allow_entry()`](file:///Users/apple/Documents/v5-of-glassytrade-ai/quant/runtime.py#L519) | Phase table + expiry gate — exact |

---

## Part 6 — Dhan Data Ceiling (Documented, Not Bugs)

| Spec Feature | Requirement | Dhan Limitation | Proxy |
|---|---|---|---|
| Tick aggressor flag | `is_buyer_maker` per trade | Not in WS feed | Direction-attributed (up-tick=buy) |
| Real bubble threshold (30-40 lots) | Print-by-print lot count | No tick-level stream | Candle vol > 1.5×avg |
| True footprint (per-price buy/sell grid) | Tick-by-tick price ladder | No tick feed | Gaussian model per candle range |
| Range bars from tick stream | Tick-by-tick for H_range | Tick aggregation only | Time bars (1m default) |

These are documented in `quant/absorption.py` and `quant/triple_a.py` docstrings. The proxies are the correct engineering response to the data ceiling.

---

> **This document is the single source of truth for all development on the `quant/` engine.**  
> The 12-step pipeline in Part 1 defines what correct looks like.  
> The scorecard in Part 2 shows where we are.  
> The bugs in Part 3 define what must be fixed before anything else.  
> Phase 1 quick-wins in Part 4 can be shipped immediately with no risk.
