# AMT Strategy Implementation Plan
## Current State Analysis & Gap Remediation Roadmap

---

## EXECUTIVE SUMMARY

The backend now implements ~90% of Fabio Valentini's AMT strategy. Core components are complete and tested.

**Status as of Iterations 1-4:**
- ✅ AMTSetupDetector: AAA, Momentum, Mean Reversion, Failed Auction detection
- ✅ RiskSizingEngine: Theta-aware with holding cost calculations
- ✅ OIWallEngine: Call/put wall detection for order flow proxy
- ✅ OptionSelectionEngine: CE/PE selection, OTM/ATM logic, OI/spread filters, theta kill
- ✅ ScaleManager: 40/30/30 scale-in with confirmation/breakout prices

---

## IMPLEMENTATION STATUS

### ✅ COMPLETED (Iterations 1-4)

| Rule | Component | Status | Tests |
|------|-----------|--------|-------|
| Session Phases (1) | `session_phase_gate.py` | ✅ Production | 8 passed |
| Risk Sizing (2) | `risk_sizing_engine.py` | ✅ Production | Covered |
| 3-Loss Circuit (9) | `session_risk_manager.py` | ✅ Production | All passed |
| Volume Profile (Core) | `volume_profile.py` | ✅ Production | 18 passed |
| AAA Setup (3) | `setup_detector.py` | ✅ Implemented | 11 passed |
| OI Walls (3B) | `oi_wall_engine.py` | ✅ Implemented | 9 passed |
| Option Selection | `option_selection_engine.py` | ✅ Implemented | 8 passed |
| Theta Management | `risk_sizing_engine.py` | ✅ Implemented | Covered |
| Failed Auction | `_detect_failed_auction()` | ✅ Implemented | 10 passed |
| Scale-In | `scale_manager.py` | ✅ Implemented | 12 passed |

### ⚠️ REMAINING ENHANCEMENTS (Lower Priority)

| Rule | Enhancement | Priority |
|------|-------------|----------|
| PCR Integration | PCR bias in gate pipeline | ✅ COMPLETE |
| Day Filters | Event days, budget days, Friday validation | P3 |
| Momentum Squeeze (10) | Compression breakout logic | P3 |
| Confirmation Gate (B4) | Additional OI alignment checks | P3 |

---

## FILE CHANGES SUMMARY (Completed)

### New Files Created:
| File | Purpose |
|------|---------|
| `backend/app/domain/services/oi_wall_engine.py` | OI wall detection |
| `backend/tests/unit/domain/test_oi_wall_engine.py` | OI wall tests |
| `backend/tests/unit/domain/test_scale_in_conditions.py` | Scale-in tests |

### Files Modified:
| File | Changes |
|------|---------|
| `setup_detector.py` | Implemented all detection methods + failed auction |
| `protocols.py` | Extended MarketContext with failed auction fields |
| `option_selection_engine.py` | Full implementation |
| `risk_sizing_engine.py` | Theta fields added |
| `test_failed_auction_detector.py` | Updated to use MarketContext |
| `test_option_selection.py` | Enabled (removed skip) |
| `gate_pipeline.py` | Added PCR bias fields and `_check_pcr_alignment()` method |
| `gate_runner.py` | Added `pcr` parameter to `run_gate_pipeline()` |
| `amt_analyzer.py` | Added `pcr=1.0` to AMTResult return statement |
| `value_objects.py` | Added `pcr` field to AMTResult dataclass |
| `session_event_router.py` | Updated `run_gate_pipeline` to pass PCR parameter |

---

## CURRENT ARCHITECTURE OVERVIEW

```
┌─────────────────────────────────────────────────────────────────┐
│  DATA FLOW: Tick → AMT → Agent → Gate → Entry → Exit            │
├─────────────────────────────────────────────────────────────────┤
│  TickReceived (WebSocket)                                       │
│      ↓                                                          │
│  TradingEngine._tick_loop()                                     │
│      ↓                                                          │
│  TradingSessionService.process_tick()                           │
│      ├─ AMTHandler.analyze() → Volume Profile, CVD, Aggression  │
│      ├─ Agent Pipeline (LightGBM) → Direction + Probability     │
│      ├─ Gate Pipeline (12 gates) → Entry validation             │
│      ├─ EntryCoordinator.execute_signal()                       │
│      └─ ExitCoordinator (callbacks)                             │
└─────────────────────────────────────────────────────────────────┘
```

---

## GAP ANALYSIS BY AMT RULE

### ✅ FULLY IMPLEMENTED

