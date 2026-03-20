# QA Process — AMT + LLM Hybrid Engine
## GlassyTrade AI — Quality Assurance Framework

**Document Version:** 1.0
**Date:** 2026-03-19
**Status:** Ready for Implementation
**Source Documents:** 07_gap_analysis.md, 08_fix_plan.md, 01_master_requirements_specification.md

---

## 1. QA Philosophy

1. **AMT correctness is measurable.** Every formula, threshold, and gate has a deterministic expected output for a given input. Test it.
2. **LLM output is qualifiable, not quantifiable.** Test that LLM doesn't block pipeline, returns within timeout, and doesn't override deterministic decisions.
3. **Test at every phase gate.** No phase is "done" until its tests pass.
4. **Synthetic scenarios before live data.** Build known scenarios first, validate against live later.

---

## 2. Test Pyramid

```
                    ┌─────────────┐
                    │  E2E Tests  │  6 tests — full pipeline scenarios
                    │  (6 tests)  │
                ┌───┴─────────────┴───┐
                │ Integration Tests   │  12 tests — cross-module flows
                │   (12 tests)        │
            ┌───┴─────────────────────┴───┐
            │    Unit Tests               │  62 tests — per-module correctness
            │     (62 tests)              │
        ┌───┴─────────────────────────────┴───┐
        │  Validation Tests (Synthetic)       │  20 tests — known-scenario verification
        │      (20 tests)                     │
    ┌───┴─────────────────────────────────────┴───┐
    │  Spec Compliance Tests                      │  14 tests — plan vs code threshold check
    │      (14 tests)                             │
    └─────────────────────────────────────────────┘

    TOTAL: 114 tests
```

---

## 3. Test Specification by Module

### 3.1 Volume Profile Tests (8 tests)

| Test ID | Module | Input | Expected Output | Verify |
|---|---|---|---|---|
| VP-01 | `find_lvns()` | Profile with bucket at 10% of mean | LVN detected | LVN threshold 0.15 |
| VP-02 | `find_lvns()` | Profile with bucket at 20% of mean | NOT detected | Below threshold edge |
| VP-03 | `find_hvns()` | Profile with bucket at 250% of mean | HVN detected | HVN threshold 2.0 (after fix) |
| VP-04 | `find_hvns()` | Profile with bucket at 160% of mean | NOT detected | 1.6 < 2.0 threshold |
| VP-05 | `create_profile()` | 10 candles, known volumes | POC at max volume bucket | POC calculation |
| VP-06 | Value area | Profile with 1000 total vol | VA contains 700 vol (70%) | VA expansion logic |
| VP-07 | Delta profile | Candles with known buy/sell | buy_volume + sell_volume = volume | Delta tracking |
| VP-08 | Leg profile | Directional candles from VA break | Leg profile built from leg start | Leg detection |

### 3.2 Order Flow Tests (14 tests)

| Test ID | Module | Input | Expected Output | Verify |
|---|---|---|---|---|
| OF-01 | `CVDTracker` | 20 candles with known deltas | CVD = sum(deltas) | Cumulative calc |
| OF-02 | `CVDTracker` | Window=20 candles | Slope over 20, not 14 | Window fix |
| OF-03 | `CVDTracker` | Price new low, CVD higher | BULLISH_DIV detected | Divergence |
| OF-04 | `CVDTracker` | Price new high, CVD lower | BEARISH_DIV detected | Divergence |
| OF-05 | Footprint | 3:1 ratio at 40%+ cells | Imbalance confirmed | FR-03-06 |
| OF-06 | Footprint | 3:1 ratio at 30% cells | NOT confirmed | Below 40% |
| OF-07 | `BubbleDetector` | Volume at 2.5σ above mean | Bubble detected | 2σ threshold |
| OF-08 | `BubbleDetector` | Volume at 1.5σ above mean | NOT detected | Below 2σ |
| OF-09 | `AbsorptionDetector` | Small range + high volume | SELL_ABSORBED detected | Dual condition |
| OF-10 | `AbsorptionDetector` | Large range + high volume | NOT detected | Range too wide |
| OF-11 | `BigTradeDetector` | 3 prints ≥ 5× avg within 2 ticks | Cluster detected | FR-03-11 |
| OF-12 | `BigTradeDetector` | 2 prints (not enough) | NOT detected | Min 3 required |
| OF-13 | `OFICalculator` | 10 candles with known OFI | Correct rolling average | Window=10 |
| OF-14 | `IBDetector` | First 2 candles, then break | IB set, then break detected | FR-03-14/15 |

