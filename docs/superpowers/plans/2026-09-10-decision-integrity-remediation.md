# Decision Integrity Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close all 4 blocking and 10 high-severity decision-integrity defects found by the 2026-09-10 code-level audit, then the medium/low duplication, dead-code and cleanliness debt — until `scripts/pre_release_decision_check.py` exits 0.

**Architecture:** Four waves, each independently shippable. Wave 1 isolates the money-path failures (silent model-exit loss, a close path that skips the single release path, a fabricated entry from an absent profile, and a shared-engine double-feed). Wave 2 makes the four authorities agree on one stop, one sizing policy, one advisor-enable rule and one inference per bar. Wave 3 collapses the 3-4× duplicated forecast builder and the repeated vocabulary helpers into single canonical owners. Wave 4 removes dead code, untracks generated artifacts and names the duplicated literals.

**Tech Stack:** Python 3.13, pytest, numpy (TimesFM paths only). No new dependencies.

## Global Constraints

- Sources of truth (do not introduce a second one):
  - entry seam: `strategy.should_enter(ctx)`; runtime never calls `DecisionService.evaluate()` directly.
  - full close: `PositionManager._execute_full_close` is the ONLY full-close release path.
  - sizing: `SessionRisk.position_size` + `clamp_quantity`; strategies never size final quantity.
  - exit: `ExitEngine.evaluate` → `TimesFMRiskAuthority` (or deterministic rules), stamped via `last_exit_source`.
  - absorption semantics: `SELL_ABSORBED = LONG` (absorbed sellers), `BUY_ABSORBED = SHORT` (absorbed buyers).
  - quantile index contract: for `quantiles` of shape `(H, 9)`, index `0`=p10, `4`=p50, `8`=p90.
- No new runtime dependencies. No behaviour change on the deterministic (non-`TIMESFM_END_TO_END`) path except where a task states otherwise.
- Every wave must leave `PYTHONPATH=backend:. python -m pytest tests/quant/ -q` green.
- Commit style: `fix:` for Wave 1/2, `refactor:` for Wave 3, `chore:` for Wave 4. One task per commit.
- Test invocation prefix for every task: `PYTHONPATH=backend:. .venv/bin/python -m pytest`.
- Reference: `docs/reviews/2026-09-10-pre-release-code-audit.md` (defect IDs D-1..D-28 match this plan).
- Do NOT delete `backend/graphify-out/` contents before Task 20's `git rm -r --cached` succeeds — order matters.
- **Brief-integrity rule (learned in Tasks 1 and 2).** A task's stated END STATE — its interfaces, its test assertions, and its release-gate check — outranks the literal code in its steps. Two briefs in this plan shipped code that could not be transcribed as written: Task 1's `global` was a `SyntaxError`, and Task 2's helper double-closed each add-on. When a brief's code and its own end state conflict, implement the end state, keep the semantics the brief names, and report the contradiction with the evidence. Never silently ship a different design, and never weaken a test to make a contradiction go away.
- **When a fix routes work through a shared path, check what else that path does.** `_execute_full_close` calls `self._risk.record_trade(fill.pnl)` with `count_as_trade=True` default, which increments `trades_today` and moves the consecutive win/loss counters that `SessionRisk.can_trade()` reads against `max_trades_per_session`. Any task that funnels a previously-uncounted close through that path must preserve the original `count_as_trade=False` intent or state why the change is intended.

---

## File Structure

**Wave 1 — blocking (money path):**
- `quant/execution/exits.py` — replace the swallowing handler around the model-exit block.
- `quant/runtime.py` — route the pyramid-only close through the release path.
- `quant/decision/timesfm_agents.py` — profile-validity guard in the scanner.
- `quant/decision/timesfm_engine.py` — lock + monotonic-stamp dedup in `add_context`.

**Wave 2 — one authority per decision:**
- `quant/position_manager.py` — leg-LVN key, double-close guard lifetime, single trail source.
- `quant/execution/exit_checks.py` — bar/tick stop-price parity.
- `quant/execution/risk.py` — refusing (not silently switching) sizing policy; expiry/day-of-week on the forecast path.
- `quant/transitions.py` — fold `StopMoved` into the projected stop.
- `quant/wiring_advisor.py`, `backend/app/application/di/composition_root.py` — one advisor-enable rule.
- `quant/decision/timesfm_advisor.py` + `quant/decision/timesfm_engine.py` — one inference per bar.

**Wave 3 — single canonical owners:**
- Create `quant/decision/timesfm_forecast_factory.py` — the one forecast builder.
- Create `quant/contracts/vocabulary.py` — absorption, option-kind, session-phase helpers.
- Modify `quant/multi_engine.py`, `quant/amt/session/scanner.py`, `quant/strategies/timesfm_strategy.py`, `quant/decision/timesfm_engine.py`, `quant/decision/context_builder.py`, `quant/llm/narrative.py`.
- `quant/amt/session/scanner_config.py` — one settings authority.

**Wave 4 — debt and cleanliness:**
- `quant/execution/exit_rules.py`, `quant/decision/timesfm_sizing.py`, `quant/decision/signal_builder.py`, `quant/decision/context_builder.py`, `quant/strategies/timesfm_strategy.py` — kill dead code and named literals.
- Split `quant/runtime.py::_decide` and `quant/decision/timesfm_agents.py::evaluate`.
- Repo root — untrack generated/throwaway artifacts.

---

# WAVE 1 — Blocking defects

## Task 1: D-2 — model-risk failure must be observable

**Files:**
- Modify: `quant/execution/exits.py:196-198`
- Test: `tests/quant/execution/test_exit_source.py` (append)

**Interfaces:**
- Consumes: `TimesFMRiskAuthority.evaluate_exit(...)` (existing), `ModuleExitEvaluation`.
- Produces: module-level `MODEL_RISK_FAILURES: int` counter on `quant.execution.exits`, incremented per swallowed model-exit failure; `ExitEngine.model_risk_failures` property returning it.

- [ ] **Step 1: Write the failing test**

Append to `tests/quant/execution/test_exit_source.py`:

```python
def test_model_risk_failure_is_logged_and_counted(monkeypatch, caplog):
    """D-2: a raising TimesFMRiskAuthority must not vanish silently."""
    import logging

    from quant.decision.timesfm_agents import TimesFMForecast
    import numpy as np

    import quant.execution.exits as exits_mod

    eng = ExitEngine()
    pos = _position()
    p50 = np.full(8, 101.0, dtype=np.float32)
    fc = TimesFMForecast(
        horizon=8, p50_path=p50, p10_path=p50 - 1, p90_path=p50 + 1,
        q_spread=2.0, mean_forecast=101.0, pct_change=0.01,
        forecast_steps=["LONG"] * 8, curr_price=100.0, lat_ms=1.0,
    )

    class _Boom:
        def clear_position(self, *_a):
            pass

        def evaluate_exit(self, **_k):
            raise RuntimeError("quantile path corrupt")

        def get_session_budget_multiplier(self):
            return 1.0

    eng._timesfm_risk = _Boom()
    before = exits_mod.MODEL_RISK_FAILURES
    with caplog.at_level(logging.WARNING, logger="quant.execution.exits"):
        decision = eng.evaluate(pos, bar_close=100.5, bar_index=2, timesfm_forecast=fc)

    # The engine still falls back to deterministic rules (behaviour preserved)...
    assert decision is not None
    # ...but the failure is now counted and logged, not swallowed.
    assert exits_mod.MODEL_RISK_FAILURES == before + 1
    assert any("TimesFM risk authority failed" in r.message for r in caplog.records)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/test_exit_source.py::test_model_risk_failure_is_logged_and_counted -v`
Expected: FAIL with `AttributeError: module 'quant.execution.exits' has no attribute 'MODEL_RISK_FAILURES'`

- [ ] **Step 3: Write the minimal implementation**

In `quant/execution/exits.py`, add the counter near the other module-level state (after the `Event`/`Position` imports, before `class ExitDecision`):

```python
# Model-risk failures observed since process start. The TimesFM exit authority
# is allowed to degrade to deterministic rules, but it must never do so
# silently: a degraded session has to be distinguishable from a healthy one.
MODEL_RISK_FAILURES = 0
```

Replace the swallowing handler at the end of the model-exit block. Two ordering details matter and were wrong in an earlier draft of this plan:

- `global MODEL_RISK_FAILURES` must go at the TOP of `evaluate` (just after the docstring-equivalent first statement), not inside the handler. A `global` declaration placed after the name has already been used in the same scope is a **SyntaxError**, not a style issue. Confirmed empirically.
- The handler's first statement must be `logger.` with the increment after it. `scripts/pre_release_decision_check.py` requires the first non-comment statement of this handler to be `logger.` or `raise`; a leading `global` or `+=` scores FAIL.

So, at the top of `evaluate`:

```python
    def evaluate(
        self,
        position: Position,
        ...
        timesfm_forecast: object | None = None,
    ) -> ExitDecision:
        global MODEL_RISK_FAILURES
        from quant.execution.exit_checks import (
```

and the handler:

```python
            except Exception as exc:
                # Degrade to deterministic rules — but LOUDLY. Silently
                # swallowing this disables the dynamic VaR stop, the trajectory
                # take-profit, the velocity-decay exit and the quantile stop
                # ratchet for the whole bar with no signal to ops.
                logger.warning(
                    "TimesFM risk authority failed for %s (%s) — falling back to "
                    "deterministic exits for this bar (total failures: %d)",
                    position._id, exc, MODEL_RISK_FAILURES + 1,
                    exc_info=True,
                )
                MODEL_RISK_FAILURES += 1
```

The logged total is `MODEL_RISK_FAILURES + 1` so it equals the post-increment counter. The counter is best-effort under concurrency (two threads can log the same total); that is acceptable for a diagnostic and must not be "fixed" with a lock on the exit hot path.

Add `import logging` and a module logger if absent (check the top of the file first; if `logger` already exists, reuse it):

```python
logger = logging.getLogger(__name__)
```

Add the accessor on `ExitEngine`, immediately after `session_budget_multiplier`:

```python
    @property
    def model_risk_failures(self) -> int:
        """Count of model-risk-authority failures seen this process."""
        return MODEL_RISK_FAILURES
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/test_exit_source.py -v`
Expected: PASS (all tests in the file)

- [ ] **Step 5: Run the release gate for this finding**

Run: `PYTHONPATH=backend:. .venv/bin/python scripts/pre_release_decision_check.py --skip-suites 2>&1 | grep "model-risk"`
Expected: `[PASS] model-risk failure is observable, not swallowed`

- [ ] **Step 6: Commit**

```bash
git add quant/execution/exits.py tests/quant/execution/test_exit_source.py
git commit -m "fix: log and count model-risk authority failures instead of swallowing them"
```

---

## Task 2: D-3 — every full close routes through the single release path

**Files:**
- Modify: `quant/runtime.py:1402-1412`
- Test: `tests/quant/test_eod_force_close.py` (create if absent; otherwise append)

**Interfaces:**
- Consumes: `PositionManager._execute_full_close(position, exit_dec, time_str)` (existing).
- Produces: no new API. Behaviour: a lingering pyramid-only close stamps `exit_source`, emits `PositionClosed`, obeys `_closed_ids` and releases portfolio risk exactly as the base path.

- [ ] **Step 1: Write the failing test**

Create `tests/quant/test_eod_force_close.py`:

```python
"""D-3: a pyramid-only force-close must not bypass the single release path."""

from quant.bars import Bar
from quant.decision.signal_builder import Signal
from quant.execution.exits import ExitEngine
from quant.execution.oms import PaperOMS
from quant.execution.order import Order, Position
from quant.execution.risk import SessionRisk
from quant.position_manager import PositionManager


def _pyramid():
    sig = Signal(type="LONG", reason="r", entry=100.0, sl=99.0, tp=103.0,
                 rr=3.0, model_label="Triple-A", symbol="SYM", timestamp="t0")
    return Position(order=Order(sig, 10.0), open_price=100.0, open_time="t0",
                    size=10.0, pyramid_level=1, is_pyramid=True)


def test_pyramid_only_close_stamps_exit_source():
    """A lingering pyramid add-on must be closed through _execute_full_close,
    so last_exit_source is stamped and the close is logged like any other."""
    events = []
    pm = PositionManager(
        oms=PaperOMS(lot_size=1.0),
        exits=ExitEngine(),
        risk=SessionRisk(storage=None, symbol="SYM"),
        emit_fn=events.append,
        symbol="SYM",
        market="NSE",
        contract_expiry=None,
        tick_size=0.05,
    )
    pm.pyramid_positions = [_pyramid()]
    pm.current_position = None

    # The runtime helper under test (extracted so it is callable in isolation).
    from quant.runtime import close_lingering_pyramids

    bar = Bar("2026-09-10T15:20:00", 100.0, 101.0, 99.0, 100.0, 10, 10)
    closed = close_lingering_pyramids(pm, 100.0, bar.time, "EOD_SQUARE_OFF")

    assert closed == 1
    assert pm.pyramid_positions == []
    # The stamp is the whole point: previously this path left it blank/stale.
    assert pm._exits.last_exit_source == "DETERMINISTIC:EOD_SQUARE_OFF"
    assert any(type(e).__name__ == "PositionClosed" for e in events)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/test_eod_force_close.py -v`
Expected: FAIL with `ImportError: cannot import name 'close_lingering_pyramids' from 'quant.runtime'`

- [ ] **Step 3: Write the minimal implementation**

In `quant/runtime.py`, add a module-level helper immediately before `class QuantEngine` (search for `class QuantEngine:` and insert above it):

```python
def close_lingering_pyramids(pm, price: float, time_str: str, reason: str) -> int:
    """Close pyramid add-ons whose base position is already gone.

    Routes every add-on through ``PositionManager._execute_full_close`` — the
    ONLY full-close release path — so the exit-source stamp, the
    ``[POSITION CLOSED]`` log, the double-close guard and the portfolio-risk
    release all happen exactly as they do for the base position. A direct
    ``pm._oms.close(...)`` loop here previously skipped all four.

    Returns the number of add-ons closed.
    """
    from quant.execution.exits import ExitDecision

    closed = 0
    for pyr_pos in list(pm.pyramid_positions):
        pm._execute_full_close(
            pyr_pos, ExitDecision(True, reason, float(price)), time_str
        )
        closed += 1
    pm.pyramid_positions = []
    pm.pyramid_count = 0
    return closed
```

