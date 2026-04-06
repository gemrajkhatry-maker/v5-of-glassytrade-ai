<img src="https://r2cdn.perplexity.ai/pplx-full-logo-primary-dark%402x.png" style="height:64px;margin-right:32px"/>

# give me next phase

Continuing from Phase 3 Component 2 (IV/VIX/PCR features were being specified). Completing Phase 3, then Phase 4 and Phase 5 in full.

***

# PHASE 3 — "Intelligence Upgrade" (Continued)

## ML Validation + IV/VIX/PCR + LLM Restructure


***

### P3 Component 2: New Features — Completion

#### Total Feature Vector After Phase 3

```
RETAINED FROM PHASE 0 (41 features — after duplicate removal):
  Volume Profile:     5 (removed market_state_encoded duplicate)
  Order Flow:         8 (now using real Lee-Ready delta)
  Price Action:       12
  Market State:       6
  Time/Session:       4
  Order Book:         6

NEW IN PHASE 3 (+6 features):
  india_vix_normalized        → VIX / 20.0
  vix_regime                  → 0/1/2/3 categorical (LOW/NORMAL/ELEVATED/SPIKE)
  iv_rank                     → 0-100 scale per underlying
  iv_percentile               → 0-100 percentile vs 20-day history
  pcr_oi                      → put OI / call OI ratio
  pcr_signal_normalized       → (pcr - 0.95) / 0.95

IB ENGINE FEATURES (from Phase 2, added to vector now):
  ib_location                 → -1 / 0 / 1 (BELOW / INSIDE / ABOVE)
  ib_width_pct                → IB width as % of ATR(5) — regime width signal
  ib_position_pct             → (price - IB_LOW) / IB_WIDTH

TOTAL FEATURE COUNT: 41 + 6 + 3 = 50 features
```


#### Feature Data Refresh Schedule

```
india_vix_normalized:    updated every tick (VIX is a live index)
vix_regime:              updated every tick
iv_rank:                 updated at session open + every 30 min
iv_percentile:           updated at session open + every 30 min
pcr_oi:                  updated every 5 min (option chain refresh)
pcr_signal_normalized:   derived from pcr_oi — same refresh
ib_location:             updated every bar (real-time post IB completion)
ib_width_pct:            set once at IB completion (09:45 NSE / 09:30 MCX)
ib_position_pct:         updated every bar
```


***

### P3 Component 3: LLM Full Restructure Specification

**Current state**: `llm_entry_handler.py` (983 lines) mixing entry gate + overseer + advisory. Already partially addressed in Phase 0 decomposition. Phase 3 completes the restructure with proper prompt engineering for all 3 roles.[^1]

#### Role 1 — PreCandleAdvisor (9-section prompt → 5-section prompt)

**Current 9-section prompt is too long** — causes LLM to ramble, max_tokens=120 cuts important content. Redesign:

```
OPTIMISED 5-SECTION PROMPT STRUCTURE:

SECTION 1 — MARKET CONTEXT (2 lines max)
  Format: "{symbol} | {market_state} | Price {current_price} | POC {poc} | VAH {vah} | VAL {val}"
  Format: "Session {minutes_since_open}min | IB {ib_location} | VIX {vix_regime} | PCR {pcr}"

SECTION 2 — PRICE LOCATION (1 line max)
  Format: "Price is {X} ticks {above/below} {nearest_level} ({level_type})"
  Example: "Price is 8 ticks above VAH (potential failed breakout territory)"

SECTION 3 — ORDER FLOW STATE (1 line max)
  Format: "CVD slope {slope:.1f} ({direction}) | Aggression {score:.1f}/4.5 | Delta {delta_normalized:.2f}"

SECTION 4 — ML SIGNAL (1 line max)
  Format: "ML: P(long)={prob_long:.2f} | P(short)={prob_short:.2f} | Playbook={playbook}"

SECTION 5 — QUESTION (1 line max)
  Always identical: "What is the most likely next scenario and key level to watch?"

RESPONSE FORMAT (strict JSON):
  {
    "scenario": "TREND_CONTINUATION | MEAN_REVERSION | CONSOLIDATION | AVOID",
    "key_level": <float>,
    "level_type": "LVN | VAH | VAL | POC | IB_HIGH | IB_LOW",
    "bias": "LONG | SHORT | NEUTRAL",
    "confidence": 0.0-1.0,
    "note": "<15 words max>"
  }

TEMPERATURE: 0.25 (reduced from 0.4 — more deterministic classification)
MAX TOKENS: 60 (reduced — JSON fits in 60 tokens)
TIMEOUT: 10s (reduced — simpler prompt = faster response)
```

**Key change**: Advisory output goes to React dashboard `Scenario Panel` only. No gate reads it. No position decision uses it. It is purely informational for the human operator.

***

#### Role 2 — PositionOverseer (refine existing — keep structure, fix prompt)

**Current problem**: Prompt is 9 sections → too long → max_tokens=120 truncates the reasoning → JSON output sometimes malformed.