### 3.3 Market State Tests (8 tests)

| Test ID | Input | Expected State | Verify |
|---|---|---|---|
| MS-01 | Price = POC (within 2 ticks) | NO_TRADE | POC dead zone |
| MS-02 | Price inside VAH-VAL | BALANCED | Inside value area |
| MS-03 | Price outside VA + displacement + acceptance | IMBALANCED | Confirmed break |
| MS-04 | Price outside VA, no displacement | PROBING | Unconfirmed break |
| MS-05 | PROBING state → no trade signal | FLAT output | FR-04-06 suppression |
| MS-06 | BALANCED, price in upper half | NEAR_VAH | Zone sub-classification |
| MS-07 | BALANCED, price near POC | NEAR_POC | Zone sub-classification |
| MS-08 | State transition logged | Log entry exists | FR-04-07 audit |

### 3.4 Drive Detection Tests (6 tests)

| Test ID | Input | Expected Output | Verify |
|---|---|---|---|
| DD-01 | First touch of VAH | D1 recorded, entry suppressed | FR-05-02 |
| DD-02 | D1 rejected (wick + close opposite) + re-touch | D2, entry valid | FR-05-03/04 |
| DD-03 | D1 NOT rejected + re-touch | Entry suppressed | FR-05-05 |
| DD-04 | Third touch of same level | Entry suppressed | FR-05-06 |
| DD-05 | D2 with lower volume than D1 | Momentum fade detected | FR-05-07 |
| DD-06 | Session open | All drives reset | FR-05-08 |

### 3.5 Aggression Scoring Tests (7 tests)

| Test ID | Input Signals | Expected Score | Verify |
|---|---|---|---|
| AS-01 | All 7 signals confirmed | 4.5 (max) | Additive scoring |
| AS-02 | Footprint + CVD + BigTrade | 3.0 (HIGH) | Three 1.0 signals |
| AS-03 | Footprint + CVD only | 2.0 (MEDIUM, tradeable) | Min threshold |
| AS-04 | Footprint only | 1.0 (LOW, no trade) | Below min |
| AS-05 | Absorption + OFI + Confluence | 1.5 (no trade) | Three 0.5 signals |
| AS-06 | Score 3.0 | pyramid_eligible = True | FR-06-09 |
| AS-07 | Score 2.5 | pyramid_eligible = False | Below 3.0 |

### 3.6 Gate Pipeline Tests (12 tests)

| Test ID | Gate | Scenario | Expected Output |
|---|---|---|---|
| GP-00 | GATE 0 | Session not started | BLOCKED |
| GP-01 | GATE 1 | Tick gap > 30 seconds | STALE |
| GP-02 | GATE 2 | 3 consecutive losses | SESSION_STOPPED |
| GP-03 | GATE 3 | Price at POC ± 2 ticks | FLAT |
| GP-04 | GATE 4 | Price outside VA, no displacement | FLAT |
| GP-05 | GATE 5 | No key level near price | WAIT |
| GP-06 | GATE 6 | Price > 3 ticks from level | ALERT |
| GP-07 | GATE 7 | First drive only | FLAT |
| GP-08 | GATE 8 | Aggression 1.5 (< 2.0) | WAIT |
| GP-09 | GATE 9 | Cushion > 10 ticks | INVALID |
| GP-10 | GATE 10 | R:R = 1.2 (< 1.5) | SKIP |
| GP-11 | GATE 11 | Position sizing fails | BLOCKED |

### 3.7 Trade Setup Tests (6 tests)

| Test ID | Input | Expected Output | Verify |
|---|---|---|---|
| TS-01 | MR setup, price near VAL, LONG | TP = POC, SL below VAL | FR-07-06/07 |
| TS-02 | Trend setup, LONG | TP = prev session POC, SL beyond agg print | FR-07-06 |
| TS-03 | R:R = 1.3 | Signal rejected | FR-07-08 (min 1.5) |
| TS-04 | Cushion = 12 ticks | Signal rejected | FR-07-05 (>10 invalid) |
| TS-05 | Cushion = 4 ticks | Signal accepted | FR-07-05 (≤6 acceptable) |
| TS-06 | Cushion = 2 ticks | Signal accepted | FR-07-05 (≤3 excellent) |

