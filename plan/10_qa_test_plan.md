# Comprehensive QA Test Plan
## GlassyTrade AI — Fabio Valentini AMT + LLM Hybrid Engine

**Document Version:** 1.0
**Date:** 2026-03-19
**Status:** Ready for Execution
**Source Documents:** 03_responsibility_matrix.md, 01_master_requirements_specification.md, 07_gap_analysis.md, IMPLEMENTATION_STATE_REPORT.md

---

## 1. Test Strategy Overview

### 1.1 Test Pyramid

```
┌─────────────────────────────────────────────────────────┐
│                    E2E TESTS (5%)                        │
│          Full pipeline: Tick → Signal → Execution        │
├─────────────────────────────────────────────────────────┤
│               INTEGRATION TESTS (25%)                    │
│     Component binding, data flow, dependency validation   │
├─────────────────────────────────────────────────────────┤
│                 UNIT TESTS (70%)                          │
│        Individual module correctness, edge cases          │
└─────────────────────────────────────────────────────────┘
```

### 1.2 Test Categories

| Category | Focus | Priority | Count |
|----------|-------|----------|-------|
| **Unit Tests** | Individual module logic | Critical | 50+ |
| **Integration Tests** | Component binding per RACI | Critical | 30+ |
| **Fabio Methodology Tests** | AMT spec compliance | Critical | 25+ |
| **LLM Integration Tests** | Advisory layer correctness | High | 15+ |
| **E2E Pipeline Tests** | Full tick-to-signal flow | High | 10+ |
| **Risk Tests** | Capital protection | Critical | 15+ |
| **Performance Tests** | Latency, throughput | Medium | 10+ |

---

## 2. Unit Tests (Per Module)

### 2.1 Volume Profile Layer

#### Test VP-01: Session Profile Build
```
Given: 100 ticks with known prices and volumes
When: VolumeProfile.update() called for each tick
Then:
  - Profile buckets sum to total volume
  - POC = bucket with max volume
  - VAH/VAL calculated via 70% rule
  - O(1) per tick update confirmed
```

#### Test VP-02: LVN Detection
```
Given: Profile with known volume distribution
When: NodeDetector.detect_lvns() called
Then:
  - LVNs at buckets where vol < 15% of mean
  - HVNs at buckets where vol > 200% of mean
  - LVN quality scoring: thinness (60%) + proximity (40%)
```

#### Test VP-03: Leg Profile Auto-Reset
```
Given: Active leg profile, price re-enters value area
When: LegAnchor.should_reset_leg() called
Then:
  - Leg profile cleared
  - New leg anchor set at re-entry point
```

### 2.2 Order Flow Layer

#### Test OF-01: CVD Calculation
```
Given: 20 ticks with known deltas
When: CVDEngine.update() called
Then:
  - CVD = cumulative sum of deltas
  - Slope = (cvd[-1] - cvd[-20]) / 20
  - Divergence detected when price/CVD diverge
```

#### Test OF-02: Footprint Imbalance
```
Given: Candle with known bid/ask volumes per level
When: FootprintEngine.detect_imbalance() called
Then:
  - Imbalance where ratio ≥ 3.0 (300%)
  - Confirmation requires ≥ 40% cells imbalanced
```

#### Test OF-03: Absorption Detection
```
Given: Candle with (high-low) < ATR×0.3 AND volume > avg×2.0
When: AbsorptionDetector.detect() called
Then:
  - Detected = True
  - Side classified correctly (SELL_ABSORBED → LONG, BUY_ABSORBED → SHORT)
```

#### Test OF-04: Big Trade Cluster
```
Given: Ticks with 3+ prints ≥ 5× avg within 2 ticks
When: BigTradeDetector.detect() called
Then:
  - Cluster detected
  - Side classified from delta
```

#### Test OF-05: Volume Bubble
```
Given: 21 candles with last candle vol ≥ mean + 2σ
When: BubbleDetector.detect() called
Then:
  - Detected = True
  - Direction classified (BUY/SELL/NEUTRAL)
```

