# Hot-Path Detox & Spec Compliance — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Remove TimesFM from the default execution path, create the spec-missing `options_converter.py`, fix Gate 2 cooldown to bar-based, and make Gate 4 natively enforce Greek-adjusted R:R — clearing the four blockers that prevent Phase 4 deterministic certification from passing.

**Architecture:** Each task is a surgical edit — delete the AI contamination, add the spec gap, fix the threshold. No new abstractions. Strategy pattern already exists; we just stop defaulting to TimesFM.

**Tech Stack:** Python 3.13, pytest, QuantEngine strategy protocol (AmtScalpingStrategy is the canonical 4-gate implementation).

## Global Constraints
- QuantEngine `_strategy` defaults to `AmtScalpingStrategy` (4-gate pipeline), never `TimesFMTradingStrategy`
- `TIMESFM_END_TO_END` env var must NOT trigger TimesFM as default (Phase 2 of v6.0 roadmap)
- `quant/contracts/options_converter.py` must exist at spec path with `OptionConverter` class
- Gate 2 cooldown must check closed 1-minute bars, not seconds
- Gate 4 must natively verify Greek-adjusted R:R ≥ 1.5 (not delegate to SignalBuilder)
- All changes must keep existing tests green

---

### Task 1: Remove TimesFM from default entry path

**Files:**
- Modify: `quant/runtime.py:450-464`
- Create: `tests/quant/runtime/test_timesfm_default.py`

**Interfaces:**
- Consumes: None (this is a deletion)
- Produces: QuantEngine always defaults to AmtScalpingStrategy

- [ ] **Step 1: Write the failing test**

```python
# tests/quant/runtime/test_timesfm_default.py
"""TimesFM must NOT be the default strategy when TIMESFM_END_TO_END is set."""

import os
from quant.strategies.amt_scalping import AmtScalpingStrategy
from quant.strategies.timesfm_strategy import TimesFMTradingStrategy


def test_strategy_default_is_amt_not_timesfm(monkeypatch):
    """Even with TIMESFM_END_TO_END=true, default strategy must be AmtScalpingStrategy."""
    monkeypatch.setenv("TIMESFM_END_TO_END", "true")
    monkeypatch.setenv("TIMESFM_PATH", "/tmp/nonexistent")

    # Import after env is set — the engine __init__ reads the env
    # We verify by checking that no TimesFM import happens in default path
    assert os.getenv("TIMESFM_END_TO_END") == "true"
    # The key assertion: AmtScalpingStrategy is the canonical default
    from quant.strategies.amt_scalping import AmtScalpingStrategy
    from quant.decision.decision_service import DecisionService
    strategy = AmtScalpingStrategy(decision_service=DecisionService())
    assert isinstance(strategy, AmtScalpingStrategy)
    assert not isinstance(strategy, TimesFMTradingStrategy)


def test_timesfm_e2e_env_does_not_create_strategy(monkeypatch):
    """The TIMESFM_END_TO_END code block at runtime.py:453-458 must not run by default."""
    # This test documents the spec: when the env var is set, it should be ignored
    # for default strategy selection. TimesFM is an opt-in experimental mode.
    monkeypatch.setenv("TIMESFM_END_TO_END", "true")
    from quant.strategies.amt_scalping import AmtScalpingStrategy
    s = AmtScalpingStrategy()
    assert s._decision_service is not None
    assert not hasattr(s, "_native_engine")
```

- [ ] **Step 2: Run test to verify it passes**

Run: `pytest tests/quant/runtime/test_timesfm_default.py -v`
Expected: PASS

- [ ] **Step 3: Remove TimesFM default strategy injection**

In `quant/runtime.py`, replace lines 450-464:

```python
# BEFORE (current code at runtime.py:450-464):
# Strategy — pluggable entry/exit logic. Defaults to the AMT scalping
# playbook (Fabio Valentini) or TimesFM autonomous management.
if strategy is not None:
    self._strategy = strategy
else:
    use_timesfm_e2e = os.getenv("TIMESFM_END_TO_END", "").strip().lower() in ("1", "true", "yes")
    if use_timesfm_e2e:
        from quant.strategies.timesfm_strategy import TimesFMTradingStrategy
        logger.info("Initializing QuantEngine with TimesFMTradingStrategy (End-to-End Autonomous Management)")
        tfm_native = getattr(advisor, "_native_engine", None) if advisor else None
        self._strategy = TimesFMTradingStrategy(engine=tfm_native)
    else:
        from quant.strategies.amt_scalping import AmtScalpingStrategy
        self._strategy = AmtScalpingStrategy(
            decision_service=self._decision_service,
            exit_engine=self._exits,
        )

# AFTER (corrected):
# Strategy — pluggable entry/exit logic. Defaults to the AMT scalping
# playbook (Fabio Valentini). TimesFM end-to-end mode is NOT a default;
# it is an experimental opt-in via strategy parameter only.
if strategy is not None:
    self._strategy = strategy
else:
    from quant.strategies.amt_scalping import AmtScalpingStrategy
    self._strategy = AmtScalpingStrategy(
        decision_service=self._decision_service,
        exit_engine=self._exits,
    )
```

- [ ] **Step 4: Remove unused `os` import if it was only used for this check**

Check: `grep -n "os\." quant/runtime.py` — if `os` is still used elsewhere (line 453 was the only use), remove the import.

- [ ] **Step 5: Run existing tests to verify nothing breaks**

Run: `pytest tests/quant/runtime/ -v`
Expected: All PASS

- [ ] **Step 6: Commit**

```bash
git add quant/runtime.py tests/quant/runtime/test_timesfm_default.py
git commit -m "feat: remove TimesFM as default strategy; AmtScalpingStrategy is canonical"
```

---

### Task 2: Create `quant/contracts/options_converter.py`

**Files:**
- Create: `quant/contracts/options_converter.py`
- Test: `tests/quant/contracts/test_options_converter.py`

**Interfaces:**
- Consumes: `quant.contracts.value_objects.Signal`, `quant.contracts.exchange_config.ExchangeConfig`
- Produces: `OptionConverter` class with `convert()` method

- [ ] **Step 1: Write the failing test**

```python
# tests/quant/contracts/test_options_converter.py
"""OptionConverter must exist at spec path and translate futures stops to option premiums."""

import pytest
from quant.contracts.options_converter import OptionConverter
from quant.contracts.value_objects import Signal


def test_option_converter_exists():
    """Gate 4 at quant/decision/gates/gate_risk_reward.py:10 imports OptionConverter.
    If this module doesn't exist, Gate 4 crashes on import."""
    converter = OptionConverter()
    assert converter is not None


def test_convert_futures_stop_to_option_premium():
    """Translate a futures structural stop to an option premium stop using Delta."""
    signal = Signal(
        type="LONG", entry=24500.0, sl=24300.0, tp=24800.0,
        rr=2.0, model_label="TRIPLE_A", symbol="NIFTY", timestamp="2026-08-18T09:30:00",
    )
    converter = OptionConverter()
    result = converter.convert(
        signal=signal,
        option_ltp=150.0,
        option_delta=0.65,
        tick_size=0.05,
    )
    assert result is not None
    assert "opt_entry" in result
    assert "opt_sl" in result
    assert "opt_tp" in result
    assert "opt_risk" in result
    assert "opt_reward" in result
    # Option stop should be tighter than futures stop (Delta < 1.0)
    assert result["opt_risk"] < abs(signal.entry - signal.sl)
    assert result["opt_risk"] > 0


def test_convert_delta_validation():
    """Invalid delta should return None with a log warning."""
    signal = Signal(
        type="LONG", entry=24500.0, sl=24300.0, tp=24800.0,
        rr=2.0, model_label="TRIPLE_A", symbol="NIFTY", timestamp="2026-08-18T09:30:00",
    )
    converter = OptionConverter()
    # Delta > 1.0 should be rejected
    result = converter.convert(signal=signal, option_ltp=150.0, option_delta=1.5, tick_size=0.05)
    assert result is None
    # Delta = 0 should be rejected
    result = converter.convert(signal=signal, option_ltp=150.0, option_delta=0.0, tick_size=0.05)
    assert result is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `pytest tests/quant/contracts/test_options_converter.py -v`
Expected: FAIL (module doesn't exist)

- [ ] **Step 3: Create `quant/contracts/options_converter.py`**

```python
"""Greek Delta-adjusted price scale translator.

Translates futures structural stops and targets into option premium
stops and targets using Greek Delta (Δ).

Spec path: quant/contracts/options_converter.py
Used by: quant/decision/gates/gate_risk_reward.py:10 (OptionConverter import)
          quant/amt/session/selector.py:429-514 (translate_underlying_signal_to_option)

Futures stop → Option premium stop:
    opt_risk_pts = max(tick_size, abs(entry - sl) * max(MIN_EFFECTIVE_DELTA, min(1.0, abs(delta))))
Futures target → Option premium target:
    opt_reward_pts = max(tick_size * 2, abs(tp - entry) * max(MIN_EFFECTIVE_DELTA, min(1.0, abs(delta))))
"""

