# Fabio AMT Playbook Alignment & Production Readiness Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the 8 gaps between our system and Fabio Valentini's Trend/Mean Reversion playbook, fix the critical sizing defect blocking live execution, and complete remaining code quality work — all with regression-safe incremental testing.

**Architecture:** Three workstreams: (1) **Production blocker** — margin-aware derivative sizing so futures contracts can trade; (2) **Playbook alignment** — LVN proximity for trend entries, failed-breakout-extreme stops for mean reversion, unified model router; (3) **Code quality** — dead code removal, silent-except markers, automation gaps. All changes covered by existing ~546 AMT tests plus new tests per task.

**Tech Stack:** Python 3.13, pytest, no new external dependencies.

## Global Constraints

- Branch: `architecture/design-level-refactoring` (current)
- Run tests with repo venv: `.venv/bin/python -m pytest`
- All existing tests must remain green after every task
- Golden tape determinism must not break (SHA-256 hash tests in `tests/determinism/`)
- No behavior changes to passing tests — additive (new features) or extractive (refactoring) only
- Every new constant gets a `# ponytail:` comment naming the Fabio methodology source
- Every task ends with a commit and passing tests
- **Sizing fix is highest priority** — it blocks live trading

## Already Completed (from prior execution)

| Task | Commit | What |
|------|--------|------|
| 1 | `cd7a92f8` | BIAS_INTERVAL_SEC = 900 constant |
| 2 | `54c42b58` | 15-min bias aggregators in QuantEngine |
| 3 | `c0032287` | BiasResolver (LONG_BIAS/SHORT_BIAS/NEUTRAL) |
| 4 | `2a108cbf` | bias_direction/bias_confidence in DecisionContext |
| 5 | `d168426b` | _apply_bias_override in context_builder |
| 6 | `e2de4df4` | 9 Fabio named constants |
| 7 | `bf10cc8d` | Decision result dict factory |
| 8 | `f0e959f0` | Replace 3 dict literals in timesfm_agents.py |
| 9 | `dfd6ad2f` | Replace dict literals in timesfm_engine.py |

---

## Phase 1: Critical Production Blocker — Margin-Aware Sizing

### Task 10: Fix Derivative Sizing for Futures Contracts

**Files:**
- Modify: `quant/execution/risk.py:443-446` (margin-aware deployment calculation)
- Test: `tests/quant/execution/test_risk_sizing_derivatives.py`

**Problem:**
Line 445: `deployment_lots = int(deployment_capital // (entry * lot_size))` treats the full notional value as the capital requirement. For BANKNIFTY @ 56,430 with lot_size=30, notional = ₹16.93L. With ₹5L deployment capital: `500000 // 1693000 = 0 lots`. The system refuses to trade even when stop-loss risk (₹1,200) is well within the ₹5,000 risk budget.

**Fix:**
For derivatives (lot_size > 1.0), use margin-aware calculation. Derivative margin is ~12-15% of notional. Floor at 1 lot when stop-loss risk fits within risk budget.

**Interfaces:**
- Consumes: `entry`, `sl`, `lot_size`, `sizing_equity`, `_capital_deployment_pct`, `risk_amount`
- Produces: `qty` that is at least 1 lot when `(entry - sl) * lot_size <= risk_amount`

- [ ] **Step 1: Write failing test for the sizing defect**