#### Test OF-06: OFI Calculation
```
Given: 10 candles with known deltas and volumes
When: OFICalculator.update() called
Then:
  - OFI = (sum of deltas) / (sum of volumes)
  - Range: -1.0 to +1.0
```

### 2.3 Strategy Layer

#### Test ST-01: Market State Classification
```
Given: Price at POC ± 1 tick
When: detect_market_state() called
Then: Returns NO_TRADE

Given: Price inside VAH-VAL
When: detect_market_state() called
Then: Returns BALANCED with zone (NEAR_VAH/NEAR_VAL/NEAR_POC)

Given: Price outside VA + displacement + acceptance
When: detect_market_state() called
Then: Returns IMBALANCED

Given: Price outside VA without displacement
When: detect_market_state() called
Then: Returns PROBING
```

#### Test ST-02: Drive Detection
```
Given: First touch of VAH level
When: DriveTracker.classify_drive() called
Then: Returns D1, entry_valid=False

Given: D1 rejected (wick through, close opposite) + re-touch
When: DriveTracker.classify_drive() called
Then: Returns D2, entry_valid=True

Given: D2 completed + third touch
When: DriveTracker.classify_drive() called
Then: Returns D3+, entry_valid=False
```

#### Test ST-03: Aggression Scoring
```
Given: All 7 signals confirmed
When: AggressionScorer.score() called
Then:
  - Score = 4.5 (max)
  - Confidence = HIGH
  - pyramid_eligible = True

Given: Only footprint + CVD confirmed
When: AggressionScorer.score() called
Then:
  - Score = 2.0
  - Confidence = MEDIUM
  - pyramid_eligible = False
```

#### Test ST-04: Three-Align Gate
```
Given: Market BALANCED + price at VAH + confirmation bundle passes
When: three_align_check() called
Then: gate_passed=True, confirmation_strong=True

Given: Market IMBALANCED + first drive only
When: three_align_check() called
Then: gate_passed=False (waiting for D2)

Given: CVD slope < -100 in BALANCED
When: three_align_check() called
Then: gate_passed=False (CVD hard block)
```

### 2.4 Gate Pipeline

#### Test GP-01: Sequential Gate Evaluation
```
Given: Context with candle_count=0
When: GatePipeline.evaluate() called
Then: FAIL at GATE 0 (BLOCKED)

Given: Context with tick_age=35s
When: GatePipeline.evaluate() called
Then: FAIL at GATE 1 (STALE)

Given: Context with is_risk_halted=True
When: GatePipeline.evaluate() called
Then: FAIL at GATE 2 (SESSION_STOPPED)

Given: Context with market_state=NO_TRADE
When: GatePipeline.evaluate() called
Then: FAIL at GATE 3 (FLAT)

Given: All gates pass
When: GatePipeline.evaluate() called
Then: PASS, reason=TRADE
```

#### Test GP-02: EIA Window (GATE 12)
```
Given: Thursday 10:15-10:45 ET, symbol=NATURALGAS
When: EIACalendar.is_suppressed() called
Then: Returns True

Given: Wednesday 10:15-10:45 ET, symbol=CRUDEOIL
When: EIACalendar.is_suppressed() called
Then: Returns True

Given: Monday 10:30 ET, symbol=NATURALGAS
When: EIACalendar.is_suppressed() called
Then: Returns False
```

### 2.5 Trade Management

#### Test TM-01: Partition Exit
```
Given: Long position, price reaches 33% of R, CVD slope weak
When: PartitionExitManager.check_exits() called
Then: P1 exit signal (30% of position)

Given: Long position, price reaches target
When: PartitionExitManager.check_exits() called
Then: P2 exit signal (50% of position)

Given: P2 taken, CVD slope > 2.0
When: PartitionExitManager.check_exits() called
Then: P3 trail active (20% of position)
```

