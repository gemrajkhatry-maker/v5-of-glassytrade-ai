# Fix Plan — AMT Accuracy + LLM Leverage
## GlassyTrade AI — Hybrid Engine Remediation

**Document Version:** 1.0
**Date:** 2026-03-19
**Status:** Ready for Implementation
**Source Documents:** 07_gap_analysis.md, 01-06 (plan), backend/app/ (code)

---

## 0. Design Principles

1. **AMT is the authority.** Every entry/exit decision is deterministic.
2. **LLM enriches, never decides.** LLM provides rationale, narrative, and context.
3. **Fix bugs before features.** Broken thresholds corrupt everything downstream.
4. **Test each layer independently.** AMT accuracy is verifiable without LLM.
5. **Keep existing LLM infrastructure.** Reposition it, don't remove it.
6. **Single config source.** All thresholds in `constants.py`, imported everywhere.

---

## 1. Phase 1 — Bug Fixes (Day 1-2)

**Goal:** Fix all 10 critical bugs. System produces correct results with existing structure.

### 1.1 Fix BUG-01: HVN Threshold

```python
# BEFORE (amt_analyzer.py:389):
threshold = mean_vol * 1.5  # WRONG

# AFTER:
threshold = mean_vol * cfg.HVN_THRESHOLD  # Uses 2.0 from config
```

**Files:** `app/domain/fabio_ai/services/amt_analyzer.py`
**Test:** `find_hvns()` with known profile should return HVNs at >200% mean, not >150%.

### 1.2 Fix BUG-02: Regime Detector Crash

```python
# BEFORE (regime_detector.py:465):
exit_price = post_break[-1].exit_price  # OHLC has no exit_price

# AFTER:
exit_price = post_break[-1].close  # Use close price
```

**Files:** `app/domain/fabio_ai/services/regime_detector.py`
**Test:** `analyze_follow_through()` with SHORT direction should not crash.

### 1.3 Fix BUG-03/04: R:R Inconsistency

Unify R:R to plan spec (1:1.5) in ONE place.

```python
# NEW in constants.py:
MIN_RR_RATIO = 1.5  # Plan FR-07-08: minimum 1:1.5

# entry_gate.py:625:
from app.domain.constants import MIN_RR_RATIO
if rr < MIN_RR_RATIO:
    return None

# trade_manager.py:441:
from app.domain.constants import MIN_RR_RATIO
return (reward / risk) >= MIN_RR_RATIO
```

**Files:** `constants.py`, `entry_gate.py`, `trade_manager.py`
**Test:** Entry signal with R:R < 1.5 is rejected. Same in trade_manager.

### 1.4 Fix BUG-05/06: Risk Thresholds

```python
# risk_manager.py:
MAX_DAILY_DRAWDOWN_PCT = 0.02  # Plan: 2%, was 5%
MAX_CONSECUTIVE_LOSSES = 3      # Plan: 3, was 5
```

**Files:** `app/domain/trading/services/risk_manager.py`
**Test:** 3rd consecutive loss halts trading. 2% drawdown halts trading.

### 1.5 Fix BUG-07: Initial Balance Window

```python
# amt_analyzer.py:493:
class InitialBalanceTracker:
    def __init__(self, ib_minutes: int = 10) -> None:
        # Plan: first 2 candles. For 5-min candles = 10 minutes.
        # Was 30 minutes.
```

**Files:** `app/domain/fabio_ai/services/amt_analyzer.py`
**Test:** IB completes after 10 minutes (2 × 5-min candles), not 30.

### 1.6 Fix BUG-08: Balance Ratio Threshold

```python
# config.py:74:
BALANCE_RATIO_THRESHOLD: float = Field(default=0.55)  # Was 0.70
```

**Files:** `app/config.py`
**Test:** Market with 60% candles inside VA classified as BALANCED (0.60 > 0.55).

### 1.7 Fix BUG-09: Displacement Scaling

```python
# amt_analyzer.py:1066:
if leg_range < avg_range * AMTConfig.DISPLACEMENT_MULTIPLIER:
    # Remove * N scaling. Plan says: range >= ATR × 1.5
    return False
```

**Files:** `app/domain/fabio_ai/services/amt_analyzer.py`
**Test:** 3-candle leg with range >= 1.5× ATR detected as displacement.

### 1.8 Fix BUG-10: Hardcoded SL/TP