```
OPTIMISED OVERSEER PROMPT STRUCTURE:

SECTION 1 — POSITION STATE (2 lines max)
  "{symbol} {direction} | Entry {entry_price} | Current {current_price}"
  "PnL {pnl_r:.2f}R ({pnl_inr:,.0f} INR) | Time held {bars_held} bars | SL {sl_price} | TP {tp_price}"

SECTION 2 — CURRENT FLOW (1 line max)
  "CVD slope {slope:.1f} ({state}) | Aggression {score:.1f} | Delta {delta_normalized:.2f}"

SECTION 3 — CONTEXT (1 line max)
  "Price vs VWAP: {close_vs_vwap_pct:.2%} | VIX regime: {vix_regime} | Bars to session end: {bars_remaining}"

SECTION 4 — QUESTION (fixed)
  "Overseer action: HOLD, TIGHTEN_SL, PARTIAL_EXIT, or FULL_EXIT?"

RESPONSE FORMAT (strict JSON):
  {
    "action": "HOLD | TIGHTEN_SL | PARTIAL_EXIT | FULL_EXIT",
    "new_sl": <float | null>,
    "reason": "<10 words max>"
  }

TEMPERATURE: 0.2 (highly deterministic — action must be consistent)
MAX TOKENS: 40 (action + new_sl + 10-word reason fits in 40 tokens)
TIMEOUT: 12s (keep — overseer has 3s cycle, 12s timeout is acceptable)
DEFAULT ON TIMEOUT: HOLD (never exit on timeout — position stays open)
```

**Overseer trigger conditions** (refine existing):

```
TRIGGER overseer call ONLY when:
  Condition A: position is open for > 2 bars AND no recent overseer call (> 3s ago)
  Condition B: CVD kill signal fired (slope reversal > 40 units)
  Condition C: PnL crosses +1R milestone (first time only)
  Condition D: PnL crosses -0.5R (position in trouble)
  Condition E: price approaches TP within 5 ticks

DO NOT trigger when:
  Overseer already running for this position (concurrent call guard)
  Position was opened < 1 bar ago (too early to evaluate)
  Session end within 15 minutes (let time stop handle it)
```


***

#### Role 3 — PostTradeAnalyst (redesign for learning)

**Purpose**: Builds a learning loop. Each closed trade generates an analysis that feeds the LLM fine-tuning dataset over time.

```
PROMPT STRUCTURE (triggered on PositionClosed event):

SECTION 1 — TRADE SUMMARY
  "Trade: {symbol} {direction} | Entry {entry_price} → Exit {exit_price}"
  "PnL: {pnl_r:.2f}R ({pnl_inr:,.0f} INR) | Hold: {hold_bars} bars"
  "Setup: {playbook} | Drive: D{drive_number} | Tier: {risk_tier}"
  "Exit reason: {exit_reason}"

SECTION 2 — ENTRY CONDITIONS
  "At entry: Market={market_state} | Aggression={aggression_score}/4.5 | ML P={ml_prob:.2f}"
  "Gate rejections before signal: {rejected_gates_list}"

SECTION 3 — EXIT CONDITIONS
  "At exit: CVD slope={cvd_slope:.1f} | Delta={delta_normalized:.2f} | PnL={pnl_r:.2f}R"

SECTION 4 — QUESTION
  "Evaluate: Was this a good Fabio AMT setup? What could have been done better?"

RESPONSE FORMAT:
  {
    "quality_score": 1-5,
    "setup_correct": true | false,
    "entry_timing": "EARLY | CORRECT | LATE",
    "exit_timing": "EARLY | CORRECT | LATE",
    "mistake": "<20 words or null>",
    "improvement": "<20 words or null>",
    "fabio_rule_violated": "<rule name or null>"
  }

TEMPERATURE: 0.35 (some creativity for improvement notes)
MAX TOKENS: 100
TIMEOUT: 25s (post-trade — no latency concern)
STORAGE: save to trades table as llm_analysis JSON column → feeds fine-tune dataset
```


***

### P3 Component 4: LLM Fine-Tuning Dataset Construction

**Every PostTradeAnalyst response** that has `quality_score ≥ 4` and `setup_correct = true` becomes a training example for the next LoRA fine-tune cycle.

#### Dataset Schema

```
FINE-TUNE SAMPLE STRUCTURE:
  instruction: "Analyse this NSE {symbol} AMT setup using Fabio's rules"
  input:       full 5-section prompt used for PreCandleAdvisor at entry time
  output:      ideal response JSON (from PostTradeAnalyst review of that trade)
  metadata:
    trade_id:         UUID
    pnl_r:            float (reward signal)
    quality_score:    1-5 (from PostTradeAnalyst)
    fabio_rule:       which rule governed this setup
    session_date:     date
    market_regime:    vix_regime at time of trade

QUALITY FILTER:
  Include in dataset:  quality_score ≥ 4 AND pnl_r > 0.5R
  Exclude:            quality_score ≤ 2 (bad trades teach bad habits)
  Special include:    quality_score ≥ 4 AND pnl_r < 0 (good setup, bad outcome — valuable)

TARGET DATASET SIZE before re-fine-tune:
  Minimum: 200 high-quality samples
  Preferred: 500+ samples (after ~2 months of paper trading)
```


***

### P3 Component 5: ML Threshold Recalibration Post Walk-Forward

After walk-forward validation produces real precision metrics, thresholds must be updated in YAML — not guessed:

