# Fabio Valentino's Methodology: LLM/ML/RL Decision Framework

**Analysis Based on Chart Fanatics Interview Transcript**

---

## Executive Summary

Fabio Valentino's approach centers on **reading market auction dynamics** through a precise 3-step process that requires **conviction-based execution**. For LLM/ML/RL systems, this translates to:

1. **State Assessment** → Market state classification (BALANCED/IMBALANCED)
2. **Location Validation** → Volume profile alignment
3. **Aggression Confirmation** → Order flow signals

**System Conviction Principle**: All three must align with minimum confidence thresholds.

---

## 1. The Three-Step Decision Model

### Step 1: Market State Assessment
```
INPUT: Volume Profile, CVD (Cumulative Volume Delta), Session Context
OUTPUT: {BALANCED, IMBALANCED}

BALANCED conditions:
- POC stable, VA range tight
- CVD slope near 0, no extremes
- Price oscillating within VA

IMBALANCED conditions:
- VA range expanding
- CVD slope > ±100 (extreme reading)
- Price outside VA with conviction volume
```

**ML Implementation**:
```python
def assess_market_state(profile, cvd_slope, price_vs_va):
    if abs(cvd_slope) > 100:
        return "IMBALANCED"
    if price_vs_va < 0.1:  # Outside 10% of VA
        return "IMBALANCED"
    return "BALANCED"
```

### Step 2: Location Validation
```
INPUT: Price, POC, VAH, VAL, Low Volume Nodes, Weekly POC
OUTPUT: {VALID_LOCATION, INVALID_LOCATION}

VALID_LOCATION requires:
- Price within 5 ticks of key level
- Key level = POC, VAH, VAL, LVN, Weekly POC, IB levels
- For IMBALANCED: leg_POC/VAH/VAL preferred over session levels
```

**RL Implementation**:
```python
def validate_location(price, levels, tick_size):
    threshold = max(tick_size * 5, va_range * 0.10)
    distances = [abs(price - level) for level in levels]
    return min(distances) <= threshold
```

### Step 3: Aggression Confirmation
```
INPUT: Footprint data, Bubble detection, Delta analysis
OUTPUT: {AGGRESSION_CONFIRMED, NO_AGGRESSION}

AGGRESSION_CONFIRMED when:
- 30+ contracts at same price (NSE: 50+ lots)
- Delta flip at key level (absorption)
- CVD divergence with price
```

**LLM Implementation**:
```python
def check_aggression(tick_data, location_level):
    print(f"COORDINATOR: checking aggression at {location_level}")
    if bubble_count(tick_data[-5:]) >= 30 and bubble_price_match:
        return True
    return False
```

---

## 2. Conviction-Based Entry System

### Conviction Levels (Fabio's Risk Model)

| Conviction | Probability Threshold | Action |
|------------|----------------------|--------|
| HIGH | ≥ 0.70 | Execute with full size |
| MEDIUM | ≥ 0.55 | Execute with reduced size |
| LOW | < 0.55 | No entry |

**LLM Confidence Scoring**:
```python
def calculate_conviction(market_state, location_valid, aggression_confirmed):
    base_score = 0.5
    
    if market_state == "IMBALANCED":
        base_score += 0.2
    elif market_state == "BALANCED":
        base_score += 0.1
    
    if location_valid:
        base_score += 0.15
    
    if aggression_confirmed:
        base_score += 0.15
    
    return base_score
```

---

## 3. Session Phase Integration

### New York Session (Primary Trading Window)
```
09:30-11:30 NY Time: TREND MODEL ACTIVE
- Full aggression validation required
- Higher position sizing allowed

11:30-14:00 NY Time: MEAN REVERSION ONLY
- Balanced state trades
- Reduced position sizing

14:00-15:15 NY Time: TREND MODEL ACTIVE
- All models available
- Friday: 50% reduced sizing
```

**RL State Machine**:
```python
class SessionPhaseGate:
    def __init__(self):
        self.phase = "UNKNOWN"
        self.allowed_models = []
        self.size_multiplier = 1.0
    
    def evaluate_phase(self, timestamp):
        # Phase determination logic
        if self.is_new_york_session():
            self.phase = "NEW_YORK"
            self.size_multiplier = 1.0
        return self
```

---

## 4. Setup Detection Engine

### Playbook 1: Trend Following
```python
def detect_trend_setup(market_state, price, profile, aggression):
    if market_state != "IMBALANCED":
        return None
    
    if not aggression:
        return None  # Waiting for trigger
    
    # Target = Previous balance area (POC)
    target = profile.previous_poc
    stop = aggression_level - (tick_size * 2)
    
    return {
        "type": "TREND_FOLLOWING",
        "direction": aggression.direction,
        "risk_reward": 3.0,
        "confidence": 0.75
    }
```

### Playbook 2: Mean Reversion
```python
def detect_mr_setup(market_state, price, profile):
    if market_state != "BALANCED":
        return None
    
    # Look for extreme + rejection
    if price < profile.val - (va_range * 0.5):
        return {
            "type": "MEAN_REVERSION",
            "direction": "LONG",
            "target": profile.poc,
            "confidence": 0.70
        }
```

---

## 5. Risk Management Automation

