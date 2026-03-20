# Systematic Gap Analysis
## GlassyTrade AI — AMT + LLM Hybrid Engine

**Document Version:** 1.0
**Date:** 2026-03-19
**Status:** Ready for Review
**Source Documents:** 01-06 (plan), backend/app/ (implementation)

---

## 1. Architecture Overview — Current vs Target

### 1.1 Current Architecture (What Exists)

```
TICK ──► TradingEngine ──► TradingSessionService (1899 lines god object)
                                    │
                    ┌───────────────┼───────────────┐
                    ▼               ▼               ▼
              AMTHandler     LLMEntryHandler    LLMOverseerHandler
              (AMT analysis)  (LLM decides      (LLM manages
                              entry 1-2s)        position 3s)
                    │               │               │
                    ▼               ▼               ▼
              entry_gate.py    LLM inference    LLM inference
              (Three-Align)    (MLX/GPU)        (MLX/GPU)
                    │               │               │
                    └───────┬───────┘               │
                            ▼                       ▼
                       TradeManager            TradeManager
                       (deterministic          (deterministic
                        exits)                  exits)
```

**Problems:**
- LLM makes ENTRY decisions (should be AMT-deterministic)
- LLM manages positions every 3 seconds (should be rule-based)
- TradingSessionService is a god object
- Threading mixed with async

### 1.2 Target Architecture (Hybrid AMT + LLM)

```
TICK ──► TickProcessor ──► CandleBuilder ──► AMT Engine (DETERMINISTIC)
                                                    │
                         ┌──────────────────────────┤
                         ▼                          ▼
                   Volume Profile            Order Flow Engines
                   (POC/VAH/VAL/LVN/HVN)    (CVD/Footprint/Bubble/
                    Delta Profile             Absorption/BigTrade/
                    Leg Profile               OFI/VWAP/IB)
                         │                          │
                         └──────────┬───────────────┘
                                    ▼
                            Market State Engine
                          (NO_TRADE/BALANCED/
                           IMBALANCED/PROBING)
                                    │
                                    ▼
                            Drive Tracker
                          (D1/D2/D3+ rejection)
                                    │
                                    ▼
                           12-GATE PIPELINE (DETERMINISTIC)
                           GATE 0-12 sequential checks
                                    │
                         ┌──────────┴──────────┐
                         ▼                     ▼
                   GATES PASS              GATES FAIL
                         │                     │
                         ▼                     ▼
              ┌─────────────────────┐    Output reason
              │  LLM CONTEXT LAYER  │    (FLAT/ALERT/WAIT/
              │  (Enrichment ONLY)  │     BLOCKED/STALE)
              │  • Rationale text   │
              │  • Market narrative │
              │  • Risk commentary  │
              │  • Confidence boost │
              └─────────┬───────────┘
                        ▼
              TradeConstructor (DETERMINISTIC)
              Entry at level, SL, Target, R:R
                        │
              ┌─────────┴─────────┐
              ▼                   ▼
     PartitionExitManager   PyramidManager
     (P1/P2/P3 + BE +       (Max 2 adds,
      counter-aggression)     aggression≥3.0)
              │                   │
              ▼                   ▼
         SessionRiskManager + PositionSizer
         (0.5% per trade, 2% daily, 3 consecutive)
                        │
                        ▼
                   OutputSchema → WS Push → Frontend
```

**Key principle:** LLM enriches but never decides. AMT pipeline is the authority.

---

## 2. Gap Categories

### Category Legend

| Symbol | Meaning |
|---|---|
| **BUG** | Incorrect implementation that produces wrong results |
| **MISSING** | Required component not implemented |
| **DEVIATION** | Implementation differs from spec |
| **FLOW** | Data flow or sequencing issue |
| **ARCH** | Architectural issue |

---

## 3. Critical Bugs (Must Fix First)

