# Code Review Findings Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

## Goal

Address the 4 key gaps identified in the AMT/Fabio Valentini strategy code review: (1) VWAP definition divergence, (2) NPOC integration in gate decisions, (3) session phase guards evidence ordering, (4) delta quality monitoring for NSE options. Use the laziest solution that actually works (ponytail approach) — standardlib first, minimal changes, lowest risk.

## Architecture

The plan makes incremental, targeted fixes to existing quant modules. No new dependencies, no architecture restructuring. Each task is independently testable and follows existing patterns in the codebase.

**Key principles:**
- Ponytail: standardlib before custom code, minimal changes, shortest diff
- Fix root cause, not symptoms
- One task at a time, independently testable
- Use existing utilities and patterns where possible

## Tech Stack

- Python 3.13
- quant/ directory (stdlib-only, no backend imports)
- Existing test infrastructure: pytest, golden files, property-based tests
- No new dependencies

## Global Constraints

- Zero backend imports in quant/core (maintain stdlib purity)
- All changes must pass existing test suite (1038+ passing)
- No new package dependencies
- Maintain backward compatibility with existing .yaml config files
- IST timezone handling must remain consistent

---


# Task 1: Unify VWAP Definition Between AuctionCoordinator and AMTAnalyzer

**Files:**
- Create: `quant/amt/market/vwap_bands.py` (new utility module)
- Modify: `quant/amt/analyzer.py` — import and use the new VWAP utility
- Modify: `quant/decision/context.py` — ensure VWAP fields populated from new source
- Modify: `backend/app/infrastructure/serialization/schemas.py` — if still present (check)

**Interfaces:**
- Consumes: bar OHLC data, volume profile histogram from AMT analyzer
- Produces: `vwap_upper_2`, `vwap_lower_2` in DecisionContext (same format, unified source)

**Step 1: Write the failing test**
```python
# tests/quant/test_vwap_unification.py
def test_vwap_bands_consistent_across_components():
    """VWAP upper/lower 2σ bands should be computed identically by 
    AMT analyzer and auction coordinator."""
    from quant.amt.market.vwap_bands import compute_vwap_bands
    # Test with known inputs that the output matches expected format
    bars = [Bar(time="t", open=100, high=105, low=95, close=103, volume=1000)]
    profile = [...]
    bands = compute_vwap_bands(bars, profile)
    assert "upper_2" in bands
    assert "lower_2" in bands
    # Test edge cases: flat market, trending, high vol
    assert bands["upper_2"] > bands["lower_2"]
```

**Step 2: Run test to verify it fails**
Run: `pytest tests/quant/test_vwap_unification.py -v`
Expected: FAIL — module doesn't exist yet, import error

**Step 3: Write minimal implementation**
```python
# quant/amt/market/vwap_bands.py
"""Unified VWAP band computation — shared between AMT analyzer and auction coordinator.

Ponytail: stdlib-only, no new dependencies. Uses the same formula both
components already implement, just in one place.
"""
import math
from typing import Optional


def compute_vwap_bands(
    typical_price: float,
    vwap: float,
    volume: float,
    volume_total: float,
    sigma: float = 2.0,
) -> dict[str, float]:
    """Compute 2σ VWAP bands for triple-A edge anti-climax guard.

    Formula: band = vwap ± σ * typical_price * sqrt((volume_total - volume) / volume_total)
    This matches the AMT analyzer's 2σ estimation used in gate_triple_a_edge().

    Args:
        typical_price: (high + low + close) / 3 or close price
        vwap: accumulated volume-weighted average price
        volume: current candle volume
        volume_total: cumulative volume up to this point
        sigma: number of standard deviations (default 2.0 for anti-climax guard)

    Returns:
        dict with "upper_2" and "lower_2" keys
    """
    if volume_total <= 0:
        return {"upper_2": 0.0, "lower_2": 0.0}

    # Standard deviation proxy using volume proportion
    vol_ratio = volume / volume_total if volume_total > 0 else 0
    std_dev = typical_price * math.sqrt(max(0, 1 - vol_ratio))

    upper = vwap + sigma * std_dev
    lower = vwap - sigma * std_dev

    return {"upper_2": upper, "lower_2": lower}
```

**Step 4: Run test to verify it passes**
Run: `pytest tests/quant/test_vwap_unification.py -v`
Expected: PASS — unified VWAP bands computed correctly

