# Volume Profile Logic Correctness & Component Analysis

## Reference: Fabio AMT Playbook vs Current UI (localhost)

This document cross-references the three Fabio playbook chart screenshots (NQ futures on Deepchart) against your current localhost UI (BTC PERP) to identify every correctness gap and provide the exact logic each component should use.

---

## Current UI State (From Screenshot)

```
INTELLIGENCE Panel — Fabio Playbook AMT Execution Engine (10X LIVE)

EQUITY:      $10,000,000
OPEN PNL:    +$0.00

01. STATE:       BALANCED / Range Mode      ● (green dot)
02. LOCATION:    VA High    68,334.77
                 POC        68,317.72       (red label)
                 VA Low     68,300.67
                 LVNs       None
03. AGGRESSION:  Delta Score  0.48          (bar ~48%)
    Status:      MONITORING MARKET / Initializing AI Model...
04. MODEL I/O:   PROMPT → MODEL: System Startup
                 MODEL → OUTPUT: No output yet.
05. DECISION HISTORY (1):  FLAT Low  12:43:04 PM

Chart:  BTC PERP at 68,296.61 (current price)
        VAH/POC/VAL lines drawn on chart at ~68,300–68,335 zone
        Price is BELOW the VA (68,296 < VAL 68,300)
```

---

## PROBLEM 1: Volume Profile is Computed Over Wrong Data Window

### What the UI is doing (observed)

The VA range is extremely tight: VAH 68,334 – VAL 68,300 = **only 34 points** (~0.05% of price). Looking at the chart, BTC moved from ~67,850 to ~69,200 (a 1,350-point range) over the visible period. A 34-point value area on a 1,350-point range means the profile is being computed on a **tiny window** — likely just the last few candles or a very recent micro-period.

### What Fabio's playbook requires

From Image 1 (NQ chart), the Value Area spans 21,840 to 21,948 = **108 points** on a 5-min chart covering an entire session. The profile is built from the **previous day's complete session** (or the current session so far).

### Correct Logic

```
VOLUME PROFILE WINDOW SELECTION:

    Option A — Previous Session Profile (primary, used for Location Gate):
        start = previous_session_open_time
        end   = previous_session_close_time
        candles = all candles in [start, end]
        Purpose: establishes the "balance reference" for today's trading

    Option B — Current Session Profile (secondary, developing):
        start = current_session_open_time
        end   = now
        candles = all candles in [start, end]
        Purpose: tracks where today's value is developing

    Option C — Impulse Leg Profile (for LVN detection):
        start = displacement_leg_start_candle
        end   = displacement_leg_end_candle
        candles = only the candles within the displacement move
        Purpose: find LVN reaction points within the impulse

    For BTC (24/7 market):
        "Session" should be defined as a configurable rolling window.
        Recommended: previous 24-hour period OR previous UTC-day candles.
        Alternatively: use the last completed 4h/8h balance region.

    MINIMUM CANDLE COUNT for meaningful profile:
        At least 50–100 candles (on chosen timeframe)
        If < 50 candles available, flag profile as LOW_CONFIDENCE

    CURRENT BUG:
        VA width of 34 pts on a 1,350 pt range suggests the profile
        is being built from ~5-10 candles at most.
        This produces meaningless VAH/VAL/POC.
```

### Fix Priority: **CRITICAL** — Every gate downstream depends on this.

---

## PROBLEM 2: State Classification (01. STATE) — Likely Incorrect

### What the UI shows

`BALANCED / Range Mode` with a green indicator, while current price (68,296) is **below** the VAL (68,300) and the chart shows price having dropped ~1,350 points from the high of 69,200 to 67,850 before bouncing.

### What this should look like

Looking at the chart: price crashed from 69,200 to 67,850 (a massive drop), then bounced to ~68,300. This is clearly an **imbalanced market** — there was a displacement leg down, and price is now attempting to recover. Classifying this as "BALANCED" is incorrect given the visible price action.

### Correct State Classification Logic