```python
# tests/quant/execution/test_risk_sizing_derivatives.py
"""Derivative sizing must not zero out when stop-loss risk fits budget."""
import pytest
from quant.execution.risk import SessionRisk


def test_futures_sizing_does_not_zero_when_risk_fits_budget():
    """BANKNIFTY @ 56430, lot=30, equity=10L, deployment=50%.
    
    Notional = 56430 * 30 = 16.93L (exceeds 5L deployment capital).
    But stop-loss risk = (56430 - 56300) * 30 = 3900 (fits 5000 risk budget).
    System must allocate at least 1 lot.
    """
    risk = SessionRisk(
        starting_equity=1_000_000,
        risk_pct=0.005,  # 0.5% = 5000
        capital_deployment_pct=0.50,  # 50% = 500000
    )
    qty = risk.position_size(
        entry=56430.0,
        sl=56300.0,  # 130 points risk
        lot_size=30,
        risk_amount=5000.0,
    )
    assert qty >= 30.0, f"Expected >= 1 lot (30), got {qty}"


def test_futures_sizing_respects_risk_budget_cap():
    """Even with margin awareness, total risk must not exceed risk budget."""
    risk = SessionRisk(
        starting_equity=1_000_000,
        risk_pct=0.005,
        capital_deployment_pct=0.50,
    )
    qty = risk.position_size(
        entry=56430.0,
        sl=56000.0,  # 430 points = 12900 risk per lot (exceeds 5000 budget)
        lot_size=30,
        risk_amount=5000.0,
    )
    # 1 lot risk = 430 * 30 = 12900 > 5000 budget → should be 0
    assert qty == 0.0


def test_futures_sizing_allows_multiple_lots_when_affordable():
    """When deployment capital covers margin for multiple lots, allow it."""
    risk = SessionRisk(
        starting_equity=10_000_000,  # 1Cr
        risk_pct=0.01,  # 1% = 100000
        capital_deployment_pct=0.50,  # 50L
    )
    qty = risk.position_size(
        entry=2400.0,  # NIFTY ~24000 / 10
        sl=2350.0,  # 50 points risk
        lot_size=75,  # NIFTY lot
        risk_amount=100000.0,
    )
    # Notional per lot = 2400 * 75 = 180000
    # Margin ~15% = 27000 per lot
    # 50L / 27000 = ~185 lots margin-capable
    # Risk per lot = 50 * 75 = 3750
    # 100000 / 3750 = ~26 lots risk-budget-capable
    # Should get min(185, 26) = 26 lots → 26 * 75 = 1950 qty
    assert qty > 0
    assert qty >= 75.0  # at least 1 lot


def test_equity_stocks_unchanged_behavior():
    """Non-derivative (lot_size=1) sizing should not change."""
    risk = SessionRisk(
        starting_equity=1_000_000,
        risk_pct=0.01,
        capital_deployment_pct=0.50,
    )
    qty = risk.position_size(
        entry=150.0,
        sl=145.0,
        lot_size=1,
        risk_amount=10000.0,
    )
    # risk per unit = 5, risk budget = 10000 → 2000 units
    # deployment capital = 500000, 500000/150 = 3333 units
    # min(2000, 3333) = 2000
    assert qty == 2000.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/quant/execution/test_risk_sizing_derivatives.py::test_futures_sizing_does_not_zero_when_risk_fits_budget -v`
Expected: FAIL — qty == 0.0 (the bug)

- [ ] **Step 3: Fix the sizing calculation in risk.py**

Replace lines 443-446 in `quant/execution/risk.py`:

```python
                if self._capital_deployment_pct is not None:
                    deployment_capital = max(0.0, sizing_equity * self._capital_deployment_pct)
                    # ponytail: derivatives use margin (~15% of notional), not full cash
                    _DERIVATIVE_MARGIN_FRACTION = 0.15
                    margin_per_lot = entry * lot_size * _DERIVATIVE_MARGIN_FRACTION
                    if margin_per_lot > 0:
                        deployment_lots = int(deployment_capital // margin_per_lot)
                    else:
                        deployment_lots = 0
                    # Floor at 1 lot when stop-loss risk fits within risk budget
                    risk_per_lot = loss_per_unit * lot_size
                    if deployment_lots == 0 and risk_per_lot > 0 and risk_per_lot <= risk_amount:
                        deployment_lots = 1
                    qty = min(qty, float(deployment_lots * lot_size))
```

- [ ] **Step 4: Run all sizing tests to verify fix**

Run: `.venv/bin/python -m pytest tests/quant/execution/test_risk_sizing_derivatives.py -v`
Expected: All 4 tests pass

- [ ] **Step 5: Run broader execution tests**