```python
# trade_manager.py:37-38:
# Remove hardcoded defaults. SL/TP come from TradeConstructor.
# Keep as fallback only.
stop_loss_pct: float = 0.005  # Fallback only — real SL from entry signal
take_profit_pct: float = 0.015  # Fallback only — real TP from entry signal
```

**Files:** `app/domain/fabio_ai/services/trade_manager.py`
**Test:** When entry signal provides SL/TP, those are used (not hardcoded %).

### 1.9 Fix CVD Slope Window

```python
# cvd_tracker.py:43:
def __init__(self, slope_window: int = 20, ...):  # Was 14
```

**Files:** `app/domain/fabio_ai/services/cvd_tracker.py`
**Test:** CVD slope computed over 20 candles.

### 1.10 Consolidate Constants

Move ALL thresholds to `constants.py`. Remove magic numbers from other files.

```python
# constants.py — consolidated:
# Volume Profile
LVN_THRESHOLD = 0.15
HVN_THRESHOLD = 2.00
VALUE_AREA_PCT = 0.70

# Order Flow
CVD_SLOPE_WINDOW = 20
CVD_STRONG_SLOPE = 2.0
FOOTPRINT_IMBALANCE_RATIO = 3.0
FOOTPRINT_IMBALANCE_PCT = 0.40
ABSORPTION_RANGE_ATR = 0.30
ABSORPTION_VOL_MULT = 2.0
BIG_TRADE_MULTIPLIER = 5.0
VOLUME_BUBBLE_SIGMA = 2.0
OFI_WINDOW = 10

# Aggression
MIN_AGGRESSION_SCORE = 2.0
PYRAMID_AGGRESSION_SCORE = 3.0

# Risk
RISK_PER_TRADE_PCT = 0.005
MAX_DAILY_LOSS_PCT = 0.020
MAX_CONSECUTIVE_LOSSES = 3
MAX_DRAWDOWN_PCT = 0.030
ABSOLUTE_CEILING_PCT = 0.010

# Market State
POC_NO_TRADE_TICKS = 2
BALANCE_RATIO_THRESHOLD = 0.55
DISPLACEMENT_MULTIPLIER = 1.5

# Time
WARM_UP_MINUTES_MCX = 15
WARM_UP_MINUTES_NSE = 15
IB_CANDLES = 2

# Trade Setup
MIN_RR_RATIO = 1.5
MAX_CUSHION_TICKS = 10
```

**Files:** `app/domain/constants.py` + all files importing from it
**Test:** All constants accessible from single source. No magic numbers.

---

## 2. Phase 2 — Market State Engine (Day 3-4)

**Goal:** Implement 4-state market state machine with NO_TRADE and PROBING.

### 2.1 Add NO_TRADE and PROBING States

```python
# enums.py:
class MarketState(str, Enum):
    NO_TRADE = "NO_TRADE"      # ±2 ticks of POC
    BALANCED = "BALANCED"      # Inside VAH-VAL
    IMBALANCED = "IMBALANCED"  # Outside VA + displacement + acceptance
    PROBING = "PROBING"        # Outside VA without displacement
```

### 2.2 Implement Market State Detection

```python
# New method in amt_analyzer.py or standalone:

def detect_market_state(
    price: float,
    poc: float,
    vah: float,
    val: float,
    tick_size: float,
    has_displacement: bool,
    has_acceptance: bool,
) -> MarketState:
    """Fabio's market state classification."""
    
    # GATE 3: NO_TRADE — dead zone around POC
    if abs(price - poc) <= tick_size * POC_NO_TRADE_TICKS:
        return MarketState.NO_TRADE
    
    # Inside value area
    if val <= price <= vah:
        return MarketState.BALANCED
    
    # Outside VA
    if has_displacement and has_acceptance:
        return MarketState.IMBALANCED
    
    # Outside VA but no displacement = PROBING
    return MarketState.PROBING
```

### 2.3 Add Zone Sub-Classification

```python
def classify_zone(price: float, poc: float, vah: float, val: float) -> str:
    """Sub-classification within BALANCED state."""
    mid_va = (vah + val) / 2
    if abs(price - poc) <= (vah - val) * 0.1:
        return "NEAR_POC"
    elif price > mid_va:
        return "NEAR_VAH"
    else:
        return "NEAR_VAL"
```

### 2.4 Wire State Transitions

Log every state change with trigger values for audit trail (FR-04-07).