| Rule | Component | Status |
|------|-----------|--------|
| Session Phases (1) | `session_phase_gate.py`, `session_context.py` | ✅ Production |
| Risk Sizing (2) | `risk_sizing_engine.py`, `position_sizer.py` | ✅ Production |
| 3-Loss Circuit (9) | `session_risk_manager.py`, `risk_tier_engine.py` | ✅ Production |
| Volume Profile (Core) | `volume_profile.py`, `incremental_volume_profile.py` | ✅ Production |
| Breakeven | `exit_coordinator.py` | ✅ Production |

### ⚠️ PARTIALLY IMPLEMENTED

| Rule | Gap | Priority |
|------|-----|----------|
| AAA Setup (3) | `setup_detector.py` is stub - no absorption/V-shape detection | P1 |
| Scaling In (4) | Calculated but not executed in pipeline | P2 |
| OI Walls (3B) | No OI wall detection as order flow proxy | P1 |
| Option Selection | Basic strike selection exists, missing PCR/max_pain | P1 |
| Theta Management | No theta decay in risk calculations | P1 |
| Confirmation Gate (B4) | Missing OI alignment, spread checks | P2 |

### ❌ NOT IMPLEMENTED

| Rule | Missing | Priority |
|------|---------|----------|
| Day Filters | Event days, budget days, Friday validation | P2 |
| Momentum Squeeze (10) | No compression breakout logic | P3 |
| Failed Auction Logic | Need failed auction detection | P1 |

---

## IMPLEMENTATION PLAN

### PHASE 1: FOUNDATION (Week 1-2)

#### 1.1 AAA Setup Detector & Absorption Logic
**File**: `backend/app/domain/fabio_ai/strategy/setup_detector.py`

```python
class AMTSetupDetector:
    def detect_aaa_setup(self, amt_result, underlying_data, oi_data):
        """
        Detect AAA setup per Fabio rules:
        1. Price at VAL (within 3 ticks)
        2. Volume spike >= 1.5x average
        3. OI increasing (absorption proxy)
        4. Bullish candle at VAL (close > open, upper 40% range)
        """
        # Implementation details...
```

**Changes needed**:
- Implement `detect_aaa_setup()` 
- Add `is_failed_auction()` logic
- Add absorption detection using OI + volume

#### 1.2 OI Wall Engine
**New File**: `backend/app/domain/services/oi_wall_engine.py`

```python
@dataclass
class OIWall:
    strike: int
    type: str  # CALL_WALL or PUT_WALL
    oi: int
    oi_change: int
    strength: float  # oi / avg_oi ratio

class OIWallEngine:
    def detect_walls(self, option_chain):
        """Identify high-OI strikes as protection levels"""
        # Find strikes where OI > 3x average
        # Return list of OIWalls
```

**Integration**: Called from AMT pipeline, results stored in AMTResult

---

### PHASE 2: OPTIONS ENGINE (Week 2-3)

#### 2.1 Enhanced Option Selector
**File**: `backend/app/domain/fabio_ai/services/option_selector.py`

**Current State**: Basic ATM/OTM selection

**Required Enhancements**:
```python
class OptionSelector:
    def select_option(self, underlying_price, direction, underlier):
        """
        Select optimal option leg with:
        - Liquidity check (OI > threshold, spread < 2%)
        - PCR analysis for directional bias
        - Max pain proximity for strike selection
        - DTE >= 3 days
        - Theta-aware sizing adjustment
        """
        pass
    
    def calculate_theta_risk(self, days_to_expiry, volatility):
        """Estimate theta decay for position sizing"""
        pass
```

#### 2.2 Theta-Aware Position Sizing
**File**: `backend/app/domain/services/risk_sizing_engine.py`

Add theta adjustment to `SizingResult`:
```python
@dataclass(frozen=True)
class SizingResult:
    # existing fields...
    theta_decay_risk: float  # Estimated theta per day
    holding_cost_ratio: float  # theta / expected_profit
    theta_adjusted_lots: int  # Reduced if theta > 20% profit
```

---

### PHASE 3: EXECUTION LOGIC (Week 3-4)

#### 3.1 Scale-In Execution Pipeline
**File**: `backend/app/application/services/entry_coordinator.py`

**Current**: Scale-in plan calculated but not used

**Required**:
```python
def execute_scale_in_signal(self, symbol, sig, session):
    """
    Execute 40/30/30 scale-in:
    1. Entry 1 (40%): Initial signal
    - Add stop management for partial fills
    2. Entry 2 (30%): Price moves 50% toward target
    3. Entry 3 (30%): Price at target zone
    """
    # Track scale-in progress in Signal.metadata
```