```
INPUTS:
    prev_session_profile: VolumeProfile  (VAH, VAL, POC from previous session)
    recent_candles: list[Candle]         (last N candles, e.g., 50–100)
    current_price: float

STEP 1 — Check if price is within previous value area:
    inside_va = (prev_session.VAL <= current_price <= prev_session.VAH)

STEP 2 — Check rotation ratio (how much time spent inside VA recently):
    candles_inside_va = count(c for c in recent_candles
                              if prev_session.VAL <= c.close <= prev_session.VAH)
    rotation_ratio = candles_inside_va / len(recent_candles)

STEP 3 — Check for displacement leg:
    displacement = detect_displacement_leg(recent_candles)
    # See Section 6 of the formulas doc:
    # 3+ candles, range >= 1.5× avg, closes near extremes

STEP 4 — Check acceptance:
    closes_above_vah = count consecutive candles where close > prev_session.VAH
    closes_below_val = count consecutive candles where close < prev_session.VAL
    accepted_above = closes_above_vah >= 2
    accepted_below = closes_below_val >= 2

STEP 5 — Classify:
    IF rotation_ratio >= 0.70 AND NOT displacement.detected:
        state = BALANCED
        mode = "Range Mode"

    ELIF displacement.detected AND (accepted_above OR accepted_below):
        state = IMBALANCED
        mode = "Trending — Accepted"
        trend_direction = displacement.direction

    ELIF displacement.detected AND NOT (accepted_above OR accepted_below):
        state = TRANSITIONING
        mode = "Breakout Attempt — Unconfirmed"

    ELIF NOT inside_va AND rotation_ratio < 0.30:
        state = IMBALANCED
        mode = "Out of Value"
        trend_direction = "BULLISH" if current_price > prev_session.VAH else "BEARISH"

    ELSE:
        state = BALANCED
        mode = "Range Mode"

FOR YOUR BTC CHART:
    Price dropped from 69,200 to 67,850 = massive displacement down.
    Current price 68,296 is BELOW the displayed VAL (68,300).
    Even with the narrow profile, price is outside VA.
    State should be: IMBALANCED or at minimum TRANSITIONING.
    "BALANCED / Range Mode" is wrong here.

    The root cause may be the profile window issue (Problem 1):
    if the profile is being built from only recent candles,
    the "value area" shifts to wherever price currently is,
    making everything look "balanced" by definition.
    Fix the profile window FIRST, then the state classification
    will likely become correct.
```

---

## PROBLEM 3: Location Gate (02. LOCATION) — Missing Key Data

### What the UI shows

```
VA High:  68,334.77
POC:      68,317.72
VA Low:   68,300.67
LVNs:     None
```

### Issues

1. **LVNs = None:** This is the most critical missing piece. Fabio's entire entry logic revolves around LVNs. If no LVNs are detected, no trade can be taken in either model. From Images 1 and 3, LVNs are clearly visible in the volume profile as thin areas within the histogram. The "None" likely means either:
   - The profile window is too small to produce meaningful LVNs (back to Problem 1)
   - The LVN detection threshold is too aggressive
   - LVN detection is not implemented

2. **No previous session levels shown:** Fabio uses the previous session's VAH/VAL/POC as the primary location reference. The UI only shows one set of levels — unclear if these are current or previous session.

3. **No impulse leg profile levels:** When a displacement leg occurs, Fabio builds a *separate* volume profile on just that leg to find LVNs within the impulse. This doesn't appear to be implemented.

4. **No distance-to-level indicator:** The UI should show how far current price is from each level (in ticks and %).

### Correct Location Logic