Then replace the inline `else:` branch in `force_close_position` (currently the direct-OMS loop):

```python
            if pos is not None:
                pm._execute_full_close(pos, ExitDecision(True, reason, price), ts)
            else:
                # Base already gone but pyramid add-ons linger — close them
                # through the single release path so the exit is stamped,
                # logged and risk-released exactly like the base close.
                close_lingering_pyramids(pm, price, ts, reason)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/test_eod_force_close.py -v`
Expected: PASS

- [ ] **Step 5: Verify the bypass is gone**

Run: `PYTHONPATH=backend:. .venv/bin/python scripts/pre_release_decision_check.py --skip-suites 2>&1 | grep "single release path"`
Expected: `[PASS] every full close routes through the single release path`

- [ ] **Step 6: Run the affected suites**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/test_position_management_flow.py tests/quant/test_eod_stress.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add quant/runtime.py tests/quant/test_eod_force_close.py
git commit -m "fix: route pyramid-only force-close through the single full-close release path"
```

---

## Task 3: D-4 — an absent volume profile must not fabricate an entry

**Files:**
- Modify: `quant/decision/timesfm_agents.py:109-119` and the Setup D fade branches at `:194-217`
- Test: `tests/quant/decision/test_timesfm_agents.py` (append)

**Interfaces:**
- Consumes: `DecisionContext.poc/vah/val` (floats, `0.0` when no profile).
- Produces: `TimesFMScanningAgent.evaluate` returns `action="FLAT"`, `setup="NO_EDGE"`, `reason="NO_PROFILE"` when the profile is absent.

- [ ] **Step 1: Write the failing test**

Append to `tests/quant/decision/test_timesfm_agents.py`:

```python
def test_absent_volume_profile_never_fabricates_a_setup():
    """D-4: poc/vah/val == 0 means 'no profile yet'. The scanner must stay FLAT
    instead of collapsing the VA to curr_price and trivially satisfying the
    fade conditions."""
    import numpy as np

    horizon = 32
    curr = 100.0
    p50 = np.linspace(curr, curr + 1.5, horizon)
    fc = TimesFMForecast(
        horizon=horizon, p50_path=p50, p10_path=p50 - 0.5, p90_path=p50 + 0.5,
        q_spread=1.0, mean_forecast=float(p50[-1]),
        pct_change=0.015, forecast_steps=["LONG"] * horizon,
        curr_price=curr, lat_ms=1.0,
    )
    bar = Bar("2026-09-10T10:00:00", 100.0, 101.0, 99.0, 100.0, 100, 100)
    ctx = DecisionContext(
        symbol="NIFTY", bar=bar, bar_index=20, session_open=True,
        warmup_complete=True, session_phase="PRIMARY",
        poc=0.0, vah=0.0, val=0.0, cvd_slope=1.0, allow_reversion=True,
    )
    res = TimesFMScanningAgent(target_horizon=horizon).evaluate(ctx, fc)
    assert res["action"] == "FLAT", res
    assert res["setup"] == "NO_EDGE", res
    assert res["reason"] == "NO_PROFILE", res


def test_valid_profile_still_trades():
    """Guard against over-correcting: a real profile must still fire."""
    import numpy as np

    horizon = 32
    curr = 100.0
    p50 = np.linspace(curr, curr + 1.2, horizon)
    fc = TimesFMForecast(
        horizon=horizon, p50_path=p50, p10_path=p50 - 0.5, p90_path=p50 + 0.5,
        q_spread=1.0, mean_forecast=float(p50[-1]),
        pct_change=0.012, forecast_steps=["LONG"] * horizon,
        curr_price=curr, lat_ms=1.0,
    )
    bar = Bar("2026-09-10T10:00:00", 100.0, 101.0, 99.0, 100.0, 100, 100)
    ctx = DecisionContext(
        symbol="NIFTY", bar=bar, bar_index=20, session_open=True,
        warmup_complete=True, session_phase="PRIMARY",
        poc=101.0, vah=101.5, val=99.0, cvd_slope=1.0, allow_reversion=True,
    )
    res = TimesFMScanningAgent(target_horizon=horizon).evaluate(ctx, fc)
    assert res["action"] != "FLAT", res
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_timesfm_agents.py -k "absent_volume_profile or valid_profile_still_trades" -v`
Expected: `test_absent_volume_profile_never_fabricates_a_setup` FAILS with `assert 'ENTER_LONG' == 'FLAT'`; the second test PASSES.

- [ ] **Step 3: Write the minimal implementation**

In `quant/decision/timesfm_agents.py`, replace the resolution block (currently `poc = float(ctx.poc or (ctx.state.poc if ctx.state else curr_price))` etc.) with:

```python
        # A zero/absent volume profile is NOT a value area at curr_price — it
        # means the AMT profile has not populated yet (empty seed, cold start).
        # Collapsing vah/val to curr_price makes every location test trivially
        # true and fabricates a fade with no auction structure behind it.
        poc = float(ctx.poc or 0.0)
        vah = float(ctx.vah or 0.0)
        val = float(ctx.val or 0.0)
        has_profile = vah > 0.0 and val > 0.0 and vah > val
        if not has_profile:
            return {
                "role": "SCANNING",
                "action": "FLAT",
                "direction": "FLAT",
                "setup": "NO_EDGE",
                "reason": "NO_PROFILE",
                "confidence": "Low",
                "confidenceScore": 0.0,
                "rationale": (
                    f"No volume profile on {symbol} yet (poc={poc:.2f}, "
                    f"vah={vah:.2f}, val={val:.2f}) — standing down until the "
                    f"AMT profile populates."
                ),
                "forecastSteps": list(forecast.forecast_steps),
                "quantileSpread": round(float(forecast.q_spread), 4),
                "meanForecast": round(float(forecast.mean_forecast), 2),
                "gateResults": [
                    {"gate_no": 1, "gate_name": "SESSION_PHASE", "passed": True, "message": ""},
                    {"gate_no": 2, "gate_name": "POSITION_COOLDOWN", "passed": True, "message": ""},
                    {"gate_no": 3, "gate_name": "TRIPLE_A_EDGE", "passed": False, "message": "No volume profile"},
                    {"gate_no": 4, "gate_name": "RISK_REWARD", "passed": False, "message": "No setup"},
                ],
                "activePosition": None,
                "dynamicTrailStop": None,
                "dynamicSizing": None,
                "recommendedOption": None,
                "source": "TIMESFM_3.0_NATIVE",
                "latencyMs": round(float(forecast.lat_ms), 1),
                "modelLabel": "TimesFM-NoProfile",
                "modelVersions": {"timesfm": "3.0", "agent_role": "SCANNING", "engine": "native_direct"},
                "regime": ctx.market_state.value if hasattr(ctx.market_state, "value") else str(ctx.market_state or "BALANCED"),
                "timing": str(ctx.session_phase or "REGULAR"),
                "sizeFraction": 0.0,
                "latencyUs": int(float(forecast.lat_ms) * 1000),
            }
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_timesfm_agents.py -v`
Expected: PASS (all tests, including the pre-existing ones)

- [ ] **Step 5: Guard the context-builder production of a zero profile**

The same hazard exists at the source. In `quant/decision/context_builder.py`, in the `build(...)` return, the AMT VA fields are already `float(amt_dto.get(...) or 0.0)`, so no change is needed there — confirm by reading lines 432-434 and leave them as-is. Record the confirmation in the commit body.

- [ ] **Step 6: Run the release gate for this finding**

Run: `PYTHONPATH=backend:. .venv/bin/python scripts/pre_release_decision_check.py --skip-suites 2>&1 | grep "volume profile"`
Expected: `[PASS] empty volume profile cannot fabricate an entry`

- [ ] **Step 7: Run the affected suites**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/ -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add quant/decision/timesfm_agents.py tests/quant/decision/test_timesfm_agents.py
git commit -m "fix: refuse to trade when the AMT volume profile is absent

The scanner fell back to curr_price for vah/val when the profile had not
populated, which made the VA-fade location tests trivially true and produced
an approved entry with no auction structure behind it (reproduced: VA_FADE
LONG approved, entry=100.0 sl=99.45 tp=101.5). The deterministic path returns
NO_EDGE on the same context."
```

---

## Task 4: D-10 — shared-engine dedup must survive concurrency and lag

**Files:**
- Modify: `quant/decision/timesfm_engine.py:30-31` (add lock), `:99-105` (`__init__`), `:186-201` (`add_context`)
- Test: `tests/quant/decision/test_timesfm_engine.py` (append)

**Interfaces:**
- Consumes: `DecisionContext.bar_index` (int, `-1` when unstamped).
- Produces: `TimesFMEngine.add_context` is safe to call concurrently and ignores any bar whose `bar_index` is not strictly greater than the last recorded one. New private `self._buffer_lock: threading.RLock`.

- [ ] **Step 1: Write the failing tests**

Append to `tests/quant/decision/test_timesfm_engine.py`:

```python
def test_add_context_is_thread_safe_for_one_bar():
    """D-10: two consumers racing on the same bar must append it once."""
    import threading

    engine = TimesFMEngine(target_horizon=8)
    bar = Bar("2026-09-10T10:00:00", 100, 101, 99, 100.5, 1000, 100)
    ctx = DecisionContext(symbol="NIFTY", bar=bar, bar_index=42)

    class _Rendezvous(dict):
        def __init__(self):
            super().__init__()
            self._barrier = threading.Barrier(2, timeout=5)

        def get(self, key, default=None):
            value = super().get(key, default)
            try:
                self._barrier.wait()
            except threading.BrokenBarrierError:
                pass
            return value

    engine._last_context_bar = _Rendezvous()

    def consumer():
        try:
            engine.add_context(ctx)
        except Exception:
            pass

    threads = [threading.Thread(target=consumer) for _ in range(2)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(timeout=10)

    assert len(engine._price_buffers["NIFTY"]) == 1


def test_add_context_ignores_a_late_replayed_bar():
    """D-10: the advisor drains its queue behind the engine thread, so a bar
    already recorded must not be appended again."""
    engine = TimesFMEngine(target_horizon=8)

    def mk(idx, px):
        bar = Bar(f"2026-09-10T10:{idx:02d}:00", px, px, px, px, 10, 10)
        return DecisionContext(symbol="NIFTY", bar=bar, bar_index=idx)

    for idx, px in [(1, 100.0), (2, 101.0), (3, 102.0)]:
        engine.add_context(mk(idx, px))          # strategy, on time
    for idx, px in [(1, 100.0), (2, 101.0), (3, 102.0)]:
        engine.add_context(mk(idx, px))          # advisor, lagging

    assert list(engine._price_buffers["NIFTY"]) == [100.0, 101.0, 102.0]


def test_add_context_still_accepts_unstamped_callers():
    """bar_index < 0 (unit tests, ad-hoc probes) keeps appending."""
    engine = TimesFMEngine(target_horizon=8)
    bar = Bar("2026-09-10T10:00:00", 100, 101, 99, 100.5, 1000, 100)
    ctx = DecisionContext(symbol="NIFTY", bar=bar, bar_index=-1)
    engine.add_context(ctx)
    engine.add_context(ctx)
    assert len(engine._price_buffers["NIFTY"]) == 2
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_timesfm_engine.py -k "thread_safe or late_replayed" -v`
Expected: both FAIL — first with `assert 2 == 1`, second with `assert [100.0, 101.0, 102.0, 100.0, 101.0, 102.0] == [100.0, 101.0, 102.0]`

- [ ] **Step 3: Write the minimal implementation**

In `quant/decision/timesfm_engine.py`, inside `TimesFMEngine.__init__`, after `self._last_context_bar: Dict[str, int] = {}`, add:

```python
        # The advisor worker thread and the E2E strategy engine thread share
        # ONE engine, so buffer mutation and the per-bar dedup must be atomic.
        # The old check-then-act allowed both threads past the guard (same-bar
        # double append) and allowed a lagging consumer to replay an older bar
        # after a newer one (out-of-order window).
        self._buffer_lock = threading.RLock()
```

Replace the whole body of `add_context` from `symbol = str(...)` to the final `return` with:

```python
        symbol = str(ctx.symbol or "DEFAULT")
        price = float(ctx.bar.close if ctx.bar else (ctx.state.poc if ctx.state else 100.0))
        bar_index = int(getattr(ctx, "bar_index", -1) or -1)

        with self._buffer_lock:
            buf = self._price_buffers[symbol]

            # A stamped bar index must be STRICTLY newer than the last recorded
            # one. Equal means another consumer already recorded this bar;
            # lesser means a lagging consumer (advisor queue) is replaying a bar
            # the engine thread has already passed. Both must be dropped, or
            # the model window sees duplicate/out-of-order prices.
            # bar_index < 0 means the caller did not stamp one (unit tests,
            # ad-hoc probes) — append unchanged so those keep working.
            if bar_index >= 0:
                last = self._last_context_bar.get(symbol)
                if last is not None and bar_index <= last:
                    return self._context_window(buf)
                self._last_context_bar[symbol] = bar_index

            buf.append(price)
            self._live_bar_counts[symbol] += 1
            return self._context_window(buf)
```

Add `import threading` at the top of the module if it is not already imported (it is used by the model cache) — confirm before editing.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_timesfm_engine.py -v`
Expected: PASS (all)

- [ ] **Step 5: Lock inference against the shared singleton**

`model.predict` is called from the advisor worker, the strategy engine thread and the coordinator with no lock held. In `quant/decision/timesfm_engine.py`, add a module-level inference lock beside `_TIMESFM_LOCK`:

```python
# Serializes inference on the shared TimesFM singleton. The model object is not
# documented as thread-safe and every engine in the coordinator shares it.
_TIMESFM_INFER_LOCK = threading.Lock()
```

In `TimesFMEngine.analyze`, wrap the predict call:

```python
        try:
            np_prices = np.array(context_prices, dtype=np.float32)
            with _TIMESFM_INFER_LOCK:
                res = model.predict(context=np_prices, horizon=self.target_horizon, return_quantiles=True)
            lat_ms = (time.perf_counter() - t0) * 1000.0
        except Exception as e:
```

Apply the same wrap in `quant/strategies/timesfm_strategy.py::_compute_forecast` around its `model_inst.predict(...)` call, importing `_TIMESFM_INFER_LOCK` from `quant.decision.timesfm_engine`.

- [ ] **Step 6: Run the release gate and the widest affected suites**

Run: `PYTHONPATH=backend:. .venv/bin/python scripts/pre_release_decision_check.py 2>&1 | tail -25`
Expected: `0 failed` — all four Wave 1 checks now PASS.

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/ tests/quant/strategies/ tests/quant/execution/ -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add quant/decision/timesfm_engine.py quant/strategies/timesfm_strategy.py tests/quant/decision/test_timesfm_engine.py
git commit -m "fix: make shared-engine per-bar dedup thread-safe and monotonic

The advisor worker thread and the E2E strategy engine thread share one
TimesFMEngine. add_context's check-then-act allowed both threads past the
guard on the same bar (reproduced: buffer depth 2 for 1 bar) and allowed a
lagging advisor to replay older bars after newer ones (reproduced: buffer
[100,101,102,100,101,102] for 3 bars). Inference on the shared singleton is
now serialized too."
```

---

# WAVE 2 — One authority per decision

## Task 5: D-5 — pyramid add-ons must see the LVN the DTO actually emits

**Files:**
- Modify: `quant/position_manager.py:521`
- Test: `tests/quant/execution/test_pyramid_integration.py` (append)

**Interfaces:**
- Consumes: AMT DTO key `legLvns` (tuple of floats, `dto.py:88`).
- Produces: `check_pyramid` reads the nearest leg LVN from `legLvns`, falling back to the legacy plural-less key.

- [ ] **Step 1: Write the failing test**

Append to `tests/quant/execution/test_pyramid_integration.py`:

```python
def test_pyramid_reads_leg_lvn_from_the_dto_key_that_exists():
    """D-5: the DTO emits legLvns (plural). Reading legLvn (singular) made the
    pyramid guard return on every bar, making the whole engine inert."""
    from quant.position_manager import PositionManager
    from quant.execution.oms import PaperOMS
    from quant.execution.exits import ExitEngine
    from quant.execution.risk import SessionRisk

    pm = PositionManager(
        oms=PaperOMS(lot_size=1.0), exits=ExitEngine(),
        risk=SessionRisk(storage=None, symbol="SYM"), emit_fn=lambda e: None,
        symbol="SYM", market="NSE", contract_expiry=None, tick_size=0.05,
    )
    # The guard under test is the leg-LVN source line; assert the resolution
    # itself so the test does not depend on the rest of the pyramid ladder.
    resolved = pm._resolve_leg_lvn({"legLvns": [99.5, 101.25], "legLvn": None}, close_px=101.0)
    assert resolved == 101.25

    legacy = pm._resolve_leg_lvn({"legLvn": 100.0}, close_px=100.0)
    assert legacy == 100.0

    assert pm._resolve_leg_lvn({}, close_px=100.0) == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/test_pyramid_integration.py -k leg_lvn_from_the_dto_key -v`
Expected: FAIL with `AttributeError: 'PositionManager' object has no attribute '_resolve_leg_lvn'`

- [ ] **Step 3: Write the minimal implementation**

In `quant/position_manager.py`, add a static helper just above `def check_pyramid`:

```python
    @staticmethod
    def _resolve_leg_lvn(amt_dto: dict, close_px: float) -> float:
        """Nearest impulse-leg LVN from the AMT DTO.

        The DTO emits ``legLvns`` (plural, the full list); ``legLvn`` (singular)
        is a legacy key the AMT layer never produces. Reading only the singular
        key made the pyramid guard bail on every bar, so add-ons never fired.
        """
        raw = amt_dto.get("legLvns")
        if isinstance(raw, (list, tuple)):
            valid = [float(x) for x in raw if float(x) > 0]
            if valid:
                return min(valid, key=lambda x: abs(x - float(close_px)))
        try:
            legacy = float(amt_dto.get("legLvn") or 0.0)
        except (TypeError, ValueError):
            legacy = 0.0
        return legacy if legacy > 0 else 0.0
```

Replace line 521 (`leg_lvn = float(amt_dto.get("legLvn") or 0.0)`) with:

```python
        leg_lvn = self._resolve_leg_lvn(amt_dto, float(bar.close))
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/test_pyramid_integration.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quant/position_manager.py tests/quant/execution/test_pyramid_integration.py
git commit -m "fix: read the impulse-leg LVN from the key the AMT DTO emits

check_pyramid read the singular legLvn, which the DTO never produces
(dto.py emits legLvns, a list). The guard therefore returned on every bar and
the pyramid add-on engine was inert in production."
```

---

## Task 6: D-6 — retire the unreachable `optionGreekDelta` branch (corrected)