#### 3.2 IB-Based Phase Transitions
**File**: `backend/app/domain/services/session_phase_gate.py`

Already has `evaluate_with_ib()` - needs to wire into main session check

---

### PHASE 4: CONFIRMATION GATES (Week 4-5)

#### 4.1 Enhanced Confirmation Bundle
**File**: `backend/app/domain/fabio_ai/services/gate_pipeline.py`

Add to GateContext:
```python
@dataclass
class GateContext:
    # existing fields...
    oi_pressure_aligned: bool  # OI wall + VP level
    bid_ask_spread_ok: bool  # Option spread check
    liquidity_meets_threshold: bool  # OI/volume minimum
```

#### 4.2 Option Chain Confirmation
**File**: `backend/app/application/services/entry_coordinator.py`

```python
def validate_option_confirmation(self, symbol, option_data):
    """
    Pre-execution checks:
    1. Bid-ask spread <= 2% of premium
    2. OI increasing at strike (conviction)
    3. PCR alignment with direction
    """
```

---

### PHASE 5: ADVANCED FEATURES (Week 5-6)

#### 5.1 Momentum Squeeze Detector
**New File**: `backend/app/domain/fabio_ai/strategy/squeeze_detector.py`

```python
class MomentumSqueezeDetector:
    def detect_squeeze_setup(self, price_series, volume_series):
        """
        Identify compression after expansion:
        1. Range compression < 30% of prior expansion
        2. Volume declining
        3. ATR declining
        """
        pass
    
    def detect_breakout(self, current_candle, compression_zone):
        """Entry trigger for squeeze"""
        pass
```

#### 5.2 Event Day Filter
**File**: `backend/app/domain/services/eia_calendar.py`

```python
class EventDayCalendar:
    def is_no_trade_day(self, date, event_type):
        """
        Check against:
        - RBI policy dates
        - Budget dates
        - Election results
        - Monthly expiry Thursday adjustments
        """
```

---

## FILE CHANGES SUMMARY

### New Files to Create:
| File | Purpose |
|------|---------|
| `backend/app/domain/services/oi_wall_engine.py` | OI wall detection |
| `backend/app/domain/fabio_ai/strategy/squeeze_detector.py` | Momentum squeeze |
| `backend/app/domain/fabio_ai/strategy/failed_auction.py` | Failed auction detection |

### Files to Modify:
| File | Changes |
|------|---------|
| `setup_detector.py` | Implement all detection methods |
| `option_selector.py` | Add PCR, max_pain, theta checks |
| `risk_sizing_engine.py` | Add theta adjustments |
| `gate_pipeline.py` | Add OI confirmation gates |
| `entry_coordinator.py` | Add scale-in execution |
| `trading_session.py` | Wire OI wall results |

---

## TESTING PLAN

### Unit Tests (per file):
```bash
pytest tests/unit/test_setup_detector.py
pytest tests/unit/test_oi_wall_engine.py  
pytest tests/unit/test_option_selector.py
pytest tests/unit/test_gate_pipeline.py
```

### Integration Tests:
```bash
# Test full pipeline with mock NIFTY data
pytest tests/integration/test_amt_pipeline.py
```

### Backtesting:
- Use historical NIFTY options data (2024-2025)
- Validate AAA setup detection rate
- Compare realized vs expected R:R

---

## SUCCESS METRICS

| Metric | Target | Measurement |
|--------|--------|-------------|
| AAA Setup Detection Accuracy | >70% | Manual validation |
| Scale-In Execution Rate | 100% | Log analysis |
| Theta-Adjusted Win Rate | >45% | Backtest |
| OI Wall Alignment Bonus | 15% edge | A/B testing |

---

## RISK CONSIDERATIONS

1. **Theta Risk**: Options can lose 50% premium in 2 hours post-expiry
   - Mitigation: Minimum 3 days to expiry
   - Check in position sizing

2. **OI Lag**: NSE OI updates every 3 minutes
   - Mitigation: Use volume as primary, OI as confirmation

3. **Scale-In Complexity**: Partial fills, stop management
   - Mitigation: Test with paper trading first

---

## DEPLOYMENT PHASES

### Phase 1 (Develop): 
- Local testing with historical data
- Unit test coverage >80%

### Phase 2 (Paper):
- Paper trading with NIFTY options
- Monitor real tick rates

### Phase 3 (Live):
- Small position sizes (0.1% equity)
- Gradual scale-up based on performance