```
LOCATION GATE OUTPUT should contain:

    previous_session:
        VAH:  float   (yesterday's or previous period's VA high)
        POC:  float   (yesterday's POC — primary target level)
        VAL:  float   (yesterday's VA low)

    current_session:
        VAH:  float   (developing today's VA high)
        POC:  float   (developing today's POC)
        VAL:  float   (developing today's VA low)

    impulse_leg_profile (if displacement detected):
        leg_POC:  float
        leg_VAH:  float
        leg_VAL:  float
        leg_LVNs: list[LVNZone]  ← THIS IS THE KEY MISSING PIECE

    all_lvns: list[LVNZone]
        Each LVN zone:
            center_price: float
            zone_low:  center - buffer
            zone_high: center + buffer
            volume_at_node: float (should be low relative to surrounding bins)
            source: "previous_session" | "impulse_leg" | "current_session"

    nearest_level:
        level_type:    "VAH" | "VAL" | "POC" | "LVN"
        level_price:   float
        distance:      float (in price units)
        distance_pct:  float (as % of price)
        within_buffer: bool  (is price within the tradeable buffer zone?)

LVN DETECTION FIX:

    The profile MUST have enough bins and enough candles to produce
    meaningful peaks and valleys. With only 34 points of VA width,
    the histogram has insufficient resolution.

    Required: profile range of at least 0.5–2% of price
    For BTC at 68,000: minimum profile range ~340–1,360 points.
    Current: 34 points = 0.05% — 10× too narrow.

    LVN detection algorithm (from Section 4 of formulas doc):
        1. Build histogram with N = 100–200 bins
        2. Smooth: kernel size 3 (or Gaussian)
        3. Find local minima where volume < 0.3 × mean
        4. Each minimum becomes an LVN zone with buffer

    For BTC (wide spreads):
        buffer = 5–10 ticks (or 0.05–0.1% of price)
    For NSE futures:
        buffer = 2–3 ticks
```

---

## PROBLEM 4: Aggression Gate (03. AGGRESSION) — Incomplete

### What the UI shows

```
Delta Score: 0.48  (with a green bar showing ~48%)
```

### Issues

1. **Single metric instead of a bundle:** Fabio's confirmation gate requires ≥ 2 of 3 conditions (spread tightness, volume impulse, pressure proxy). The UI shows only a single "Delta Score" with no breakdown.

2. **No directional context:** The delta score of 0.48 gives no information about direction. Is buying or selling dominant? Fabio needs to know if aggression aligns with the *expected trade direction*.

3. **Threshold unclear:** 0.48 out of what scale? Is 0 = no delta, 1 = maximum? The playbook needs specific thresholds tied to the confirmation bundle.

4. **Missing sub-components:** No spread indicator, no volume impulse indicator, no OI/pressure proxy.

### Correct Aggression / Confirmation Logic

```
CONFIRMATION GATE OUTPUT should contain:

    THREE SUB-SCORES (require >= 2 to pass):

    1. spread_tightness:
        current_spread: float     (bid-ask spread in absolute terms)
        spread_pct: float         (spread as % of price)
        threshold: float          (configured per instrument)
        passed: bool              (current_spread <= threshold)

        For BTC PERP:
            typical spread: 0.01–0.05% (varies by exchange)
            threshold: 0.05% (crypto is wider than futures)

    2. volume_impulse:
        current_volume: float     (current candle or recent N candles)
        avg_volume: float         (20-period rolling average)
        ratio: float              (current / avg)
        multiplier_threshold: 1.5 (configurable)
        passed: bool              (ratio >= multiplier_threshold)

    3. pressure_proxy:
        candle_delta: float       (buy_vol - sell_vol for current candle)
        cvd_direction: str        ("RISING" | "FALLING" | "FLAT")
        oi_change: float | None   (if available from exchange)
        signal_direction: str     (BUY or SELL — what the Location+State suggest)
        aligned: bool             (is pressure in same direction as signal?)
        passed: bool

        For BTC PERP:
            If signal_direction == BUY:
                passed = (candle_delta > 0 AND cvd_direction == "RISING")
            If signal_direction == SELL:
                passed = (candle_delta < 0 AND cvd_direction == "FALLING")

    BUNDLE SCORE:
        score = int(spread_passed) + int(volume_passed) + int(pressure_passed)
        confirmation_passed = (score >= 2)

    DIRECTIONAL DELTA SCORE (what the UI should show):
        Instead of a single 0–1 number, show:
        - Delta direction: BUY_DOMINANT | SELL_DOMINANT | NEUTRAL
        - Delta strength: 0.0–1.0 (how strong the dominance is)
        - Bundle result: "2/3 PASSED" or "1/3 — WAITING"

UI DISPLAY FIX:
    Current:  "Delta Score 0.48" (single bar, no context)

    Should be:
    ┌─────────────────────────────────────────┐
    │ 03. AGGRESSION                          │
    │                                         │
    │  Spread:    0.02%  ✅ (< 0.05%)        │
    │  Volume:    1.8×   ✅ (> 1.5× avg)     │
    │  Pressure:  +0.48  ❌ (weak, neutral)   │
    │                                         │
    │  Bundle: 2/3 PASSED                     │
    │  Direction: BUY-leaning                 │
    └─────────────────────────────────────────┘
```

