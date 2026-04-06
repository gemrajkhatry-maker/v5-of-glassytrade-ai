# Trading Logic Fixes Unit Test Cases

## Test File

`test_trading_logic_fixes.py`

## Test Purpose

Validate critical fixes in two areas:
1. **RegimeDetector re-entry buffer and circuit breaker** -- Tests for the widened 1.5% default buffer (Bug 1), ATR-based widening, circuit breaker activation/expiry/reset (Bug 4), and squeeze override.
2. **LLM Entry Handler gate logic** -- Tests for CVD hard gate, profile shape hard gate, C-grade gate, and CVD penalty/bonus in grade scoring. These are tested as extracted logic patterns since the handler's worker loop is deeply threaded.

## Test Cases Overview

| Case ID | Feature Description                                         | Test Type     |
| ------- | ----------------------------------------------------------- | ------------- |
| RD-01   | Re-entry buffer default is 1.5% (not 0.3%)                 | Positive Test |
| RD-02   | ATR-based widening when ATR > pct buffer                    | Positive Test |
| RD-03   | ATR used when wider than pct buffer                         | Positive Test |
| RD-04   | Outside buffer allows re-entry                              | Positive Test |
| RD-05   | 3 consecutive stops triggers circuit breaker                | Positive Test |
| RD-06   | Circuit breaker expires after time                          | Positive Test |
| RD-07   | Profitable exit resets consecutive counter                  | Positive Test |
| RD-08   | clear_failed_entries resets everything                      | Positive Test |
| RD-09   | Squeeze overrides re-entry blocking                         | Positive Test |
| GL-01   | CVD hard gate blocks LONG on extreme selling                | Positive Test |
| GL-02   | CVD hard gate blocks SHORT on extreme buying                | Positive Test |
| GL-03   | CVD hard gate allows LONG on moderate selling               | Positive Test |
| GL-04   | Profile shape gate blocks LONG on P-shape                   | Positive Test |
| GL-05   | Profile shape gate blocks SHORT on b-shape                  | Positive Test |
| GL-06   | Profile shape gate allows LONG on b-shape                   | Positive Test |
| GL-07   | C-grade gate blocks Low confidence entries                  | Positive Test |
| GL-08   | B-grade (Medium confidence) passes gate                     | Positive Test |
| GL-09   | CVD opposing direction applies -2 penalty                   | Positive Test |
| GL-10   | CVD confirming direction applies +1 bonus                   | Positive Test |

## Detailed Test Steps

### RD-01: Re-entry Buffer Default 1.5%

**Test Purpose**: Verify that the default re-entry buffer is 1.5% (not 0.3%).

**Test Data Preparation**:
- Create RegimeDetector instance
- Record failed entry at level 1000, LONG, phase 1

**Test Steps**:
1. Record failed entry at level 1000
2. Check `is_re_entry_blocked(1010, "LONG", 1)` -- 1% away < 1.5% buffer
3. Expected: True (blocked)

**Expected Results**:
- Re-entry at 1010 is blocked (within 1.5% buffer of 1000)

### RD-02: ATR-based Widening

**Test Purpose**: Verify ATR widens the buffer when ATR exceeds pct-based buffer.

**Test Data Preparation**:
- Record failed entry at 1000

**Test Steps**:
1. Check `is_re_entry_blocked(1010, "LONG", 1, atr=20)` -- ATR=20 > 15 (1.5% of 1000)
2. Expected: True (ATR buffer of 20 used instead of 15)

**Expected Results**:
- ATR buffer (20) is wider than pct buffer (15), so ATR is used and entry is blocked

### RD-03: ATR Used When Wider

**Test Purpose**: Verify ATR buffer is used when it exceeds the percentage-based buffer.

**Test Data Preparation**:
- Record failed entry at 1000

**Test Steps**:
1. Check `is_re_entry_blocked(1018, "LONG", 1, atr=20)` -- 18 < 20 ATR buffer
2. Expected: True (within ATR buffer)

**Expected Results**:
- Price 1018 is 18 away from 1000, ATR buffer is 20, so blocked

### RD-04: Outside Buffer Allows Re-entry

**Test Purpose**: Verify price outside the buffer is NOT blocked.

**Test Data Preparation**:
- Record failed entry at 1000

**Test Steps**:
1. Check `is_re_entry_blocked(1020, "LONG", 1)` -- 2% > 1.5% buffer
2. Expected: False (allowed)

**Expected Results**:
- Re-entry at 1020 is allowed (outside 1.5% buffer)

### RD-05: Circuit Breaker Activation

**Test Purpose**: Verify 3 consecutive stops activates the circuit breaker.

**Test Steps**:
1. Record 3 failed entries
2. Check `is_circuit_breaker_active()` -- should be True

**Expected Results**:
- Circuit breaker is active after 3 consecutive stops

### RD-06: Circuit Breaker Expiry

**Test Purpose**: Verify circuit breaker deactivates after the timeout period.

**Test Steps**:
1. Record 3 failed entries (breaker active)
2. Set `_circuit_breaker_until` to a past time
3. Check `is_circuit_breaker_active()` -- should be False

**Expected Results**:
- Circuit breaker is no longer active after expiry

### RD-07: Profitable Exit Resets Counter

**Test Purpose**: Verify a profitable exit resets the consecutive stop counter.

**Test Steps**:
1. Record 2 failed entries
2. Call `record_successful_exit()`
3. Record 1 more failed entry
4. Check `is_circuit_breaker_active()` -- should be False (only 1 consecutive)

**Expected Results**:
- Circuit breaker is NOT active because successful exit reset the counter

### RD-08: Clear Resets Everything

**Test Purpose**: Verify `clear_failed_entries()` resets all state.

**Test Steps**:
1. Record 3 failed entries (breaker active)
2. Call `clear_failed_entries()`
3. Check `is_circuit_breaker_active()` -- should be False
4. Check `is_re_entry_blocked()` -- should be False

**Expected Results**:
- All state is cleared

### RD-09: Squeeze Overrides Re-entry Block

**Test Purpose**: Verify squeeze_active=True allows re-entry even at a failed level.

**Test Steps**:
1. Record failed entry at 1000 LONG phase 1
2. Check `is_re_entry_blocked(1000, "LONG", 1, squeeze_active=True)` -- should be False

**Expected Results**:
- Re-entry is allowed because squeeze is the entry catalyst

### GL-01 through GL-10: Gate Logic Tests

**Test Purpose**: Validate extracted gate logic patterns from LLM Entry Handler.

These tests implement the exact conditional logic used in the handler's worker loop but in isolation, testing each gate independently.

## Test Considerations

### Mock Strategy
- RegimeDetector tests: No mocks needed, the class is self-contained. Time manipulation uses direct attribute access to `_circuit_breaker_until`.
- Gate logic tests: No mocks needed. Tests replicate the exact conditional patterns from `llm_entry_handler.py` to validate correctness in isolation.

### Boundary Conditions
- Re-entry buffer at exact 1.5% boundary
- ATR exactly equal to pct buffer
- Circuit breaker at exactly MAX_CONSECUTIVE_STOPS
- CVD slope at threshold boundaries (-50, +50)
- Grade score at confidence tier boundaries (0, 1, 3)

### Asynchronous Operations
None. All functions under test are synchronous. The LLM worker loop tests are extracted logic patterns, not actual async operations.