**Test:** Price at POC → NO_TRADE. Price inside VA → BALANCED. Price outside VA + displacement → IMBALANCED. Price outside VA without displacement → PROBING.

---

## 3. Phase 3 — Drive Detection Engine (Day 5-6)

**Goal:** Implement full D1/D2/D3+ drive system per FR-05.

### 3.1 Standalone DriveTracker Class

```python
class DriveTracker:
    """Tracks touches at key levels per Fabio's drive methodology."""
    
    def __init__(self):
        self._level_history: dict[float, LevelDriveState] = {}
    
    def classify_drive(
        self,
        price: float,
        level: float,
        candle: OHLC,
        direction: str,
    ) -> DriveResult:
        """Classify the current touch of a level.
        
        Returns:
            DriveResult with:
            - drive_number: 1, 2, or 3+
            - entry_valid: True only for D2 with D1 rejected
            - rejection_detected: wick through + close opposite
            - fading_momentum: D2 volume < D1 volume
        """
```

### 3.2 Rejection Detection

```python
def detect_rejection(candle: OHLC, level: float, direction: str) -> bool:
    """Wick through level, close on opposite side."""
    wick_through = (direction == "LONG" and candle.low < level) or \
                   (direction == "SHORT" and candle.high > level)
    close_opposite = (direction == "LONG" and candle.close > level) or \
                     (direction == "SHORT" and candle.close < level)
    return wick_through and close_opposite
```

### 3.3 Momentum Fade Check (FR-05-07)

D2 should show less momentum than D1: lower volume, smaller range.

### 3.4 Session Reset (FR-05-08)

All drive states reset at session open.

**Test:** First touch → D1 (no entry). D1 rejected + re-touch → D2 (entry valid). D1 not rejected + re-touch → suppress. Third touch → suppress.

---

## 4. Phase 4 — Aggression Scoring Engine (Day 7-8)

**Goal:** Implement additive weighted scoring (max 4.5) per FR-06.

### 4.1 Standalone AggressionScorer

```python
class AggressionScorer:
    """Multi-signal additive scoring per Fabio spec."""
    
    @staticmethod
    def score(
        footprint_confirmed: bool,      # FR-06-01: +1.0
        cvd_confirmed: bool,            # FR-06-02: +1.0
        big_trade_confirmed: bool,      # FR-06-03: +1.0
        absorption_detected: bool,      # FR-06-04: +0.5
        ofi_aligned: bool,              # FR-06-05: +0.5
        confluence_bonus: bool,         # FR-06-06: +0.5
        volume_bubble_near: bool,       # FR-06-07: +0.5
    ) -> AggressionResult:
        total = 0.0
        if footprint_confirmed: total += 1.0
        if cvd_confirmed: total += 1.0
        if big_trade_confirmed: total += 1.0
        if absorption_detected: total += 0.5
        if ofi_aligned: total += 0.5
        if confluence_bonus: total += 0.5
        if volume_bubble_near: total += 0.5
        
        if total >= 3.0:
            confidence = "HIGH"
        elif total >= 2.0:
            confidence = "MEDIUM"
        else:
            confidence = "LOW"
        
        return AggressionResult(
            score=total,
            confirmed=total >= 2.0,
            pyramid_eligible=total >= 3.0,
            confidence=confidence,
        )
```

### 4.2 Footprint Imbalance Confirmation (FR-03-06)

Add percentage calculation to FootprintAnalyzer:

```python
def imbalance_confirmed(self, candle: FootprintCandle) -> bool:
    """≥40% of cells at ≥3:1 ratio."""
    if not candle.levels:
        return False
    imbalanced = sum(1 for lv in candle.levels if lv.imbalance)
    return (imbalanced / len(candle.levels)) >= 0.40
```

### 4.3 Wire Each Signal

| Signal | Source Module | Detection Logic |
|---|---|---|
| Footprint confirmed | FootprintEngine | 40% cells at 3:1 ratio |
| CVD confirmed | CVDEngine | Slope confirms direction OR divergence detected |
| Big trade cluster | BigTradeDetector | 3+ prints ≥ 5× avg within 2 ticks |
| Absorption | AbsorptionDetector | Range < ATR×0.3 AND volume > avg×2.0 |
| OFI aligned | OFICalculator | >+0.10 for LONG, <-0.10 for SHORT |
| Confluence | ProfileSelector | LVN within ±3 ticks of session VAH/VAL/POC |
| Volume bubble | BubbleDetector | Directional bubble within 3 ticks of entry zone |