---

## PROBLEM 5: Model Selection Missing

### What the UI shows

No explicit model selection indicator. The "MONITORING MARKET / Initializing AI Model..." status and the decision "FLAT Low" give no indication of which model (Trend Continuation vs Mean Reversion) is active or being considered.

### What's needed

```
MODEL SELECTION OUTPUT:

    Based on the State classification:

    IF state == IMBALANCED + displacement + acceptance:
        active_model = TREND_CONTINUATION
        UI shows: "TREND MODEL — Seeking continuation at LVN"

    ELIF state == BALANCED OR breakout_failed:
        active_model = MEAN_REVERSION
        UI shows: "REVERSION MODEL — Watching for failed breakout"

    ELIF state == TRANSITIONING:
        active_model = NONE
        UI shows: "WAITING — Breakout unconfirmed"

    ELSE:
        active_model = NONE
        UI shows: "FLAT — No setup conditions"

UI DISPLAY FIX:
    Add a section between Location and Aggression:

    ┌─────────────────────────────────────────┐
    │ ACTIVE MODEL                            │
    │                                         │
    │  🔴 TREND CONTINUATION                  │
    │  Market out of balance, displacement    │
    │  detected, seeking LVN pullback entry   │
    │                                         │
    │  OR                                     │
    │                                         │
    │  🔵 MEAN REVERSION                      │
    │  Failed breakout detected, watching     │
    │  for reclaim + LVN entry back to POC    │
    │                                         │
    │  OR                                     │
    │                                         │
    │  ⚪ NO MODEL ACTIVE                     │
    │  Conditions not met for either setup    │
    └─────────────────────────────────────────┘
```

---

## PROBLEM 6: Decision Output Lacks Explainability

### What the UI shows

```
05. DECISION HISTORY (1):  FLAT  Low  12:43:04 PM
```

### Issues

1. **"Low" is ambiguous** — does it mean "low confidence" or "low priority"?
2. **No gate-by-gate breakdown** — which gate failed? Why is the system FLAT?
3. **No "why no trade" explanation** — Fabio's entire edge is knowing *why* you're not trading.

### Correct Decision Output

```
DECISION OUTPUT should contain:

    ┌─────────────────────────────────────────────────┐
    │ 05. DECISION                                    │
    │                                                 │
    │  Signal:  FLAT (no trade)                       │
    │  Time:    12:43:04 PM                           │
    │                                                 │
    │  Gate Breakdown:                                │
    │  ✅ State:        IMBALANCED (bearish)          │
    │  ❌ Location:     Not at level                  │
    │     Nearest: VAL 68,300 — 4 pts away (0.006%)  │
    │  ⏸️ Confirmation: Not evaluated (location fail)  │
    │                                                 │
    │  Reason: Price not yet at a tradeable level.    │
    │  Watching: VAL (68,300), LVN (67,950) below     │
    └─────────────────────────────────────────────────┘

    OR when all gates pass:

    ┌─────────────────────────────────────────────────┐
    │  Signal:  SHORT (Mean Reversion)                │
    │  Time:    12:47:22 PM                           │
    │                                                 │
    │  ✅ State:        Failed breakout detected      │
    │  ✅ Location:     At VAH (68,334) within buffer │
    │  ✅ Confirmation: 2/3 (spread ✅, volume ✅)    │
    │                                                 │
    │  Entry:   68,330                                │
    │  Stop:    68,350 (+20 pts, behind failed high)  │
    │  Target:  68,317 (POC, -13 pts)                 │
    │  R:R:     1:0.65 — ⚠️ Below minimum 1:1.5      │
    │  Status:  BLOCKED (R:R too low)                 │
    └─────────────────────────────────────────────────┘
```