```
RECALIBRATION PROCESS:

STEP 1: Run walk-forward on 6-month data
STEP 2: For each playbook × direction combination, plot precision-recall curve
STEP 3: Find threshold where precision = 0.60 (long) or 0.62 (short)
STEP 4: Update config/strategies/ml_models.yaml with validated thresholds
STEP 5: SHAP prune features with importance < 0.001
STEP 6: Retrain models with pruned features
STEP 7: Re-run walk-forward with pruned feature set — confirm no degradation
STEP 8: Activate walk_forward_validation feature flag

AFTER FLAG ACTIVE:
  System checks at startup: are loaded models from validated walk-forward run?
  If not: log CRITICAL warning, block live mode, allow paper mode only
```


***

### P3 Exit Criteria

```
[ ] Walk-forward validation script runs on 6-month data
[ ] Long model: precision ≥ 0.58 across ALL 3 walk-forward windows
[ ] Short model: precision ≥ 0.60 across ALL 3 walk-forward windows
[ ] SHAP pruning complete — duplicate/noise features removed
[ ] Final feature count: 47-50 high-signal features
[ ] VIX, IV Rank, PCR features active and feeding into ML inference
[ ] PreCandleAdvisor uses 5-section prompt — response rate ≥ 80% of candles
[ ] PositionOverseer uses optimised prompt — HOLD on timeout confirmed
[ ] PostTradeAnalyst writes analysis to DB for every closed trade
[ ] LLM fine-tune dataset table created — storing quality-filtered trade analyses
[ ] Validated ML models loaded at startup — ConfigValidator checks model metadata
[ ] All 1450+ tests pass + walk-forward test harness + LLM prompt tests
[ ] Target test count: 1650+
[ ] Temperature for llm_entry_gate confirmed false in all environments (re-verify)
```


***
***

# PHASE 4 — "Scalping Layer"

## 1-Min/15-Sec MTF Stack + Print-Level Triggers + IB Scalps

### Duration: 12 Days | Requires: Phase 3 complete


***

### Why Phase 4 is Separate From Earlier Phases

Scalping requires a **fundamentally different signal pipeline** — not an extension of the existing 5-min structural pipeline:[^1]


| Dimension | Structural (Phase 0-3) | Scalping (Phase 4) |
| :-- | :-- | :-- |
| Signal timeframe | 5-min bar close | 15-sec tick event |
| Signal latency budget | < 50ms acceptable | < 10ms required |
| Signal frequency | 3-6 per day | 10-25 per day |
| Hold time | 30-90 min | 30 sec - 10 min |
| Risk tier | Uses full tier A/B/C | Uses sub-tier within each |
| Trigger | Bar close + ML probability | Live print + absorption |
| Gate pipeline | 12 gates | 6 gates (lighter) |
| LLM involvement | Pre-candle advisory | None (too slow) |

**The scalping layer is additive** — it runs alongside the structural layer. Both can fire independently. Portfolio limits (max 5 positions, 60% notional) apply across both.

***

### P4 Component 1: Multi-Timeframe Stack

#### Three-Timeframe Hierarchy (Fabio's exact model)

```
TIMEFRAME 1 — 5-MIN (Context Layer)
  Purpose: Determine structural bias — DO NOT TRADE against this
  Outputs: market_state, trend_direction, key_levels (POC, VAH, VAL, LVNs)
  Update: on 5-min bar close (already exists — structural pipeline)
  Rule: Scalps must align with 5-min structure direction

TIMEFRAME 2 — 1-MIN (Aggression Confirmation Layer)
  Purpose: Confirm aggression building at structural levels
  Outputs: 1-min aggression score, 1-min CVD slope, print clusters
  Update: on 1-min bar close
  Rule: 1-min aggression must score ≥ 2.0 before allowing scalp entry

TIMEFRAME 3 — 15-SEC (Execution Trigger Layer)
  Purpose: Precise entry — detect absorption + final aggression burst
  Outputs: large_print_detected, opposing_absorption_absent, cvd_flip
  Update: on every tick within 15-sec micro-bars
  Rule: All 3 conditions must be true to fire scalp entry
```


#### MTF Signal Alignment Rule (strict)

```
LONG SCALP — ALL must be true:
  5-min:  market_state = IMBALANCED_UP or (BALANCED + price above POC)
  1-min:  aggression_score_1m ≥ 2.0 AND cvd_slope_1m > +15
  15-sec: large_buy_print detected (≥ 3× avg 15-sec volume)
          AND no large sell print absorbing it (absorption check)
          AND 15-sec CVD makes positive flip (was negative, now positive)

SHORT SCALP — mirror logic:
  5-min:  market_state = IMBALANCED_DOWN or (BALANCED + price below POC)
  1-min:  aggression_score_1m ≥ 2.0 AND cvd_slope_1m < -15
  15-sec: large_sell_print detected
          AND no large buy print absorbing it
          AND 15-sec CVD makes negative flip
```


***

### P4 Component 2: 1-Min Bar Engine

**New component — not in current system**. Runs alongside 5-min bar processing.[^1]

#### 1-Min State Maintained Per Symbol