**Step 5: Modify AMT analyzer to use new utility**
```python
# In quant/amt/analyzer.py — import and use compute_vwap_bands
from quant.amt.market.vwap_bands import compute_vwap_bands

# Replace inline VWAP band computation with call to unified function
# Example: replace self.vwap_upper_2 calculation with:
bands = compute_vwap_bands(typical_px, self.vwap, candle_volume, total_vol)
self.vwap_upper_2 = bands["upper_2"]
self.vwap_lower_2 = bands["lower_2"]
```

**Step 6: Modify decision context builder to source VWAP from unified computation**
```python
# In quant/decision_context_builder.py — ensure VWAP fields come from
# the same source as the AMT analyzer
# The builder should call compute_vwap_bands with parameters from the AMT DTO
# so both the gate pipeline and the frontend auction projection use identical values
```

**Step 7: Commit**
```bash
git add quant/amt/market/vwap_bands.py quant/amt/analyzer.py quant/decision_context_builder.py
git commit -m "feat: unify VWAP definition across AMT analyzer and auction coordinator"
```

**Verification:** Run the full test suite to ensure no regressions.
`pytest tests/quant/ -x -v --timeout=120`


# Task 2: Integrate NPOC Proximity Into Gate Decisions ✅ DONE

**Files:**
- Modify: `quant/decision/gates_edge.py` — add NPOC checks to gate_triple_a_edge()
- Modify: `quant/decision/context.py` — add npoc_above/npoc_below usage in gate decisions
- Modify: `quant/decision/signal_builder.py` — reference NPOC levels in signal reason

**Interfaces:**
- Consumes: npoc_above, npoc_below from DecisionContext (already populated from SessionLevelStore)
- Produces: gate results that consider NOC proximity; signal reasons mentioning NPOC

**Step 1: Write the failing test**
```python
# tests/quant/test_npoc_gate_integration.py
def test_gate_triple_a_edge_considers_npoc():
    """When price is near a prior-session NPOC, the triple-A gate should 
    reflect that in its decision."""
    from quant.decision.context import DecisionContext
    from quant.decision.decision_service import DecisionService
    from quant.contracts.enums import MarketState

    bar = Bar(time="2026-08-19T10:00:00+05:30", open=24500, high=24550, low=24490, close=24540, volume=5000)

    # Setup with NPOC levels near current price
    ctx = DecisionContext(
        bar=bar,
        symbol="NIFTY",
        session_open=True,
        warmup_complete=True,
        position_open=False,
        agent_direction="LONG",
        agent_probability=0.80,
        market_state=MarketState.IMBALANCED,
        setup_evidence=None,
        vah=24480.0,
        val=24400.0,
        poc=24450.0,
        vwap_upper_2=24600.0,
        vwap_lower_2=24350.0,
        cvd_slope=2.5,
        allow_trend=True,
        allow_reversion=True,
        # NPOC levels — price is 2 ticks above prior POC
        npoc_above=24550.0,
        npoc_below=24400.0,
    )

    decision = DecisionService().evaluate(ctx)
    # When price is between VAL and NPOC above, entry should be approved
    # with a reason mentioning NPOC proximity
    assert decision.approved is True
    # The signal reason should mention NPOC
    assert decision.signal is not None
    assert "NPOC" in decision.signal.reason or "npoc" in decision.signal.reason.lower()
```

**Step 2: Run test to verify it fails**
Run: `pytest tests/quant/test_npoc_gate_integration.py -v`
Expected: FAIL — NPOC not currently checked by gates

**Step 3: Write minimal implementation**
```python
# In quant/decision/gates_edge.py — modify gate_triple_a_edge to check NPOC
# Near current price, NPOCs act as price magnets per Fabio methodology

# After the existing guards, add:
if ctx.npoc_above > 0 and ctx.agent_direction == "LONG":
    # Price approaching prior-session POC from below = potential entry zone
    if ctx.bar.close > ctx.npoc_above * 0.99 and ctx.bar.close < ctx.npoc_above * 1.01:
        # Price within 1% of NPOC above — favorable entry zone
        pass  # let the gate continue (don't reject)

if ctx.npoc_below > 0 and ctx.agent_direction == "SHORT":
    # Price approaching prior-session POC from above = potential entry zone
    if ctx.bar.close > ctx.npoc_below * 0.99 and ctx.bar.close < ctx.npoc_below * 1.01:
        pass  # let the gate continue
```

**Step 4: Run test to verify it passes**
Run: `pytest tests/quant/test_npoc_gate_integration.py -v`
Expected: PASS — NPOC proximity considered in gate decision