### 3.8 Partition Exit Tests (8 tests)

| Test ID | Scenario | Expected Output | Verify |
|---|---|---|---|
| PE-01 | Price at 33% R, CVD weak | P1 exits 30% | FR-08-01 |
| PE-02 | Price at 33% R, CVD strong | P1 skipped | FR-08-02 |
| PE-03 | Price at target | P2 exits 50% (always) | FR-08-03 |
| PE-04 | After P2, CVD > 2.0 | P3 trails | FR-08-04 |
| PE-05 | After P2, CVD weak | P3 exits with P2 | FR-08-04 |
| PE-06 | 2 counter-aggression signals | ALL partitions exit | FR-08-06 |
| PE-07 | Price at 35% R | BE triggered (SL → entry) | FR-08-07 |
| PE-08 | P3 trailing | SL = current - (remaining × 0.40) | FR-08-08 |

### 3.9 Pyramid Tests (5 tests)

| Test ID | Scenario | Expected Output | Verify |
|---|---|---|---|
| PY-01 | Not in profit | No pyramid | FR-09-01 |
| PY-02 | 2 adds already done | No pyramid | FR-09-02 |
| PY-03 | In profit, aggression 3.5, new LVN | Pyramid add 1 (100%) | FR-09-04/05 |
| PY-04 | Second add | Pyramid add 2 (50%) | FR-09-05 |
| PY-05 | After pyramid add | All stops moved to latest SL | FR-09-06 |

### 3.10 Risk Management Tests (8 tests)

| Test ID | Scenario | Expected Output | Verify |
|---|---|---|---|
| RM-01 | Equity 100K, risk 0.5% | Max risk = 500 per trade | FR-10-01 |
| RM-02 | Daily loss reaches 2% | Trading halted | FR-10-02 |
| RM-03 | 3 consecutive losses | Trading paused | FR-10-03 |
| RM-04 | Drawdown from peak = 3% | Trading halted | FR-10-04 |
| RM-05 | Risk calculation > 1% | Capped at 1% | FR-10-05 |
| RM-06 | PositionSizer: entry 100, SL 98, equity 50K | lots = 12 (50K × 0.005 / (2 × point_value)) | FR-10-01 |
| RM-07 | Session risk checked at every signal | Check runs before trade | FR-10-06 |
| RM-08 | All events logged to DB | Log entries exist | FR-10-07 |

### 3.11 LLM Integration Tests (6 tests)

| Test ID | Scenario | Expected Output | Verify |
|---|---|---|---|
| LM-01 | Gates pass, LLM timeout | Signal still emitted (empty rationale) | LLM never blocks |
| LM-02 | Gates pass, LLM returns | Rationale attached to signal | Enrichment works |
| LM-03 | Gates fail | LLM NOT called | No wasted compute |
| LM-04 | LLM rationale contains AMT data | POC, VAH, aggression in output | Prompt accuracy |
| LM-05 | Signal latency without LLM | < 500ms | NFR-01 |
| LM-06 | Overseer as advisory only | Overseer output in UI, not execution | LLM doesn't manage exits |

### 3.12 Spec Compliance Tests (14 tests)