### Position Sizing (ML-Driven)
```python
def calculate_position_size(account_equity, volatility_regime, conviction):
    base_risk = account_equity * 0.0025  # 0.25% per trade
    
    if volatility_regime == "HIGH":
        multiplier = 0.5
    elif volatility_regime == "LOW":
        multiplier = 2.0
    else:
        multiplier = 1.0
    
    if conviction == "HIGH":
        size = base_risk * multiplier
    elif conviction == "MEDIUM":
        size = base_risk * multiplier * 0.5
    else:
        size = 0  # No trade
    
    return size
```

### Drawdown Protection
```python
class DrawdownManager:
    def __init__(self, max_daily_loss=0.02):
        self.max_loss = max_daily_loss
        self.cum_loss = 0
    
    def check_trade(self, proposed_risk):
        if self.cum_loss + proposed_risk > self.max_loss:
            return False, "Daily loss limit exceeded"
        return True, "OK"
```

---

## 6. Real-Time Signal Coordination

### Multi-Timeframe Alignment
```python
def check_three_align(data_5min, data_1min, amt_result, tick):
    # Higher timeframe bias
    ht_bias = assess_market_state(data_5min)
    
    # Lower timeframe entry
    lt_location = validate_location(tick, amt_result.levels)
    
    # Aggression confirmation
    aggression = check_confirmation_bundle(data_1min, tick)
    
    # All must align
    if ht_bias == amt_result.market_state and lt_location and aggression:
        return build_trade_signal(ht_bias, tick)
    
    return None
```

---

## 7. Conviction Matrix for LLM Decision Making

| Market State | Location | Aggression | Conviction Score | Entry Allowed |
|--------------|----------|------------|------------------|---------------|
| IMBALANCED | ✓ | ✓ | 0.80 (HIGH) | YES |
| IMBALANCED | ✓ | ✗ | 0.55 (MEDIUM) | WAIT |
| IMBALANCED | ✗ | ✓ | 0.55 (MEDIUM) | WAIT |
| BALANCED | ✓ | ✓ | 0.70 (MEDIUM) | MR ONLY |
| BALANCED | ✗ | ✗ | 0.50 (LOW) | NO |

---

## 8. Implementation Architecture

### Core Decision Pipeline
```
1. SESSION_PHASE_GATE → Filter sessions
2. MARKET_STATE_ENGINE → Classify state
3. LOCATION_VALIDATOR → Check proximity
4. AGGRESSION_DETECTOR → Confirm trigger
5. CONVICTION_CALCULATOR → Score entry
6. RISK_MANAGER → Size position
7. EXECUTION_ENGINE → Place order
```

### Data Flow
```python
class FabioDecisionEngine:
    def __init__(self):
        self.phase_gate = SessionPhaseGate()
        self.state_engine = MarketStateEngine()
        self.location_validator = LocationValidator()
        self.aggression_detector = AggressionDetector()
    
    def generate_signal(self, market_data):
        # Step 1: Session check
        phase = self.phase_gate.evaluate()
        if phase.blocked:
            return None
        
        # Step 2: Market state
        state = self.state_engine.analyze(market_data.profile)
        
        # Step 3: Location
        location_valid = self.location_validator.check(
            market_data.price, 
            market_data.key_levels
        )
        
        # Step 4: Aggression
        aggression = self.aggression_detector.detect(
            market_data.tick,
            market_data.order_flow
        )
        
        # Step 5: Conviction
        conviction = self.calculate_conviction(
            state, location_valid, aggression
        )
        
        if conviction >= 0.55:
            return self.build_signal(conviction, aggression, state)
        
        return None
```

---

## 9. Key Implementation Notes

### Critical Success Factors:
1. **Profile Construction**: Must use spot prices for options, not premiums
2. **Aggression Thresholds**: Scale by instrument (NSE: 50 lots, MCX: 20 lots)
3. **Session Timing**: NY session 09:30-11:30 primary, 14:00-15:15 secondary
4. **Stop Placement**: Below aggression level, not structural level
5. **Target Selection**: Previous POC for trend, current POC for MR

### Common Failures to Avoid:
- Trading against market state (PROBING without confirmation)
- Ignoring CVD extreme values in balanced markets
- Taking first drive instead of second drive in IMBALANCED
- Missing weekly context (weekly POC alignment)
- Overtrading in compression days

---

## 10. Performance Metrics

### Target Win Rates:
- TREND MODEL: 70-75% win rate, 1:3 RR
- MEAN REVERSION: 65-70% win rate, 1:2 RR
- Compression Days: < 40% win rate, avoid

### Daily Goals:
- 20-40 executions for statistical significance
- Maximum 4 consecutive losses → session stop
- Daily loss limit: 2% of account
- Focus on quality, not quantity

---

## Conclusion

The LLM/ML/RL system must **embody Fabio's three-alignment principle**:

> "When direction + location + aggression align with conviction, execute."

**System Design Priority**:
1. Accurate market state classification
2. Precise location validation
3. Real-time aggression detection
4. Conviction-based execution filtering
5. Adaptive risk management

The system's edge comes from **patience** - waiting for all three elements to align before acting, then managing the trade with precise stops and targets based on the auction structure.