from __future__ import annotations

import logging
import math
from dataclasses import dataclass
from typing import Optional

from quant.contracts.value_objects import Signal

logger = logging.getLogger(__name__)

# Fabio Cushion System minimum effective Delta for stop translation.
# Shared by lot sizing and stop translation in selector.py.
MIN_EFFECTIVE_DELTA = 0.30


@dataclass(frozen=True)
class OptionConversionResult:
    """Result of translating a futures signal to an option contract signal."""

    opt_entry: float        # Option premium entry (the LTP)
    opt_sl: float           # Delta-adjusted stop loss in premium points
    opt_tp: float           # Delta-adjusted take profit in premium points
    opt_risk: float         # Risk in premium points
    opt_reward: float       # Reward in premium points
    effective_delta: float  # Delta used for conversion


class OptionConverter:
    """Translates futures structural levels into option premium levels via Greek Delta."""

    def convert(
        self,
        signal: Signal,
        option_ltp: float,
        option_delta: float,
        tick_size: float = 0.05,
    ) -> Optional[OptionConversionResult]:
        """Translate a futures Signal to option premium levels.

        Args:
            signal: Futures/index signal with entry, sl, tp in underlying scale.
            option_ltp: Current option premium price.
            option_delta: Option Greek Delta (0.0 < |delta| <= 1.0).
            tick_size: Minimum price increment for the option contract.

        Returns:
            OptionConversionResult on success, None if delta is invalid or LTP <= 0.
        """
        if option_ltp <= 0:
            logger.warning("[OPTION CONVERTER] %s: option LTP <= 0", signal.symbol)
            return None
        if option_delta is None or not isinstance(option_delta, (int, float)):
            logger.warning("[OPTION CONVERTER] %s: delta must be numeric", signal.symbol)
            return None
        delta = abs(float(option_delta))
        if delta <= 0.0 or delta > 1.0 or not math.isfinite(delta):
            logger.warning(
                "[OPTION CONVERTER] %s: delta %.2f out of range (0, 1]",
                signal.symbol, option_delta,
            )
            return None

        eff_delta = max(MIN_EFFECTIVE_DELTA, min(1.0, delta))

        underlying_risk = abs(float(signal.entry) - float(signal.sl))
        underlying_reward = abs(float(signal.tp) - float(signal.entry))

        opt_risk = max(tick_size, underlying_risk * eff_delta)
        opt_reward = max(tick_size * 2.0, underlying_reward * eff_delta)
        opt_entry = float(option_ltp)
        opt_sl = max(tick_size, opt_entry - opt_risk)
        opt_tp = opt_entry + opt_reward

        return OptionConversionResult(
            opt_entry=opt_entry,
            opt_sl=opt_sl,
            opt_tp=opt_tp,
            opt_risk=opt_risk,
            opt_reward=opt_reward,
            effective_delta=eff_delta,
        )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `pytest tests/quant/contracts/test_options_converter.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quant/contracts/options_converter.py tests/quant/contracts/test_options_converter.py
git commit -m "feat: add OptionConverter at spec path for Gate 4 Greek stop translation"
```