**Files:**
- Modify: `quant/decision/context_builder.py` (`option_delta=` expression)
- Test: `tests/quant/decision/test_option_delta_semantics.py` (append)
- Modify: `docs/reviews/2026-09-10-pre-release-code-audit.md` (correct D-6's stated remedy)

**Interfaces:**
- Consumes: nothing new.
- Produces: `DecisionContext.option_delta` documents, in one place, that it is a best-effort default and cannot be a chain Greek today.

> **CORRECTION (found while executing).** The original Task 6 said to emit `optionGreekDelta` from `amt_result_to_dto` via `getattr(r, "option_greek_delta", None)`. That is wrong twice over:
> 1. `AMTResult` (`quant/contracts/value_objects.py`) has **no** `option_greek_delta` field, so the planned `getattr` default would always yield `None` — a no-op, not a fix.
> 2. `deltaNormalizedOption` is candle **order-flow** delta, not a Greek, and a test exists to keep it out (`tests/quant/decision/test_option_delta_semantics.py`).
>
> There is therefore no chain-Greek producer available to wire. This task does not invent one; it removes a misleading dead branch and records the truth.

- [ ] **Step 1: Write the failing test**

Append to `tests/quant/decision/test_option_delta_semantics.py`:

```python
def test_option_delta_is_a_documented_default_not_a_chain_greek():
    """D-6 (corrected): no chain-Greek producer exists, so option_delta is
    always the documented ATM default. Assert that plainly so a future reader
    (or a future chain integration) cannot mistake it for a real Greek."""
    from types import SimpleNamespace

    from quant.decision.context_builder import DecisionContextBuilder

    bar = SimpleNamespace(close=150.0, open=149.0, high=151.0, low=148.0,
                          volume=100, time="2026-09-10T10:00:00+05:30")
    risk = SimpleNamespace(halted=False, consecutive_losses=0,
                           equity=1_000_000.0, risk_per_trade_pct=0.05)

    ctx = DecisionContextBuilder().build(
        bar=bar, symbol="NIFTY 24600 CALL", market="NSE", contract_expiry=None,
        tick_size=0.05, bar_index=20, warm_bars=0, cooldown_remaining_sec=0.0,
        risk_state=risk, amt_dto={},
    )
    # Options get the conservative ATM default; futures get None.
    assert ctx.option_delta == 0.50

    ctx_fut = DecisionContextBuilder().build(
        bar=bar, symbol="NIFTY FUT", market="NSE", contract_expiry=None,
        tick_size=0.05, bar_index=20, warm_bars=0, cooldown_remaining_sec=0.0,
        risk_state=risk, amt_dto={},
    )
    assert ctx_fut.option_delta is None
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_option_delta_semantics.py -k documented_default -v`
Expected: FAIL with `ImportError: cannot import name 'DEFAULT_OPTION_DELTA'` (after Step 3 adds the name, re-run: PASS). If it PASSES now, the behaviour already holds — say so in the report and keep the test as a pin.

- [ ] **Step 3: Remove the dead branch and name the default**

In `quant/decision/context_builder.py`, replace the `option_delta=` expression with a single named constant defined at module top:

```python
# Conservative ATM delta used to scale underlying stop distance into option
# premium distance. There is NO chain Greek producer in this codebase:
# AMTResult carries no option delta, and deltaNormalizedOption is candle
# order-flow delta (see tests/quant/decision/test_option_delta_semantics.py).
# So this default is authoritative until a real option chain is wired.
# ponytail: wire a real chain delta here when the chain feed lands.
DEFAULT_OPTION_DELTA = 0.50
```

and at the construction site:

```python
            option_delta=(
                DEFAULT_OPTION_DELTA if is_option_contract(symbol) else None
            ),
```

This deletes the unreachable `amt_dto["optionGreekDelta"]` branch rather than adding a producer for a key nothing can populate.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_option_delta_semantics.py -v`
Expected: PASS (all, including the pre-existing `test_translation_requires_explicit_greek_delta`)

- [ ] **Step 5: Correct the audit document**

In `docs/reviews/2026-09-10-pre-release-code-audit.md`, amend D-6 to state the corrected finding: no chain-Greek producer exists, `optionGreekDelta` cannot be emitted from `AMTResult`, and the branch was removed rather than faked. Keep the original text below a `> Corrected 2026-09-10 during execution:` note so the record shows the change of understanding.

- [ ] **Step 6: Run the affected suites**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/ tests/quant/amt/ -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add quant/decision/context_builder.py tests/quant/decision/test_option_delta_semantics.py docs/reviews/2026-09-10-pre-release-code-audit.md
git commit -m "refactor: retire the unreachable optionGreekDelta branch

AMTResult carries no option delta, so the planned emit was a no-op and the
branch never ran. There is no chain-Greek producer to wire; the ATM default is
now a named constant with that fact documented, instead of a dead branch that
implied a live Greek was being consumed."
```

---

## Task 7: D-7 — the displayed stop must be the enforced stop

**Files:**
- Modify: `quant/transitions.py` (`apply_event`), `quant/state.py:209` (read the folded stop)
- Test: `tests/quant/test_state_machine.py` (append) and `tests/quant/execution/test_exit_source.py` (append)

**Interfaces:**
- Consumes: `StopMoved(old_sl, new_sl, reason)` (existing event, already emitted on every ratchet).
- Produces: `EngineState.position.sl` and `EngineState.pyramids[i].sl` reflect the latest `StopMoved`; `_position_to_view` reads the folded value so the portfolio row shows the enforced stop.

- [ ] **Step 1: Write the failing test**

Append to `tests/quant/test_state_machine.py`:

```python
def test_stop_moved_folds_into_the_projected_stop():
    """D-7: StopMoved was journaled but never folded, so the UI showed the
    submitted stop while ExitEngine enforced the ratcheted one."""
    from quant.state_machine import EngineState, PositionState
    from quant.events import StopMoved
    from quant.transitions import apply_event

    state = EngineState(symbol="SYM")
    state = state.with_position(
        PositionState(id="p1", entry=100.0, size=10.0, sl=99.0, tp=103.0, side="LONG")
    )
    assert state.position.sl == 99.0

    state = apply_event(state, StopMoved(symbol="SYM", time="t1", old_sl=99.0,
                                         new_sl=100.5, reason="TRAIL_RATCHET"))
    assert state.position.sl == 100.5

    # Stale/replayed moves must not loosen an already-ratcheted stop.
    state = apply_event(state, StopMoved(symbol="SYM", time="t2", old_sl=100.5,
                                         new_sl=98.0, reason="TRAIL_RATCHET"))
    assert state.position.sl == 100.5
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/test_state_machine.py -k stop_moved_folds -v`
Expected: FAIL with `assert 99.0 == 100.5`

- [ ] **Step 3: Write the minimal implementation**

In `quant/transitions.py`, add a branch inside `apply_event` after the `PositionReduced` branch (match the file's existing `elif isinstance(event, ...)` style):

```python
    elif isinstance(event, StopMoved):
        # Fold the protective-stop move into the position it belongs to.
        # Without this the event-fold authority kept the submitted stop while
        # ExitEngine enforced the ratcheted one, so the portfolio row and the
        # operator's "Trail SL" showed a stop the engine would never honour.
        def _tighten(pos):
            if pos is None:
                return None, False
            long = str(pos.side).upper() == "LONG"
            new_sl = float(event.new_sl)
            if new_sl <= 0:
                return pos, False
            # Monotonic: a move may only tighten, never loosen.
            if (long and new_sl <= float(pos.sl)) or (not long and new_sl >= float(pos.sl)):
                return pos, False
            return replace(pos, sl=new_sl), True

        new_pos, changed = _tighten(state.position)
        if changed:
            return replace(state, position=new_pos, sequence=state.sequence + 1)
        new_pyramids = []
        pyramid_changed = False
        for p in state.pyramids:
            tightened, did = _tighten(p)
            new_pyramids.append(tightened)
            pyramid_changed = pyramid_changed or did
        if pyramid_changed:
            return replace(state, pyramids=tuple(new_pyramids), sequence=state.sequence + 1)
        return state
```

Confirm `StopMoved` is imported in `quant/transitions.py`; add it to the existing `from quant.events import (...)` list if not.

In `quant/state.py`, `_position_to_view` should read the folded stop. In `quant/multi_engine.py::snapshot`, the position dicts already come from `project_state(engine.event_store.fold())`, so once the fold is correct the portfolio row is correct. Verify by reading `quant/state.py:200-230` and confirm `sl` is read from the folded position's `stop_loss`/`sl`; if `_position_to_view` is only used for the non-folded path, no change is needed. Record the confirmation in the commit body.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/test_state_machine.py tests/quant/execution/test_exit_source.py tests/quant/test_replay_journal.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quant/transitions.py tests/quant/test_state_machine.py
git commit -m "fix: fold StopMoved into the projected stop

StopMoved was emitted on every ratchet but never applied, so the portfolio row
and the operator's displayed Trail SL showed the submitted stop while
ExitEngine enforced the tighter ratcheted one. Three different stops existed
for one trade (submitted / enforced / displayed); now the displayed one is the
enforced one. The fold is monotonic, so a replayed or stale move cannot loosen
a stop."
```

---

## Task 8: D-13 — the bar path and the tick path must agree on the breached stop

**Files:**
- Modify: `quant/execution/exits.py` (`evaluate` — reorder the protective-stop resolution)
- Test: `tests/quant/execution/test_exits_trailing.py` (append)

**Interfaces:**
- Consumes: `ExitEngine._trail`, `ExitEngine._breakeven` (existing).
- Produces: on a bar that pierces both the raw SL and an armed trail/breakeven, `ExitDecision.reason` is `TRAIL`/`BREAKEVEN` and `close_price` is the merged stop — identical to the tick path at `position_manager.manage_tick_exit`.

- [ ] **Step 1: Write the failing test**

Append to `tests/quant/execution/test_exits_trailing.py`:

```python
def test_bar_path_books_trail_not_sl_when_trail_is_tighter():
    """D-13: the bar path checked the raw frozen SL before the merged
    trail/breakeven stop, so the same breach booked SL at the worse price on
    the bar path and TRAIL on the tick path."""
    from quant.decision.signal_builder import Signal
    from quant.execution.exits import ExitEngine, _Trail
    from quant.execution.order import Order, Position

    sig = Signal(type="LONG", reason="r", entry=100.0, sl=95.0, tp=110.0,
                 rr=2.0, model_label="Triple-A", symbol="SYM", timestamp="t0")
    pos = Position(order=Order(sig, 10.0), open_price=100.0, open_time="t0", size=10.0)

    eng = ExitEngine()
    # Arm a trailing stop well above the raw SL.
    eng._trail[pos._id] = _Trail(active=True, stop=99.0)

    # Bar sweeps below BOTH the trail (99.0) and the raw SL (95.0).
    d = eng.evaluate(pos, bar_close=94.0, bar_high=101.0, bar_low=94.0, bar_index=5)

    assert d.should_exit is True
    assert d.reason == "TRAIL", f"expected TRAIL, got {d.reason} at {d.close_price}"
    assert d.close_price == 99.0
    assert eng.last_exit_source == "DETERMINISTIC:TRAIL"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/test_exits_trailing.py -k books_trail_not_sl -v`
Expected: FAIL with `assert 'SL' == 'TRAIL'`

- [ ] **Step 3: Write the minimal implementation**

The fix is a **reorder**. Adding the block without moving the existing one leaves the raw-SL check first and the bug intact. The order inside `evaluate` must end up as:

1. spread blowout (unchanged)
2. TimesFM risk-authority block (unchanged, from Task 1)
3. **protective stop (NEW POSITION — moved up from Rule 4b)**
4. CVD kill
5. take-profit tiers
6. trailing/breakeven **state advance** for the next bar
7. time stop

Delete the current `# Rule 2: Stop-loss` / `check_stop_loss(...)` lines entirely — the block below subsumes them (`protective_reason == "SL"` is the raw-SL case). Insert at position 3:

```python
        # Rule 2: protective stop — the TIGHTEST of raw SL, breakeven floor and
        # active trail. The bar path previously checked the raw frozen SL first,
        # so a bar sweeping both the SL and the trail booked SL at the worse
        # price while the identical tick breach booked TRAIL. One resolver, one
        # price, one exit_source for the same economic event.
        be_floor = self._breakeven.get(position._id)
        tr = self._trail.get(position._id)
        trail_stop = tr.stop if (tr and tr.active) else None
        protective = float(sl)
        protective_reason = "SL"
        if trail_stop is not None:
            if (long and trail_stop > protective) or (not long and trail_stop < protective):
                protective, protective_reason = float(trail_stop), "TRAIL"
        if be_floor is not None:
            if (long and be_floor > protective) or (not long and be_floor < protective):
                protective, protective_reason = float(be_floor), "BREAKEVEN"

        breached = (long and low <= protective) or (not long and high >= protective)
        if breached and protective_reason != "SL":
            self.last_exit_source = f"DETERMINISTIC:{protective_reason}"
            return ExitDecision(True, protective_reason, protective, trail_stop=protective)
        if breached:
            self.last_exit_source = "DETERMINISTIC:SL"
            return ExitDecision(True, "SL", float(sl))

        # Rule 3: CVD kill
        r = check_cvd_kill(position, dto, self.cvd_kill_threshold)
        if r:
            self.last_exit_source = f"DETERMINISTIC:{r.reason}"
            return ExitDecision(True, r.reason, close)
```

Then confirm the Rule 4b block reads as the state advance only:

```python
        # Rule 4b: advance the trailing/breakeven stores for the NEXT bar.
        # The breach check for THIS bar already ran above, against the tightest
        # protective level, so this call only ratchets state forward.
        be_floor = self._breakeven.get(position._id)
        tr = self._trail.get(position._id)
        trail_stop = tr.stop if tr else None
        if risk > 0:
            r, be_floor, trail_stop = check_trailing_stop(
                position, close, low, high, sl, entry, risk, dto,
                session_vwap, self.trail_giveback_pct, self.vwap_adverse_drift_pct,
                self.cvd_be_threshold, be_floor, trail_stop,
            )
            if be_floor is not None:
                self._breakeven[position._id] = be_floor
            if trail_stop is not None:
                if tr is None:
                    tr = _Trail()
                    self._trail[position._id] = tr
                tr.active = True
                tr.stop = trail_stop
            if r:
                self.last_exit_source = f"DETERMINISTIC:{r.reason}"
                return r
```

Remove the now-unused `check_stop_loss` import only if nothing else uses it; grep `check_stop_loss` first and keep the import if `exit_checks` tests reference it.

**Expect existing tests to change.** Assertions that encode the OLD order must be updated to the new, intended behaviour (state this in the commit body):

- `tests/quant/execution/test_exits_trailing.py` — a bar low piercing both the raw SL and the armed trail now returns `TRAIL` at `trail_stop`, not `SL` at the raw SL.
- `tests/quant/execution/test_exit_source.py::test_exit_source_labels_deterministic_sl` — that position has no trail and no breakeven armed, so it still returns `SL`; verify it passes unchanged.

If any other test asserts the old ordering, fix it to assert the new behaviour. Do not weaken it to accept either.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/test_exits.py tests/quant/execution/test_exits_trailing.py tests/quant/execution/test_exits_spread.py tests/quant/execution/test_tick_level_exits.py tests/quant/execution/test_exit_source.py -v`
Expected: PASS

- [ ] **Step 5: Add the tick-path parity assertion**

Append to `tests/quant/execution/test_exits_trailing.py`:

```python
def test_tick_and_bar_paths_agree_on_the_breached_stop():
    """The bar path and the tick path must book the same reason and price."""
    from quant.decision.signal_builder import Signal
    from quant.execution.exits import ExitEngine, _Trail
    from quant.execution.order import Order, Position
    from quant.execution.oms import PaperOMS
    from quant.execution.risk import SessionRisk
    from quant.position_manager import PositionManager

    def _pos(pid):
        sig = Signal(type="LONG", reason="r", entry=100.0, sl=95.0, tp=110.0,
                     rr=2.0, model_label="Triple-A", symbol="SYM", timestamp="t0")
        return Position(order=Order(sig, 10.0), open_price=100.0,
                        open_time="t0", size=10.0, _id=pid)

    eng_bar = ExitEngine()
    pos_bar = _pos("bar")
    eng_bar._trail[pos_bar._id] = _Trail(active=True, stop=99.0)
    d_bar = eng_bar.evaluate(pos_bar, bar_close=94.0, bar_high=101.0,
                             bar_low=94.0, bar_index=5)

    eng_tick = ExitEngine()
    pos_tick = _pos("tick")
    eng_tick._trail[pos_tick._id] = _Trail(active=True, stop=99.0)
    pm = PositionManager(oms=PaperOMS(lot_size=1.0), exits=eng_tick,
                         risk=SessionRisk(storage=None, symbol="SYM"),
                         emit_fn=lambda e: None, symbol="SYM", market="NSE",
                         contract_expiry=None, tick_size=0.05)
    pm.manage_tick_exit(pos_tick, 94.0, "t1")
    tick_reason = pm._exits.last_exit_source

    assert d_bar.reason == "TRAIL"
    assert tick_reason == "DETERMINISTIC:TRAIL"
```

- [ ] **Step 6: Run and commit**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/ -q`
Expected: PASS

```bash
git add quant/execution/exits.py tests/quant/execution/test_exits_trailing.py
git commit -m "fix: resolve the tightest protective stop once for both exit paths

The bar path checked the raw frozen SL before the merged trail/breakeven stop,
so a bar sweeping both booked SL at the worse price while the identical tick
breach booked TRAIL — two reasons and two prices for one economic event."
```

---

## Task 9: D-15 — the double-close guard must survive across calls

**Files:**
- Modify: `quant/position_manager.py:144-145`
- Test: `tests/quant/chaos/test_crash_recovery.py` (flip the documented-bug assertions)

**Interfaces:**
- Consumes: nothing new.
- Produces: `PositionManager._closed_ids` is initialised once in `__init__` and never reset per call; a second `_execute_full_close` on the same id is refused.

- [ ] **Step 1: Write the failing test**

In `tests/quant/chaos/test_crash_recovery.py`, replace `test_manage_exit_resets_closed_ids`'s body so it asserts the FIXED behaviour:

```python
    def test_manage_exit_does_not_reset_closed_ids(self):
        """FIXED (D-15): _closed_ids survives across manage_exit calls, so a
        position closed in a previous call cannot be closed again."""
        from quant.position_manager import PositionManager
        from quant.execution.oms import PaperOMS
        from quant.execution.exits import ExitDecision, ExitEngine
        from quant.execution.risk import SessionRisk
        from quant.bars import Bar

        pm = PositionManager(
            oms=PaperOMS(lot_size=1.0),
            exits=ExitEngine(time_stop_bars=30),
            risk=SessionRisk(storage=None, symbol="TEST"),
            emit_fn=lambda e: None,
            symbol="TEST", market="NSE", contract_expiry=None, tick_size=0.05,
        )
        pos = _open_position()          # reuse this module's existing helper/fixture
        bar = Bar("2026-09-10T10:00:00", 100.0, 101.0, 99.0, 100.0, 10, 10)

        pm.manage_exit(amt_dto={}, bar=bar, position=pos, bar_index=1,
                       entry_bar_index=0, entry_time_epoch=0.0)
        first = set(pm._closed_ids)
        assert first, "a full close must record the id"

        # A later bar must not clear the guard.
        pm.manage_exit(amt_dto={}, bar=bar, position=pos, bar_index=2,
                       entry_bar_index=0, entry_time_epoch=0.0)
        assert pos._id in pm._closed_ids
```

If `_open_position` does not exist in that module, inline the same construction the existing test uses.

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/chaos/test_crash_recovery.py -k does_not_reset_closed_ids -v`
Expected: FAIL with `assert 'p1' in set()`

- [ ] **Step 3: Write the minimal implementation**

In `quant/position_manager.py`, add the field to `__init__` (after `self.current_position = None` or the last field assignment in `__init__`):

```python
        # Ids of positions fully closed by this manager. Lives for the manager's
        # lifetime (NOT per call): a per-call reset made the double-close guard
        # non-functional across bars, so a stale reference could re-close a
        # position the broker had already flattened.
        self._closed_ids: set[str] = set()
```

Delete the per-call reset inside `manage_exit` (the two lines `# Double-close guard: ...` and `self._closed_ids: set[str] = set()`). Confirm the line `self._closed_ids: set[str] = set()` at the class body/`__init__` is the only remaining definition.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/chaos/test_crash_recovery.py tests/quant/execution/test_position_management_flow.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quant/position_manager.py tests/quant/chaos/test_crash_recovery.py
git commit -m "fix: keep the double-close guard for the manager lifetime

_closed_ids was rebuilt at the top of every manage_exit call, so it could not
block a re-close across bars despite its docstring claiming it did. Its own
chaos test documented the gap."
```

---

## Task 10: D-16 — one trailing-stop authority

**Files:**
- Modify: `quant/execution/exits.py` (make the deterministic trail read the TimesFM ratchet, not a parallel store)
- Test: `tests/quant/execution/test_exits_trailing.py` (append)

**Interfaces:**
- Consumes: `TimesFMRiskAuthority.evaluate_exit(...).new_stop` (existing).
- Produces: when a fresh forecast is present, the deterministic `check_trailing_stop` may only ratchet the SAME `_trail` entry — never introduce a candidate below the authority's stop.

- [ ] **Step 1: Write the failing test**

Append to `tests/quant/execution/test_exits_trailing.py`:

```python
def test_authority_stop_wins_over_deterministic_candidate():
    """D-16: the deterministic trail could propose a looser stop than the
    TimesFM authority had already ratcheted on the same bar."""
    import numpy as np

    from quant.decision.signal_builder import Signal
    from quant.decision.timesfm_agents import TimesFMForecast
    from quant.execution.exits import ExitEngine
    from quant.execution.order import Order, Position

    sig = Signal(type="LONG", reason="r", entry=100.0, sl=95.0, tp=110.0,
                 rr=2.0, model_label="Triple-A", symbol="SYM", timestamp="t0")
    pos = Position(order=Order(sig, 10.0), open_price=100.0, open_time="t0", size=10.0)

    p50 = np.linspace(100.0, 108.0, 32)
    fc = TimesFMForecast(
        horizon=32, p50_path=p50, p10_path=p50 - 1.0, p90_path=p50 + 1.0,
        q_spread=2.0, mean_forecast=float(p50[-1]), pct_change=0.08,
        forecast_steps=["LONG"] * 32, curr_price=100.0, lat_ms=1.0,
    )

    eng = ExitEngine()
    eng.evaluate(pos, bar_close=106.0, bar_high=107.0, bar_low=105.0,
                 bar_index=3, timesfm_forecast=fc)
    after_authority = eng._trail[pos._id].stop

    # A later bar with NO forecast must not loosen the authority's stop.
    eng.evaluate(pos, bar_close=104.0, bar_high=106.0, bar_low=103.0, bar_index=4)
    assert eng._trail[pos._id].stop >= after_authority
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/test_exits_trailing.py -k authority_stop_wins -v`
Expected: FAIL with `assert 103.x >= <authority stop>` (the deterministic giveback loosens it)

- [ ] **Step 3: Write the minimal implementation**

In `quant/execution/exits.py`, in the Rule 4b state-advance block, after `trail_stop` comes back from `check_trailing_stop`, clamp it so it can never loosen what the authority already set:

```python
            if trail_stop is not None:
                if tr is None:
                    tr = _Trail()
                    self._trail[position._id] = tr
                elif tr.active and tr.stop is not None:
                    # Single trail authority: the TimesFM quantile ratchet owns
                    # the stop when a forecast is live. The deterministic
                    # candidate may only tighten it, never loosen it — two
                    # parallel stores produced a first-writer-wins stop.
                    trail_stop = (
                        max(float(trail_stop), float(tr.stop)) if long
                        else min(float(trail_stop), float(tr.stop))
                    )
                tr.active = True
                tr.stop = trail_stop
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/ tests/quant/decision/test_timesfm_risk.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quant/execution/exits.py tests/quant/execution/test_exits_trailing.py
git commit -m "fix: make the TimesFM ratchet the single trail authority

ExitEngine._trail and TimesFMRiskAuthority._trail_stops were parallel stores
for one position. The deterministic candidate could propose a looser stop than
the authority had already set on the same bar. The deterministic path may now
only tighten."
```

---

## Task 11: D-17 — `LLM_ADVISOR_ENABLED` must mean one thing

**Files:**
- Modify: `backend/app/application/di/composition_root.py:162-165`
- Test: `backend/tests/unit/application/test_composition_root.py` (append; create if absent)

**Interfaces:**
- Consumes: `build_live_advisor(emit_fn)` semantics from `quant/wiring_advisor.py:67-72` (it is the advisor authority).
- Produces: `coord_config["advisor_enabled"]` is True **only** if the advisor factory would actually build one.

- [ ] **Step 1: Write the failing test**

Create/append `backend/tests/unit/application/test_composition_root.py`:

```python
def test_advisor_enabled_matches_the_factory(monkeypatch):
    """D-17: composition_root treated LLM_ADVISOR_ENABLED as an OR-enable while
    wiring_advisor treats it as a hard disable, so the two disagreed about
    whether an advisor exists."""
    import os

    monkeypatch.setenv("LLM_ADVISOR_ENABLED", "false")
    monkeypatch.setenv("TIMESFM_ADVISOR_ENABLED", "true")

    from app.application.di.composition_root import _advisor_enabled_from_env

    assert _advisor_enabled_from_env() is False


def test_advisor_enabled_true_only_when_factory_would_build(monkeypatch):
    monkeypatch.setenv("LLM_ADVISOR_ENABLED", "true")
    monkeypatch.setenv("TIMESFM_ADVISOR_ENABLED", "false")

    from app.application.di.composition_root import _advisor_enabled_from_env

    assert _advisor_enabled_from_env() is True
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd backend && PYTHONPATH=..:. ../.venv/bin/python -m pytest tests/unit/application/test_composition_root.py -v`
Expected: FAIL with `ImportError: cannot import name '_advisor_enabled_from_env'`

- [ ] **Step 3: Write the minimal implementation**

In `backend/app/application/di/composition_root.py`, add a module-level helper above `_coordinator_config`:

```python
def _advisor_enabled_from_env() -> bool:
    """Whether an advisor would actually be built.

    This must mirror ``quant.wiring_advisor.build_live_advisor`` exactly: that
    function hard-disables on LLM_ADVISOR_ENABLED=false BEFORE considering
    TimesFM. Composition previously treated the same flag as one arm of an
    OR-enable, so the coordinator recorded advisor_enabled=True while
    build_live_advisor returned None — the two disagreed about whether an
    advisor existed.
    """
    llm = os.getenv("LLM_ADVISOR_ENABLED", "false").strip().lower()
    if llm in ("0", "false", "no", "disable", "disabled"):
        return False
    return llm in ("true", "1", "yes") or (
        os.getenv("TIMESFM_ADVISOR_ENABLED", "false").strip().lower()
        in ("true", "1", "yes")
    )
```

Replace the inline expression:

```python
        "advisor_enabled": _advisor_enabled_from_env(),
```

- [ ] **Step 4: Run test to verify it passes**

Run: `cd backend && PYTHONPATH=..:. ../.venv/bin/python -m pytest tests/unit/application/test_composition_root.py -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add backend/app/application/di/composition_root.py backend/tests/unit/application/test_composition_root.py
git commit -m "fix: make advisor_enabled agree with the advisor factory

composition_root OR-enabled on LLM_ADVISOR_ENABLED while wiring_advisor
hard-disables on it, so LLM_ADVISOR_ENABLED=false + TIMESFM_ADVISOR_ENABLED=true
recorded advisor_enabled=True with no advisor built."
```

---

## Task 12: D-12 — sizing must refuse when the model path is unavailable

**Files:**
- Modify: `quant/execution/risk.py:333-392`
- Test: `tests/quant/execution/test_lot_aware_risk.py` (append)

**Interfaces:**
- Consumes: `forecast` (TimesFMForecast or None), `self._base_risk_pct`.
- Produces: when `forecast is not None` and model sizing raises, `position_size` returns `0.0` (refuse) rather than silently deploying a non-equivalent policy. Also: the forecast path now applies the expiry and day-of-week multipliers.

- [ ] **Step 1: Write the failing test**

Append to `tests/quant/execution/test_lot_aware_risk.py`:

```python
def test_model_sizing_failure_refuses_instead_of_deploying_50pct(monkeypatch):
    """D-12: a raising model-sizing call used to fall through to the flat
    50%-of-equity deployment branch — a structurally different, non-risk-
    equivalent policy — with only a warning."""
    from quant.execution.risk import SessionRisk

    risk = SessionRisk(storage=None, symbol="SYM", base_risk_pct=0.05)

    import quant.decision.timesfm_sizing as sz

    class _Boom:
        def compute_size(self, **_k):
            raise RuntimeError("empty p10_path")

    monkeypatch.setattr(sz, "TimesFMPositionSizer", lambda *a, **k: _Boom())

    class _Fc:
        forecast_steps = ["LONG"] * 32

    qty = risk.position_size(100.0, 99.0, lot_size=1.0, forecast=_Fc(), side="LONG")
    assert qty == 0.0


def test_forecast_path_applies_expiry_and_day_of_week_cuts():
    """D-12: the expiry halving and the Mon/Fri multiplier were applied only
    on the static branches, so they never applied on the E2E (forecast) path."""
    import numpy as np

    from quant.decision.timesfm_agents import TimesFMForecast
    from quant.execution.risk import SessionRisk

    p50 = np.linspace(100.0, 104.0, 32)
    fc = TimesFMForecast(
        horizon=32, p50_path=p50, p10_path=p50 - 1.0, p90_path=p50 + 1.0,
        q_spread=2.0, mean_forecast=float(p50[-1]), pct_change=0.04,
        forecast_steps=["LONG"] * 32, curr_price=100.0, lat_ms=1.0,
    )

    normal = SessionRisk(storage=None, symbol="SYM", day_of_week=2)   # Wednesday
    qty_normal = normal.position_size(100.0, 99.0, lot_size=1.0, forecast=fc, side="LONG")

    expiry = SessionRisk(storage=None, symbol="SYM", day_of_week=2)
    qty_expiry = expiry.position_size(100.0, 99.0, lot_size=1.0, forecast=fc,
                                      side="LONG", is_expiry=True)

    assert qty_expiry == pytest.approx(qty_normal * 0.5)

    monday = SessionRisk(storage=None, symbol="SYM", day_of_week=0)
    qty_monday = monday.position_size(100.0, 99.0, lot_size=1.0, forecast=fc, side="LONG")
    assert qty_monday == pytest.approx(qty_normal * 0.5)
```

Note on the fixtures: `day_of_week` and `storage` are keyword-only on `SessionRisk.__init__` (`quant/execution/risk.py:59-72`), so pass them by keyword. `day_of_week=None` (the default) resolves to `datetime.now(tz=IST).weekday()` inside the constructor — pinning it is what makes the Mon/Wed assertion deterministic.

Ensure `import pytest` is at the top of the file.

- [ ] **Step 2: Run tests to verify they fail**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/test_lot_aware_risk.py -k "refuses_instead or applies_expiry" -v`
Expected: first FAILS with `assert <large number> == 0.0`; second FAILS with `assert <qty> == approx(<qty*0.5>)`

- [ ] **Step 3: Write the minimal implementation**

In `quant/execution/risk.py`, replace the TimesFM branch's tail. The block currently ends with `return float(res.quantity)` inside the `try` and falls through to the static branches. Change it to:

```python
                    res = sizer.compute_size(
                        equity=sizing_equity,
                        entry=entry,
                        side=side,
                        forecast=forecast,
                        lot_size=lot_size,
                        override_sl=sl if sl > 0 else None,
                        is_aggressive=aggressive,
                        max_lots=max_lots,
                        max_rupee_risk_cap=max_rupee_risk_cap,
                    )
                    qty = float(res.quantity)
                    # The forecast path must honour the same protective cuts as
                    # the static branches: expiry halving and the Mon/Fri
                    # defensive multiplier. Applying them only below meant they
                    # silently did not apply on the E2E path.
                    if is_expiry:
                        qty *= 0.5
                    qty *= DAY_OF_WEEK_MULTIPLIER.get(self._day_of_week, 1.0)
                    if lot_size and lot_size > 1.0:
                        qty = float(int(qty // lot_size) * lot_size)
                    return qty
                except Exception as exc:
                    # Do NOT fall through to the static deployment policy: it is
                    # a structurally different, non-risk-equivalent size (it
                    # ignores max_rupee_risk_cap and sizes on notional). If the
                    # model path is unavailable, REFUSE the trade.
                    logger.error(
                        "TimesFM dynamic sizing failed (%s) — refusing entry "
                        "rather than switching to the deployment policy", exc,
                        exc_info=True,
                    )
                    return 0.0
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/test_lot_aware_risk.py tests/quant/execution/test_risk_persistence.py -q`
Expected: PASS

- [ ] **Step 5: Confirm the runtime skips a zero-size entry**

Read `quant/runtime.py` around the `if quantity <= 0:` guard and confirm it already blocks entry with a `SignalBlocked` latch. No change expected; record the confirmation in the commit body.

- [ ] **Step 6: Commit**

```bash
git add quant/execution/risk.py tests/quant/execution/test_lot_aware_risk.py
git commit -m "fix: refuse entry when model sizing fails; apply expiry/Mon-Fri on the forecast path

A raising TimesFM sizing call silently fell through to the flat
50%-of-equity deployment branch, which ignores max_rupee_risk_cap and sizes on
notional — not risk-equivalent to Kelly. The forecast path also skipped the
expiry halving and the Mon/Fri defensive multiplier, which were applied only
on the static branches."
```

---

## Task 12b: D-11 — one inference per bar

**Files:**
- Modify: `quant/decision/timesfm_engine.py` (expose the last forecast), `quant/strategies/timesfm_strategy.py:277-345`, `quant/decision/timesfm_advisor.py:203-233`
- Test: `tests/quant/strategies/test_timesfm_strategy.py` (append)

**Interfaces:**
- Consumes: `TimesFMEngine.add_context(ctx)` and the engine's own inference.
- Produces: `TimesFMEngine.analyze(ctx)` returns the payload built from a forecast it also exposes as `TimesFMEngine.last_forecast_for(symbol) -> TimesFMForecast | None`; `TimesFMTradingStrategy._compute_forecast` reuses that forecast for the same `bar_index` instead of calling `predict` again.

- [ ] **Step 1: Write the failing test**

Append to `tests/quant/strategies/test_timesfm_strategy.py`:

```python
def test_strategy_and_advisor_share_one_inference_per_bar(monkeypatch):
    """D-11: the advisor engine and the strategy each ran model.predict for the
    same bar, doubling latency and allowing the two payloads to disagree."""
    import numpy as np
    from unittest.mock import Mock

    import quant.decision.timesfm_engine as eng_mod
    from quant.bars import Bar
    from quant.decision.context import DecisionContext
    from quant.decision.timesfm_engine import TimesFMEngine
    from quant.strategies.timesfm_strategy import TimesFMTradingStrategy

    horizon = 8
    p50 = np.linspace(100.0, 103.0, horizon, dtype=np.float32)
    q = np.zeros((horizon, 9), dtype=np.float32)
    q[:, 0] = p50 - 0.5
    q[:, 4] = p50
    q[:, 8] = p50 + 0.5
    fake = Mock()
    fake.predict.return_value = Mock(quantiles=q)

    engine = TimesFMEngine(target_horizon=horizon)
    original = eng_mod.get_timesfm_model
    eng_mod.get_timesfm_model = lambda *a, **k: fake
    try:
        strategy = TimesFMTradingStrategy(target_horizon=horizon, engine=engine)
        bar = Bar("2026-09-10T10:00:00+05:30", 100.0, 101.0, 99.0, 100.0, 100, 100)
        ctx = DecisionContext(symbol="NIFTY", bar=bar, bar_index=7,
                              session_open=True, warmup_complete=True,
                              session_phase="PRIMARY", poc=101.0, vah=101.5,
                              val=99.0, cvd_slope=1.0)
        engine.analyze(ctx)            # advisor consumer
        strategy.should_enter(ctx)     # decision consumer, same bar
    finally:
        eng_mod.get_timesfm_model = original

    assert fake.predict.call_count == 1, (
        f"expected one inference per bar, got {fake.predict.call_count}"
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/strategies/test_timesfm_strategy.py -k one_inference_per_bar -v`
Expected: FAIL with `expected one inference per bar, got 2`

- [ ] **Step 3: Write the minimal implementation**

In `quant/decision/timesfm_engine.py`, add a per-symbol forecast cache keyed by `bar_index`. In `__init__`:

```python
        # Forecast computed for a bar, keyed by symbol. The advisor and the E2E
        # strategy both need a forecast for the same bar; without this they each
        # ran model.predict, doubling latency and allowing the two payloads to
        # disagree on the very input the decision was made from.
        self._forecast_cache: Dict[str, Tuple[int, Any]] = {}
```

Add the accessor next to `is_healthy`:

```python
    def last_forecast_for(self, symbol: str) -> Optional[Any]:
        """Forecast computed for the current bar, or None."""
        entry = self._forecast_cache.get(str(symbol))
        return entry[1] if entry is not None else None
```

In `analyze`, after the forecast is constructed and before routing to the agents, store it:

```python
        self._forecast_cache[str(ctx.symbol or "UNKNOWN")] = (int(getattr(ctx, "bar_index", -1) or -1), forecast)
```

In `quant/strategies/timesfm_strategy.py::_compute_forecast`, reuse the engine's forecast for the same bar as the FIRST step:

```python
        bar_index = int(getattr(ctx, "bar_index", -1) or -1)
        cached = self._engine.last_forecast_for(str(ctx.symbol or "UNKNOWN"))
        if cached is not None and not self._forecast_provider:
            cached_bar = int(getattr(cached, "asof_bar", -1))
            # The advisor already inferred this bar — reuse it instead of paying
            # a second inference and risking a divergent payload.
            if cached_bar >= 0 and cached_bar == bar_index:
                return cached
```

Place this before the `if self._forecast_provider is not None:` branch so the provider path still wins when configured.

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/strategies/ tests/quant/decision/test_timesfm_engine.py -q`
Expected: PASS

- [ ] **Step 5: Record the residual**

Update `docs/PRE_RELEASE_READINESS_CHECKLIST.md` §4.4 row R2 to: `Resolved by Task 12b — one inference per bar; the advisor and the strategy share the engine's forecast for the current bar_index.` Then set the audit's D-11 status to fixed.

- [ ] **Step 6: Commit**

```bash
git add quant/decision/timesfm_engine.py quant/strategies/timesfm_strategy.py tests/quant/strategies/test_timesfm_strategy.py docs/PRE_RELEASE_READINESS_CHECKLIST.md
git commit -m "perf: one TimesFM inference per bar shared by advisor and strategy

The advisor engine and the E2E strategy each called model.predict for the same
bar, doubling latency and allowing the two payloads to disagree. The engine now
caches the bar's forecast and the strategy reuses it."
```

---

# WAVE 3 — Single canonical owners

## Task 13: D-18 — one forecast factory, with the quantile contract checked

**Files:**
- Create: `quant/decision/timesfm_forecast_factory.py`
- Modify: `quant/multi_engine.py:1450-1481`, `quant/amt/session/scanner.py:460-495`, `quant/strategies/timesfm_strategy.py:301-342`, `quant/decision/timesfm_engine.py:354-383`
- Test: `tests/quant/decision/test_timesfm_forecast_factory.py` (create)

**Interfaces:**
- Produces: `build_forecast(quantiles, curr_price, horizon, lat_ms, *, vah=None, val=None) -> TimesFMForecast`, and `QUANTILE_COUNT = 9`, `P10_INDEX = 0`, `P50_INDEX = 4`, `P90_INDEX = 8`.

- [ ] **Step 1: Write the failing test**

Create `tests/quant/decision/test_timesfm_forecast_factory.py`:

```python
"""D-18: one owner for the quantile -> TimesFMForecast conversion."""

import numpy as np
import pytest

from quant.decision.timesfm_forecast_factory import (
    P10_INDEX,
    P50_INDEX,
    P90_INDEX,
    QUANTILE_COUNT,
    build_forecast,
)


def test_contract_constants():
    assert (P10_INDEX, P50_INDEX, P90_INDEX, QUANTILE_COUNT) == (0, 4, 8, 9)


def test_builds_from_quantiles():
    horizon = 4
    q = np.zeros((horizon, QUANTILE_COUNT), dtype=np.float32)
    q[:, P10_INDEX] = 99.0
    q[:, P50_INDEX] = 100.0
    q[:, P90_INDEX] = 101.0

    fc = build_forecast(q, curr_price=100.0, horizon=horizon, lat_ms=2.0)
    assert fc.p50_path.shape == (horizon,)
    assert fc.p10_path[0] == pytest.approx(99.0)
    assert fc.q_spread == pytest.approx(2.0)
    assert fc.mean_forecast == pytest.approx(100.0)


def test_rejects_a_quantile_count_it_does_not_understand():
    """The (H, 9) contract was asserted by comment in four places and checked
    nowhere; a model change would silently corrupt every consumer."""
    q = np.zeros((4, 3), dtype=np.float32)
    with pytest.raises(ValueError, match="expected 9 quantiles"):
        build_forecast(q, curr_price=100.0, horizon=4, lat_ms=1.0)


def test_degenerate_quantiles_fall_back_to_a_flat_path():
    fc = build_forecast(None, curr_price=100.0, horizon=4, lat_ms=1.0)
    assert np.allclose(fc.p50_path, 100.0)
    assert fc.q_spread == 0.0
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_timesfm_forecast_factory.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'quant.decision.timesfm_forecast_factory'`

- [ ] **Step 3: Write the implementation**

Create `quant/decision/timesfm_forecast_factory.py`:

```python
"""The single owner of the quantile -> TimesFMForecast conversion.

Four sites built this independently (multi_engine, amt/session/scanner, the E2E
strategy and the native engine), each asserting the ``(H, 9)`` quantile-index
contract in a comment and checking it nowhere. A model whose quantile count
changed would have silently corrupted every consumer.
"""

from __future__ import annotations

from typing import Any, List, Optional

import numpy as np

from quant.decision.timesfm_agents import TimesFMForecast

# TimesFM 3.0 returns (horizon, 9) quantiles. These indices are the contract.
QUANTILE_COUNT = 9
P10_INDEX = 0
P50_INDEX = 4
P90_INDEX = 8

# Degenerate-forecast fallback: a flat path bracketed by +/-0.2%. Named once so
# the four former copies cannot drift apart again.
FALLBACK_BAND_PCT = 0.002


def make_steps(p50_path, curr_price: float) -> List[str]:
    """Per-step direction labels. FLAT exists, so consumers may test for it."""
    return [
        "LONG" if float(p) > curr_price else ("SHORT" if float(p) < curr_price else "FLAT")
        for p in p50_path
    ]


def build_forecast(
    quantiles: Optional[Any],
    curr_price: float,
    horizon: int,
    lat_ms: float,
    *,
    vah: Optional[float] = None,
    val: Optional[float] = None,
) -> TimesFMForecast:
    """Convert raw model quantiles into the shared forecast object.

    ``quantiles`` None (inference unavailable) yields a flat fallback path.
    A present-but-wrong shape raises: silently guessing the index layout is how
    a model upgrade corrupts every downstream consumer at once.
    """
    curr_price = float(curr_price)

    if quantiles is None or len(quantiles) == 0:
        p50 = np.full(horizon, curr_price, dtype=np.float32)
        p10 = p50 - (curr_price * FALLBACK_BAND_PCT)
        p90 = p50 + (curr_price * FALLBACK_BAND_PCT)
        q_spread = 0.0
    else:
        q = np.asarray(quantiles)
        if q.ndim != 2 or q.shape[1] != QUANTILE_COUNT:
            raise ValueError(
                f"expected {QUANTILE_COUNT} quantiles per step, got shape {q.shape}"
            )
        # A step-by-step band when vah/val are supplied, quantile indices
        # otherwise: both are the same contract, read once here.
        p50 = q[:, P50_INDEX].astype(np.float32)
        p10 = q[:, P10_INDEX].astype(np.float32)
        p90 = q[:, P90_INDEX].astype(np.float32)
        q_spread = float(np.mean(p90 - p10))

    mean_forecast = float(p50[-1])
    pct_change = (mean_forecast - curr_price) / max(curr_price, 1e-4)

    return TimesFMForecast(
        horizon=horizon,
        p50_path=p50,
        p10_path=p10,
        p90_path=p90,
        q_spread=q_spread,
        mean_forecast=mean_forecast,
        pct_change=pct_change,
        forecast_steps=make_steps(p50, curr_price),
        curr_price=curr_price,
        lat_ms=float(lat_ms),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_timesfm_forecast_factory.py -v`
Expected: PASS

- [ ] **Step 5: Replace the four call sites**

Replace each hand-rolled block with `build_forecast`:

- `quant/multi_engine.py:1450-1481` → `forecasts[root] = build_forecast(quantiles, curr_price, 32, 5.0)`
- `quant/amt/session/scanner.py:460-495` → `forecast = build_forecast(quantiles, curr_price, 32, lat_ms)`
- `quant/strategies/timesfm_strategy.py:301-342` → `return build_forecast(quantiles, curr_price, self.target_horizon, lat_ms)` (keep the provider branch above it)
- `quant/decision/timesfm_engine.py:354-383` → `build_forecast(quantiles, curr_price, self.target_horizon, lat_ms, vah=vah, val=val)`

Delete the now-unused local `p50/p10/p90/q_spread/forecast_steps` temporaries in each. For `timesfm_engine.py`, note the engine previously derived `forecast_steps` from `vah`/`val` bands rather than a mid-price comparison — `build_forecast` uses the mid comparison for `forecast_steps` in all cases, which is the strategy's semantics. Update the engine test that asserted band semantics if one exists (grep `forecast_steps` under `tests/quant/decision/test_timesfm_engine.py`) and record the change in the commit body.

- [ ] **Step 6: Run the affected suites**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/ tests/quant/strategies/ tests/quant/test_multi_engine_startup.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add quant/decision/timesfm_forecast_factory.py tests/quant/decision/test_timesfm_forecast_factory.py quant/multi_engine.py quant/amt/session/scanner.py quant/strategies/timesfm_strategy.py quant/decision/timesfm_engine.py
git commit -m "refactor: one forecast factory owns the quantile contract

The (H, 9) quantile-index contract was asserted by comment in four builders and
checked nowhere. It now has one owner that validates the shape, and the four
fallback constants that had already drifted (\`0.998/1.002\` vs
\`+/-curr_price*0.002\`) are one named constant."
```

---

## Task 14: D-19 — one `forecast_steps` rule

**Files:**
- Modify: any remaining producer after Task 13
- Test: `tests/quant/decision/test_timesfm_forecast_factory.py` (append)

**Interfaces:**
- Consumes: `make_steps(p50_path, curr_price)` from Task 13.
- Produces: every `TimesFMForecast` in the repo has FLAT-aware steps.

- [ ] **Step 1: Write the failing test**

Append to `tests/quant/decision/test_timesfm_forecast_factory.py`:

```python
def test_steps_are_flat_aware():
    from quant.decision.timesfm_forecast_factory import make_steps

    steps = make_steps([99.0, 100.0, 101.0], curr_price=100.0)
    assert steps == ["SHORT", "FLAT", "LONG"]


def test_no_producer_emits_binary_only_steps():
    """Every TimesFMForecast construction must go through the factory, so no
    site can emit a LONG/SHORT-only series that consumers cannot test for."""
    import pathlib
    import re

    root = pathlib.Path("quant")
    offenders = []
    for path in root.rglob("*.py"):
        if path.name == "timesfm_forecast_factory.py":
            continue
        text = path.read_text(encoding="utf-8")
        for m in re.finditer(r'"LONG" if p > curr_price else "SHORT"', text):
            offenders.append(f"{path}:{text[:m.start()].count(chr(10)) + 1}")
    assert not offenders, f"binary-only step labels remain: {offenders}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_timesfm_forecast_factory.py -k "flat_aware or binary_only" -v`
Expected: `test_steps_are_flat_aware` PASSES; `test_no_producer_emits_binary_only_steps` FAILS listing any file Task 13 missed.

- [ ] **Step 3: Fix any remaining producer**

For each offender the test names, route it through `build_forecast` or `make_steps`. If none remain, the test passes as-is.

- [ ] **Step 4: Run and commit**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_timesfm_forecast_factory.py -v`
Expected: PASS

```bash
git add -A quant tests/quant/decision/test_timesfm_forecast_factory.py
git commit -m "refactor: one forecast_steps rule, FLAT-aware everywhere"
```

---

## Task 15: D-20/D-21/D-22 — one vocabulary module

**Files:**
- Create: `quant/contracts/vocabulary.py`
- Modify: `quant/decision/context_builder.py:121,218`, `quant/decision/timesfm_engine.py:434`, `quant/position_manager.py:538`, `quant/decision/timesfm_agents.py:501`, `quant/amt/session/selector.py:478`, `quant/runtime.py:1276`, `backend/app/infrastructure/adapters/_dhan_common.py:66`, `quant/amt/analyzer.py:350`, `quant/decision/timesfm_agents.py:59,69,74,254`, `quant/llm/narrative.py:238`
- Test: `tests/quant/contracts/test_vocabulary.py` (create)

**Interfaces:**
- Produces: `absorption_direction(side: str) -> str | None`, `is_call_symbol(symbol) -> bool`, `is_put_symbol(symbol) -> bool`, `is_opening_phase(phase) -> bool`, `is_closing_phase(phase) -> bool`.

- [ ] **Step 1: Write the failing test**

Create `tests/quant/contracts/test_vocabulary.py`:

```python
"""D-20/21/22: one owner for the repeated domain vocabulary."""

from quant.contracts.vocabulary import (
    absorption_direction,
    is_call_symbol,
    is_closing_phase,
    is_opening_phase,
    is_put_symbol,
)


def test_absorption_direction_canonical_semantics():
    assert absorption_direction("SELL_ABSORBED") == "LONG"
    assert absorption_direction("BUY_ABSORBED") == "SHORT"
    # Legacy bare forms keep working (the DTO now sends _ABSORBED).
    assert absorption_direction("SELL") == "LONG"
    assert absorption_direction("BUY") == "SHORT"
    assert absorption_direction("") is None


def test_option_kind_is_gated_on_being_an_option():
    assert is_call_symbol("NIFTY 24600 CALL")
    assert is_call_symbol("NIFTY24600CE")
    assert not is_call_symbol("CRUDEOILM 17 AUG FUT")
    assert is_put_symbol("NIFTY 24600 PUT")
    assert is_put_symbol("NIFTY24600PE")
    # A futures root that merely ends in CE must not classify as a call.
    assert not is_call_symbol("SOMECE")


def test_session_phase_classification_is_single_valued():
    assert is_opening_phase("NSE_OPENING")
    assert is_opening_phase("PRE_MARKET")
    assert not is_opening_phase("NSE_PRIMARY")
    assert is_closing_phase("NSE_CLOSE")
    assert is_closing_phase("POST_MARKET")
    assert not is_closing_phase("NSE_PRIMARY")
    # PRE_MARKET is opening noise, NOT a close — the two sets must not overlap.
    assert not is_closing_phase("PRE_MARKET")
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/contracts/test_vocabulary.py -v`
Expected: FAIL with `ModuleNotFoundError: No module named 'quant.contracts.vocabulary'`

- [ ] **Step 3: Write the implementation**

Create `quant/contracts/vocabulary.py`:

```python
"""Canonical domain vocabulary.

These mappings were re-derived at five to six sites each, and had already begun
to drift: the session-phase "opening" set omitted PRE_MARKET in one copy, and
the option-kind test was not gated on ``is_option_contract`` in another. One
owner, one meaning.
"""

from __future__ import annotations

from quant.contracts.instrument_registry import is_option_contract

# Absorption semantics (Fabio AMT): absorbed sellers are bullish, absorbed
# buyers are bearish.
_SELL_ABSORBED = ("SELL_ABSORBED", "SELL")
_BUY_ABSORBED = ("BUY_ABSORBED", "BUY")

# Session phases. Opening noise and close protection are DISJOINT: membership in
# one must never imply the other.
_OPENING_PHASES = ("OPENING", "PRE_OPEN", "PRE_MARKET")
_CLOSING_PHASES = ("CLOSE", "POST_MARKET", "EOD")


def absorption_direction(absorption_side: str) -> str | None:
    """Direction implied by an absorption print, or None when unrecognised."""
    text = str(absorption_side or "").upper()
    if not text:
        return None
    if any(tag in text for tag in _SELL_ABSORBED):
        return "LONG"
    if any(tag in text for tag in _BUY_ABSORBED):
        return "SHORT"
    return None


def is_call_symbol(symbol) -> bool:
    """True only for a CALL/CE option instrument (never a bare futures root)."""
    text = str(symbol or "").upper().rstrip()
    return is_option_contract(symbol) and text.endswith(("CALL", "CE", "-CE"))


def is_put_symbol(symbol) -> bool:
    """True only for a PUT/PE option instrument."""
    text = str(symbol or "").upper().rstrip()
    return is_option_contract(symbol) and text.endswith(("PUT", "PE", "-PE"))


def is_opening_phase(phase) -> bool:
    """True during opening-noise phases (no fresh entries)."""
    return any(tag in str(phase or "").upper() for tag in _OPENING_PHASES)


def is_closing_phase(phase) -> bool:
    """True during close-protection phases (flatten, no fresh entries)."""
    return any(tag in str(phase or "").upper() for tag in _CLOSING_PHASES)
```

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/contracts/test_vocabulary.py -v`
Expected: PASS

- [ ] **Step 5: Replace every duplicate**

- `quant/decision/context_builder.py:121` → `return absorption_direction(amt_dto.get("absorptionSide"))`
- `quant/decision/context_builder.py:218` → `direction = absorption_direction(amt_dto.get("absorptionSide"))`
- `quant/decision/timesfm_engine.py:434-437` → `direction = absorption_direction(absorption) or "FLAT"`
- `quant/decision/timesfm_agents.py:501` → `absorption_direction(absorption) not in (None, side)`
- `quant/position_manager.py:538-541` → compare against `absorption_direction(absorption_side)`
- `quant/amt/session/selector.py:478-482`, `quant/runtime.py:1276-1281`, `backend/app/infrastructure/adapters/_dhan_common.py:66`, `quant/amt/analyzer.py:350` → `is_call_symbol` / `is_put_symbol`
- Session-phase checks at `quant/decision/timesfm_agents.py:59,69,74,254`, `quant/decision/timesfm_engine.py:301`, `quant/llm/narrative.py:238` → `is_opening_phase` / `is_closing_phase`

Note: `_dhan_common.py` and `analyzer.py`'s versions were NOT gated on `is_option_contract` and used a different regex; the canonical helper is stricter. Run `backend/tests/` and `tests/quant/amt/` after and fix any symbol that now classifies differently — that change is the point of the task, so assert the new behaviour in the failing test above rather than preserving the old.

- [ ] **Step 6: Run the affected suites**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/ backend/tests/unit/infrastructure/ -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add quant/contracts/vocabulary.py tests/quant/contracts/test_vocabulary.py quant backend/app
git commit -m "refactor: one owner for absorption, option-kind and session-phase vocabulary

Absorption direction was re-derived at five sites, the option CALL/CE test at
four (one ungated with a different regex) and the session-phase substring
check at six (one copy had already dropped PRE_MARKET)."
```

---

## Task 16: D-23 — one settings authority for the scanner knobs

**Files:**
- Modify: `quant/amt/session/scanner_config.py:38-62`
- Test: `tests/quant/amt/test_scanner_config.py` (append; create if absent)

**Interfaces:**
- Produces: `ScannerConfig.from_env()` is removed; `ScannerConfig.from_settings(settings)` is the only constructor, and it reads every knob through the settings adapter.

- [ ] **Step 1: Write the failing test**

Create/append `tests/quant/amt/test_scanner_config.py`:

```python
def test_scanner_config_has_one_construction_path():
    """D-23: from_env and from_settings read the same vars with different
    defaults (SCANNER_TOP_N was 4, 4 and 8 across three authorities)."""
    from quant.amt.session import scanner_config

    assert not hasattr(scanner_config.ScannerConfig, "from_env"), (
        "from_env duplicates the settings adapter and must be removed"
    )


def test_top_n_has_a_single_default(monkeypatch):
    from types import SimpleNamespace
    from quant.amt.session.scanner_config import ScannerConfig

    settings = SimpleNamespace(
        SCANNER_TOP_N=None, SCANNER_UNDERLYINGS=None, SCANNER_OPTION_TYPE=None,
        SCANNER_EXPIRY_INDEX=None, STRIKES_AROUND_ATM=None,
    )
    cfg = ScannerConfig.from_settings(settings)
    assert cfg.top_n == ScannerConfig.DEFAULT_TOP_N
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt/test_scanner_config.py -v`
Expected: FAIL with `assert False` on `from_env` presence

- [ ] **Step 3: Write the minimal implementation**

In `quant/amt/session/scanner_config.py`, add the default as a class attribute:

```python
    DEFAULT_TOP_N: int = 8
```

Delete the whole `from_env` classmethod. Grep for its callers (`grep -rn "from_env()" quant backend/app tests`) and point each at `from_settings(<the settings singleton>  )`; where a caller has no settings object, pass `None` and let the field defaults apply.

In `from_settings`, replace each `settings.X` read with a defaulted access:

```python
        top_n = int(getattr(settings, "SCANNER_TOP_N", None) or cls.DEFAULT_TOP_N)
        underlyings = _split_underlyings(
            getattr(settings, "SCANNER_UNDERLYINGS", None) or DEFAULT_UNDERLYINGS
        )
        option_type = getattr(settings, "SCANNER_OPTION_TYPE", "") or ""
        expiry_index = int(getattr(settings, "SCANNER_EXPIRY_INDEX", None) or 0)
        strikes_around_atm = int(getattr(settings, "STRIKES_AROUND_ATM", None) or 2)
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt/test_scanner_config.py tests/quant/test_multi_engine_startup.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add quant/amt/session/scanner_config.py tests/quant/amt/test_scanner_config.py
git commit -m "refactor: one settings authority for the scanner knobs

from_env read the same env vars as from_settings with different defaults
(SCANNER_TOP_N resolved to 4, 4 or 8 depending on the construction path)."
```

---

# WAVE 4 — Dead code, smells, cleanliness

## Task 17: D-24 — remove silent exception swallowing on live paths

**Files:**
- Modify: `quant/decision/context_builder.py:347,351`, `quant/execution/exits.py` (done in Task 1), `quant/runtime.py:565,571,587,996,1160,1348,1517`, `quant/execution/live_oms.py:139,223,447`, `quant/multi_engine.py:590,663,1434,1446,1545,1600,1652,1766,1890`, `quant/amt/analyzer.py:454,1047`, `quant/persistence.py:85`, `quant/amt_engine.py:342`, `quant/decision/timesfm_advisor.py:185,252`
- Test: `tests/architecture/test_no_silent_except_pass.py` (create)

**Interfaces:**
- Produces: no `except Exception: pass` remains in `quant/`; every handler logs at `debug` or above, or carries an inline `# noqa: silent-except - <reason>` comment when silence is genuinely correct.

- [ ] **Step 1: Write the failing test**

Create `tests/architecture/test_no_silent_except_pass.py`:

```python
"""D-24: a swallowed exception must be a deliberate, annotated choice."""

import ast
import pathlib

QUANT = pathlib.Path(__file__).resolve().parents[2] / "quant"


def test_no_unannotated_silent_except_pass_in_quant():
    offenders = []
    for path in QUANT.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        tree = ast.parse(source)
        lines = source.splitlines()
        for node in ast.walk(tree):
            if not isinstance(node, ast.ExceptHandler):
                continue
            if len(node.body) != 1 or not isinstance(node.body[0], ast.Pass):
                continue
            handler_line = lines[node.lineno - 1]
            if "silent-except" in handler_line:
                continue
            offenders.append(f"{path.relative_to(QUANT.parent)}:{node.lineno}")
    assert not offenders, (
        "silent `except: pass` without a `# silent-except - <reason>` marker:\n  "
        + "\n  ".join(offenders)
    )
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/architecture/test_no_silent_except_pass.py -v`
Expected: FAIL listing ~45 locations

- [ ] **Step 3: Resolve each location**

For every location the test lists, apply exactly one of:

(a) **It should not be silent** — add a log at the appropriate level. Example for `quant/decision/context_builder.py:347`:

```python
            try:
                session_info = get_session_info(effective_time, market=market)
            except Exception:
                logger.warning(
                    "session-info resolution failed for %r (market=%s) — "
                    "falling back to PRIMARY phase", effective_time, market,
                    exc_info=True,
                )
```

(b) **Silence is genuinely correct** — annotate the handler line:

```python
            except Exception:  # silent-except - best-effort cert trace, never blocks trading
                pass
```

Work file by file. For the hot-path files (`live_oms.py`, `runtime.py`) prefer (a) at `warning`; for purely diagnostic paths (`hotpath`, cert traces, `_cert_trace`) prefer (b). Confirm `logger` exists in each module before using it.

- [ ] **Step 4: Run test to verify it passes**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/architecture/ -v`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add -A quant tests/architecture/test_no_silent_except_pass.py
git commit -m "refactor: make every swallowed exception deliberate and visible

47 bare except-pass blocks hid failures on live paths (session-info
resolution feeding session_phase, LiveOMS order/audit state, engine init).
Each now logs, or carries an explicit silent-except marker with its reason."
```

---

## Task 18: D-25 — split the two live decision monoliths

**Files:**
- Modify: `quant/runtime.py:861` (`_decide`, 318 lines), `quant/decision/timesfm_agents.py:93` (`evaluate`, 324 lines)
- Test: existing suites must stay green (characterization by the existing tests)

**Interfaces:**
- Produces: `_decide` delegates to `_entry_guards()`, `_build_decision()`, `_translate_and_submit()`, `_apply_risk_ceilings()`; `TimesFMScanningAgent.evaluate` delegates setup detection to `_detect_setup()` and sizing to `_dynamic_sizing()`. No public signature changes.

- [ ] **Step 1: Capture the current behaviour as golden traces**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/runtime/test_decide_golden.py tests/quant/decision/test_timesfm_agents.py -q`
Expected: PASS — this is the before-snapshot. Record the pass counts in the commit body.

- [ ] **Step 2: Extract `_decide` in four moves**

Each move is a pure extraction (no behaviour change), verified by re-running the golden test after each:

1. Move the cooldown + risk-halt + debounce block (currently the first ~80 lines) into `def _entry_guards(self, bar) -> QuantDecision | None:` returning the blocking decision or None.
2. Move context build + `should_enter` + the option-translation block into `def _build_decision(self, bar, amt_dto, execution_bar) -> QuantDecision`.
3. Move the sizing + portfolio-ceiling + OMS-submit block into `def _translate_and_submit(self, decision, bar) -> bool`.
4. Leave `_decide` as the orchestrator calling the three, plus the cert-record and emit steps.

- [ ] **Step 3: Extract the scanner's setup detection**

In `quant/decision/timesfm_agents.py`, move the Setup A–E `if/elif` chain into:

```python
    def _detect_setup(self, ctx, forecast, *, curr_price, vah, val, poc,
                      cvd_slope, absorption, stacked_imb, allow_trend,
                      allow_reversion, is_option, symbol):
        """Return (action, direction, setup, confidence, confidence_score, rationale)."""
```

and the `dynamic_sizing` block into `_dynamic_sizing(ctx, forecast, direction, structural_target, curr_price)`. `evaluate` keeps the guards, the call, the 4-gate evaluation and the payload assembly.

- [ ] **Step 4: Verify behaviour is unchanged**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/runtime/ tests/quant/decision/ tests/quant/strategies/ -q`
Expected: PASS with the same counts as Step 1.

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/test_golden_tape.py tests/quant/test_golden_replay.py -q`
Expected: PASS (byte-identical traces)

- [ ] **Step 5: Commit**

```bash
git add quant/runtime.py quant/decision/timesfm_agents.py
git commit -m "refactor: decompose the two live decision monoliths

_decide was 318 lines and TimesFMScanningAgent.evaluate 324. Both are now thin
orchestrators over named phases. Pure extraction: golden traces byte-identical."
```

---

## Task 19: D-28 — name the duplicated literals

**Files:**
- Modify: `quant/decision/timesfm_agents.py:323,414`, `quant/decision/timesfm_client.py:115`, `quant/decision/context_builder.py`, `quant/decision/signal_builder.py:13`, `quant/execution/risk.py:18-24`, `quant/decision/timesfm_sizing.py:232`, `quant/contracts/constants.py`
- Test: `tests/architecture/test_no_drifting_literals.py` (create)

**Interfaces:**
- Produces: canonical constants in `quant/contracts/constants.py` (extend the existing module) and reuse of the existing `CONFIDENCE_HIGH_THRESHOLD`.

- [ ] **Step 1: Write the failing test**

Create `tests/architecture/test_no_drifting_literals.py`:

```python
"""D-28: the same numeral meant different things across modules."""

import pathlib
import re

QUANT = pathlib.Path(__file__).resolve().parents[2] / "quant"

PATTERNS = {
    "fallback equity literal": re.compile(r"\bor\s+100000\.0\b|\bor\s+200000\.0\b"),
    "binary forecast band": re.compile(r"0\.998|1\.002"),
    "hardcoded conviction threshold": re.compile(r"agent_probability\s*>=\s*0\.65"),
}


def test_no_drifting_literals():
    offenders = []
    for path in QUANT.rglob("*.py"):
        if path.name == "constants.py":
            continue
        text = path.read_text(encoding="utf-8")
        for label, pattern in PATTERNS.items():
            for m in pattern.finditer(text):
                line = text[: m.start()].count("\n") + 1
                offenders.append(f"{label}: {path.relative_to(QUANT.parent)}:{line}")
    assert not offenders, "\n  ".join(offenders)
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/architecture/test_no_drifting_literals.py -v`
Expected: FAIL listing the equity fallbacks, the `0.998/1.002` sites and the `0.65` site

- [ ] **Step 3: Add the canonical constants**

In `quant/contracts/constants.py` (extend the existing module; do NOT create a new one):

```python
# Equity fallback when a context carries none. Must be the canonical capital,
# never a local literal — the scanner used 100000 and the snapshot client
# 200000 while INITIAL_CAPITAL is 1000000.
FALLBACK_EQUITY = float(INITIAL_CAPITAL)

# Forecast fallback band for a degenerate quantile response (flat path +/- this
# fraction). One definition shared by every forecast builder.
FORECAST_FALLBACK_BAND_PCT = 0.002

# Leverage cap applied to notional in dynamic sizing.
MAX_NOTIONAL_LEVERAGE = 2.5
NOTIONAL_LEVERAGE_GUARD = 3.0
```

Import `INITIAL_CAPITAL` from `quant.contracts.aggregates` at the top of `constants.py` if it is not already present.

- [ ] **Step 4: Replace each site**

- `quant/decision/timesfm_agents.py:323` → `equity=float(getattr(ctx, "equity", None) or FALLBACK_EQUITY)`
- `quant/decision/timesfm_client.py:115` → `"equity": float(ctx.equity or FALLBACK_EQUITY)`
- `quant/decision/timesfm_sizing.py:232` → use `MAX_NOTIONAL_LEVERAGE` / `NOTIONAL_LEVERAGE_GUARD`
- `quant/decision/decision_service.py:73` → `>= CONFIDENCE_HIGH_THRESHOLD`
- The `0.998/1.002` sites were already collapsed by Task 13; if any remain, use `FORECAST_FALLBACK_BAND_PCT`.

- [ ] **Step 5: Run tests to verify they pass**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/architecture/ tests/quant/decision/ -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add -A quant tests/architecture/test_no_drifting_literals.py
git commit -m "refactor: name the duplicated literals

Three different equity fallbacks (100000 / 200000 / INITIAL_CAPITAL=1000000),
five copies of the 0.998/1.002 forecast band, and three hardcoded uses of an
existing CONFIDENCE_HIGH_THRESHOLD constant."
```

---

## Task 20: D-26/D-27 — untrack generated and throwaway artifacts

**Files:**
- Modify: `.gitignore`
- Remove from index: `backend/graphify-out/` (235 files), `.freebuff/`, `runtime_audit/`, `scratch/`, `.kilo/`, `.commandcode/`
- Test: `tests/architecture/test_repo_hygiene.py` (create)

**Interfaces:**
- Produces: no generated or throwaway path is tracked; the `/goal` script-gate is unaffected.

- [ ] **Step 1: Write the failing test**

Create `tests/architecture/test_repo_hygiene.py`:

```python
"""D-26/D-27: generated and throwaway paths must not be tracked."""

import subprocess

FORBIDDEN_PREFIXES = (
    "backend/graphify-out/",
    ".freebuff/",
    "runtime_audit/",
    "scratch/",
    ".kilo/",
    ".commandcode/",
    "quantv2/",
)


def _tracked():
    out = subprocess.run(["git", "ls-files"], capture_output=True, text=True,
                         check=True).stdout.splitlines()
    return out


def test_no_generated_or_throwaway_paths_are_tracked():
    offenders = [p for p in _tracked() if p.startswith(FORBIDDEN_PREFIXES)]
    assert not offenders, f"{len(offenders)} tracked artifact paths, e.g. {offenders[:5]}"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/architecture/test_repo_hygiene.py -v`
Expected: FAIL reporting 235+ tracked paths

- [ ] **Step 3: Update `.gitignore`**

Add to `.gitignore`:

```gitignore
# Generated graphify output at any depth (root and quant/ were already ignored)
**/graphify-out/

# Throwaway probe/bench/audit scripts — kept on disk, not in history
.freebuff/
runtime_audit/
scratch/
.kilo/
.commandcode/

# Orphaned bytecode for a removed source tree
quantv2/
```

- [ ] **Step 4: Untrack without deleting**

```bash
git rm -r --cached backend/graphify-out quantv2
git rm -r --cached .freebuff runtime_audit scratch .kilo .commandcode
```

Do NOT pass `-f` to a plain `rm` on these directories: the files stay on disk for the existing tooling that reads them.

- [ ] **Step 5: Verify nothing needed was untracked**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/architecture/ tests/quant/ -q`
Expected: PASS. If a test reads a fixture from one of these trees, move that fixture under `tests/fixtures/` and re-run.

Run: `git ls-files | grep -c graphify-out`
Expected: `0`

- [ ] **Step 6: Commit**

```bash
git add .gitignore tests/architecture/test_repo_hygiene.py
git commit -m "chore: untrack generated graphify output and throwaway script trees

235 generated files were committed under backend/graphify-out (~10 MB), while
the root and quant/ counterparts were correctly ignored. Also untracked
.freebuff/, runtime_audit/, scratch/, .kilo/ and .commandcode/, and the orphan
quantv2/ bytecode tree (62 .pyc, no source, no importers)."
```

---

## Task 21: D-24b — remove verified dead code

**Files:**
- Delete: `quant/execution/exit_rules.py::update_peak_profit` (`:111`), `::is_valid_rr` (`:234`), `quant/execution/exit_rules.py::update_excursions` (`:84`)
- Delete: `quant/runtime.py::_check_pyramid` (`:1525`)
- Delete: `quant/decision/timesfm_client.py` + `tests/quant/decision/test_timesfm_client.py`, OR wire it — decide by one question
- Modify: `quant/strategy.py` (make the Protocol enforced)
- Test: `tests/architecture/test_no_dead_exports.py` (create)

**Interfaces:**
- Produces: no unreferenced public function remains in the audited set.

- [ ] **Step 1: Decide the `timesfm_client` question, then act**

`timesfm_client.py` is unreachable because `TIMESFM_NATIVE` defaults to `true`. Choose one and record the choice in the commit body:

- **Remove** (recommended if no remote service is planned): delete the module and its test, and delete the `else:` branch in `quant/decision/timesfm_advisor.py:143-152` with it.
- **Keep**: mark the remote path as tested-by-contract in the module docstring and add a test that constructs `TimesFMAdvisor(use_native_engine=False)` so the branch is covered.

- [ ] **Step 2: Write the failing test**

Create `tests/architecture/test_no_dead_exports.py`:

```python
"""D-24: functions with no production caller are deleted, not left to rot."""

import subprocess

DEAD = [
    "update_peak_profit",
    "is_valid_rr",
]


def test_audited_dead_functions_are_gone():
    for name in DEAD:
        out = subprocess.run(
            ["grep", "-rn", f"def {name}", "quant"], capture_output=True, text=True
        )
        assert out.stdout.strip() == "", f"{name} still defined:\n{out.stdout}"
```

- [ ] **Step 3: Run test to verify it fails**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/architecture/test_no_dead_exports.py -v`
Expected: FAIL for both names

- [ ] **Step 4: Delete the dead code**

Delete `update_peak_profit`, `is_valid_rr` and `update_excursions` from `quant/execution/exit_rules.py` (confirm with `grep -rn` that only tests reference `update_excursions`; delete those test bodies too, or move the assertions inline into a test of the caller).

Delete `quant/runtime.py::_check_pyramid`; update `tests/quant/runtime/test_exit_golden.py` and `tests/quant/test_certification.py:292`, which assert its existence — replace those assertions with a call through `pm.check_pyramid` (the real path).

- [ ] **Step 5: Enforce the strategy Protocol**

In `quant/strategy.py`, decorate the protocol:

```python
from typing import Protocol, runtime_checkable

@runtime_checkable
class TradingStrategy(Protocol):
```

Add to `tests/architecture/test_no_dead_exports.py`:

```python
def test_strategies_satisfy_the_protocol():
    from quant.strategies.amt_scalping import AmtScalpingStrategy
    from quant.strategies.timesfm_strategy import TimesFMTradingStrategy
    from quant.strategy import TradingStrategy

    assert isinstance(AmtScalpingStrategy(), TradingStrategy)
    assert isinstance(TimesFMTradingStrategy(), TradingStrategy)
```

Run it; if `runtime_checkable` rejects a strategy for a signature mismatch, fix the strategy, not the test.

- [ ] **Step 6: Run the affected suites**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/ tests/architecture/ -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add -A quant tests
git commit -m "chore: delete verified dead code and enforce the strategy protocol

update_peak_profit and is_valid_rr had zero callers; update_excursions was
tests-only, so MAE/MFE tracking was never wired into the exit path;
runtime._check_pyramid was tests-only (pyramids run from manage_exit). The
TradingStrategy protocol is now runtime_checkable and asserted."
```

---

## Task 22: Final verification and gate close

**Files:**
- Modify: `docs/reviews/2026-09-10-pre-release-code-audit.md` (status column), `docs/PRE_RELEASE_READINESS_CHECKLIST.md` (§1, §4.3, §6)
- Test: the full release gate

- [ ] **Step 1: Run the full release gate**

Run: `PYTHONPATH=backend:. .venv/bin/python scripts/pre_release_decision_check.py`
Expected: exit code **0**, `N passed, 0 warned, 0 failed` with all four Wave 1 checks PASSing.

- [ ] **Step 2: Run the broad suites**

Run: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/ tests/architecture/ -q`
Expected: PASS

Run: `cd backend && PYTHONPATH=..:. ../.venv/bin/python -m pytest tests/ -q -m "not slow and not live"`
Expected: PASS

- [ ] **Step 3: Run the determinism battery**

Run: `make parity`
Expected: PASS (golden traces and journal-replay determinism unchanged)

- [ ] **Step 4: Re-run the two audit probes**

Run: `PYTHONPATH=backend:. .venv/bin/python scripts/audit_e2e_entry_probe.py`
Expected: `session_open=False`, `warmup_complete=False` and every non-PRIMARY phase still `blocked` (no regression); baseline still `APPROVED`.

Run: `PYTHONPATH=backend:. .venv/bin/python scripts/audit_engine_race_probe.py`
Expected: both cases now report `dedup held` (depth 1) — the D-10 reproduction is closed.

- [ ] **Step 5: Update the audit and checklist status**

- In `docs/reviews/2026-09-10-pre-release-code-audit.md`: mark D-2..D-28 fixed with the task number that closed each.
- In `docs/PRE_RELEASE_READINESS_CHECKLIST.md`: mark every §1 row Fixed, empty §4.3 (or move any deliberate residual to §4.4 with a reason), and fill the §6 automated rows with the observed result and date.

- [ ] **Step 6: Commit**

```bash
git add docs/reviews/2026-09-10-pre-release-code-audit.md docs/PRE_RELEASE_READINESS_CHECKLIST.md
git commit -m "docs: close the decision-integrity audit — all blocking defects fixed

Release gate exits 0; parity and the broad suites are green; both audit probes
now show the fixed behaviour."
```

---

## Self-Review

**Spec coverage.** Every audit defect maps to a task:

| Defect | Task | Defect | Task |
|---|---|---|---|
| D-2 silent model-exit | 1 | D-16 two trail stores | 10 |
| D-3 close bypass | 2 | D-17 advisor flag conflict | 11 |
| D-4 fabricated entry | 3 | D-12 sizing fallback | 12 |
| D-10 engine double-feed | 4 | D-11 two inferences | 12b |
| D-5 legLvn key | 5 | D-18/D-19 forecast builder | 13, 14 |
| D-6 option delta | 6 | D-20/21/22 vocabulary | 15 |
| D-7 three stop prices | 7 | D-23 env drift | 16 |
| D-13 bar/tick stop conflict | 8 | D-24 silent except | 17 |
| D-15 double-close guard | 9 | D-25 monoliths | 18 |
| | | D-26/D-27/D-28 + dead code | 19, 20, 21 |

D-1 (`_DETERMINISTIC_CONVICTION` / `_WARMUP_BARS` unused in `runtime.py`) is folded into Task 21's cleanup pass; add those two lines to its deletions.

**Ordering constraints.** Task 4 must land before Task 12b (12b reuses the engine's cached forecast, which Task 4 makes safe). Task 13 must land before Task 19 (19 depends on the band constant existing). Task 2 before Task 9 (both touch `_closed_ids` consumers). Task 20's `git rm --cached` must not run before Task 22's suites, which do not read those trees.

**Type consistency.** `build_forecast(quantiles, curr_price, horizon, lat_ms, *, vah, val)` is defined in Task 13 and called with exactly that signature in its four replacements. `_resolve_leg_lvn(amt_dto, close_px)` is defined and used in Task 5 only. `last_forecast_for(symbol) -> TimesFMForecast | None` is defined in Task 12b and consumed in the same task. `MODEL_RISK_FAILURES` and `ExitEngine.model_risk_failures` are both introduced in Task 1; only the module-level name is asserted in `scripts/pre_release_decision_check.py`.

**No placeholders.** Every code step carries the code to write; every test step carries the test; every run step carries the command and the expected result.