#### Test TM-02: Pyramid Manager
```
Given: Position in profit, aggression ≥ 3.0, at new LVN
When: PyramidManager.check_pyramid() called
Then: Pyramid signal with size_multiplier=1.0

Given: 1 previous add, position in profit, aggression ≥ 3.0
When: PyramidManager.check_pyramid() called
Then: Pyramid signal with size_multiplier=0.5

Given: 2 previous adds
When: PyramidManager.check_pyramid() called
Then: None (max adds reached)
```

#### Test TM-03: Break-Even Trigger
```
Given: Long position, price reaches 35% of R toward target
When: PartitionExitManager checks break-even
Then: Stop moved to entry price
```

### 2.6 Risk Management

#### Test RK-01: Position Sizing
```
Given: equity=100000, entry=100, stop=99, point_value=10
When: PositionSizer.calculate() called
Then: lots = 5 (100000 * 0.005 / (1 * 10))
```

#### Test RK-02: Daily Loss Limit
```
Given: Session P&L = -2000 (2% of 100000)
When: SessionRiskManager.check() called
Then: can_trade = False, halt_reason = "DAILY_LOSS_LIMIT"
```

#### Test RK-03: Consecutive Losses
```
Given: 3 consecutive losing trades
When: SessionRiskManager.record_loss() called
Then: can_trade = False, halt_reason = "CONSECUTIVE_LOSSES"
```

---

## 3. Integration Tests (Per RACI Matrix)

### 3.1 Data Ingestion → Profile Binding

#### Test INT-01: Tick → Profile Pipeline
```
Given: DhanWSClient streams 100 ticks for NATURALGAS
When: TickProcessor → CandleBuilder → VolumeProfile pipeline runs
Then:
  - 100 normalized ticks produced
  - 5-minute candles built correctly
  - Session profile updated O(1) per tick
  - POC/VAH/VAL calculated
  - LVNs detected
```

#### Test INT-02: Profile → MarketState Binding
```
Given: Session profile with known POC/VAH/VAL
When: Price moves through different zones
Then:
  - NO_TRADE when price at POC ± 2 ticks
  - BALANCED when price inside VA
  - IMBALANCED when price outside VA + displacement
  - PROBING when price outside VA without displacement
  - Zone sub-classification (NEAR_VAH/NEAR_VAL/NEAR_POC) correct
```

### 3.2 OrderFlow → Aggression Binding

#### Test INT-03: Multi-Signal Aggregation
```
Given: All 7 order flow signals confirmed
When: AggressionScorer.score() called with all flags=True
Then:
  - Score = 4.5
  - Breakdown shows all components at full weight
  - Confidence = HIGH
```

#### Test INT-04: Partial Signal Aggregation
```
Given: Only footprint + CVD confirmed
When: AggressionScorer.score() called
Then:
  - Score = 2.0
  - Breakdown: footprint=1.0, cvd=1.0, others=0.0
  - Confidence = MEDIUM
```

### 3.3 Strategy → Trade Construction Binding

#### Test INT-05: Gate Pipeline → Trade Constructor
```
Given: All 12 gates pass
When: TradeConstructor.build() called
Then:
  - Entry at structural level (LVN/VAH/VAL)
  - Stop loss beyond aggressive print + buffer
  - Target at POC (mean reversion) or extended (trend)
  - R:R ≥ 1.5
  - Cushion ≤ 10 ticks
```

#### Test INT-06: Aggression → Pyramid Binding
```
Given: Position in profit, aggression_score ≥ 3.0
When: PyramidManager.check_pyramid() called
Then:
  - Pyramid eligible
  - Size: 100% for add 1, 50% for add 2
  - Unified SL computed
```

### 3.4 Risk → Trade Construction Binding

#### Test INT-07: Risk Validation
```
Given: Position sizing exceeds 1% absolute ceiling
When: PositionSizer.calculate() called
Then: Lots reduced to stay within ceiling

Given: Daily loss limit hit
When: GatePipeline.evaluate() called
Then: FAIL at GATE 2 (SESSION_STOPPED)
```

### 3.5 LLM → Advisory Binding