---

## PROBLEM 7: Chart Overlay Gaps

### What the UI chart shows

- VAH, POC, VAL drawn as horizontal lines (yellow/green/red labels on chart)
- Standard candlestick chart
- A small volume profile histogram visible on the left edge of the chart
- Toggle between "Candles" and "Footprint" views

### What's missing on the chart

```
REQUIRED CHART OVERLAYS:

    1. Previous session VA zone (shaded rectangle):
        Draw a semi-transparent rectangle from prev_session.VAL to prev_session.VAH
        across the entire chart width.
        Color: subtle blue/gray shading
        Purpose: instantly see if price is inside or outside value

    2. Current session developing VA (different color):
        Draw developing VA as it updates each candle.
        Color: subtle green/yellow shading

    3. LVN zones (highlighted bands):
        Each detected LVN drawn as a narrow horizontal band
        Color: orange/amber
        Width: the buffer zone (e.g., ±5 ticks around center)
        Label: "LVN" with price
        Purpose: these are the exact entry zones for both models

    4. Displacement leg marking:
        When a displacement leg is detected, highlight those candles:
        Draw a bracket or shaded region over the leg candles
        Show the leg's range and direction
        Label: "DISPLACEMENT ↑" or "DISPLACEMENT ↓"

    5. Balance range box:
        When state == BALANCED, draw a box around the balance range
        (similar to what Image 1 shows — the white rectangle)
        Top: session high or VAH
        Bottom: session low or VAL
        Purpose: see exactly where "balance" is

    6. Entry/Stop/Target lines (when signal active):
        Entry level: green dashed line
        Stop loss: red dashed line
        Target: blue dashed line
        With distance labels (points and R-multiple)

FOOTPRINT VIEW REQUIREMENTS (when toggled):
    From Image 2, Fabio uses bubble charts showing:
    - Green bubbles: buy aggression (size = volume)
    - Red bubbles: sell aggression (size = volume)
    This is standard order flow visualization.

    The footprint view should overlay:
    - Volume delta per candle (green/red split)
    - Large print highlights (bubbles above threshold)
    - CVD line or indicator below the chart
```

---

## PROBLEM 8: Specific BTC Chart Analysis — What the System SHOULD Be Saying

Looking at your BTC chart state right now:

```
WHAT HAPPENED:
    Price was at ~69,200
    Dropped to ~67,850 (displacement leg DOWN, ~1,350 pts / ~2%)
    Bounced to ~68,500
    Dropped again to ~68,000
    Currently at 68,296

IF the profile were correctly computed over the previous 24h session:
    The VA would likely be centered around 68,500-69,000 area
    (where most volume traded during the consolidation before the drop)
    Current price at 68,296 would be BELOW the VA

CORRECT STATE:
    IMBALANCED — Bearish displacement detected
    (3+ candles of strong downward movement, closes near lows)

    OR if the initial drop is "old" and price has been rotating:
    TRANSITIONING — Price below value, monitoring for acceptance

CORRECT LOCATION:
    Previous session POC: likely ~68,800–69,000 range
    Previous session VAL: likely ~68,400–68,500
    Current price (68,296) is BELOW previous session VAL
    → Price is outside value to the downside
    → For TREND model: look for LVNs in the displacement leg for short entries
    → For REVERSION model: watch if price reclaims VAL and enters VA

CORRECT AGGRESSION:
    Delta Score 0.48 suggests roughly neutral buying/selling
    → No strong directional aggression
    → Confirmation gate would likely FAIL (no clear aggression)

CORRECT DECISION:
    FLAT — Model conditions partially met but:
    - Location: not at a key level (no LVNs detected with current narrow profile)
    - Aggression: neutral (no directional confirmation)
    Reason: "Monitoring. Price below value area. Awaiting LVN touch
             or VA reclaim for entry setup."
```

---

## Complete Component Logic Summary

### End-to-End Pipeline (What Should Run on Each New Candle)