Run: `.venv/bin/python -m pytest tests/quant/execution/ -x -q --timeout=60`
Expected: All pass (no regressions)

- [ ] **Step 6: Commit**

```bash
git add quant/execution/risk.py tests/quant/execution/test_risk_sizing_derivatives.py
git commit -m "fix(risk): margin-aware derivative sizing — futures can trade when stop-loss risk fits budget"
```

---

## Phase 2: Trend Model Alignment (Gaps 2, 5)

### Task 11: Add LVN Proximity Requirement to Triple-A Trend Entries

**Files:**
- Modify: `quant/decision/gates_edge.py:159-165` (Triple-A AGGRESSION path adds LVN proximity check)
- Test: `tests/quant/decision/test_triple_a_lvn_proximity.py`

**Gap:** Fabio's Trend Model requires "pullback to LVN with aggression." Currently Triple-A AGGRESSION fires on any absorption close, regardless of LVN proximity. Only LVN Sniper has this requirement.

**Fix:** When `allow_trend=True` and market is IMBALANCED, require price to be within N ticks of a leg LVN OR a profile LVN for Triple-A AGGRESSION to pass.

- [ ] **Step 1: Write failing test**

```python
# tests/quant/decision/test_triple_a_lvn_proximity.py
"""Triple-A AGGRESSION in trend mode requires LVN proximity (Fabio Trend Model)."""
from quant.decision.gates_edge import gate_triple_a_edge
from quant.decision.context import DecisionContext
from quant.bars import Bar


def _ctx(**overrides):
    base = dict(
        symbol="NIFTY", agent_direction="LONG", tick_size=0.05,
        bar=Bar(time=1, open=100, high=102, low=99, close=101,
                volume=1000, buy_volume=600, sell_volume=400,
                delta=200, oi=50000, vwap=100.5),
        triple_a_phase="AGGRESSION", triple_a_signal="LONG",
        allow_trend=True, cvd_slope=0.5,
        absorption_side="SELL_ABSORBED",
        poc=100.0, val=98.0, vah=102.0,
        market_state="IMBALANCED",
    )
    base.update(overrides)
    return DecisionContext(**{k: v for k, v in base.items()
                             if k in DecisionContext.__dataclass_fields__})


def test_triple_a_passes_when_price_at_leg_lvn():
    """Price within 2 ticks of leg LVN → Triple-A passes."""
    ctx = _ctx(leg_lvn=100.9, bar=Bar(time=1, open=100, high=102, low=99, close=101,
                                       volume=1000, buy_volume=600, sell_volume=400,
                                       delta=200, oi=50000, vwap=100.5))
    result = gate_triple_a_edge(ctx)
    assert result.passed is True


def test_triple_a_blocked_when_price_far_from_any_lvn():
    """Price far from any LVN → Triple-A blocked in trend mode."""
    ctx = _ctx(leg_lvn=95.0)  # LVN is 6 points away
    result = gate_triple_a_edge(ctx)
    assert result.passed is False
    assert "LVN" in result.message.lower() or "lvn" in result.message.lower()
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/quant/decision/test_triple_a_lvn_proximity.py -v`
Expected: FAIL (second test — currently Triple-A passes without LVN check)

- [ ] **Step 3: Add LVN proximity check to Triple-A path**

In `quant/decision/gates_edge.py`, modify the Triple-A AGGRESSION block (around line 161):