#### Test INT-08: LLM Rationale Generation
```
Given: All gates pass, trade signal generated
When: LLMRationaleService.generate_rationale() called
Then:
  - Rationale generated within 5s timeout
  - Rationale references AMT data (POC, VAH, VAL, aggression)
  - Rationale does NOT suggest entry/exit (advisory only)
  - If timeout: returns "Rationale unavailable (timeout)"
```

#### Test INT-09: Quant Engine Pre-Filter
```
Given: agent_decision.direction = "FLAT", probability = 0.52
When: LLMEntryHandler.should_run() called
Then: Returns False (no edge, skip LLM)

Given: agent_decision.regime = "DEAD"
When: LLMEntryHandler.run_entry() called
Then: Returns FLAT directly, no LLM call
```

### 3.6 Full Component Binding (RACI Validation)

#### Test INT-10: TickProcessor Responsibility
```
Verify: TickProcessor is R (Responsible) for tick normalization
Given: Raw tick from DhanWSClient
When: TickProcessor.process_tick() called
Then: Normalized tick produced, all downstream modules receive it
```

#### Test INT-11: VolumeProfile Responsibility
```
Verify: VolumeProfile is R for session/leg profile build, POC/VAH/VAL
Given: Normalized ticks
When: VolumeProfile.update() called
Then: Profile buckets updated, POC/VAH/VAL available to all readers
```

#### Test INT-12: MarketStateEngine Responsibility
```
Verify: MarketStateEngine is R for market state classification
Given: POC/VAH/VAL from VolumeProfile
When: detect_market_state() called
Then: State returned, all strategy modules informed
```

#### Test INT-13: AggressionScorer Responsibility
```
Verify: AggressionScorer is R for multi-signal aggregation
Given: All order flow signals
When: AggressionScorer.score() called
Then: Score returned, TradeConstructor and PyramidManager consume it
```

#### Test INT-14: TradeConstructor Responsibility
```
Verify: TradeConstructor is R for entry/SL/TP construction
Given: Aggression score, market state, profile data
When: build_entry_signal() called
Then: Signal with entry/SL/TP/R:R produced
```

---

## 4. Fabio Valentini Methodology Tests

### 4.1 Volume Profile Correctness (FR-02)

#### Test FAB-01: POC Calculation
```
Given: Profile with known volume distribution
When: POC calculated
Then: POC = price bucket with maximum cumulative volume
Formula: max(profile, key=volume)
```

#### Test FAB-02: VAH/VAL 70% Rule
```
Given: Profile with known POC
When: VAH/VAL calculated
Then:
  - Value area contains 70% of total volume
  - VAH > POC > VAL
  - Expansion from POC outward
```

#### Test FAB-03: LVN Threshold (15% of mean)
```
Given: Profile with mean volume = 1000
When: LVNs detected
Then: LVNs at buckets where volume < 150 (15% of mean)
```

#### Test FAB-04: HVN Threshold (200% of mean)
```
Given: Profile with mean volume = 1000
When: HVNs detected
Then: HVNs at buckets where volume > 2000 (200% of mean)
```

### 4.2 Order Flow Correctness (FR-03)

#### Test FAB-05: CVD Slope Window (20 candles)
```
Given: 25 candles with known deltas
When: CVD slope calculated
Then: Slope = (cvd[-1] - cvd[-20]) / 20
```

#### Test FAB-06: Footprint Imbalance Ratio (3:1)
```
Given: Level with bid=100, ask=350
When: Imbalance check
Then: Ratio = 3.5 ≥ 3.0 → imbalanced
```

#### Test FAB-07: Absorption Formula
```
Given: Candle with range=0.3, ATR=1.0, volume=500, avg_vol=200
When: Absorption check
Then:
  - range / ATR = 0.3 < 0.30 ✓
  - volume / avg_vol = 2.5 > 2.0 ✓
  - Detected = True
```

#### Test FAB-08: Big Trade Multiplier (5×)
```
Given: avg_trade_size = 100
When: Trade with size = 550 arrives
Then: 550 / 100 = 5.5 ≥ 5.0 → big trade detected
```