```
ON_NEW_CANDLE(candle):

    ┌─────────────────────────────────────────────────────────────┐
    │ STEP 0: UPDATE VOLUME PROFILE                               │
    │                                                             │
    │ Input:  new candle + all session candles                    │
    │                                                             │
    │ a) Update PREVIOUS SESSION profile (recompute once/day):   │
    │    - Use all candles from previous session                  │
    │    - Compute: VAH, VAL, POC, HVNs, LVNs                   │
    │    - This is the "balance reference"                        │
    │                                                             │
    │ b) Update CURRENT SESSION profile (incremental):           │
    │    - Add new candle's volume to bins                        │
    │    - Recheck POC                                            │
    │    - Recompute VA if POC changed                            │
    │    - Update developing dPOC                                 │
    │                                                             │
    │ c) If displacement detected, build LEG PROFILE:            │
    │    - Profile of only the displacement candles               │
    │    - Detect LVNs within the leg                             │
    │                                                             │
    │ Output: prev_profile, current_profile, leg_profile          │
    │         all_levels = [prev.VAH, prev.POC, prev.VAL,        │
    │                       leg.LVNs, current.VAH, current.POC]  │
    └─────────────────────────────────────────────────────────────┘
                              │
                              ▼
    ┌─────────────────────────────────────────────────────────────┐
    │ STEP 1: MARKET STATE GATE                                   │
    │                                                             │
    │ Input:  prev_profile, recent_candles, current_price         │
    │                                                             │
    │ Compute:                                                    │
    │   rotation_ratio = candles_inside_prev_VA / total_candles   │
    │   displacement = detect_displacement_leg(candles)           │
    │   acceptance = count_consecutive_closes_beyond_VA()         │
    │                                                             │
    │ Output: MarketStateDecision                                 │
    │   { state: BALANCED|IMBALANCED|TRANSITIONING,              │
    │     mode: str,                                             │
    │     displacement: DisplacementInfo|None,                    │
    │     accepted: bool,                                         │
    │     rotation_ratio: float,                                  │
    │     reason: str }                                          │
    │                                                             │
    │ → UI shows: "01. STATE: IMBALANCED / Trending Down"        │
    └─────────────────────────────────────────────────────────────┘
                              │
                              ▼
    ┌─────────────────────────────────────────────────────────────┐
    │ STEP 2: MODEL SELECTION                                     │
    │                                                             │
    │ Input:  market_state_decision                               │
    │                                                             │
    │ IF IMBALANCED + displacement + accepted:                   │
    │     model = TREND_CONTINUATION                              │
    │                                                             │
    │ ELIF BALANCED or breakout_failed:                           │
    │     model = MEAN_REVERSION                                  │
    │                                                             │
    │ ELSE:                                                       │
    │     model = NONE                                            │
    │                                                             │
    │ → UI shows: "MODEL: TREND / REVERSION / NONE"              │
    └─────────────────────────────────────────────────────────────┘
                              │
                              ▼
    ┌─────────────────────────────────────────────────────────────┐
    │ STEP 3: LOCATION GATE                                       │
    │                                                             │
    │ Input:  current_price, all_levels, model, instrument_config │
    │                                                             │
    │ For each level in all_levels:                               │
    │   distance = |current_price - level.price|                  │
    │   within_buffer = distance <= buffer_ticks × tick_size      │
    │                                                             │
    │ at_level = any level within buffer                           │
    │ nearest = level with minimum distance                       │
    │                                                             │
    │ TREND model specific:                                       │
    │   Prioritize LVNs from displacement leg profile             │
    │   Also check prev_session.VAH/VAL                           │
    │                                                             │
    │ REVERSION model specific:                                   │
    │   Check if price has re-entered VA after failed breakout    │
    │   Prioritize LVNs from reclaim leg profile                 │
    │   Also check prev_session.VAH/VAL                           │
    │                                                             │
    │ Output: LocationDecision                                    │
    │   { at_level: bool,                                        │
    │     level_type: "VAH"|"VAL"|"POC"|"LVN"|"NONE",           │
    │     level_price: float,                                     │
    │     distance: float,                                        │
    │     distance_pct: float,                                    │
    │     within_buffer: bool,                                    │
    │     all_levels_with_distances: list,                        │
    │     reason: str }                                          │
    │                                                             │
    │ → UI shows: "02. LOCATION" with all levels + distances     │
    │   If not at level: "Nearest: VAL 68,300 — 4 pts away"     │
    │   If at level: "AT LVN 68,310 ✅ (within 5-tick buffer)"  │
    └─────────────────────────────────────────────────────────────┘
                              │
                              ▼
    ┌─────────────────────────────────────────────────────────────┐
    │ STEP 4: CONFIRMATION GATE (only if location passed)        │
    │                                                             │
    │ Input:  current_candle, rolling_averages, depth_data        │
    │                                                             │
    │ Sub-score 1 — Spread:                                       │
    │   spread = ask - bid                                        │
    │   spread_pct = spread / mid_price                           │
    │   spread_ok = spread_pct <= threshold                       │
    │                                                             │
    │ Sub-score 2 — Volume Impulse:                               │
    │   vol_ratio = current_volume / avg_volume_20                │
    │   volume_ok = vol_ratio >= 1.5                              │
    │                                                             │
    │ Sub-score 3 — Pressure/Delta:                               │
    │   candle_delta = buy_vol - sell_vol                          │
    │   For BUY signal: pressure_ok = candle_delta > 0            │
    │   For SELL signal: pressure_ok = candle_delta < 0           │
    │                                                             │
    │ bundle_score = spread_ok + volume_ok + pressure_ok          │
    │ passed = bundle_score >= 2                                  │
    │                                                             │
    │ Output: ConfirmationDecision                                │
    │   { passed, score, spread_ok, volume_ok, pressure_ok,      │
    │     spread_value, vol_ratio, delta_value, reason }         │
    │                                                             │
    │ → UI shows: "03. AGGRESSION: 2/3 PASSED"                  │
    │   with breakdown of each sub-score                          │
    └─────────────────────────────────────────────────────────────┘
                              │
                              ▼
    ┌─────────────────────────────────────────────────────────────┐
    │ STEP 5: AGGRESSION CHECK (only if confirmation passed)     │
    │                                                             │
    │ This is the final directional confirmation.                │
    │ From Fabio: "Only enter when you see aggression.            │
    │  No aggression = no trade."                                │
    │                                                             │
    │ TREND model:                                                │
    │   For LONG: bullish candle + delta > 0 + close in upper 40%│
    │   For SHORT: bearish candle + delta < 0 + close in lower 40│
    │                                                             │
    │ REVERSION model:                                            │
    │   For SHORT (fading upside): sellers showing up,           │
    │     bearish candle + delta < 0 + price back inside VA      │
    │   For LONG (fading downside): buyers showing up,           │
    │     bullish candle + delta > 0 + price back inside VA      │
    │                                                             │
    │ Output: aggression_confirmed (bool), direction, reason     │
    └─────────────────────────────────────────────────────────────┘
                              │
                              ▼
    ┌─────────────────────────────────────────────────────────────┐
    │ STEP 6: SIGNAL GENERATION                                   │
    │                                                             │
    │ IF state_passed AND location_passed AND confirmation_passed │
    │    AND aggression_confirmed:                                │
    │                                                             │
    │     signal = direction (BUY or SELL)                        │
    │     Compute: entry, stop, target, size, R:R                │
    │                                                             │
    │ ELSE:                                                       │
    │     signal = FLAT                                           │
    │     Include full gate breakdown showing which gate(s) failed│
    │                                                             │
    │ → UI Decision History shows signal + gate breakdown         │
    └─────────────────────────────────────────────────────────────┘
```