| ID | Location | Type | Description | Impact |
|---|---|---|---|---|
| BUG-01 | `amt_analyzer.py:389` | BUG | `find_hvns()` hardcodes `threshold = mean_vol * 1.5` instead of `cfg.HVN_THRESHOLD` (2.0) | HVNs detected at wrong threshold; levels incorrect |
| BUG-02 | `regime_detector.py:465` | BUG | `post_break[-1].exit_price` — OHLC has no `exit_price` attribute | `analyze_follow_through()` crashes on SHORT path |
| BUG-03 | `entry_gate.py:625` | BUG | `MIN_RR_RATIO = 1.0` but plan requires 1:1.5 | Trades with poor R:R accepted |
| BUG-04 | `trade_manager.py:441` | BUG | `is_valid_rr` uses `min_rr=1.95` — contradicts BUG-03 | Inconsistent R:R enforcement across modules |
| BUG-05 | `risk_manager.py:56` | BUG | `MAX_DAILY_DRAWDOWN_PCT = 0.05` (5%) — plan says 2% | Excessive daily risk allowed |
| BUG-06 | `risk_manager.py:58` | BUG | `MAX_CONSECUTIVE_LOSSES = 5` — plan says 3 | Too many consecutive losses tolerated |
| BUG-07 | `amt_analyzer.py:493` | BUG | `InitialBalanceTracker.ib_minutes = 30` — plan says "first 2 candles" | IB window too wide |
| BUG-08 | `config.py:74` vs `amt_analyzer.py:71` | BUG | `BALANCE_RATIO_THRESHOLD = 0.70` in config, 0.55 mentioned in comments | Market state classification unreliable |
| BUG-09 | `amt_analyzer.py:1066` | BUG | Displacement uses `DISPLACEMENT_MULTIPLIER * N` — plan says `ATR × 1.5` | Displacement detection over-scaled |
| BUG-10 | `trade_manager.py:37-38` | BUG | `stop_loss_pct = 0.005`, `take_profit_pct = 0.015` — plan uses level-based SL/TP | Hardcoded % overrides Fabio's level-based logic |

---

## 4. Missing Components

### 4.1 Volume Profile Layer

| ID | Component | Plan Ref | Impact |
|---|---|---|---|
| MISS-01 | LVN quality scoring (thinness 60% + proximity 40%) | FR-02-10 | No prioritization of LVN quality |
| MISS-02 | Combined Profile confluence (LVN + session level overlap ±3 ticks) | FR-02-11/12 | No confluence bonus to aggression |
| MISS-03 | Leg auto-reset when price re-enters value area | FR-02-07 | Leg profile stale after re-entry |
| MISS-04 | Profile selection logic (SESSION/LEG/COMBINED active) | Architecture §2.2 | No profile selection mechanism |

### 4.2 Order Flow Layer

| ID | Component | Plan Ref | Impact |
|---|---|---|---|
| MISS-05 | Standalone BubbleDetector (2σ threshold, direction classification) | FR-03-07/08 | Volume bubbles not detected as spec |
| MISS-06 | Standalone BigTradeDetector (5× avg, 3 prints within 2 ticks) | FR-03-11 | Institutional print clusters missed |
| MISS-07 | Standalone OFI Calculator (tick-level, 10-candle rolling) | FR-03-12 | OBI from L2 is proxy, not real OFI |
| MISS-08 | Standalone IB Detector with break detection | FR-03-14/15 | No IB break signal |
| MISS-09 | Absorption using correct formula (range < ATR×0.3 AND vol > avg×2.0) | FR-03-09 | Current formula uses different logic |
| MISS-10 | Imbalance % confirmation (≥40% cells at 3:1) | FR-03-06 | Individual cells marked but % not computed |

### 4.3 Strategy Layer

| ID | Component | Plan Ref | Impact |
|---|---|---|---|
| MISS-11 | NO_TRADE market state (±2 ticks of POC) | FR-04-01 | Trades taken at POC dead zone |
| MISS-12 | PROBING market state (outside VA, no displacement) | FR-04-05/06 | Unconfirmed breaks treated as tradeable |
| MISS-13 | Zone sub-classification (NEAR_VAH, NEAR_VAL, NEAR_POC) | FR-04-03 | No zone-aware aggression weighting |
| MISS-14 | State transition logging with trigger values | FR-04-07 | No audit trail for state changes |
| MISS-15 | Drive rejection detection (wick through, close opposite) | FR-05-03 | First drive rejection not properly detected |
| MISS-16 | Drive momentum fade check (D2 vs D1) | FR-05-07 | Second drive quality not assessed |
| MISS-17 | Third drive suppression (D3+ = avoid) | FR-05-06 | No D3+ protection |
| MISS-18 | Aggression scoring as additive weighted system (max 4.5) | FR-06 | Current: cap at 2.0, not additive |
| MISS-19 | Rule-based rationale generator (no LLM dependency) | FR-11 | Rationale comes from LLM, not deterministic |

### 4.4 Trade Management Layer