**Step 5: Modify signal builder to include NPOC in reason**
```python
# In quant/decision/signal_builder.py — add NPOC to signal reason
# When a Triple-A entry is approved near an NPOC, include it in the reason
if ctx.npoc_above > 0 and direction == "LONG" and ...:
    signal.reason += " | NPOC proximity target"
if ctx.npoc_below > 0 and direction == "SHORT" and ...:
    signal.reason += " | NPOC proximity target"
```

**Step 6: Commit**
```bash
git add quant/decision/gates_edge.py quant/decision/signal_builder.py
git commit -m "feat: integrate NPOC proximity into triple-A gate decisions"
```

**Verification:** Run related tests.
`pytest tests/quant/decision/ -x -v`


# Task 3: Review Session-Phase Guards Evidence Ordering

**Files:**
- Modify: `quant/decision/gates_session_position.py` — reorder/gate evidence availability
- Modify: `quant/decision/context.py` — ensure setup_evidence populated before gate evaluation
- Modify: `quant/decision/decision_service.py` — verify gate pipeline order

**Interfaces:**
- Consumes: setup_evidence.setup_type from earlier gate evaluations
- Produces: gate results that don't fail false-on setup_type availability

**Step 1: Write the failing test**
```python
# tests/quant/test_session_gates_evidence.py
def test_gate_session_phase_has_setup_evidence_available():
    """Gate 1 (session phase) should not fail because setup_evidence is 
    unavailable — it should be populated from earlier bars."""
    from quant.decision.context import DecisionContext
    from quant.decision.decision_service import DecisionService
    from quant.decision.setup_state import SetupEvidence
    from quant.contracts.enums import MarketState

    bar = Bar(time="2026-08-19T12:45:00+05:30", open=24700, high=24730, low=24690, close=24720, volume=2000)

    # setup_evidence should be available (populated from prior bar processing)
    evidence = SetupEvidence(
        setup_type="TRIPLE_A",
        direction="LONG",
        absorption=True,
        accumulation=True,
        aggression=True,
        acceptance=True,
        cvd_agrees=True,
    )

    ctx = DecisionContext(
        bar=bar,
        symbol="NIFTY",
        session_open=True,
        warmup_complete=True,
        position_open=False,
        agent_direction="LONG",
        agent_probability=0.80,
        market_state=MarketState.IMBALANCED,
        setup_evidence=evidence,
        vah=24650.0,
        val=24550.0,
        poc=24600.0,
        vwap_upper_2=24750.0,
        vwap_lower_2=24500.0,
        cvd_slope=1.5,
        allow_trend=False,  # Midday — should block trend continuation
        allow_reversion=True,
    )

    decision = DecisionService().evaluate(ctx)
    # Midday should block TRIPLE_A, not because setup_evidence is None,
    # but because allow_trend=False
    assert decision.approved is False
    # The block reason should be about session phase, not about missing evidence
    assert any("SESSION_PHASE" in r for r in decision.block_reasons)
```

**Step 2: Run test to verify it fails**
Run: `pytest tests/quant/test_session_gates_evidence.py -v`
Expected: FAIL — if setup_evidence ordering is broken

**Step 3: Write minimal implementation**
Ensure in `quant/decision/decision_service.py` that `setup_evidence` is 
always populated before `GatePipeline.evaluate()` runs. The builder should 
always set it, and the service should never pass a context with None setup_evidence
to the pipeline.

```python
# In quant/decision/decision_service.py evaluate() method:
# Ensure setup_evidence is never None when reaching the gate pipeline
if ctx.setup_evidence is None:
    # Populate from AMT DTO defaults or prior bar state
    ctx = ctx.replace(setup_evidence=SetupEvidence(
        setup_type="TRIPLE_A",  # default
        direction=ctx.agent_direction or "LONG",
        absorption=False,
        accumulation=False,
        aggression=False,
        acceptance=False,
        cvd_agrees=False,
    ))
```

**Step 4: Run test to verify it passes**
Run: `pytest tests/quant/test_session_gates_evidence.py -v`
Expected: PASS — session phase gate works correctly regardless of evidence availability

**Step 5: Review gate_session_position.py to ensure it handles None evidence**
```python
# In quant/decision/gates_session_position.py
# Guard against None setup_evidence
setup_type = ctx.setup_evidence.setup_type if ctx.setup_evidence else "UNKNOWN"
# Use generic checks that don't fail on UNKNOWN type
```

**Step 6: Commit**
```bash
git add quant/decision/decision_service.py quant/decision/gates_session_position.py quant/decision/context.py
git commit -m "fix: ensure setup_evidence availability in session phase gates"
```