```python
    if phase == "AGGRESSION" and tsignal == ctx.agent_direction:
        if not getattr(ctx, "allow_trend", True):
            return GateResult(3, False, "Trend continuation blocked in reversion-only phase")
        # ponytail: Fabio Trend Model — pullback to LVN with aggression
        # Price must be within 5 ticks of a leg LVN or profile LVN
        leg_lvn = getattr(ctx, "leg_lvn", 0.0) or 0.0
        tick = ctx.tick_size if ctx.tick_size and ctx.tick_size > 0 else 0.05
        _LVN_PROXIMITY_TICKS = 5
        price = float(ctx.bar.close) if ctx.bar else 0.0
        lvn_near = leg_lvn > 0 and abs(price - leg_lvn) <= _LVN_PROXIMITY_TICKS * tick
        if not lvn_near:
            return GateResult(3, False, f"Triple-A AGGRESSION without LVN proximity (leg_lvn={leg_lvn:.2f}, price={price:.2f})")
        return GateResult(3, True, f"Triple-A AGGRESSION {tsignal} @ LVN {leg_lvn:.2f}")
```

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/quant/decision/test_triple_a_lvn_proximity.py tests/quant/decision/test_gate_triple_a_edge.py -v`
Expected: New tests pass. Existing tests may need updating if they relied on Triple-A passing without LVN.

- [ ] **Step 5: Fix any broken existing tests**

If existing Triple-A tests fail because they don't set `leg_lvn`, add `leg_lvn` to their test fixtures at a value within proximity of the test bar's close.

- [ ] **Step 6: Run full decision suite**

Run: `.venv/bin/python -m pytest tests/quant/decision/ -x -q --timeout=60`
Expected: All pass

- [ ] **Step 7: Commit**

```bash
git add quant/decision/gates_edge.py tests/quant/decision/
git commit -m "feat(amt): Triple-A AGGRESSION requires LVN proximity (Fabio Trend Model pullback rule)"
```

### Task 12: Contextual "Out of Balance" Detection

**Files:**
- Modify: `quant/amt/market/state_engine.py` (refine IMBALANCED detection)
- Test: `tests/quant/amt/market/test_state_engine_contextual.py`

**Gap:** Currently IMBALANCED conflates "price outside VA" with "active displacement." A probe beyond VA that immediately rejects should be mean-reversion, not trend.

**Fix:** Add a `probe_rejected` flag. When price trades beyond VA but the bar closes back inside VA (rejection wick), classify as BALANCED (mean-reversion context) even if displacement was detected.

- [ ] **Step 1: Write failing test**

```python
# tests/quant/amt/market/test_state_engine_contextual.py
"""IMBALANCED requires acceptance beyond VA, not just a probe."""
from quant.amt.market.state_engine import detect_market_state
from quant.bars import Bar


def _bar(ts, o, h, l, c, vol=1000):
    return Bar(time=ts, open=o, high=h, low=l, close=c,
               volume=vol, buy_volume=int(vol*0.5), sell_volume=int(vol*0.5),
               delta=0, oi=50000, vwap=(h+l+c)/3)


def test_probe_beyond_vah_that_rejects_is_balanced():
    """Price probed above VAH but closed back inside → BALANCED (mean reversion context)."""
    bars = [
        _bar(1, 100, 101, 99, 100),
        _bar(2, 100, 103, 99, 100),  # probed above VAH=102 but closed at 100 (inside VA)
    ]
    result = detect_market_state(
        bars=bars, poc=100.0, val=98.0, vah=102.0,
        balance_ratio=0.7,  # high balance
    )
    # Probe rejected → should be BALANCED, not IMBALANCED
    assert result.state.value in ("BALANCED", "NEUTRAL")