| Test ID | Parameter | Plan Value | Code Value | Pass? |
|---|---|---|---|---|
| SC-01 | `LVN_THRESHOLD` | 0.15 | 0.15 | ? |
| SC-02 | `HVN_THRESHOLD` | 2.00 | 2.00 | ? |
| SC-03 | `VALUE_AREA_PCT` | 0.70 | 0.70 | ? |
| SC-04 | `FOOTPRINT_IMBALANCE_RATIO` | 3.0 | 3.0 | ? |
| SC-05 | `MIN_AGGRESSION_SCORE` | 2.0 | 2.0 | ? |
| SC-06 | `CVD_SLOPE_WINDOW` | 20 | 20 | ? |
| SC-07 | `MAX_DAILY_LOSS_PCT` | 0.02 | 0.02 | ? |
| SC-08 | `MAX_CONSECUTIVE_LOSSES` | 3 | 3 | ? |
| SC-09 | `MIN_RR_RATIO` | 1.5 | 1.5 | ? |
| SC-10 | `BALANCE_RATIO_THRESHOLD` | 0.55 | 0.55 | ? |
| SC-11 | `DISPLACEMENT_MULTIPLIER` | 1.5 | 1.5 | ? |
| SC-12 | `ABSORPTION_RANGE_ATR` | 0.30 | 0.30 | ? |
| SC-13 | `ABSORPTION_VOL_MULT` | 2.00 | 2.00 | ? |
| SC-14 | `BIG_TRADE_MULTIPLIER` | 5.0 | 5.0 | ? |

---

## 4. E2E Scenario Tests (6 tests)

### Scenario 1: TREND_LONG_AT_LVN

```
Given:
  - Market is IMBALANCED (displacement + acceptance)
  - Price pulls back to LVN in leg profile
  - CVD slope positive (buyers confirming)
  - Footprint shows 50% imbalanced cells at 3:1
  - Big trade cluster at LVN
  - D2 (second drive with D1 rejected)
  - Aggression = 4.0 (HIGH)

When: GatePipeline.evaluate()

Then:
  - GATE 0-12 ALL PASS
  - Signal: LONG at LVN price
  - SL: beyond aggressive print + buffer
  - TP: previous session POC
  - R:R ≥ 1.5
  - Partition: P1 ready at 33%R, P2 at TP, P3 trail
  - Rationale: LLM explains setup
```

### Scenario 2: BALANCED_MEAN_REVERSION

```
Given:
  - Market is BALANCED (inside VA)
  - Price near VAL, rejected (wick + close above)
  - CVD divergence bullish (price low, CVD higher)
  - Absorption detected (SELL_ABSORBED)
  - Aggression = 2.5 (MEDIUM)

When: GatePipeline.evaluate()

Then:
  - Signal: LONG at VAL
  - SL: below VAL + buffer
  - TP: POC
  - R:R ≥ 1.5
```

### Scenario 3: NO_TRADE_AT_POC

```
Given:
  - Price within ±2 ticks of POC

When: GatePipeline.evaluate()

Then:
  - GATE 3 FAILS → output "FLAT"
  - No LLM call
  - No signal
```

### Scenario 4: PROBING_SUPPRESSED

```
Given:
  - Price outside VA
  - No displacement candle
  - Market state = PROBING

When: GatePipeline.evaluate()

Then:
  - GATE 4 FAILS → output "FLAT"
  - No entry signal
```

### Scenario 5: COUNTER_AGGRESSION_EXIT

```
Given:
  - Open LONG position
  - 2+ SELL aggression signals detected

When: PartitionExitManager.check_exits()

Then:
  - ALL partitions exit immediately
  - Exit reason: COUNTER_AGGRESSION
```

### Scenario 6: PYRAMID_ADD

```
Given:
  - Open LONG in profit
  - Price at different LVN from entry
  - Aggression = 3.5 (≥ 3.0)
  - Only 1 previous entry (0 adds)

When: PyramidManager.check_pyramid()

Then:
  - Pyramid add triggered
  - Size = 100% of base lots
  - All stops moved to new entry SL
```

---

## 5. QA Process Flow

### 5.1 Per-Phase QA Gate

```
Phase N Implementation
        │
        ▼
┌───────────────────┐
│ Unit Tests Pass   │──► FAIL ──► Fix and re-run
│ (module-level)    │
└───────┬───────────┘
        │ PASS
        ▼
┌───────────────────┐
│ Spec Compliance   │──► FAIL ──► Align code to plan
│ (thresholds match)│
└───────┬───────────┘
        │ PASS
        ▼
┌───────────────────┐
│ Integration Tests │──► FAIL ──► Fix cross-module flow
│ (flow-level)      │
└───────┬───────────┘
        │ PASS
        ▼
┌───────────────────┐
│ E2E Scenario Pass │──► FAIL ──► Debug end-to-end
│ (synthetic data)  │
└───────┬───────────┘
        │ PASS
        ▼
   PHASE COMPLETE
```