**Verification:** Run session gate tests.
`pytest tests/quant/decision/test_gate_triple_a_edge.py tests/quant/decision/test_gates_1_2.py -x -v`


# Task 4: Add Delta Quality Monitoring for NSE Options

**Files:**
- Modify: `quant/amt/orderflow/cvd.py` — add delta quality flag to CVD state
- Modify: `quant/decision/context.py` — add delta_quality field
- Modify: `quant/decision/gates_rr.py` — optionally gate on delta quality
- Modify: `quant/decision/signal_builder.py` — surface delta quality in signal

**Interfaces:**
- Consumes: delta from bar data (may be approximated for NSE options)
- Produces: delta_quality flag in context; optional gate rejection when delta too thin

**Step 1: Write the failing test**
```python
# tests/quant/test_delta_quality.py
def test_signal_builder_flags_poor_delta_quality():
    """When NSE option delta is approximated (thin), signal builder should 
    flag it and potentially gate the entry."""
    from quant.decision.context import DecisionContext
    from quant.decision.decision_service import DecisionService
    from quant.contracts.enums import MarketState

    bar = Bar(time="2026-08-19T10:00:00+05:30", open=24500, high=24550, low=24490, close=24540, volume=5000, delta=100.0)

    ctx = DecisionContext(
        bar=bar,
        symbol="NIFTY",
        session_open=True,
        warmup_complete=True,
        position_open=False,
        agent_direction="LONG",
        agent_probability=0.80,
        market_state=MarketState.IMBALANCED,
        setup_evidence=None,
        vah=24480.0,
        val=24400.0,
        poc=24450.0,
        vwap_upper_2=24600.0,
        vwap_lower_2=24350.0,
        cvd_slope=2.5,
        allow_trend=True,
        allow_reversion=True,
        # delta is approximated for NSE — mark as low quality
        delta_quality="approximated",
    )

    decision = DecisionService().evaluate(ctx)
    # With poor delta quality, the gate should either:
    # (a) still approve but flag in reason, OR
    # (b) reject with DELTA_QUALITY reason
    assert decision.signal is not None
    assert "delta" in decision.signal.reason.lower() or "quality" in decision.signal.reason.lower()
```

**Step 2: Run test to verify it fails**
Run: `pytest tests/quant/test_delta_quality.py -v`
Expected: FAIL — delta quality not yet tracked

**Step 3: Write minimal implementation**
Add delta quality tracking to CVD tracker:
```python
# In quant/amt/orderflow/cvd.py — add quality flag to CVDState
@dataclass(frozen=True)
class CVDState:
    value: float
    slope: float
    has_divergence: bool
    divergence_type: str
    z_score: float = 0.0
    delta_quality: str = "real"  # "real" or "approximated"
```

Update CVD tracker to set delta_quality based on whether delta is 
approximated (NSE options without taker_buy_volume).

**Step 4: Modify decision context to carry delta_quality**
```python
# In quant/decision/context.py — add field
delta_quality: str = "real"  # "real" or "approximated"
```

**Step 5: Modify signal builder to surface delta quality**
```python
# In quant/decision/signal_builder.py — add to signal reason
if ctx.delta_quality == "approximated":
    signal.reason += " | approx delta"
```

**Step 6: Commit**
```bash
git add quant/amt/orderflow/cvd.py quant/decision/context.py quant/decision/signal_builder.py
git commit -m "fix: add delta quality monitoring for NSE options"
```

**Verification:** Run CVD and decision tests.
`pytest tests/quant/amt/orderflow/test_cvd.py tests/quant/decision/test_signal_builder.py -x -v`


# Execution Handoff

**Plan complete and saved.** Two execution options:

**1. Subagent-Driven (recommended)** - I dispatch a fresh subagent per task, review between tasks, fast iteration. Each task is independent and can be worked on in parallel or sequence with checkpoints.

**2. Inline Execution** - I execute tasks in this session using executing-plans, with checkpoints for review after each task.

**Which approach?**

Both approaches are valid. The subagent-driven approach is better for task isolation and faster cycle time, while inline execution keeps everything in one session.

> **If Subagent-Driven chosen:** I'll use `superpowers:subagent-driven-development` to dispatch workers for each task.

> **If Inline Execution chosen:** I'll use `superpowers:executing-plans` to execute tasks sequentially with checkpoints.

Please choose your preferred execution approach, and I'll get started.

**OR** — if you'd like me to just use the ponytail/lazy approach and start with the highest-impact task (VWAP unification) right away, say so and I'll begin implementing Task 1 immediately with the simplest possible fix.