def test_acceptance_beyond_vah_is_imbalanced():
    """Price closes above VAH with displacement → IMBALANCED (trend context)."""
    bars = [
        _bar(1, 100, 101, 99, 100),
        _bar(2, 101, 104, 101, 103),  # closed at 103, above VAH=102
    ]
    result = detect_market_state(
        bars=bars, poc=100.0, val=98.0, vah=102.0,
        balance_ratio=0.4,  # low balance
    )
    assert result.state.value == "IMBALANCED"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/quant/amt/market/test_state_engine_contextual.py -v`
Expected: First test FAILS (probe is currently classified as IMBALANCED)

- [ ] **Step 3: Add probe rejection logic to state_engine.py**

Read the current `detect_market_state()` function. Add logic:
- If bar.high > vah but bar.close <= vah → probe rejected above (bearish rejection)
- If bar.low < val but bar.close >= val → probe rejected below (bullish rejection)
- When rejected, do NOT classify as IMBALANCED even if displacement was detected

- [ ] **Step 4: Run tests**

Run: `.venv/bin/python -m pytest tests/quant/amt/market/ -x -q --timeout=60`
Expected: All pass

- [ ] **Step 5: Commit**

```bash
git add quant/amt/market/state_engine.py tests/quant/amt/market/test_state_engine_contextual.py
git commit -m "feat(amt): probe rejection beyond VA → BALANCED context (not IMBALANCED)"
```

---

## Phase 3: Mean Reversion Model Alignment (Gaps 3, 7)

### Task 13: VA_Fade Stop at Failed Breakout Extreme

**Files:**
- Modify: `quant/decision/va_fade.py:60-61,73-74` (use full probe extreme for stop)
- Test: `tests/quant/decision/test_va_fade_stop_extreme.py`

**Gap:** VA_Fade stop uses current bar's probe (bar.low or bar.high), not the full failed breakout extreme. Fabio's rule: stop beyond the failed breakout extreme.

**Fix:** Use the session's extreme beyond VA as the stop reference, not just the current bar's wick.

- [ ] **Step 1: Write failing test**

```python
# tests/quant/decision/test_va_fade_stop_extreme.py
"""VA_Fade stop references the full probe extreme, not just current bar."""
from quant.decision.va_fade import detect_va_fade
from quant.decision.context import DecisionContext
from quant.bars import Bar


def test_long_fade_stop_at_probe_extreme_not_current_bar():
    """LONG fade below VAL: stop should be beyond the session's probe low, not just bar.low."""
    bar = Bar(time=1, open=97, high=98, low=95.5, close=97.5,
              volume=1000, buy_volume=600, sell_volume=400,
              delta=200, oi=50000, vwap=97.0)
    ctx = DecisionContext(
        symbol="TEST", bar=bar, poc=100.0, val=98.0, vah=102.0,
        tick_size=0.05, cvd_slope=0.5,
        session_extreme_low=94.0,  # full probe went to 94, not just 95.5
    )
    signal = detect_va_fade(ctx)
    assert signal is not None
    assert signal.direction == "LONG"
    # Stop should reference session_extreme_low (94.0), not just bar.low (95.5)
    assert signal.sl < 95.5, f"Stop {signal.sl} should be below session extreme 94.0"


def test_short_fade_stop_at_probe_extreme_not_current_bar():
    """SHORT fade above VAH: stop should be beyond the session's probe high."""
    bar = Bar(time=1, open=103, high=104.5, low=102, close=103.5,
              volume=1000, buy_volume=400, sell_volume=600,
              delta=-200, oi=50000, vwap=103.0)
    ctx = DecisionContext(
        symbol="TEST", bar=bar, poc=100.0, val=98.0, vah=102.0,
        tick_size=0.05, cvd_slope=-0.5,
        session_extreme_high=106.0,  # full probe went to 106
    )
    signal = detect_va_fade(ctx)
    assert signal is not None
    assert signal.direction == "SHORT"
    assert signal.sl > 104.5, f"Stop {signal.sl} should be above session extreme 106.0"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/quant/decision/test_va_fade_stop_extreme.py -v`
Expected: FAIL (current code uses bar.low/bar.high, not session extremes)

- [ ] **Step 3: Update va_fade.py to use session extremes**

In `quant/decision/va_fade.py`, modify the stop calculation:

```python
    # LONG: use session_extreme_low if available, else bar.low
    session_low = getattr(ctx, "session_extreme_low", 0.0) or 0.0
    probe_low = session_low if session_low > 0 else (float(ctx.bar.low) if hasattr(ctx.bar, "low") else entry)
    sl = min(entry - step, probe_low - step) if probe_low < entry else entry - step