```
1-min volume profile:
  Bucket size = same as 5-min but rolling 30-min window only (not full session)
  Used for: intra-session micro-LVN detection

1-min CVD:
  Same Lee-Ready delta classification (reuse TickDeltaClassifier)
  Rolling slope over 10 bars (shorter window vs 20 for 5-min)
  Slope threshold for scalp: ±15 (tighter than 5-min threshold of ±30)

1-min Aggression:
  Reuse AggressionScorer with 1-min bar data
  Same 6-component formula — same max 4.5 points
  Threshold for scalp: ≥ 2.0 (lower than structural ≥ 2.5 because faster timeframe)

1-min bar close trigger:
  Every 60 seconds: compute 1-min snapshot
  Feed to MTFSignalMerger for scalp evaluation
```


***

### P4 Component 3: 15-Sec Trigger Engine

**The most latency-sensitive component in the entire system.** Must run in < 5ms.

#### Three-Condition Trigger (ALL required)

**Condition 1 — Large Print Detection**:

```
DEFINITION: A single trade tick qualifies as "large print" when:
  trade_volume ≥ 3.0 × rolling_avg_volume_15sec

rolling_avg_volume_15sec = exponential moving average of trade volumes
  over the last 30 ticks (EMA with α = 0.1)
  Why EMA not SMA: reacts faster to volume regime shifts

TIER B threshold: ≥ 3.0× average
TIER A threshold: ≥ 5.0× average (higher conviction for premium setups)
```

**Condition 2 — No Opposing Absorption**:

```
DEFINITION: "Absorption" = large opposing print that price does NOT move through

CHECK SEQUENCE:
  Large BUY print detected (Condition 1 = true for LONG)
  Check next 3 ticks: does any tick show large SELL print at same price level?
  Large SELL print = trade_volume ≥ 2.5× avg AND trade_price within 1 tick of buy print

  IF large opposing SELL print appears AND price stays flat or drops:
    OPPOSING ABSORPTION = true → REJECT scalp (smart money selling into your buy)
  
  IF large opposing SELL print appears BUT price continues UP:
    OPPOSING ABSORPTION = false → absorption confirmed (buyers overpowered sellers)
  
  IF no opposing print within 3 ticks:
    OPPOSING ABSORPTION = false → proceed

TIMING: Check window = 3 ticks after Condition 1 fires
This is Fabio's most important scalping rule: "I wait to see who wins"
```

**Condition 3 — 15-Sec CVD Flip**:

```
DEFINITION: CVD direction changes within the 15-sec micro-bar

COMPUTE: 15-sec cumulative delta (reset every 15 seconds)
         Previous 15-sec bar CVD sign (positive = net buying, negative = net selling)

LONG FLIP: current 15-sec CVD crosses zero from negative to positive
  → Sellers were in control, buyers take over → momentum shift

SHORT FLIP: current 15-sec CVD crosses zero from positive to negative

MINIMUM FLIP MAGNITUDE: |CVD_flip| ≥ 0.15 × avg_bar_volume
  Prevents false flips on tiny delta changes
```


***

### P4 Component 4: Scalping Gate Pipeline (6 Gates)

Lighter than the structural 12-gate pipeline — optimised for speed:

```
SCALP GATE 1 — SESSION TIMING:
  NSE:  Only during prime windows: 09:45-11:30 OR 13:30-15:00
  MCX:  Only during: 11:00-13:00 OR 17:00-19:00 OR 21:00-23:00
  NEVER: First 30 min of session (09:15-09:45 NSE / 09:00-09:30 MCX)
  NEVER: Last 15 min (15:00-15:15 NSE) — too choppy before close

SCALP GATE 2 — MTF ALIGNMENT:
  All 3 timeframes must align (5-min structure + 1-min aggression + 15-sec trigger)
  Covered by Component 3 alignment rules above

SCALP GATE 3 — STRUCTURAL LEVEL PROXIMITY:
  Scalp entry must be within 5 ticks of a structural level:
    Accepted levels: LVN (5-min), VAH, VAL, POC, IB_HIGH, IB_LOW
  Why: Scalps away from structure are random — no edge

SCALP GATE 4 — RISK TIER ACTIVE:
  tier = HALT → no scalps
  tier = C → only IB_MID and mean-reversion scalps (not trend scalps)
  tier = B or A → all scalp types allowed

SCALP GATE 5 — PORTFOLIO HEADROOM:
  open_positions < 5 (same portfolio cap as structural)
  symbol_notional < 20% (same per-symbol cap)
  But: a structural position on NIFTY does NOT block a scalp on BANKNIFTY

SCALP GATE 6 — NO SIMULTANEOUS STRUCTURAL + SCALP ON SAME SYMBOL:
  If NIFTY has open structural position: no scalp entries on NIFTY
  Reason: double exposure on same underlying within same option series
  MCX exception: CRUDEOIL structural + GOLD scalp = allowed (different commodities)
```


***

### P4 Component 5: Initial Balance Breakout Scalp (IB Scalp)

**High-frequency setup — Fabio uses this daily**. IB engine from Phase 2 provides the data.[^1]

#### IB Breakout Scalp — Exact Rules

**Setup A — IB Breakout Continuation**:

```
PRE-CONDITIONS:
  IB complete (after 09:45 NSE / 09:30 MCX)
  5-min bar closes ABOVE IB_HIGH (for long) or BELOW IB_LOW (for short)
  Breakout bar volume > 1.5× session_avg_volume
  No significant LVN or HVN immediately above IB_HIGH (clear air above)
  1-min CVD slope positive and rising

WAIT FOR:
  Retest of IB_HIGH from above (pullback entry — never chase the breakout bar)
  Retest must occur within 3 bars of breakout
  On retest: 1-min aggression ≥ 1.5 (lower threshold — proven breakout)

ENTRY: Market order on 15-sec trigger at IB_HIGH retest
STOP: 1 tick below IB_HIGH (back inside IB = failed breakout → exit)
TARGET: IB_HIGH + 1× IB_WIDTH (measured move)
R:R CHECK: must be ≥ 1.5 (if IB too wide → skip)
```

**Setup B — IB Failed Breakout (Mean Reversion)**:

```
PRE-CONDITIONS:
  IB complete
  5-min bar closes ABOVE IB_HIGH (breakout)
  Within 1-2 bars: price closes BACK INSIDE IB (failure)
  Opposing aggression confirmed at breakout high (sell prints)
  1-min CVD flips negative at the high

WAIT FOR:
  Price reclaims IB_MID from above (crosses midpoint downward)
  1-min CVD negative and accelerating

ENTRY: Market order at IB_MID breach
STOP: Above the failed breakout high + 2 ticks
TARGET: IB_LOW (full mean reversion)
R:R CHECK: typically 2.5-4:1 on failed breakouts — excellent setup
```


***

### P4 Component 6: Scalp Risk Model

**Scalp trades use sub-tiers within the main Risk Tier A/B/C**:

```
SCALP RISK = 60% of structural risk at same tier

Why 60%: Scalps have shorter hold times and higher frequency.
  Running full tier risk on 15-25 scalps/day would exceed daily loss limits.

SCALP RISK BY TIER:
  Tier C scalp: 0.60 × 0.15% = 0.09% per scalp
  Tier B scalp: 0.60 × 0.25% = 0.15% per scalp
  Tier A scalp: 0.60 × 0.45% = 0.27% per scalp

DAILY SCALP COUNT LIMITS (prevents overtrading):
  Tier C: max 8 scalp trades per day
  Tier B: max 15 scalp trades per day
  Tier A: max 25 scalp trades per day (Fabio's 600-trade competition level)

COMBINED DAILY RISK (structural + scalp):
  All trades share the same daily loss limit (2% of capital)
  The risk engine tracks total daily loss across both types
```


***

### P4 Component 7: Scalp Exit Rules (Speed-Critical)

```
RULE S-EXIT-1 — HARD STOP:
  SL placed at entry - (stop_distance_ticks × tick_size)
  Stop distance = last significant opposing print level ± 2 ticks
  Minimum stop: ATR(14) × 0.5 (prevents stops too tight for spread)
  This is the only exit that fires on every tick (same as structural)

RULE S-EXIT-2 — BREAKEVEN MOVE (fastest rule):
  As soon as price moves +0.5R from entry → move stop to breakeven
  "Breakeven" = entry price + (2 × slippage_bps + commission_ticks)
  Why +cost: covers round-trip costs on exit, not a loss

RULE S-EXIT-3 — CVD OPPOSING FLIP:
  Any 15-sec CVD flip against position direction → exit immediately at market
  Threshold: |cvd_flip| ≥ 0.10 × avg_bar_volume (lower than entry threshold)
  This is the most important scalp exit — smart money changed sides

RULE S-EXIT-4 — OPPOSING ABSORPTION AT TP ZONE:
  Price approaches TP within 3 ticks
  Large opposing print appears (≥ 2.5× avg) AND price stalls
  → Exit immediately — don't wait for full TP
  Reason: absorption at TP = supply/demand reversal — take what's on the table

RULE S-EXIT-5 — TIME STOP:
  If position shows < 0.2× ATR movement after 10 bars (10 minutes)
  → Exit at market — "scratch" trade
  Reason: stuck position consumes capital and headroom without edge

RULE S-EXIT-6 — PARTITION EXIT (for Tier A scalps only):
  P1: +1R → exit 50% of position
  P2: +2R → exit 30% of position
  P3: trail remaining 20% with 15-sec CVD

  Tier B and C scalps: single exit at TP (no partitioning — position too small)
```


***

### P4 Component 8: Scalp Latency Requirements

**This is a hard engineering constraint**:

```
REQUIREMENT: Tick receipt → scalp order submission ≤ 10ms

BUDGET BREAKDOWN:
  WebSocket tick receive:          ~50-100ms (DhanHQ network — fixed)
  TickDeltaClassifier (Lee-Ready): < 0.1ms
  15-sec micro-bar update:         < 0.2ms
  Condition 1 (large print check): < 0.1ms
  Condition 2 (absorption check):  < 0.5ms (3-tick window scan)
  Condition 3 (CVD flip check):    < 0.1ms
  6 scalp gates:                   < 1.0ms
  Order construction:              < 0.5ms
  Signal bus put:                  < 0.1ms
  TOTAL internal latency:          < 3ms ✅ (well within 10ms budget)

Note: The 50-100ms network latency is irreducible with DhanHQ. The 10ms 
budget is for INTERNAL processing only — not round-trip order confirmation.

MONITORING: LatencyMetrics.p99 for scalp path must be < 5ms in paper testing.
If p99 > 5ms: investigate event loop blocking. Most likely cause = DB write
in hot path. Solution = make DB writes async fire-and-forget for scalp path.
```


***