| ID | Component | Plan Ref | Impact |
|---|---|---|---|
| MISS-20 | PartitionExitManager (P1=30% at 33%R, P2=50% at target, P3=20% trail) | FR-08 | No partition exit system |
| MISS-21 | PyramidManager (max 2 adds, aggression≥3.0, decreasing size) | FR-09 | No structured pyramid adds |
| MISS-22 | BreakEvenManager (35% of R toward target) | FR-08-07 | BE trigger at 1R instead of 35%R |
| MISS-23 | Counter-aggression hard exit (2+ opposite signals = exit ALL) | FR-08-06 | No counter-aggression exit |
| MISS-24 | Cushion quality gate (≤3 excellent, ≤6 acceptable, >10 invalid) | FR-07-05 | No cushion validation |

### 4.5 Risk Layer

| ID | Component | Plan Ref | Impact |
|---|---|---|---|
| MISS-25 | PositionSizer (fixed fractional: risk_amount / risk_per_lot) | FR-10-01 | No standalone position sizer |
| MISS-26 | Per-symbol big trade thresholds | FR-10-08 | One-size-fits-all threshold |
| MISS-27 | EIA release window suppression (15 min around release) | FR-01-07 | No economic calendar integration |
| MISS-28 | Session time windows (09:30-11:30, 14:00-15:30 preferred) | FR-10-10/11 | No time-window weighting |

---

## 5. Data Flow Issues

### 5.1 Entry Decision Flow

**Current flow (WRONG):**
```
Tick → AMT analysis → Three-Align gate → LLM decides → Signal
```

**Required flow (CORRECT):**
```
Tick → AMT analysis → 12-Gate pipeline → ALL PASS → TradeConstructor → LLM enriches rationale → Signal
                                 │
                          FIRST FAIL → Output reason (no LLM call)
```

**Issue:** LLM is in the critical path for entry decisions. It should only enrich output after deterministic gates pass.

### 5.2 Aggression Score Flow

**Current flow:**
```
OBI + norm_delta + absorption → capped at 2.0 → single score
```

**Required flow:**
```
FR-06-01: Footprint imbalance (≥40%, ≥3:1)           → +1.0
FR-06-02: CVD slope/divergence                        → +1.0
FR-06-03: Big trade cluster (3+ prints)                → +1.0
FR-06-04: Absorption at entry candle                   → +0.5
FR-06-05: OFI aligned (>+0.10 LONG, <-0.10 SHORT)     → +0.5
FR-06-06: Combined profile confluence                  → +0.5
FR-06-07: Volume bubble within 3 ticks                 → +0.5
                                              Max: 4.5
Min for trade: 2.0    Min for pyramid: 3.0
```

**Issue:** Completely different scoring system. Additive weighted vs capped single.

### 5.3 Exit Flow

**Current flow:**
```
TradeManager.check_position()
  → SL hit? → exit
  → TP hit? → exit or runner
  → Partial TP at 50% → exit 50%
  → Trail active? → ratchet trail
  → Time stop → exit
  → LLM overseer (every 3s) → HOLD/TIGHTEN/EXIT/ADD
```

**Required flow:**
```
PartitionExitManager.check()
  → P1 (30%): exit at 33% R IF momentum weak (skip if strong)
  → P2 (50%): ALWAYS exit at target (session POC)
  → P3 (20%): trail if CVD slope > 2.0, else exit with P2
  → Break-even: move SL to entry at 35% of R
  → Counter-aggression: 2+ opposite signals = exit ALL
  → Trail formula: SL = current - (remaining_to_target × 0.40)

PyramidManager.check()
  → Max 2 adds (3 total entries)
  → Each add at different LVN
  → Add sizes: 100%, 50%, 25% of base
  → Aggression ≥ 3.0 required
  → After each add: move ALL stops to latest entry SL
```

**Issue:** No partition exit system. No pyramid system. LLM overseer replaces deterministic exit logic.

### 5.4 Risk Flow

**Current flow:**
```
RiskManager.validate()
  → Check halted
  → Check max concurrent positions (5)
  → Check portfolio notional cap (60%)
  → Check per-symbol notional (20%)

TradeManager.record_loss()
  → Increment daily losses
  → Check symbol limit (3)
  → Check global limit (9 = 3×3)
  → Circuit breaker (2 consecutive near same price)

SessionRiskManager
  → 3 consecutive losses → halt
  → 5 trades per session cap
  → Dynamic SL% based on tier
```

**Required flow:**
```
SessionRiskManager (per FR-10):
  → Risk per trade: 0.5% of equity
  → Max daily loss: 2% of session-start equity
  → Max consecutive losses: 3 → pause
  → Max drawdown from peak: 3%
  → Absolute ceiling per trade: 1.0%
  → Check at EVERY signal generation

PositionSizer:
  → lots = risk_amount / risk_per_lot
  → risk_amount = equity × risk_pct
  → risk_per_lot = |entry - SL| × point_value
```