### 4.3 Market State Correctness (FR-04)

#### Test FAB-09: NO_TRADE Dead Zone (±2 ticks)
```
Given: POC = 100.00, tick_size = 0.10, price = 100.15
When: detect_market_state() called
Then: NO_TRADE (within ±2 ticks = ±0.20)
```

#### Test FAB-10: PROBING State
```
Given: Price = 102.00, VAH = 101.00, no displacement
When: detect_market_state() called
Then: PROBING (outside VA, no displacement)
```

### 4.4 Drive Detection Correctness (FR-05)

#### Test FAB-11: D1 Suppression
```
Given: First touch of VAH
When: DriveTracker.classify_drive() called
Then: D1, entry_valid=False, return_alert=True
```

#### Test FAB-12: D2 Entry After Rejection
```
Given: D1 rejected (wick through, close opposite side) + re-touch
When: DriveTracker.classify_drive() called
Then: D2, entry_valid=True
```

#### Test FAB-13: D3+ Suppression
```
Given: D2 completed + third touch
When: DriveTracker.classify_drive() called
Then: D3+, entry_valid=False
```

### 4.5 Aggression Scoring Correctness (FR-06)

#### Test FAB-14: Additive Scoring (max 4.5)
```
Given: footprint=+1.0, cvd=+1.0, big_trade=+1.0, absorption=+0.5, ofi=+0.5, confluence=+0.5, bubble=+0.5
When: AggressionScorer.score() called
Then: total = 4.5 (max)
```

#### Test FAB-15: Minimum Trade Score (2.0)
```
Given: score = 1.5
When: AggressionResult.confirmed checked
Then: confirmed = False (< 2.0)

Given: score = 2.0
When: AggressionResult.confirmed checked
Then: confirmed = True (≥ 2.0)
```

#### Test FAB-16: Pyramid Score (3.0)
```
Given: score = 2.5
When: AggressionResult.pyramid_eligible checked
Then: pyramid_eligible = False (< 3.0)

Given: score = 3.0
When: AggressionResult.pyramid_eligible checked
Then: pyramid_eligible = True (≥ 3.0)
```

### 4.6 Trade Setup Correctness (FR-07)

#### Test FAB-17: R:R Minimum (1.5)
```
Given: entry=100, SL=99, TP=101.5
When: R:R calculated
Then: reward/risk = 1.5/1.0 = 1.5 ≥ 1.5 ✓

Given: entry=100, SL=99, TP=101.4
When: R:R calculated
Then: reward/risk = 1.4/1.0 = 1.4 < 1.5 → rejected
```

#### Test FAB-18: Cushion Quality Gate (≤10 ticks)
```
Given: cushion = 8 ticks
When: Gate 9 checked
Then: PASS (≤ 10)

Given: cushion = 12 ticks
When: Gate 9 checked
Then: FAIL (INVALID)
```

### 4.7 Partition Exit Correctness (FR-08)

#### Test FAB-19: P1 Exit at 33% R (if momentum weak)
```
Given: Long position, unrealized = 33% of R, CVD slope < 2.0
When: PartitionExitManager.check_exits() called
Then: P1 exit signal (30% of position)
```

#### Test FAB-20: P2 Exit at Target (always)
```
Given: Long position, price = take_profit
When: PartitionExitManager.check_exits() called
Then: P2 exit signal (50% of position)
```

#### Test FAB-21: P3 Trail (if CVD slope > 2.0)
```
Given: P2 taken, CVD slope = 3.0
When: PartitionExitManager.check_exits() called
Then: P3 trail active, SL = current - (remaining × 0.40)
```

#### Test FAB-22: Break-Even at 35% of R
```
Given: Long position, unrealized = 35% of R
When: Break-even check
Then: Stop moved to entry price
```

#### Test FAB-23: Counter-Aggression Hard Exit
```
Given: Position with 2+ opposite signals
When: PartitionExitManager.check_exits() called
Then: Exit ALL partitions immediately
```

