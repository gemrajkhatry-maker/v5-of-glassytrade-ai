# Decision Pipeline Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix all 12 verified decision-pipeline defects across three independently shippable waves.

**Architecture:** Wave 1 restores correctness of the deterministic AMT path (enum, string formats,
reachable gate, no synthetic forecasts) plus exit-source observability. Wave 2 makes
`DecisionService`/`GatePipeline` the single entry authority in E2E mode with unified gate
reporting. Wave 3 removes dead code and wires the forecast calibration loop.

**Tech Stack:** Python 3, pytest, numpy (TimesFM paths only).

## Global Constraints

- The deterministic AMT entry path must never wait on model inference; TimesFM stays opt-in via `TIMESFM_END_TO_END`.
- Gate order is 1→2→3→4; gates 1–2 hard-reject (`quant/decision/decision_service.py:114-118`).
- One sizing authority: `SessionRisk.position_size` + `clamp_quantity`; strategies never size final quantities.
- Commit style: `fix:` prefix, one task per commit.
- After every task: run the affected test files; after every wave: run the full `tests/quant/decision/` directory.

---

## File Structure

**Wave 1 (correctness):**
- `quant/decision/context_builder.py:385` — one-line enum fix.
- `quant/decision/timesfm_agents.py:125,143` — substring absorption match.
- `quant/decision/decision_service.py:73` — threshold `0.9 → 0.65`; stale comments in `context_builder.py:22-25`, `quant/runtime.py:109-112`.
- `quant/strategies/timesfm_strategy.py:333-347` — return `None` on inference failure.
- `quant/execution/exits.py` (`ExitEngine.__init__`, `evaluate`) + `quant/position_manager.py:229` — `last_exit_source` + close log line.
- `docs/runbook.md` (or `docs/生` — check repo; if no runbook exists, append to `docs/decision_pipeline_deep_review.md` under a new `## Operator Note` section instead).

**Wave 2 (single authority):**
- `quant/strategies/timesfm_strategy.py:84-196` (`should_enter`) — canonical gate enforcement.
- `quant/decision/timesfm_agents.py:346-351,590-595` — canonical gate results in output payloads.

**Wave 3 (cleanup):**
- `quant/decision/timesfm_agents.py:315` — `equity=ctx.equity`.
- `quant/decision/timesfm_agents.py` scanner setups — `is_option_contract` guard (import from `quant.contracts.instrument_registry`, already used in `context_builder.py:13`).
- `quant/execution/exits.py` + `quant/decision/timesfm_risk.py` — outcome recording + multiplier exposure.
- Delete: `quant/decision/intent.py`, `quant/execution/risk_sizer.py`, `tests/quant/decision/test_intent.py`, `tests/quant/execution/test_risk_sizer.py`.
- `quant/decision/timesfm_agents.py:102` — remove `allow_entry`.
- Forecast freshness: `TimesFMForecast` gains defaulted `asof_bar: int = -1`; `quant/runtime.py:1427` staleness check.

---

### Task 1: BUG-2 — DEAD market state enum