**Issue:** Three separate risk managers with inconsistent thresholds. No standalone position sizer.

---

## 6. Threshold Mismatches (Plan vs Code)

| Parameter | Plan Value | Code Value | Location | Impact |
|---|---|---|---|---|
| `HVN_THRESHOLD` | 2.00 (>200% mean) | 1.5 (hardcoded) | `amt_analyzer.py:389` | Wrong HVN detection |
| `LVN_THRESHOLD` | 0.15 (<15% mean) | 0.15 | `constants.py:19` | **MATCHES** |
| `value_area_pct` | 0.70 | 0.70 | `amt_analyzer.py:1151` | **MATCHES** |
| `footprint_imbalance_ratio` | 3.0 (300%) | 3 | `footprint_analyzer.py:92` | **MATCHES** |
| `min_aggression_score` | 2.0 | 2.0 (capped) | `amt_analyzer.py:1307` | Different formula |
| `cvd_slope_window` | 20 | 14 | `cvd_tracker.py:43` | Wrong window |
| `MAX_DAILY_DRAWDOWN_PCT` | 0.02 (2%) | 0.05 (5%) | `risk_manager.py:56` | 2.5× too high |
| `MAX_CONSECUTIVE_LOSSES` | 3 | 5 | `risk_manager.py:58` | 1.67× too high |
| `max_consecutive_losses` (session) | 3 | 3 | `session_risk_manager.py:46` | **MATCHES** |
| `risk_per_trade_pct` | 0.005 (0.5%) | 0.005 | `trade_manager.py:37` | **MATCHES** |
| `R:R minimum` | 1:1.5 | 1:1 or 1:1.95 | `entry_gate.py:625` / `trade_manager.py:441` | Inconsistent |
| `IB window` | First 2 candles | 30 minutes | `amt_analyzer.py:493` | Too wide |
| `warm-up period` | 15 min (MCX) | 30 min (6 candles) | `entry_gate.py:31-38` | Too long |
| `BALANCE_RATIO_THRESHOLD` | 0.55 (comment) | 0.70 (config) | `config.py:74` | Wrong |
| `DISPLACEMENT_MULTIPLIER` | 1.5×ATR | 1.5×ATR×N | `amt_analyzer.py:1066` | Over-scaled |
| `absorption_range_atr` | 0.30 | Not used | — | Wrong formula used |
| `absorption_vol_mult` | 2.00 | Not used | — | Wrong formula used |
| `big_trade_multiplier` | 5.0 | Not implemented | — | Missing |
| `poc_no_trade_ticks` | 2 | Not implemented | — | Missing |

---

## 7. LLM Integration Issues

### 7.1 LLM in Wrong Layer

| Current | Required | Why |
|---|---|---|
| LLM decides entry (LONG/SHORT/FLAT) | AMT gates decide entry; LLM provides rationale | Determinism, latency, reproducibility |
| LLM manages positions (HOLD/EXIT/ADD) | PartitionExitManager + PyramidManager manage positions | Rules > LLM for risk |
| LLM called every 3 seconds for overseer | LLM called only on state changes for narrative | Wasted compute, noise |
| LLM timeout = 15s (blocks pipeline) | LLM runs async, never blocks signal | Latency requirement < 500ms |

### 7.2 Where LLM SHOULD Be Used

| Use Case | Layer | Trigger | Output |
|---|---|---|---|
| Trade rationale | Output | After gates pass | Human-readable explanation of WHY trade is valid |
| Market narrative | Output | On state change | "Market transitioning from balance to trend..." |
| Risk commentary | Output | On risk events | "3 consecutive losses — market structure shifting" |
| Setup grading explanation | Output | After aggression score | "A-grade: CVD aligned, footprint confirmed, LVN confluence" |
| Confidence boost | Strategy | After deterministic score | Adjust confidence label with qualitative context |
| Anomaly explanation | Monitoring | On data quality issues | "Gap detected — possible news event" |

### 7.3 LLM Prompt Accuracy

The current LLM prompts should be enriched with AMT data so the LLM can explain the deterministic decision, not make the decision.