### 4.8 Pyramid Correctness (FR-09)

#### Test FAB-24: Max 2 Adds
```
Given: add_count = 2
When: PyramidManager.check_pyramid() called
Then: None (max adds reached)
```

#### Test FAB-25: Decreasing Size
```
Given: add_count = 0
When: Pyramid signal generated
Then: size_multiplier = 1.0 (100%)

Given: add_count = 1
When: Pyramid signal generated
Then: size_multiplier = 0.5 (50%)
```

#### Test FAB-26: Aggression Gate (≥ 3.0)
```
Given: aggression_score = 2.5
When: PyramidManager.check_pyramid() called
Then: None (aggression too low)

Given: aggression_score = 3.0
When: PyramidManager.check_pyramid() called
Then: Pyramid signal (if other conditions met)
```

### 4.9 Risk Management Correctness (FR-10)

#### Test FAB-27: Risk Per Trade (0.5%)
```
Given: equity = 100000
When: PositionSizer.calculate() called
Then: risk_amount = 500 (0.5% of equity)
```

#### Test FAB-28: Daily Loss Limit (2%)
```
Given: session_pnl = -2000 (2% of 100000)
When: SessionRiskManager.check() called
Then: can_trade = False
```

#### Test FAB-29: Consecutive Losses (3)
```
Given: 3 consecutive losing trades
When: SessionRiskManager.record_loss() called
Then: can_trade = False
```

#### Test FAB-30: Max Drawdown (3%)
```
Given: equity_peak = 100000, current_equity = 97000
When: SessionRiskManager.check() called
Then: can_trade = False (drawdown = 3%)
```

---

## 5. LLM Integration Tests

### 5.1 LLM Advisory Role Validation

#### Test LLM-01: LLM Does NOT Decide Entry
```
Given: All gates pass, trade signal generated
When: LLM analyzes market
Then:
  - LLM provides rationale (advisory)
  - Entry decision made by quant engine (deterministic)
  - Signal generated BEFORE LLM completes
  - LLM rationale attached to signal metadata
```

#### Test LLM-02: LLM Does NOT Manage Positions
```
Given: Open position
When: Exit conditions checked
Then:
  - PartitionExitManager decides exits (deterministic)
  - LLM overseer provides commentary only
  - No LLM call for exit decisions
```

#### Test LLM-03: LLM Timeout Handling
```
Given: LLM call takes > 5 seconds
When: LLMRationaleService.generate_rationale() called
Then:
  - Timeout after 5s
  - Returns "Rationale unavailable (timeout)"
  - Signal still goes through (LLM not blocking)
```

### 5.2 Quant Engine Pre-Filter

#### Test LLM-04: DEAD Market Skip
```
Given: agent_decision.regime = "DEAD"
When: LLMEntryHandler.run_entry() called
Then:
  - Returns FLAT directly
  - No LLM inference
  - Rationale: "DEAD market: volume < 5% of average"
```

#### Test LLM-05: No Edge Skip
```
Given: agent_decision.direction = "FLAT", probability = 0.52
When: LLMEntryHandler.should_run() called
Then:
  - Returns False
  - No LLM inference
  - Rationale: "No quant edge: P=0.520 near 50/50"
```

### 5.3 LLM Prompt Accuracy

#### Test LLM-06: Prompt Contains AMT Data
```
Given: Market with known POC/VAH/VAL/CVD/aggression
When: LLM prompt generated
Then: Prompt contains:
  - Market state
  - POC, VAH, VAL values
  - CVD slope and divergence
  - Aggression score breakdown
  - Gate number passed
  - Setup type and R:R
```

#### Test LLM-07: Prompt Does NOT Override AMT
```
Given: AMT analysis shows LONG setup
When: LLM returns SHORT
Then:
  - LLM direction used (advisory)
  - But safety nets still apply (CVD hard gate, momentum fade)
  - If safety nets block: direction → FLAT
```

### 5.4 LLM Safety Nets