### P4 Component 9: Paper Testing Protocol for Scalping

**Must complete before Phase 5 live activation**:

```
PAPER TESTING REQUIREMENTS:
  Minimum scalp trades: 200
  Minimum trading days: 20
  Symbols active during test: NIFTY + BANKNIFTY (highest liquidity)
  
ACCEPTANCE METRICS (must meet ALL before live):
  Scalp win rate: ≥ 55%
  Scalp profit factor: ≥ 1.3
  Scalp avg R:R achieved: ≥ 1.5
  Daily count within tier limits: verified (no overtrading)
  Zero orphaned positions (all scalps closed within session)
  Latency p99 < 5ms: verified via MetricsRegistry
  
REJECTION: if any acceptance metric missed → do not proceed to Phase 5
  Action: review gate rejections, adjust thresholds in YAML, re-test
```


***

### P4 Exit Criteria

```
[ ] feature flag scalp_engine_enabled: true activates full scalping pipeline
[ ] 1-min bar engine running independently for all active symbols
[ ] 15-sec trigger engine: 3 conditions verified individually in unit tests
[ ] IB Breakout scalp and Failed Breakout scalp both firing correctly in paper
[ ] Scalp gates 1-6 all verifiable via MetricsRegistry rejection tracking
[ ] Scalp risk at 60% of tier risk — verified in SizingAgent
[ ] Daily scalp count limits enforced per tier
[ ] Scalp exit rules S-EXIT-1 through S-EXIT-6 all tested
[ ] Latency p99 < 5ms confirmed in paper run (10+ sessions)
[ ] 200+ scalp paper trades completed
[ ] Scalp win rate ≥ 55% on paper (not model assumption — actual trades)
[ ] All 1650+ tests pass + scalp engine tests
[ ] Target test count: 1900+
[ ] Combined (structural + scalp) daily trade count: 10-25 per day confirmed
```


***
***

# PHASE 5 — "Production Hardening"

## Live Broker Activation + Capital Scaling + Self-Healing

### Duration: 8 Weeks (not days — live money requires time gates) | Requires: Phase 4 complete


***

### Phase 5 Guiding Principle

**No phase prior to this involved real money. Phase 5 is different.** The approach is a staged capital ladder — not a binary paper-to-live switch. Each rung requires a time gate AND a performance gate before ascending.

***

### P5 Component 1: The Capital Ladder

```
RUNG 0 — PAPER BASELINE (must be true before entering Rung 1)
  Capital: Paper simulation
  Duration: Phase 0-4 combined (minimum 4 months)
  Gate: Phase 4 exit criteria met
  ↓

RUNG 1 — LIVE MINIMUM CAPITAL, TIER C ONLY
  Capital: ₹25,00,000 (₹25 Lakhs)
  Risk per trade: 0.09% (Tier C scalp) to 0.15% (Tier C structural)
  Maximum daily loss: ₹12,500 (2% of ₹25L)
  Duration: minimum 30 trading days
  Gate to advance: win rate ≥ 55%, PF ≥ 1.3, no daily limit breached
  ↓

RUNG 2 — LIVE STANDARD CAPITAL, TIER B UNLOCKED
  Capital: ₹50,00,000 (₹50 Lakhs)
  Risk per trade: up to 0.25% (Tier B structural)
  Maximum daily loss: ₹25,000 (2% of ₹50L)
  Duration: minimum 30 trading days
  Gate to advance: win rate ≥ 57%, PF ≥ 1.4, Sharpe > 1.5
  ↓

RUNG 3 — LIVE FULL CAPITAL, TIER A UNLOCKED
  Capital: ₹1,00,00,000 (₹1 Crore)
  Risk per trade: up to 0.45% (Tier A structural)
  Maximum daily loss: ₹50,000 (2% of ₹1Cr)
  Duration: minimum 45 trading days
  Gate to advance: win rate ≥ 58%, PF ≥ 1.5, max drawdown < 8%
  ↓

RUNG 4 — SCALE CAPITAL, ₹50L/MONTH TARGET
  Capital: ₹2,00,00,000 (₹2 Crores)
  Risk per trade: up to 0.45% (Tier A)
  Maximum daily loss: ₹1,00,000 (2% of ₹2Cr)
  Expected monthly: ₹40-55 Lakhs (at 60% win rate, 10-25 trades/day)
```


***

### P5 Component 2: Live Broker Activation Checklist

**ALL must be true before placing first live order**:

```
TECHNICAL:
  [ ] DhanBrokerAdapter tested with zero-lot test orders (₹1 notional)
  [ ] Order acknowledgment < 500ms confirmed
  [ ] SL order placement confirmed (STOP_LOSS_MARKET order type)
  [ ] Position reconciliation runs correctly (paper positions match broker positions)
  [ ] WebSocket reconnect tested: disconnect → auto-reconnect → positions recover
  [ ] Database backup running: live.duckdb backed up every 30 minutes
  [ ] React dashboard shows live positions (not just paper positions)

RISK:
  [ ] max_daily_loss_pct = 1.5% for Rung 1 (tighter than paper 2%)
  [ ] max_consecutive_losses = 2 for Rung 1 (tighter than paper 3)
  [ ] Circuit breaker tested: 2 consecutive losses → session halt → manual confirmation to resume
  [ ] Emergency stop implemented: single API call closes ALL positions immediately

CONFIG:
  [ ] GLASSYTRADE_ENV=live confirmed
  [ ] live.yaml capital = ₹25,00,000 (Rung 1)
  [ ] feature_flags: short_signals_enabled = false for Rung 1 (LONG only to start)
  [ ] feature_flags: scalp_engine_enabled = false for Rung 1 (structural only to start)
  [ ] ConfigValidator passes all live-mode hard rules

OPERATIONAL:
  [ ] Dedicated machine for live trading (not shared with development)
  [ ] UPS / power backup (power cut during open position = disaster)
  [ ] Mobile alert configured: critical events push to phone
  [ ] Manual override documented: steps to manually close all positions via DhanHQ app
```