---

## 5. Phase 5 — Missing Order Flow Modules (Day 9-12)

### 5.1 BigTradeDetector (FR-03-11)

```python
class BigTradeDetector:
    def __init__(self, multiplier: float = BIG_TRADE_MULTIPLIER):
        self._multiplier = multiplier
    
    def detect(self, ticks: list[Tick], avg_trade_size: float) -> list[BigTradeCluster]:
        """Find 3+ institutional prints (≥ 5× avg) within 2 ticks of each other."""
```

### 5.2 BubbleDetector (FR-03-07/08)

```python
class BubbleDetector:
    def detect(self, candle: OHLC, hist_candles: list[OHLC]) -> BubbleResult:
        """Volume ≥ mean + 2σ across last 21 bars.
        Classify direction: BUY (ask>bid×2), SELL (bid>ask×2), NEUTRAL."""
```

### 5.3 OFICalculator (FR-03-12)

```python
class OFICalculator:
    def __init__(self, window: int = OFI_WINDOW):
        self._window = window
    
    def update(self, tick: Tick) -> float:
        """(ask_vol - bid_vol) / total_vol, averaged over last N candles."""
```

### 5.4 IBDetector (FR-03-14/15)

```python
class IBDetector:
    def __init__(self, ib_candles: int = IB_CANDLES):
        self._ib_candles = ib_candles
    
    def update(self, candle: OHLC) -> IBResult:
        """Track IB high/low from first N candles. Detect breaks."""
```

### 5.5 AbsorptionDetector (FR-03-09/10)

```python
class AbsorptionDetector:
    def detect(self, candle: OHLC, atr: float, avg_vol: float) -> AbsorptionResult:
        """Dual condition: (high-low) < ATR × 0.30 AND volume > avg_vol × 2.0"""
        candle_range = candle.high - candle.low
        if candle_range < atr * ABSORPTION_RANGE_ATR and candle.volume > avg_vol * ABSORPTION_VOL_MULT:
            # Classify: SELL_ABSORBED → LONG, BUY_ABSORBED → SHORT
            ...
```

---

## 6. Phase 6 — 12-Gate Pipeline (Day 13-14)

**Goal:** Implement sequential gate pipeline. First FAIL = immediate output.

```python
class GatePipeline:
    """Sequential gate validation. First fail returns reason."""
    
    def evaluate(self, context: GateContext) -> GateResult:
        """Run all 12 gates in order."""
        
        # GATE 0: Session time filter
        if not self._gate_0_session_time(context):
            return GateResult(passed=False, gate=0, reason="BLOCKED")
        
        # GATE 1: Data quality
        if not self._gate_1_data_quality(context):
            return GateResult(passed=False, gate=1, reason="STALE")
        
        # GATE 2: Session risk
        if not self._gate_2_session_risk(context):
            return GateResult(passed=False, gate=2, reason="SESSION_STOPPED")
        
        # GATE 3: NO_TRADE state
        if context.market_state == MarketState.NO_TRADE:
            return GateResult(passed=False, gate=3, reason="FLAT")
        
        # GATE 4: PROBING state
        if context.market_state == MarketState.PROBING:
            return GateResult(passed=False, gate=4, reason="FLAT")
        
        # GATE 5: Profile + key level
        if not self._gate_5_profile_level(context):
            return GateResult(passed=False, gate=5, reason="WAIT")
        
        # GATE 6: Price at entry zone
        if not self._gate_6_at_entry_zone(context):
            return GateResult(passed=False, gate=6, reason="ALERT")
        
        # GATE 7: Drive = 2
        if not self._gate_7_drive_valid(context):
            return GateResult(passed=False, gate=7, reason="FLAT")
        
        # GATE 8: Aggression ≥ 2.0
        if context.aggression_score < MIN_AGGRESSION_SCORE:
            return GateResult(passed=False, gate=8, reason="WAIT")
        
        # GATE 9: Cushion ≤ 10 ticks
        if not self._gate_9_cushion(context):
            return GateResult(passed=False, gate=9, reason="INVALID")
        
        # GATE 10: R:R ≥ 1.5
        if not self._gate_10_rr(context):
            return GateResult(passed=False, gate=10, reason="SKIP")
        
        # GATE 11: Position sizing
        if not self._gate_11_position_sizing(context):
            return GateResult(passed=False, gate=11, reason="BLOCKED")
        
        # GATE 12: EIA window
        if not self._gate_12_eia_window(context):
            return GateResult(passed=False, gate=12, reason="SUPPRESSED")
        
        # ALL GATES PASSED
        return GateResult(passed=True, gate=12, reason="TRADE")
```