### 5.2 Regression Testing

After every phase:
```bash
# Run ALL tests (not just current phase)
pytest tests/ -v --tb=short

# Run spec compliance
pytest tests/validation/test_spec_compliance.py -v

# Run E2E scenarios
pytest tests/integration/test_e2e_trading_lifecycle.py -v
```

### 5.3 Live Validation Checklist

After all phases complete, validate against live data:

- [ ] Volume profile POC/VAH/VAL matches expected levels
- [ ] CVD slope direction matches visual chart inspection
- [ ] Footprint imbalances align with visible aggression candles
- [ ] Market state transitions match manual chart analysis
- [ ] Drive detection catches known level touches
- [ ] Aggression score components all fire independently
- [ ] Gate pipeline rejects known bad setups
- [ ] Partition exits trigger at correct R-multiples
- [ ] Risk limits enforce correctly (test with paper account)
- [ ] LLM rationale is coherent and references AMT data
- [ ] Signal latency < 500ms (excluding LLM)
- [ ] LLM timeout doesn't block signal

---

## 6. Test Data Requirements

### 6.1 Synthetic Data Generator

Create deterministic test fixtures for each scenario:

```python
# tests/fixtures/synthetic_data.py

def balanced_rotation(n: int = 50) -> list[OHLC]:
    """50 candles oscillating inside a VA."""
    
def displacement_leg(n: int = 5) -> list[OHLC]:
    """5 consecutive bullish candles breaking above VA."""
    
def pullback_to_lvn(va: float, lvn: float) -> list[OHLC]:
    """Candles pulling back to a known LVN level."""
    
def aggression_candle(volume_mult: float = 3.0) -> OHLC:
    """Single candle with extreme volume and directional delta."""

def rejection_wick(level: float) -> OHLC:
    """Candle that wicks through level but closes on opposite side."""
```

### 6.2 Expected Output Fixtures

For each synthetic scenario, define the expected AMTResult:

```python
EXPECTED_TREND_LONG = {
    "market_state": "IMBALANCED",
    "poc": 9.50,
    "vah": 10.20,
    "val": 8.80,
    "lvns": [9.10, 9.30],
    "aggression_score": 4.0,
    "signal_direction": "LONG",
    "gate_result": "TRADE",
}
```

---

## 7. Continuous QA Rules

### 7.1 Pre-Commit Checks

```bash
# Must pass before any commit
pytest tests/unit/ -v
pytest tests/validation/test_spec_compliance.py -v
```

### 7.2 Phase Completion Criteria

A phase is complete when:
1. All unit tests for that phase pass
2. All spec compliance tests pass
3. Integration tests involving that phase pass
4. E2E scenarios using that phase pass
5. No regression in previously passing tests
6. Code review approved

### 7.3 Threshold Drift Detection

Automated test that reads `constants.py` and verifies against plan spec:

```python
def test_threshold_drift():
    """Verify all thresholds match plan specification."""
    from app.domain import constants
    assert constants.LVN_THRESHOLD == 0.15
    assert constants.HVN_THRESHOLD == 2.00
    assert constants.MIN_RR_RATIO == 1.5
    assert constants.MAX_DAILY_LOSS_PCT == 0.02
    assert constants.MAX_CONSECUTIVE_LOSSES == 3
    assert constants.CVD_SLOPE_WINDOW == 20
    # ... all 20+ thresholds
```

---

## 8. QA Metrics Dashboard

| Metric | Target | Measured By |
|---|---|---|
| Unit test pass rate | 100% | `pytest tests/unit/` |
| Spec compliance | 100% | `pytest tests/validation/` |
| E2E scenario pass | 100% | `pytest tests/integration/` |
| Gate pipeline coverage | 12/12 gates tested | Gate test count |
| Aggression signal coverage | 7/7 signals tested | Signal test count |
| Threshold drift | 0 deviations | Drift detection test |
| Signal latency (ex-LLM) | < 500ms | Performance test |
| LLM timeout rate | < 10% | LLM integration test |
| Code coverage (new modules) | > 80% | `pytest --cov` |

---

**Document Control:**
- Created: 2026-03-19
- Next Review: After Phase 1 QA gate
- Approved By: TBD