**Files:**
- Modify: `quant/decision/context_builder.py:385`
- Test: `tests/quant/decision/test_context_builder_behavior.py` (append; reuse that file's existing imports)

**Interfaces:**
- Consumes: `MarketState` (already imported at `context_builder.py:12`)
- Produces: `ctx.market_state == MarketState.DEAD` for `decision_service.py:123`

- [ ] **Step 1: Write the failing test**

```python
def test_dead_market_state_is_enum_not_string():
    from types import SimpleNamespace
    from quant.contracts.enums import MarketState
    from quant.decision.context_builder import DecisionContextBuilder
    bar = SimpleNamespace(close=100.0, high=101.0, low=99.0,
                          time="2026-09-10T10:00:00+05:30")
    risk = SimpleNamespace(halted=False, consecutive_losses=0,
                           equity=100000.0, risk_per_trade_pct=0.05)
    ctx = DecisionContextBuilder().build(
        bar=bar, symbol="NIFTY", market="NSE", contract_expiry=None,
        tick_size=0.05, bar_index=20, warm_bars=0,
        cooldown_remaining_sec=0.0, risk_state=risk,
        amt_dto={"marketState": "DEAD"})
    assert ctx.market_state == MarketState.DEAD
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/quant/decision/test_context_builder_behavior.py::test_dead_market_state_is_enum_not_string -q`
Expected: FAIL on the `assert ctx.market_state is MarketState.DEAD` identity line (note:
`MarketState` is a `str, Enum`, so the `==` assertion alone passes even for the raw string —
the `is` line is what reproduces the bug)

- [ ] **Step 3: Minimal implementation** — in `context_builder.py:385`, change `amt_market_state = "DEAD"` to `amt_market_state = MarketState.DEAD`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/quant/decision/test_context_builder_behavior.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add quant/decision/context_builder.py tests/quant/decision/test_context_builder_behavior.py
git commit -m "fix: DEAD market state uses MarketState enum so VA-fade gate fires"
```

---

### Task 2: BUG-1 — scanner absorption format

**Files:**
- Modify: `quant/decision/timesfm_agents.py:125,143`
- Test: `tests/quant/decision/test_timesfm_agents.py` (append)

**Interfaces:**
- Consumes: `ctx.absorption_side` (uppercased at line 108), `TimesFMForecast` (fields at `timesfm_agents.py:34-45`)
- Produces: scanner Setup A/B fires for both `"BUY"` and `"BUY_ABSORBED"` forms

- [ ] **Step 1: Write the failing test**

```python
def test_scanner_triple_a_fires_on_absorbed_form():
    import numpy as np
    from types import SimpleNamespace
    from quant.decision.timesfm_agents import TimesFMScanningAgent, TimesFMForecast
    px = 100.0
    ctx = SimpleNamespace(
        symbol="NIFTY", bar=SimpleNamespace(close=px), state=None,
        session_phase="MORNING", session_open=True, warmup_complete=True,
        allow_trend=True, allow_reversion=True,
        poc=99.0, vah=101.0, val=100.0, cvd_slope=1.5,
        absorption_side="SELL_ABSORBED", stacked_imbalance_direction="",
        risk_halted=False, cooldown_remaining_sec=0.0,
        market_state=SimpleNamespace(value="BALANCED"))
    fc = TimesFMForecast(
        horizon=32, p50_path=np.full(32, 101.0, dtype=np.float32),
        p10_path=np.full(32, 100.0, dtype=np.float32),
        p90_path=np.full(32, 102.0, dtype=np.float32),
        q_spread=2.0, mean_forecast=101.0, pct_change=0.01,
        forecast_steps=["LONG"] * 32, curr_price=px, lat_ms=5.0)
    res = TimesFMScanningAgent().evaluate(ctx, fc)
    assert res["setup"] == "TRIPLE_A" and res["direction"] == "LONG"
```

Note: `curr_price (100.0) <= val + tol` is already true here, so also assert the absorption
arm independently by setting `val=90.0` (price far above VAL) with `absorption_side="SELL_ABSORBED"` —
Setup A must still fire via the absorption clause. Include both variants in the test.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/quant/decision/test_timesfm_agents.py -q -k absorbed`
Expected: FAIL on the far-from-VAL variant

- [ ] **Step 3: Minimal implementation** — canonical semantics (producer `detectors.py:268`,
  Triple-A engine `triple_a.py:85-95`, `_resolve_direction` all agree `SELL_ABSORBED` = bullish):
  Setup A (LONG) keys on SELL absorption, Setup B (SHORT) on BUY absorption:

```python
# line 125: absorption == "BUY"  →  "SELL" in absorption
# line 143: absorption == "SELL" →  "BUY" in absorption
```

(`absorption` is already uppercased at line 108; `in` covers both bare and `_ABSORBED` forms.)
Same file, same semantic: flip the `TimesFMPositionAgent` thesis-flip absorption arms to
canonical — line 492: LONG exits on `absorption in ("BUY", "BUY_ABSORBED")`; line 493: SHORT
exits on `absorption in ("SELL", "SELL_ABSORBED")`; update the rationale branches at lines
508-511 to match. Stacked-imbalance arms (lines 495-496, 512, 517) are already correct
(stacked SELL = bearish = opposes LONG) — do not touch.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/quant/decision/test_timesfm_agents.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add quant/decision/timesfm_agents.py tests/quant/decision/test_timesfm_agents.py
git commit -m "fix: scanner absorption check accepts BUY_ABSORBED/SELL_ABSORBED forms"
```

---

### Task 3: STRUCT-3 — reachable data-quality gate

**Files:**
- Modify: `quant/decision/decision_service.py:73`, `quant/decision/context_builder.py:22-25`, `quant/runtime.py:109-112`
- Test: `tests/quant/decision/test_decision_service.py` (append)

**Interfaces:**
- Consumes: `ctx.agent_probability` (always 0.7), `ctx.data_quality`
- Produces: `DATA_QUALITY_BLOCKED` reachable for inferred-quality data

- [ ] **Step 1: Write the failing test** — construct the service-level ctx the way
  `test_decision_service.py` already does (reuse its fixture/factory), set
  `agent_probability=0.7` with a non-allowlisted `data_quality` (e.g. a data-quality value
  for which `conviction_allowed()` is False), assert `decision.reason == "DATA_QUALITY_BLOCKED"`;
  and a passing case with an allowlisted quality value asserting the gate does not fire.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/quant/decision/test_decision_service.py -q -k data_quality`
Expected: FAIL (gate never fires at 0.9 threshold)

- [ ] **Step 3: Minimal implementation**

```python
# decision_service.py:73
if ctx.agent_probability >= 0.65 and not conviction_allowed(ctx.data_quality):
```

Update the stale comments: `context_builder.py:22-25` ("above the 0.55 min_probability
threshold" → describe the 0.65 data-quality conviction threshold) and the matching comment
at `runtime.py:109-112`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/quant/decision/test_decision_service.py -q`
Expected: all PASS (10 existing + new)

- [ ] **Step 5: Commit**

```bash
git add quant/decision/decision_service.py quant/decision/context_builder.py quant/runtime.py tests/quant/decision/test_decision_service.py
git commit -m "fix: data-quality conviction gate reachable at 0.65 threshold"
```

---

### Task 4: STRUCT-8 — inference failure returns None

**Files:**
- Modify: `quant/strategies/timesfm_strategy.py:333-347`
- Test: `tests/quant/decision/test_strategy_behavior.py` (append; if that file has no TimesFM
  strategy coverage, create `tests/quant/decision/test_timesfm_strategy_cache.py`)

**Interfaces:**
- Consumes: `TimesFMTradingStrategy._compute_forecast(ctx)` exception path
- Produces: `None` → existing `MODEL_UNAVAILABLE` branch (`timesfm_strategy.py:122-131`), no `_latest_forecasts` write

- [ ] **Step 1: Write the failing test** — monkeypatch `get_timesfm_model` (imported inside
  `_compute_forecast` from `quant.decision.timesfm_engine`) to raise, call
  `strategy.should_enter(ctx)` with a minimal ctx, assert `decision.reason == "MODEL_UNAVAILABLE"`
  and `strategy.get_latest_forecast(symbol) is None`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/quant/decision/test_strategy_behavior.py -q -k unavailable`
Expected: FAIL (synthetic flat forecast cached instead)

- [ ] **Step 3: Minimal implementation** — replace the `except` block body (lines 333-347,
  the synthetic `TimesFMForecast(...)` construction) with:

```python
except Exception as exc:
    logger.debug("TimesFMTradingStrategy forecast error: %s", exc)
    return None
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/quant/decision/test_strategy_behavior.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add quant/strategies/timesfm_strategy.py tests/quant/decision/test_strategy_behavior.py
git commit -m "fix: failed TimesFM inference returns None instead of synthetic flat forecast"
```

---

### Task 5: STRUCT-2 — exit-source observability

**Files:**
- Modify: `quant/execution/exits.py` (`ExitEngine.__init__`, `evaluate`), `quant/position_manager.py` (close log line)
- Docs: append `## Operator Note — advisory vs real exits` to `docs/decision_pipeline_deep_review.md`
- Test: `tests/quant/execution/` — new `test_exit_source.py`

**Interfaces:**
- Consumes: `ExitDecision.reason`, whether the TimesFM branch ran
- Produces: `ExitEngine.last_exit_source: str` read by `PositionManager.manage_exit` for logging

- [ ] **Step 1: Write the failing test**

```python
def test_exit_source_labels_timesfm_vs_deterministic():
    from quant.execution.exits import ExitEngine
    eng = ExitEngine()
    assert eng.last_exit_source == ""
```

(Extend with an `evaluate()` call on a flat no-position scenario if fixtures allow; the
attribute-exists assertion is the contract this task guarantees.)

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/quant/execution/test_exit_source.py -q`
Expected: FAIL (`ExitEngine` has no `last_exit_source`)

- [ ] **Step 3: Minimal implementation**

```python
# ExitEngine.__init__: add
self.last_exit_source: str = ""
# In evaluate(): reset at entry
self.last_exit_source = ""
# TimesFM branch (after eval_res computed, exits.py:162-183):
self.last_exit_source = f"TIMESFM_RISK_AUTHORITY:{eval_res.reason or eval_res.action}"
# Each deterministic `return r` / `return ExitDecision(...)` site:
self.last_exit_source = f"DETERMINISTIC:{r.reason if r else exit_decision.reason}"
```

In `position_manager.py:229` (`_execute_full_close` call site in `manage_exit`), extend the
close log line with `exit_source=self._exits.last_exit_source`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/quant/execution/ -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add quant/execution/exits.py quant/position_manager.py tests/quant/execution/test_exit_source.py docs/decision_pipeline_deep_review.md
git commit -m "feat: label every exit with advisory-vs-real source for ops"
```

---

### Task 6: STRUCT-5 — canonical gates enforced in E2E mode

**Files:**
- Modify: `quant/strategies/timesfm_strategy.py:84-196` (`should_enter`)
- Test: `tests/quant/decision/test_strategy_behavior.py` (append)

**Interfaces:**
- Consumes: `GatePipeline().evaluate(ctx)` → `list[GateResult]` (`quant/decision/pipeline.py:21`);
  `GateResult.passed`, `GateResult.reason`, `GateResult.name` (`quant/decision/result.py:17-26`)
- Produces: approval requires scanner candidate AND all canonical gates passed

- [ ] **Step 1: Write the failing test** — build a ctx where the scanner approves (reuse Task 2
  style ctx + forecast) but a canonical guard blocks (e.g. opposing stacked imbalance via
  `stacked_imbalance_direction` + DTO footprints, or `drive_number >= 3` without
  `drive_entry_valid`); assert `should_enter(...).approved is False`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/quant/decision/test_strategy_behavior.py -q -k canonical`
Expected: FAIL (E2E approves without canonical gates)

- [ ] **Step 3: Minimal implementation** — in `should_enter`, after `scan_res` is computed and
  `is_entry` is true (line 155), insert before signal construction:

```python
from quant.decision.pipeline import GatePipeline
canonical = GatePipeline().evaluate(ctx)
failed = [g for g in canonical if not g.passed]
if failed:
    failed_reasons = tuple(f"{g.name}: {g.reason}" for g in failed)
    return QuantDecision(
        approved=False, signal=None, reason=setup,
        phase=str(ctx.session_phase or ""),
        gate_results=tuple(canonical),
        block_reasons=failed_reasons,
        model_label=f"TimesFM-{setup}",
    )
```

Keep the TimesFM-built `Signal` (VaR stop/target/sizing) for the approved path — only the
approval authority changes, not the signal math.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/quant/decision/ -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add quant/strategies/timesfm_strategy.py tests/quant/decision/test_strategy_behavior.py
git commit -m "feat: E2E entries require canonical gate pipeline approval"
```

---

### Task 7: STRUCT-4 — canonical gate results in scanner output

**Files:**
- Modify: `quant/decision/timesfm_agents.py:346-351` (scanner), `:590-595` (position agent — leave position-agent gates as-is; only the scanner's ENTRY `gateResults` change)
- Test: `tests/quant/decision/test_timesfm_agents.py` (append)

**Interfaces:**
- Consumes: Task 6's canonical `GateResult` tuple passed into `TimesFMScanningAgent.evaluate`
  as a new optional parameter `canonical_gates: Optional[tuple] = None` (default preserves
  current standalone behavior for advisor/UI use)
- Produces: `"gateResults"` entries mirror canonical gates when provided

- [ ] **Step 1: Write the failing test** — call `evaluate(ctx, fc, canonical_gates=(GateResult(1, True), GateResult(2, False, "Cooldown")))` and assert the returned `gateResults[1]["passed"] is False`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/quant/decision/test_timesfm_agents.py -q -k canonical_gates`
Expected: FAIL (shadow booleans returned)

- [ ] **Step 3: Minimal implementation**

```python
def evaluate(self, ctx, forecast, chain=None, canonical_gates=None):
    ...
    if canonical_gates is not None:
        gate_results = [
            {"gate_no": g.gate, "gate_name": g.name, "passed": g.passed,
             "message": g.reason if not g.passed else ""}
            for g in canonical_gates
        ]
    else:
        gate_results = [ ... existing shadow computation ... ]
```

Update `TimesFMTradingStrategy.should_enter` to pass its canonical tuple through.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/quant/decision/test_timesfm_agents.py tests/quant/decision/test_strategy_behavior.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add quant/decision/timesfm_agents.py quant/strategies/timesfm_strategy.py tests/quant/decision/test_timesfm_agents.py
git commit -m "feat: scanner reports canonical gate results instead of shadow gates"
```

---

### Task 8: BUG-3 — real equity in scanner sizer

**Files:**
- Modify: `quant/decision/timesfm_agents.py:315`
- Test: `tests/quant/decision/test_timesfm_agents.py` (append)

- [ ] **Step 1: Write the failing test** — run `TimesFMScanningAgent().evaluate` twice on
  identical ctx/forecast except `ctx.equity` (100_000 vs 500_000); assert the two
  `dynamicSizing.riskAmount` values differ (scale with equity).

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/quant/decision/test_timesfm_agents.py -q -k equity`
Expected: FAIL (both use hardcoded 100000.0)

- [ ] **Step 3: Minimal implementation** — `equity=100000.0` → `equity=float(ctx.equity or 100000.0)`
  (fallback preserves behavior when equity is missing).

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/quant/decision/test_timesfm_agents.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add quant/decision/timesfm_agents.py tests/quant/decision/test_timesfm_agents.py
git commit -m "fix: scanner sizer uses account equity instead of hardcoded 100k"
```

---

### Task 9: STRUCT-6 — no option SHORT in advisory

**Files:**
- Modify: `quant/decision/timesfm_agents.py` (scanner setup arms)
- Test: `tests/quant/decision/test_timesfm_agents.py` (append)

- [ ] **Step 1: Write the failing test** — ctx with an option symbol (matching
  `is_option_contract`, same helper imported in `context_builder.py:13`) and scanner-B
  (SHORT) conditions; assert `direction != "SHORT"` (FLAT expected).

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/quant/decision/test_timesfm_agents.py -q -k option_short`
Expected: FAIL (`ENTER_SHORT` emitted)

- [ ] **Step 3: Minimal implementation**

```python
from quant.contracts.instrument_registry import is_option_contract
...
is_option = is_option_contract(symbol)
# in Setup B / D / E SHORT arms add: and not is_option
```

Mirror the `context_builder.py:364-367` rationale in a comment (retail buyers only, no naked shorts).

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/quant/decision/test_timesfm_agents.py -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add quant/decision/timesfm_agents.py tests/quant/decision/test_timesfm_agents.py
git commit -m "fix: scanner never recommends SHORT on option instruments"
```

---

### Task 10: STRUCT-7 — wire forecast calibration (observability)

**Files:**
- Modify: `quant/execution/exits.py`, `quant/decision/timesfm_risk.py` (no signature changes)
- Test: `tests/quant/decision/test_timesfm_risk.py` (append)

**Interfaces:**
- Consumes: `TimesFMRiskAuthority.record_forecast_outcome(predicted, actual, initial)`
  (`timesfm_risk.py:214`), forecast + entry + close already present in `evaluate_exit`
- Produces: populated `_forecast_errors` deque on model-driven exits; `session_budget_multiplier()`
  exposed on `ExitEngine`

- [ ] **Step 1: Write the failing test** — drive `TimesFMRiskAuthority.evaluate_exit` to a
  `VAR_STOP` exit (follow existing patterns in `test_timesfm_risk.py`), assert
  `len(authority._forecast_errors) == 1` afterwards.

- [ ] **Step 2: Run test to verify it fails**

Run: `python3 -m pytest tests/quant/decision/test_timesfm_risk.py -q -k calibration`
Expected: FAIL (nothing records outcomes)

- [ ] **Step 3: Minimal implementation** — in `evaluate_exit`, at each `should_exit=True`
  return site with a forecast:

```python
self.record_forecast_outcome(
    float(forecast.p50_path[-1]), float(current_price), float(entry))
```

Add to `ExitEngine`:

```python
def session_budget_multiplier(self) -> float:
    if self._timesfm_risk is None:
        return 1.0
    return self._timesfm_risk.get_session_budget_multiplier()
```

Log the multiplier on full close in `position_manager.py` (same line touched in Task 5).
Full throttling of sizing by this multiplier is an explicit follow-up, not this task.

- [ ] **Step 4: Run test to verify it passes**

Run: `python3 -m pytest tests/quant/decision/test_timesfm_risk.py tests/quant/execution/ -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add quant/execution/exits.py quant/decision/timesfm_risk.py quant/position_manager.py tests/quant/decision/test_timesfm_risk.py
git commit -m "feat: record forecast outcomes on model exits, expose budget multiplier"
```

---

### Task 11: STRUCT-1 — delete dead TradeIntent/RiskSizer scaffolding

**Files:**
- Delete: `quant/decision/intent.py`, `quant/execution/risk_sizer.py`, `tests/quant/decision/test_intent.py`, `tests/quant/execution/test_risk_sizer.py`
- Verify no other importers: `grep -rn "TradeIntent\|risk_sizer" quant/ backend/app/`

- [ ] **Step 1: Confirm zero production importers**

Run: `grep -rn "TradeIntent\|from quant.execution.risk_sizer\|from quant.decision.intent" quant/ backend/app/ --include="*.py" | grep -v tests/`
Expected: no output (only the two source files themselves)

- [ ] **Step 2: Delete the files**

```bash
git rm quant/decision/intent.py quant/execution/risk_sizer.py tests/quant/decision/test_intent.py tests/quant/execution/test_risk_sizer.py
```

- [ ] **Step 3: Run suite to verify nothing breaks**

Run: `python3 -m pytest tests/quant/decision/ tests/quant/execution/ -q`
Expected: all PASS

- [ ] **Step 4: Commit**

```bash
git commit -m "chore: remove unwired TradeIntent/RiskSizer scaffolding"
```

---

### Task 12: BUG-4 + forecast freshness

**Files:**
- Modify: `quant/decision/timesfm_agents.py:102`, `quant/decision/timesfm_agents.py:34-45` (`TimesFMForecast`), `quant/strategies/timesfm_strategy.py` (cache write), `quant/runtime.py:1427` (staleness check)
- Test: `tests/quant/decision/test_timesfm_strategy_cache.py` (create)

**Interfaces:**
- Consumes: `self._bar_index` (runtime), `_latest_forecasts` cache (strategy)
- Produces: forecasts older than 1 bar never reach `ExitEngine`

- [ ] **Step 1: Write the failing tests**

```python
def test_no_phantom_allow_entry_gate():
    import inspect
    from quant.decision import timesfm_agents
    src = inspect.getsource(timesfm_agents)
    assert "allow_entry" not in src
```

```python
def test_stale_forecast_not_used_for_exits():
    # strategy.get_latest_forecast returns a forecast cached >1 bar ago;
    # runtime must pass None (deterministic fallback) to manage_exit.
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python3 -m pytest tests/quant/decision/test_timesfm_strategy_cache.py -q`
Expected: FAIL (both)

- [ ] **Step 3: Minimal implementation**

```python
# timesfm_agents.py:102 → delete allow_entry; Setup A/B/D/E arms use session_open only:
allow_entry = ctx.session_open
```

```python
# TimesFMForecast: add defaulted field (kwargs construction everywhere — safe)
asof_bar: int = -1
```

Strategy cache write sites (`timesfm_strategy.py:133` and `_compute_forecast` return paths):
set `asof_bar` to the current bar index — thread `bar_index` through `should_enter` from the
existing `ctx.bar_index` field (`context.py` carries it; verify name in `quant/decision/context.py`
before editing).

Runtime (`runtime.py:1427`):

```python
tfm_fc = getattr(self._strategy, "get_latest_forecast", lambda s: None)(self.symbol)
if tfm_fc is not None and getattr(tfm_fc, "asof_bar", -1) >= 0:
    if self._bar_index - tfm_fc.asof_bar > 1:
        logger.warning("⚠️ [STALE FORECAST] %s: cached forecast %d bars old — deterministic exits",
                       self.symbol, self._bar_index - tfm_fc.asof_bar)
        tfm_fc = None
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python3 -m pytest tests/quant/decision/ tests/quant/execution/ -q`
Expected: all PASS

- [ ] **Step 5: Commit**

```bash
git add quant/decision/timesfm_agents.py quant/strategies/timesfm_strategy.py quant/runtime.py tests/quant/decision/test_timesfm_strategy_cache.py
git commit -m "fix: drop phantom allow_entry; stale forecasts never reach exits"
```

---

## Wave Gates

- [ ] Wave 1 complete: Tasks 1–5 merged, `tests/quant/decision/` green, paper-session replay shows exit-source on every close.
- [ ] Wave 2 complete: Tasks 6–7 merged, E2E-vs-canonical divergence test green, dashboard gate payload equals canonical results.
- [ ] Wave 3 complete: Tasks 8–12 merged, full `tests/quant/` green, 12-point pre-session checklist (`docs/decision_pipeline_deep_review.md`) re-verified item by item.