#### Test LLM-08: CVD Hard Gate
```
Given: LLM returns LONG, CVD slope = -150 (extreme selling)
When: Safety nets checked
Then: Direction → FLAT (CVD hard gate blocks)
```

#### Test LLM-09: Momentum Fade Gate
```
Given: LLM returns SHORT, 2.5σ bullish candle with no rejection wick
When: check_momentum_fade() called
Then: Direction → FLAT (momentum fade blocks)
```

#### Test LLM-10: Contested Zone Gate
```
Given: LLM returns LONG, footprint shows both BUY and SELL bubbles
When: Contested zone check
Then: Direction → FLAT (contested zone blocks)
```

---

## 6. End-to-End Pipeline Tests

### 6.1 Full Tick-to-Signal Pipeline

#### Test E2E-01: BALANCED Mean Reversion Setup
```
Given:
  - Market BALANCED, price near VAL
  - CVD slope positive (buyers absorbing)
  - Footprint imbalance confirmed
  - Absorption detected
  - LVN at VAL
  - D2 at VAL (D1 rejected)

When: Full pipeline runs (Tick → Profile → OrderFlow → Strategy → Signal)

Then:
  - Market state: BALANCED (NEAR_VAL)
  - Aggression: 3.0+ (HIGH)
  - Gate pipeline: PASS
  - Signal: LONG at VAL
  - SL: below VAL + buffer
  - TP: POC
  - R:R ≥ 1.5
  - Rationale: deterministic explanation generated
```

#### Test E2E-02: IMBALANCED Trend Setup
```
Given:
  - Market IMBALANCED, price outside VA
  - Displacement candle detected
  - CVD slope strong (institutional flow)
  - Big trade cluster at entry level
  - D2 at LVN inside leg

When: Full pipeline runs

Then:
  - Market state: IMBALANCED
  - Aggression: 3.5+ (HIGH)
  - Gate pipeline: PASS
  - Signal: LONG at LVN
  - SL: below LVN + buffer
  - TP: extended beyond VA
  - Trail: active
```

#### Test E2E-03: NO_TRADE Block
```
Given:
  - Price at POC ± 1 tick
  - All signals aligned

When: Full pipeline runs

Then:
  - Market state: NO_TRADE
  - Gate pipeline: FAIL at GATE 3
  - Output: FLAT
  - No signal generated
```

#### Test E2E-04: PROBING Block
```
Given:
  - Price outside VA
  - No displacement candle

When: Full pipeline runs

Then:
  - Market state: PROBING
  - Gate pipeline: FAIL at GATE 4
  - Output: FLAT
  - No signal generated
```

#### Test E2E-05: EIA Window Block
```
Given:
  - Thursday 10:20 ET
  - Symbol: NATURALGAS
  - All other conditions met

When: Full pipeline runs

Then:
  - Gate pipeline: FAIL at GATE 12 (SUPPRESSED)
  - Output: FLAT
  - No signal generated
```

### 6.2 Position Management E2E

#### Test E2E-06: Full Trade Lifecycle
```
Given: LONG signal generated at 100, SL=99, TP=102

When: Price moves through lifecycle

Then:
  1. Entry at 100
  2. Price reaches 100.33 (33% of R) → P1 exit (30%)
  3. Price reaches 101 (break-even) → SL moved to 100
  4. Price reaches 102 (target) → P2 exit (50%)
  5. CVD slope > 2.0 → P3 trail active
  6. Price reaches 102.50 → P3 trail SL = 102.30
  7. Price drops to 102.30 → P3 exit (20%)
```

#### Test E2E-07: Pyramid Add Lifecycle
```
Given: LONG position in profit at 101 (entry 100)

When: Price reaches new LVN at 101.50, aggression ≥ 3.0

Then:
  1. Pyramid add 1 at 101.50 (100% size)
  2. All stops moved to 101.50 SL
  3. Price reaches 102.50, aggression ≥ 3.0
  4. Pyramid add 2 at 102.50 (50% size)
  5. All stops moved to 102.50 SL
  6. No more adds (max 2)
```

### 6.3 Risk E2E