---

## 7. Phase 7 — Partition Exit Engine (Day 15-17)

**Goal:** Implement P1/P2/P3 partition exits per FR-08.

```python
class PartitionExitManager:
    """Manages position exits in 3 partitions."""
    
    def check_exits(
        self,
        position: ManagedPosition,
        current_price: float,
        cvd_slope: float,
    ) -> list[ExitSignal]:
        signals = []
        
        risk = abs(position.entry_price - position.initial_stop)
        unrealised = current_price - position.entry_price  # for LONG
        
        # P1: 30% at 33% R IF momentum weak
        if not position.p1_taken and unrealised >= risk * 0.33:
            if cvd_slope < CVD_STRONG_SLOPE:  # Weak momentum
                signals.append(ExitSignal("PARTITION_1", 0.30))
                position.p1_taken = True
        
        # P2: 50% at target (ALWAYS)
        if not position.p2_taken and current_price >= position.take_profit:
            signals.append(ExitSignal("PARTITION_2", 0.50))
            position.p2_taken = True
            # Move P3 SL to P2 exit price
            position.stop_loss = current_price
        
        # P3: 20% trail
        if position.p2_taken and not position.p3_taken:
            if cvd_slope >= CVD_STRONG_SLOPE:  # Strong momentum → trail
                # Trail formula: SL = current - (remaining × 0.40)
                remaining = position.take_profit - current_price
                new_sl = current_price - (remaining * 0.40)
                if new_sl > position.stop_loss:
                    position.stop_loss = new_sl
            else:  # Weak → exit with P2
                signals.append(ExitSignal("PARTITION_3", 0.20))
                position.p3_taken = True
        
        # Counter-aggression: 2+ opposite signals = exit ALL
        if position.counter_aggression_count >= 2:
            signals.append(ExitSignal("COUNTER_AGGRESSION", 1.0))
        
        # Break-even: at 35% of R toward target
        if not position.breakeven_set and unrealised >= risk * 0.35:
            position.stop_loss = position.entry_price
            position.breakeven_set = True
        
        return signals
```

---

## 8. Phase 8 — Pyramid Manager (Day 18)

```python
class PyramidManager:
    """Structured add-on to winning positions."""
    
    MAX_ADDS = 2  # 3 total entries (1 initial + 2 adds)
    
    def check_pyramid(
        self,
        position: ManagedPosition,
        current_price: float,
        aggression_score: float,
        lvns: list[float],
    ) -> PyramidSignal | None:
        if position.add_count >= self.MAX_ADDS:
            return None
        
        # Must be in profit
        if not self._in_profit(position, current_price):
            return None
        
        # Must have aggression ≥ 3.0
        if aggression_score < PYRAMID_AGGRESSION_SCORE:
            return None
        
        # Must be at different LVN from previous entries
        if not self._at_new_lvn(current_price, position.entry_lvns, lvns):
            return None
        
        # Size: Add 1 = 100%, Add 2 = 50% of base
        size_multiplier = 1.0 if position.add_count == 0 else 0.5
        
        return PyramidSignal(
            size_multiplier=size_multiplier,
            level=current_price,
            # After add: move ALL stops to latest entry SL
            unified_sl=self._compute_sl(current_price, position),
        )
```

---

## 9. Phase 9 — LLM Repositioning (Day 19-21)

**Goal:** Move LLM from decision layer to enrichment layer.

### 9.1 Remove LLM from Entry Decision Path

**Current:** `three_align_check → LLMEntryHandler → Signal`
**Target:** `GatePipeline → TradeConstructor → LLMRationaleGenerator → Signal`

### 9.2 Remove LLM from Position Management

**Current:** `LLMOverseerHandler → HOLD/EXIT/ADD every 3s`
**Target:** `PartitionExitManager + PyramidManager (deterministic)`

Keep LLMOverseerHandler as optional **advisory** only — outputs go to UI, not to execution.

### 9.3 New LLM Roles