---

## Priority Fix List (Ordered by Impact)

| Priority | Component | Issue | Fix |
|---|---|---|---|
| **P0** | Volume Profile Window | Profile built on too few candles → 34pt VA on 1,350pt range | Use previous session (24h for BTC) as the profile window |
| **P0** | LVN Detection | LVNs = None always | Fix profile window first, then verify LVN detection algorithm with smoothing + threshold |
| **P1** | State Classification | Shows BALANCED when price is clearly below VA after displacement | Implement displacement detection + acceptance rules + rotation ratio |
| **P1** | Confirmation Gate | Single "Delta Score" instead of 3-component bundle | Implement spread + volume impulse + pressure as separate sub-scores |
| **P2** | Model Selection | No model indicator | Add TREND/REVERSION/NONE selection based on state output |
| **P2** | Decision Explainability | "FLAT Low" with no context | Show gate-by-gate breakdown (which passed, which failed, why) |
| **P2** | Previous vs Current Session | Only one set of VA levels shown | Show both previous session levels (reference) and developing levels |
| **P3** | Chart Overlays | Missing LVN zones, VA shading, displacement marking | Add overlay layers for all key levels |
| **P3** | Distance to Level | No indication of how far price is from nearest level | Show distance in points and % for each level |
| **P3** | Entry/Stop/Target | Not shown on chart when signal is active | Draw entry/SL/TP as dashed lines with labels |