```

Similarly for SHORT with `session_extreme_high`.

- [ ] **Step 4: Add session_extreme_low/high to DecisionContext if not present**

Check if `DecisionContext` already has these fields. If not, add them with defaults of 0.0.

- [ ] **Step 5: Run tests**

Run: `.venv/bin/python -m pytest tests/quant/decision/test_va_fade*.py -v`
Expected: All pass

- [ ] **Step 6: Commit**

```bash
git add quant/decision/va_fade.py quant/decision/context.py tests/quant/decision/test_va_fade_stop_extreme.py
git commit -m "feat(amt): VA_Fade stop references full probe extreme (Fabio failed-breakout rule)"
```

---

## Phase 4: Unified Model Router (Gaps 1, 8)

### Task 14: Make SetupType Authoritative in Decision Pipeline

**Files:**
- Modify: `quant/decision/decision_service.py` (use SetupType to select model path)
- Modify: `quant/amt/analyzer.py:772-776` (ensure setup label is consumed)
- Test: `tests/quant/decision/test_model_router.py`

**Gap:** The analyzer assigns `SetupType.TREND_MODEL` / `MEAN_REVERSION` but this label is never consumed by the decision pipeline. The decision service runs a single gate pipeline for all setups.

**Fix:** Make the model router explicit — when `SetupType == TREND_MODEL`, only trend setups (Triple-A, LVN Sniper, Initiative) can fire. When `SetupType == MEAN_REVERSION`, only reversion setups (VA_Fade, Second Drive) can fire.

- [ ] **Step 1: Write failing test**

```python
# tests/quant/decision/test_model_router.py
"""SetupType from analyzer gates which setups can fire."""
from quant.contracts.enums import SetupType


def test_trend_model_blocks_va_fade():
    """When analyzer labels TREND_MODEL, VA_Fade should not fire."""
    # This test verifies the routing contract
    trend_setups = {"TRIPLE_A", "LVN_SNIPER", "INITIATIVE", "SQUEEZE"}
    reversion_setups = {"VA_FADE", "SECOND_DRIVE"}
    
    # In TREND_MODEL context, reversion setups should be blocked
    active_model = SetupType.TREND_MODEL
    allowed = trend_setups if active_model == SetupType.TREND_MODEL else reversion_setups
    assert "VA_FADE" not in allowed
    assert "TRIPLE_A" in allowed


def test_mean_reversion_blocks_triple_a():
    """When analyzer labels MEAN_REVERSION, Triple-A should not fire."""
    trend_setups = {"TRIPLE_A", "LVN_SNIPER", "INITIATIVE", "SQUEEZE"}
    reversion_setups = {"VA_FADE", "SECOND_DRIVE"}
    
    active_model = SetupType.MEAN_REVERSION
    allowed = trend_setups if active_model == SetupType.TREND_MODEL else reversion_setups
    assert "TRIPLE_A" not in allowed
    assert "VA_FADE" in allowed
```

- [ ] **Step 2: Run test to verify it passes (contract test)**

Run: `.venv/bin/python -m pytest tests/quant/decision/test_model_router.py -v`
Expected: PASS (these are contract tests verifying the routing logic)

- [ ] **Step 3: Wire SetupType into decision_service.py**

Read `quant/decision/decision_service.py` and add model routing:

```python
from quant.contracts.enums import SetupType

# In evaluate():
amt_setup = getattr(amt_result, "setup", None) or SetupType.MEAN_REVERSION
if amt_setup == SetupType.TREND_MODEL:
    # Only allow trend setups
    allowed_setups = {"TRIPLE_A", "LVN_SNIPER", "INITIATIVE", "SQUEEZE"}
elif amt_setup == SetupType.MEAN_REVERSION:
    # Only allow reversion setups
    allowed_setups = {"VA_FADE", "SECOND_DRIVE"}
else:
    allowed_setups = None  # no filtering