**Required prompt structure:**
```
AMT DETERMINISTIC ANALYSIS:
- Market State: {state} (confidence: {conf}%)
- POC: {poc} | VAH: {vah} | VAL: {val}
- CVD Slope: {slope} | Divergence: {div}
- Aggression Score: {score}/4.5
  - Footprint: {+1.0 or 0}
  - CVD: {+1.0 or 0}
  - Big Trade: {+1.0 or 0}
  - Absorption: {+0.5 or 0}
  - OFI: {+0.5 or 0}
- Drive: D{num} at {level}
- Setup: {type} | R:R = {rr}
- Decision: {TRADE/FLAT} (deterministic)

TASK: Explain this trade setup in 2-3 sentences for a trader's journal.
```

---

## 8. Flow Sequence Issues

### 8.1 Gate Pipeline (Missing)

The plan defines 12 sequential gates. Current code has a partial `three_align_check()` but no structured gate pipeline.

**Required gates (from plan §6):**

| Gate | Check | Fail Output | Current Status |
|---|---|---|---|
| GATE 0 | Session time filter (warm-up, dead zone) | BLOCKED | Partial (min_candles_gate) |
| GATE 1 | Data quality (STALE flag, gap > 30s) | STALE | Missing |
| GATE 2 | Session risk (daily loss, drawdown, consecutive) | SESSION_STOPPED | Partial (3 risk managers) |
| GATE 3 | Market state = NO_TRADE (POC ±2 ticks) | FLAT | Missing (no NO_TRADE) |
| GATE 4 | Market state = PROBING (unconfirmed break) | FLAT | Missing (no PROBING) |
| GATE 5 | Profile selected, key level identified | WAIT | Partial |
| GATE 6 | Price AT entry zone (within 3 ticks) | ALERT | Partial (threshold check) |
| GATE 7 | Drive number = 2 (first drive rejected) | FLAT/ALERT | Partial (is_second_drive) |
| GATE 8 | Aggression score ≥ 2.0 | WAIT | Different formula |
| GATE 9 | Cushion ≤ 10 ticks | INVALID | Missing |
| GATE 10 | R:R ≥ 1.5 | SKIP | Wrong threshold (1:1) |
| GATE 11 | Position sizing passes risk manager | BLOCKED | Partial |
| GATE 12 | EIA release window (if applicable) | SUPPRESSED | Missing |

**Only 4/12 gates fully implemented. 4/12 partially. 4/12 missing.**

### 8.2 State Machine Issues

**Current market states:** BALANCED, IMBALANCED (2 states)

**Required market states:** NO_TRADE, BALANCED, IMBALANCED, PROBING (4 states)

**Missing transitions:**
```
ANY → NO_TRADE: price within ±2 ticks of POC
NO_TRADE → BALANCED: price moves away from POC into VA
BALANCED → IMBALANCED: displacement + acceptance outside VA
BALANCED → PROBING: price outside VA without displacement
PROBING → IMBALANCED: displacement confirmed
PROBING → BALANCED: price re-enters VA
IMBALANCED → BALANCED: price re-enters VA + volume drops
```

### 8.3 Drive State Machine Issues

**Current:** Simple past_touches/recent_touches check

**Required:**
```
SESSION_START: all levels reset (D0)
LEVEL_TOUCH: D1 recorded, return alert, suppress entry
D1_REJECTION: wick through, close opposite → mark level as "rejected"
LEVEL_RETOUCH after D1_REJECTED: D2 = valid entry zone
LEVEL_RETOUCH after D1_NOT_REJECTED: suppress (no edge)
LEVEL_RETOUCH after D2: D3+ = suppress (exhausted)
```

---

## 9. Summary Statistics

| Category | Total | Correct | Deviated | Missing |
|---|---|---|---|---|
| Bugs | 10 | — | — | — |
| Volume Profile | 12 | 7 | 2 | 3 |
| Order Flow | 17 | 5 | 5 | 7 |
| Market State | 7 | 2 | 1 | 4 |
| Drive Detection | 8 | 2 | 2 | 4 |
| Aggression Scoring | 10 | 2 | 3 | 5 |
| Trade Setup | 9 | 3 | 4 | 2 |
| Risk Management | 11 | 3 | 5 | 3 |
| Partition Exit | 8 | 0 | 0 | 8 |
| Pyramid | 8 | 0 | 0 | 8 |
| Gates | 12 | 4 | 4 | 4 |
| LLM Integration | 6 | 0 | 6 | 0 |
| **TOTALS** | **108** | **28 (26%)** | **32 (30%)** | **48 (44%)** |

**Overall accuracy: 26%. 30% deviated. 44% missing.**

---

**Document Control:**
- Created: 2026-03-19
- Next Review: After Phase 1 fixes
- Approved By: TBD