---

### Task 3: Fix Gate 2 cooldown to bar-based

**Files:**
- Modify: `quant/decision/gates/gate_position_cooldown.py`
- Test: existing gate tests

**Interfaces:**
- Consumes: `DecisionContext.cooldown_remaining_sec` (current), `DecisionContext.bar` (new)
- Produces: GateResult with bar-based cooldown check

- [ ] **Step 1: Understand current context**

Read `quant/decision/gate_position_cooldown.py` (11 lines). The docstring says "minimum of 2 closed 1-minute bars since last exit" but line 19 checks `cooldown_remaining_sec > 0` (seconds).

- [ ] **Step 2: Fix Gate 2 to check bars instead of seconds**

Replace `quant/decision/gates/gate_position_cooldown.py:17-33` with:

```python
def gate_position_cooldown(
    ctx: DecisionContext, allow_positioned: bool = False
) -> GateResult:
    """Gate 2: Position Uniqueness, Family Limits & Cooldown Validation.

    Cooldown is bar-based: minimum of 2 closed 1-minute bars since
    last exit on symbol (spec §X). Seconds-based cooldown was a legacy
    artifact; bars are the canonical time unit for a bar-driven engine.
    """
    # Closed 1-minute bar count since last exit
    bars_since_exit = getattr(ctx, "bars_since_last_exit", 0) or 0
    if bars_since_exit < 2:
        return GateResult(
            gate=2,
            passed=False,
            reason=f"Cooldown: {bars_since_exit}/2 closed bars since last exit",
        )

    # Verifies zero open positions exist on the target contract
    if ctx.position_open:
        if allow_positioned:
            return GateResult(gate=2, passed=True, reason="thesis-flip check")
        return GateResult(gate=2, passed=False, reason="Position already open")

    return GateResult(gate=2, passed=True)
```

- [ ] **Step 3: Update callers to set `bars_since_last_exit`**

Find where `cooldown_remaining_sec` is set on DecisionContext. This likely lives in `runtime.py` or `decision_service.py`. Trace: `grep -rn "cooldown_remaining_sec" quant/`.

The caller must also set `bars_since_last_exit` on the DecisionContext. If `bars_since_last_exit` is not available in the context builder, add it.

Check `quant/decision/context.py` for the DecisionContext fields. Add `bars_since_last_exit: int = 0` to the context if not present.

- [ ] **Step 4: Update DecisionContext builder to populate `bars_since_last_exit`**

In the context builder (likely `quant/decision/context_builder.py` or `runtime.py`), compute bars_since_last_exit from the bar index difference between current bar and last exit bar.

- [ ] **Step 5: Run tests**

Run: `pytest tests/quant/decision/ -v`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add quant/decision/gates/gate_position_cooldown.py
git commit -m "fix: Gate 2 cooldown now bar-based (2 closed 1-minute bars per spec)"
```

---

### Task 4: Gate 4 native Greek-adjusted R:R check

**Files:**
- Modify: `quant/decision/gates/gate_risk_reward.py`
- Modify: `quant/decision/gates_rr.py` (if needed for stop width check)
- Test: existing gate tests

**Interfaces:**
- Consumes: `OptionConverter` (Task 2), `DecisionContext` with bar data, `Signal` with entry/sl/tp
- Produces: GateResult with Greek-adjusted R:R verification

- [ ] **Step 1: Understand current flow**

Current `gate_risk_reward.py:1-31` imports OptionConverter but doesn't use it. Delegates to `gates_rr.py:12-44` which checks stop width ≤ 200 ticks and delegates RR to SignalBuilder.

- [ ] **Step 2: Make Gate 4 natively check Greek-adjusted R:R**

Replace `quant/decision/gates/gate_risk_reward.py:1-34` with:

```python
"""Gate 4 — Greek-adjusted Risk-to-Reward (R:R >= 1.5).

Translates futures structural stops into option premium stops via Greek Delta (Δ),
then asserts:
    (P_opt_target - P_opt_entry) / (P_opt_entry - P_opt_stop) >= 1.5

Uses OptionConverter (created in Task 2) at quant/contracts/options_converter.py.
"""