#### Test E2E-08: Daily Loss Circuit Breaker
```
Given: 3 losing trades, total loss = 2% of equity

When: Next signal generated

Then:
  - Gate pipeline: FAIL at GATE 2 (SESSION_STOPPED)
  - No new entries
  - Existing positions still managed
```

#### Test E2E-09: Consecutive Loss Circuit Breaker
```
Given: 3 consecutive losing trades

When: Next signal generated

Then:
  - Gate pipeline: FAIL at GATE 2 (SESSION_STOPPED)
  - halt_reason = "CONSECUTIVE_LOSSES"
```

---

## 7. Performance Tests

### 7.1 Latency Tests

#### Test PERF-01: Tick Processing Latency
```
Given: Single tick arrival
When: Full pipeline runs (Tick → Profile → OrderFlow → Strategy)
Then: Latency < 500ms (NFR-01)
```

#### Test PERF-02: Profile Update (O(1))
```
Given: 10,000 ticks
When: VolumeProfile.update() called for each
Then: Total time < 100ms (O(1) per tick confirmed)
```

### 7.2 Throughput Tests

#### Test PERF-03: Concurrent Symbol Processing
```
Given: 10 symbols streaming simultaneously
When: All pipelines run in parallel
Then: No degradation, all signals processed within latency target
```

### 7.3 Memory Tests

#### Test PERF-04: Buffer Management
```
Given: 100,000 ticks streamed
When: Tick buffer reaches maxlen=10,000
Then: Oldest ticks dropped, no memory leak
```

---

## 8. Test Execution Plan

### 8.1 Phase 1: Unit Tests (Day 1-2)
- Execute all unit tests (Section 2)
- Fix any failures
- Target: 100% pass rate

### 8.2 Phase 2: Integration Tests (Day 3-4)
- Execute all integration tests (Section 3)
- Validate RACI bindings
- Target: 100% pass rate

### 8.3 Phase 3: Fabio Methodology Tests (Day 5-6)
- Execute all Fabio tests (Section 4)
- Validate AMT spec compliance
- Target: 100% pass rate

### 8.4 Phase 4: LLM Integration Tests (Day 7-8)
- Execute all LLM tests (Section 5)
- Validate advisory role
- Target: 100% pass rate

### 8.5 Phase 5: E2E Tests (Day 9-10)
- Execute all E2E tests (Section 6)
- Validate full pipeline
- Target: 100% pass rate

### 8.6 Phase 6: Performance Tests (Day 11)
- Execute all performance tests (Section 7)
- Validate latency/throughput targets
- Target: All NFRs met

---

## 9. Test Data Requirements

### 9.1 Synthetic Data
- 1,000 ticks with known prices, volumes, deltas
- 100 candles with known OHLCV
- Volume profiles with known POC/VAH/VAL/LVNs
- Footprint data with known imbalances

### 9.2 Historical Data
- 1 week of NATURALGAS tick data (MCX)
- 1 week of NIFTY options tick data (NSE)
- Known trade setups from backtesting

### 9.3 Edge Cases
- Zero volume ticks
- Gap ticks (session boundary)
- Stale data (tick age > 30s)
- Extreme CVD (±500)
- Maximum aggression (4.5)

---

## 10. Success Criteria

| Metric | Target | Measurement |
|--------|--------|-------------|
| Unit test pass rate | 100% | All unit tests pass |
| Integration test pass rate | 100% | All RACI bindings validated |
| Fabio spec compliance | 100% | All FR requirements tested |
| LLM advisory correctness | 100% | LLM never decides, only advises |
| E2E pipeline correctness | 100% | Full tick-to-signal validated |
| Latency (NFR-01) | < 500ms | Tick to signal output |
| Profile update (NFR-02) | O(1) | Per-tick update confirmed |
| Threshold match | 17/17 | All constants match plan |
| Gate pipeline | 12/12 | All gates implemented and tested |

---

**Document Control:**
- Created: 2026-03-19
- Next Review: After test execution
- Approved By: TBD