***

### P5 Component 3: Position Reconciliation

**Critical for live trading** — the system's internal state must match broker's actual state every N seconds.

#### Reconciliation Rules

```
RECONCILIATION RUNS: every 30 seconds during live session

STEP 1 — FETCH BROKER STATE:
  Call DhanHQ positions API → get all open positions with live LTP

STEP 2 — COMPARE TO INTERNAL STATE:
  For each internal open position:
    IF not in broker response → GHOST POSITION
    IF in broker but different quantity → PARTIAL FILL MISMATCH
    IF in broker but different symbol → CRITICAL ERROR

STEP 3 — RESOLVE DISCREPANCIES:
  GHOST POSITION (in system, not in broker):
    → Position was closed externally (manual close via DhanHQ app)
    → System: mark position as closed, compute PnL from last known LTP
    → Log: "Ghost position reconciled"
    
  MISSING POSITION (in broker, not in system):
    → Position was opened externally (manual trade outside system)
    → System: register it as an external position, monitor only (no auto-exit)
    → Alert: "External position detected"
    
  QUANTITY MISMATCH (partial fill):
    → Reduce internal position size to match broker
    → Recompute SL lot sizes accordingly

STEP 4 — LTP SYNC:
  Update all internal LTPs from broker response (not just from tick stream)
  Prevents stale LTP risk when tick stream lags or reconnects
```


***

### P5 Component 4: Mobile Alert System

**Without this, a position blowing through SL while you are away = disaster**:

```
ALERT LEVELS:

CRITICAL (immediate SMS + push notification):
  Daily loss limit breached
  Session halted by circuit breaker
  Any position showing PnL < -2R (SL should have fired — investigate)
  WebSocket disconnected for > 60 seconds during session
  Session crash (watchdog fires)
  Reconciliation finds ghost position

WARNING (push notification only):
  Daily loss at 50% of limit (₹12,500 at Rung 1 = alert at ₹6,250 loss)
  3 consecutive losses (before halt — early warning)
  VIX spike to regime 3 during open position
  LLM overseer unable to respond for > 5 consecutive calls

INFO (logged + dashboard only):
  Session started / stopped
  Signal fired
  Position opened / closed
  Tier upgrade (C→B, B→A)

DELIVERY:
  Push via Telegram Bot API (free, reliable, works on all phones)
  Backup: email via SMTP
  Format: "{timestamp} | {level} | {symbol} | {message}"
```


***

### P5 Component 5: Self-Healing Mechanisms

```
MECHANISM 1 — SESSION AUTO-RESTART:
  If session crashes: watchdog restarts after 5s (max 3 restarts/day)
  On restart: re-read open positions from DB + broker reconciliation
  Do NOT re-enter positions that were open before crash (risk of double entry)

MECHANISM 2 — WEBSOCKET AUTO-RECONNECT:
  On disconnect: attempt reconnect after 1s, 2s, 4s, 8s, 16s (exponential backoff)
  Max reconnect attempts: 5
  After 5 failures: halt session, alert CRITICAL
  On reconnect: request full snapshot from DhanHQ before resuming tick processing
  
MECHANISM 3 — LLM OVERSEER TIMEOUT RECOVERY:
  On timeout: action = HOLD (never exits position on timeout)
  Consecutive timeouts ≥ 5: disable LLM overseer for this session
  Log: LLM unavailable → rule-based exit only (TradeManager handles via CVD + time stop)
  
MECHANISM 4 — ORDER REJECTION RECOVERY:
  On broker order rejection: log reason, do NOT retry entry (signal may be stale)
  For SL order rejection: CRITICAL alert + retry once after 2s + alert if second failure
  For exit order rejection: retry 3 times with 1s gap, then alert + manual intervention
  
MECHANISM 5 — DB WRITE FAILURE RECOVERY:
  DB write failure: log to in-memory fallback buffer (max 10,000 events)
  Attempt DB write every 30s from buffer
  On session close: flush all buffered events to DB
  Trade decisions never blocked by DB write failures
```


***

### P5 Component 6: Performance Monitoring Dashboard (React)

**Additions to existing dashboard at localhost:5190**:[^1]