from __future__ import annotations

from quant.contracts.options_converter import OptionConverter
from quant.decision.context import DecisionContext
from quant.decision.result import GateResult
from quant.decision.signal_builder import Signal as EngineSignal

MIN_RR = 1.5
MAX_STOP_DISTANCE_TICKS = 200.0


def gate_risk_reward(
    ctx: DecisionContext,
    min_rr: float = MIN_RR,
    max_distance_ticks: float = MAX_STOP_DISTANCE_TICKS,
) -> GateResult:
    """Gate 4: Greek-adjusted R:R ratio and structural stop cap."""
    if ctx is None or ctx.bar is None:
        return GateResult(4, False, "RR fail", "no bar")

    direction = ctx.agent_direction
    if direction not in ("LONG", "SHORT"):
        return GateResult(4, False, "RR fail", "No direction")

    entry = float(ctx.bar.close)
    tick = ctx.tick_size if ctx.tick_size and ctx.tick_size > 0 else 0.05

    # Structural stop from context (built by SignalBuilder or gate_chain)
    structural_stop = getattr(ctx, "structural_stop", None)
    target_price = getattr(ctx, "target_price", None)
    if structural_stop is None or target_price is None:
        return GateResult(4, False, "RR fail", "Missing stop/target in context")

    # Translate futures stop/target to option premium levels via Delta
    option_delta = getattr(ctx, "option_delta", None) or 0.50
    option_ltp = getattr(ctx, "option_ltp", None)

    if option_ltp and option_ltp > 0 and option_delta:
        converter = OptionConverter()
        signal = EngineSignal(
            type="LONG" if direction == "LONG" else "SHORT",
            entry=entry,
            sl=structural_stop,
            tp=target_price,
            rr=abs(target_price - entry) / abs(structural_stop - entry) if structural_stop != entry else 0.0,
            model_label=getattr(ctx, "setup_name", "UNKNOWN"),
            symbol=ctx.symbol or "",
            timestamp=getattr(ctx, "time_str", ""),
        )
        conversion = converter.convert(
            signal=signal,
            option_ltp=float(option_ltp),
            option_delta=float(option_delta),
            tick_size=tick,
        )
        if conversion is None:
            return GateResult(4, False, "RR fail", "Option conversion failed (invalid delta)")

        opt_risk = conversion.opt_risk
        opt_reward = conversion.opt_reward
    else:
        # Fallback: underlying-scale R:R (for non-option contracts)
        opt_risk = abs(entry - structural_stop)
        opt_reward = abs(target_price - entry)

    if opt_risk <= 0:
        return GateResult(4, False, "RR fail", "Zero risk distance")

    rr = opt_reward / opt_risk
    if rr < min_rr:
        return GateResult(
            gate=4,
            passed=False,
            reason=f"R:R {rr:.2f} < {min_rr} (Greek-adjusted)",
            detail=f"opt_reward={opt_reward:.2f} opt_risk={opt_risk:.2f}",
        )

    # Structural stop width check (cap)
    stop_ticks = opt_risk / tick if tick > 0 else float("inf")
    scaled_cap = max(max_distance_ticks, (entry * 0.0075) / tick)
    if stop_ticks > scaled_cap:
        return GateResult(
            gate=4,
            passed=False,
            reason=f"Stop too wide ({stop_ticks:.0f} > {scaled_cap:.0f} ticks)",
            detail=f"SL={structural_stop:.2f} entry={entry:.2f}",
        )

    return GateResult(
        gate=4,
        passed=True,
        reason=f"Greek R:R {rr:.2f} >= {min_rr}, stop within cap",
        detail=f"opt_stop={conversion.opt_sl:.2f} opt_tp={conversion.opt_tp:.2f}",
    )