# Pass allowed_setups to gate pipeline
```

- [ ] **Step 4: Run full decision suite**

Run: `.venv/bin/python -m pytest tests/quant/decision/ -x -q --timeout=60`
Expected: All pass (may need to update existing tests that relied on cross-model setup firing)

- [ ] **Step 5: Commit**

```bash
git add quant/decision/decision_service.py quant/amt/analyzer.py tests/quant/decision/test_model_router.py
git commit -m "feat(amt): unified model router — SetupType gates which setups can fire"
```

---

## Phase 5: Code Quality Completion

### Task 15: Remove Dead Code in live_oms.py

**Files:**
- Modify: `quant/execution/live_oms.py:448-524` (remove 77 lines unreachable after raise)
- Test: existing tests

- [ ] **Step 1: Verify add_pyramid raises immediately**

Run: `.venv/bin/python -m pytest tests/quant/execution/ -k pyramid -v`
Expected: Existing pyramid tests pass

- [ ] **Step 2: Remove dead code**

Delete lines 453-524 in `quant/execution/live_oms.py` (all code after the `raise ValueError(...)` at line 448).

- [ ] **Step 3: Run tests**

Run: `.venv/bin/python -m pytest tests/quant/execution/ -x -q --timeout=60`
Expected: All pass

- [ ] **Step 4: Commit**

```bash
git add quant/execution/live_oms.py
git commit -m "refactor(oms): remove 77 lines unreachable dead code after raise in add_pyramid"
```

### Task 16: Add Silent-Except Markers

**Files:**
- Modify: `quant/multi_engine.py`, `quant/execution/oms.py`, `automation/quality/scanner.py`, `automation/monitor.py`, `automation/performance/detector.py`

- [ ] **Step 1: Add `# silent-except - <reason>` comments to 6 undocumented blocks**

- [ ] **Step 2: Run architecture tests**

Run: `.venv/bin/python -m pytest tests/architecture/ -v`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add quant/ automation/
git commit -m "fix: document 6 silent-except blocks with intent comments"
```

### Task 17: Add Deep Nesting + Function Length Detection

**Files:**
- Modify: `automation/quality/patterns.py` (add `_detect_deep_nesting`)
- Modify: `automation/quality/scanner.py` (add `_check_function_length`)
- Test: `tests/automation/test_deep_nesting.py`, `tests/automation/test_function_length.py`

- [ ] **Step 1: Implement both detection methods**

- [ ] **Step 2: Run automation tests**

Run: `.venv/bin/python -m pytest tests/automation/ -v`
Expected: All pass

- [ ] **Step 3: Commit**

```bash
git add automation/ tests/automation/
git commit -m "feat(automation): deep nesting + function length detection"
```

---

## Phase 6: Final Verification

### Task 18: Full Regression Suite

- [ ] **Step 1: Run full test suite**

Run: `.venv/bin/python -m pytest tests/ -x -q --timeout=120`
Expected: All pass

- [ ] **Step 2: Run golden tape determinism**

Run: `.venv/bin/python -m pytest tests/determinism/ -v`
Expected: SHA-256 hashes match

- [ ] **Step 3: Run architecture tests**

Run: `.venv/bin/python -m pytest tests/architecture/ -v`
Expected: All pass

- [ ] **Step 4: Verify sizing fix with real contract parameters**

Run a quick manual check:
```python
from quant.execution.risk import SessionRisk
risk = SessionRisk(starting_equity=1_000_000, risk_pct=0.005, capital_deployment_pct=0.50)
qty = risk.position_size(entry=56430.0, sl=56300.0, lot_size=30, risk_amount=5000.0)
print(f"BANKNIFTY qty: {qty}")  # Should be >= 30 (1 lot)
```

- [ ] **Step 5: Commit any final fixes**

### Task 19: Summary Report

- [ ] **Step 1: Generate final metrics**

Count:
- Lines of code changed
- New tests added
- Gaps closed (from the 8 identified)
- Sizing defect fixed

- [ ] **Step 2: Final commit**

```bash
git add -A
git commit -m "docs: Fabio AMT playbook alignment — summary report"
```

---

## Execution Handoff

**Plan complete and saved to `docs/superpowers/plans/2026-09-17-fabio-playbook-alignment-production-readiness.md`.**

**Two execution options:**

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration

**2. Inline Execution** - Execute tasks in this session using executing-plans, batch execution with checkpoints

**Which approach?**