| Role | Trigger | Output | Blocks Signal? |
|---|---|---|---|
| Rationale Generator | After gates pass | Human-readable trade explanation | NO |
| Market Narrator | On state change | "Market transitioning from BALANCE to IMBALANCED" | NO |
| Risk Commentator | On risk events | "3 consecutive losses — reviewing structure" | NO |
| Setup Grader | After aggression score | "A-grade: 4.0/4.5, all signals aligned" | NO |
| Anomaly Explainer | On data issues | "Possible EIA release — suppressing signals" | NO |

### 9.4 LLM Prompt Redesign

```python
def build_rationale_prompt(amt_result, gate_result, aggression_result) -> str:
    return f"""
AMT ANALYSIS (DETERMINISTIC — DO NOT OVERRIDE):
Market State: {amt_result.market_state}
POC: {amt_result.poc} | VAH: {amt_result.value_area_high} | VAL: {amt_result.value_area_low}
CVD Slope: {amt_result.cvd_slope} | Divergence: {amt_result.cvd_divergence}
Aggression: {aggression_result.score}/4.5 ({aggression_result.confidence})
Gate: PASSED at gate {gate_result.gate}
Setup: {gate_result.setup_type} | R:R = {gate_result.rr}

YOUR TASK: Write a 2-3 sentence rationale for a trading journal.
Explain WHY this trade setup is valid using the AMT data above.
Do NOT suggest entry/exit — the system has already decided.
"""
```

### 9.5 LLM Runs Async, Never Blocks

```python
class LLMRationaleService:
    """Async LLM enrichment. Never blocks signal pipeline."""
    
    async def generate_rationale(self, context: dict) -> str:
        """Generate rationale asynchronously. Returns empty string on timeout."""
        try:
            return await asyncio.wait_for(
                self._llm.predict(prompt),
                timeout=5.0  # Short timeout — rationale is nice-to-have
            )
        except asyncio.TimeoutError:
            return "Rationale unavailable (timeout)"
```

---

## 10. Phase 10 — Position Sizer (Day 22)

```python
class PositionSizer:
    """Fixed fractional position sizing per FR-10-01."""
    
    @staticmethod
    def calculate(
        equity: float,
        entry_price: float,
        stop_loss: float,
        point_value: float,
        risk_pct: float = RISK_PER_TRADE_PCT,
    ) -> PositionSize:
        risk_amount = equity * risk_pct
        risk_per_lot = abs(entry_price - stop_loss) * point_value
        if risk_per_lot <= 0:
            return PositionSize(lots=0, risk_amount=0, risk_pct=0)
        
        lots = int(risk_amount / risk_per_lot)
        
        # Hard ceiling: 1% absolute max per trade
        max_risk = equity * ABSOLUTE_CEILING_PCT
        if lots * risk_per_lot > max_risk:
            lots = int(max_risk / risk_per_lot)
        
        return PositionSize(
            lots=max(0, lots),
            risk_amount=lots * risk_per_lot,
            risk_pct=(lots * risk_per_lot) / equity if equity > 0 else 0,
        )
```

---

## 11. Milestone Summary

| Phase | Duration | Deliverable | QA Checkpoint |
|---|---|---|---|
| 1: Bug Fixes | Day 1-2 | All 10 bugs fixed, constants consolidated | All existing tests pass + new threshold tests |
| 2: Market State | Day 3-4 | 4-state machine (NO_TRADE/BALANCED/IMBALANCED/PROBING) | State transition matrix tests |
| 3: Drive Detection | Day 5-6 | D1/D2/D3+ with rejection + momentum fade | Drive scenario tests |
| 4: Aggression Scoring | Day 7-8 | Additive scoring (max 4.5) with all 7 signals | Aggression component tests |
| 5: Order Flow Modules | Day 9-12 | BigTrade, Bubble, OFI, IB, Absorption detectors | Per-module unit tests |
| 6: Gate Pipeline | Day 13-14 | 12-gate sequential pipeline | Gate fail/pass tests |
| 7: Partition Exits | Day 15-17 | P1/P2/P3 + BE + counter-aggression | Exit scenario tests |
| 8: Pyramid Manager | Day 18 | Max 2 adds, decreasing size, unified stops | Pyramid scenario tests |
| 9: LLM Reposition | Day 19-21 | LLM moved to enrichment layer | Latency test (<500ms without LLM) |
| 10: Position Sizer | Day 22 | Fixed fractional sizing | Sizing calculation tests |

**Total: 22 days for complete remediation.**

---

**Document Control:**
- Created: 2026-03-19
- Next Review: After Phase 1
- Approved By: TBD