---

## UI Panel Redesign Recommendation

```
┌──────────────────────────────────────────────┐
│ FABIO PLAYBOOK          10X LIVE             │
│ AMT EXECUTION ENGINE                         │
│                                              │
│ EQUITY: $10,000,000    OPEN PNL: +$0.00     │
├──────────────────────────────────────────────┤
│ 01. STATE                                    │
│ ┌──────────────────────────────────────────┐ │
│ │ IMBALANCED ↓                         🔴 │ │
│ │ Bearish displacement detected            │ │
│ │ Rotation: 25% inside VA (< 70%)         │ │
│ │ Acceptance: 3 closes below VAL ✅       │ │
│ └──────────────────────────────────────────┘ │
├──────────────────────────────────────────────┤
│ 02. MODEL                                    │
│ ┌──────────────────────────────────────────┐ │
│ │ TREND CONTINUATION (SHORT)               │ │
│ │ Seeking pullback to LVN for short entry  │ │
│ └──────────────────────────────────────────┘ │
├──────────────────────────────────────────────┤
│ 03. LOCATION                                 │
│ ┌──────────────────────────────────────────┐ │
│ │ Previous Session:                        │ │
│ │   VAH   69,050   ▲ 754 pts (1.10%)      │ │
│ │   POC   68,800   ▲ 504 pts (0.74%)      │ │
│ │   VAL   68,500   ▲ 204 pts (0.30%)      │ │
│ │                                          │ │
│ │ Displacement Leg LVNs:                   │ │
│ │   LVN₁  68,650   ▲ 354 pts (0.52%)      │ │
│ │   LVN₂  68,380   ▲  84 pts (0.12%)  ⚡  │ │
│ │   LVN₃  68,100   ▼ 196 pts (0.29%)      │ │
│ │                                          │ │
│ │ Status: NOT at level                     │ │
│ │ Nearest: LVN₂ at 68,380 (84 pts away)   │ │
│ └──────────────────────────────────────────┘ │
├──────────────────────────────────────────────┤
│ 04. AGGRESSION                               │
│ ┌──────────────────────────────────────────┐ │
│ │ Spread:    0.03%  ✅ (< 0.05%)          │ │
│ │ Volume:    0.9×   ❌ (< 1.5× avg)       │ │
│ │ Pressure:  -0.12  ❌ (weak selling)      │ │
│ │                                          │ │
│ │ Bundle: 1/3 — NOT CONFIRMED              │ │
│ └──────────────────────────────────────────┘ │
├──────────────────────────────────────────────┤
│ 05. DECISION                                 │
│ ┌──────────────────────────────────────────┐ │
│ │ FLAT — No trade                          │ │
│ │                                          │ │
│ │ ✅ State:     IMBALANCED (bearish)       │ │
│ │ ❌ Location:  Not at level               │ │
│ │ ⏸️ Confirm:   Not evaluated              │ │
│ │                                          │ │
│ │ Watching: LVN₂ (68,380) for short entry  │ │
│ │ Target would be: POC (68,800)            │ │
│ └──────────────────────────────────────────┘ │
├──────────────────────────────────────────────┤
│ 06. TRADE HISTORY                            │
│ ┌──────────────────────────────────────────┐ │
│ │ No closed trades for BTC                 │ │
│ └──────────────────────────────────────────┘ │
└──────────────────────────────────────────────┘
```