```
NEW PANELS (add to existing dashboard):

PANEL 1 — CAPITAL LADDER STATUS
  Current rung, days at rung, gates met/pending for next rung
  Visual progress bar to next rung

PANEL 2 — GATE REJECTION HEATMAP
  7 symbols × 12 structural gates + 7 symbols × 6 scalp gates
  Each cell = rejection rate for that gate on that symbol
  Color: green (< 20%) → yellow (20-50%) → red (> 50%)
  Insight: red cells = gates that need threshold tuning in YAML

PANEL 3 — DELTA ACCURACY PANEL
  Lee-Ready CVD vs Gaussian proxy (if comparator still active)
  Real-time CVD direction per symbol
  Divergence alerts

PANEL 4 — RISK TIER PANEL
  Current tier per session, daily P&L in R per symbol
  Consecutive loss count, daily loss % used
  Tier unlock progress (how close to +3R for Tier A)

PANEL 5 — SESSION HEALTH
  Latency p50/p95/p99 per symbol (live, updating)
  Tick receive rate per symbol
  WebSocket status (connected / reconnecting / failed)
  LLM response rate (% of candles advisory responded)

PANEL 6 — TRADE LOG
  All trades today: symbol, direction, setup type, entry, exit, R, tier
  Sortable by PnL, by symbol, by setup type
  LLM post-trade analysis visible on click
```


***

### P5 Component 7: Path to ₹50 Lakhs/Month

**The math at Rung 4 (₹2 Crore capital)**:

```
DAILY TARGET: ₹2,27,273 (₹50L / 22 trading days)

STRUCTURAL TRADES (3-5 per day):
  Tier B avg: 3 trades × ₹25,000 risk × 1.8R avg win × 60% win rate
  = 3 × ₹25,000 × 1.8 × 0.60 = ₹81,000 gross
  Losses: 3 × ₹25,000 × 0.40 = -₹30,000
  Structural net: ₹51,000/day → ₹11.2L/month

SCALP TRADES (10-20 per day):
  Tier B scalp avg: 15 trades × ₹15,000 risk × 1.5R avg × 58% win rate
  = 15 × ₹15,000 × 1.5 × 0.58 = ₹1,96,200 gross
  Losses: 15 × ₹15,000 × 0.42 = -₹94,500
  Scalp net: ₹1,01,700/day → ₹22.4L/month

TIER A PREMIUM SETUPS (1-3 per day, 2-3 days/week):
  2 Tier A trades × ₹45,000 risk × 2.5R avg × 62% win rate
  = 2 × ₹45,000 × 2.5 × 0.62 = ₹1,39,500 gross
  Losses: 2 × ₹45,000 × 0.38 = -₹34,200
  Tier A net: ₹1,05,300/day × 60 days/month = ₹19.0L/month (for those days)

MONTHLY COMBINED ESTIMATE:
  Structural:        ₹11.2L
  Scalp:             ₹22.4L
  Tier A premium:    ₹8-12L (not every day)
  MCX commodity:     ₹5-8L (separate session, lower variance)
  TOTAL:             ₹46-54L/month

BREAK-EVEN DAYS: 2-3 low-conviction days per month reduce total by ~₹4-6L
NET REALISTIC:   ₹40-50L/month at ₹2Cr capital, all phases active
```


***

### P5 Exit Criteria (System Complete)

```
[ ] Live broker activated — first live order placed and confirmed
[ ] Rung 1 complete: 30 days, win rate ≥ 55%, PF ≥ 1.3
[ ] Rung 2 complete: 30 days, win rate ≥ 57%, PF ≥ 1.4, Sharpe > 1.5
[ ] Rung 3 complete: 45 days, win rate ≥ 58%, max drawdown < 8%
[ ] Rung 4 active: ₹2Cr capital, Tier A unlocked
[ ] Scalping enabled in live: 10-25 trades/day confirmed
[ ] SHORT signals enabled in live: PE trades firing
[ ] Reconciliation running every 30s: zero ghost position incidents
[ ] Mobile alerts working: CRITICAL alerts reach phone within 30s
[ ] Self-healing: session crash recovery tested (artificial crash in live low-volume period)
[ ] Dashboard: all 6 new panels live and updating
[ ] Test count: 2000+
[ ] Monthly P&L tracking: actual vs target per rung
```


***

## Complete Phase Summary

| Phase | Name | Duration | Key Deliverable | Gate to Next |
| :-- | :-- | :-- | :-- | :-- |
| **-1** | Nervous System | 10 days | YAML config, feature flags, observability | constants.py deleted, 950+ tests |
| **0** | Domain Integrity | 10 days | Decomposed god objects, real delta, real costs | 1100+ tests, realistic PnL |
| **1** | Parallel Engine | 8 days | 7 symbols concurrent, DuckDB, watchdog | Latency p99 < 20ms, 1250+ tests |
| **2** | Bilateral + Risk | 10 days | SHORT/PE signals, Tier A/B/C, IB engine | PE trades firing, 1450+ tests |
| **3** | Intelligence | 12 days | Validated ML, VIX/IV/PCR, LLM restructure | Precision ≥ 0.58 all windows |
| **4** | Scalping | 12 days | 1-min/15-sec MTF, IB scalps, 10-25/day | 200+ paper scalps, 1900+ tests |
| **5** | Production | 8 weeks | Live broker, capital ladder, ₹50L target | Rung 4 active |

**Total to Rung 1 live**: ~9-10 weeks of focused development.[^1]
**Total to ₹50L/month**: ~6-7 months from today (including 2-3 months capital ladder climb at Rung 1-3).

<div align="center">⁂</div>

[^1]: AMT_ARCHITECTURE_INTAKE.md