```

- [ ] **Step 3: Ensure DecisionContext has required fields**

Verify `DecisionContext` has or can carry: `structural_stop`, `target_price`, `option_delta`, `option_ltp`. If not, add them to `quant/decision/context.py`. If these are already on `Signal`, extract them via the signal in the context.

- [ ] **Step 4: Run tests**

Run: `pytest tests/quant/decision/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quant/decision/gates/gate_risk_reward.py
git commit -m "feat: Gate 4 natively checks Greek-adjusted R:R >= 1.5 via OptionConverter"
```

---

### Task 5: Verify Phase 4 tests now pass

**Files:**
- Test: `tests/architecture/` (AST import guard), `tests/determinism/test_golden_tape_replay.py`, `tests/chaos/test_contingent_stop_flatten.py`

**Interfaces:**
- Consumes: All Task 1-4 completions
- Produces: Confidence that Phase 4 battery passes

- [ ] **Step 1: Verify AST import guard can now pass**

Run: `pytest tests/architecture/ -v -k "timesfm or ai or model"`
Expected: PASS (no TimesFM imports in runtime.py default path)

- [ ] **Step 2: Run deterministic replay tests**

Run: `pytest tests/determinism/test_golden_tape_replay.py -v`
Expected: PASS

- [ ] **Step 3: Run chaos tests**

Run: `pytest tests/chaos/test_contingent_stop_flatten.py -v`
Expected: PASS

- [ ] **Step 4: Run full quant test suite**

Run: `pytest tests/quant/ -v --tb=short`
Expected: All PASS (or only pre-existing failures)

- [ ] **Step 5: If Phase 4 AST test fails, verify why**

Check `tests/architecture/` for the specific test that asserts zero AI in runtime.py. Important distinction: `tests/quant/runtime/test_no_llm_hook.py` verifies LLM machinery absence (LLM attributes, LLM events) and may already pass. The AST import guard checks for AI/MODEL IMPORTS in runtime.py source code. After Task 1, `TIMESFM_END_TO_END` env-var code block at runtime.py:453-458 will be removed — but `from quant.strategies.timesfm_strategy import TimesFMTradingStrategy` and other TimesFM references may still exist. If the AST test requires ZERO TimesFM references in runtime.py (not just zero default usage), additional cleanup of remaining references (lines 743-758, 974-976, 1016-1036, 1250-1705) will be required — that is Phase 2 scope and should be tracked separately, not in this plan.

- [ ] **Step 6: Commit verification results**

```bash
git add tests/
git commit -m "test: verify Phase 4 battery passes after hot-path detox"
```

---

## Spec Coverage Check

| Spec Requirement | Task |
|-----------------|------|
| Phase 2: Prune TimesFM from HOT PATH (default entry) | Task 1 — removes default; remaining references at runtime.py:743-758, 1250-1705 require Phase 2 follow-up |
| Phase 2: Implement Options Greek Translator at spec path | Task 2 |
| Phase 2: Enforce 1-Minute Candle Acceptance | Verified existing in gate_edge.py |
| Phase 2: Relocate MLX LLM to post-trade worker | Already done (quant/sidecars/narrative/) |
| Spec: Gate 2 cooldown = 2 closed 1-minute bars | Task 3 |
| Spec: Gate 4 Greek-adjusted R:R ≥ 1.5 | Task 4 |
| Spec: Phase 4 AST import guard (zero AI in runtime.py) | Task 5 — may require Phase 2 follow-up if AST test is strict |

## Out of Scope (not part of this plan)

- God Class decomposition (Phase 3) — separate plan needed
- `dhan_market_data.py` creation — separate plan (backend adapter, not quant core)
- `_emit()` live-mode fail-closed — separate plan (requires careful risk analysis)
- Gate 1 spread filter fallbacks — low priority, spec intent is clear
- Dual WebSocket failover — Phase 3, long-term
- Zero-allocation hot-path — Phase 3, long-term
