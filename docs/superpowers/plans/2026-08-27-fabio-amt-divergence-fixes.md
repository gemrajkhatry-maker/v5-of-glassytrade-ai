# Fabio AMT Divergence Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close the highest-impact divergences found in the 2026-08-27 deep audit against Fabio Valentini's AMT methodology — rewire the dead squeeze setup, fix the A/R double-update corruption, enable flow-aware exits, and make risk sizing honor its own spec — with the smallest possible diffs.

**Architecture:** Deterministic 4-gate pipeline (`quant/decision/pipeline.py`) fed by event-driven AMT engine (`quant/amt_engine.py` → `quant/amt/analyzer.py`). Most fixes are WIRING between modules that already exist (per ponytail: no new math). Two are one-line deletions of buggy calls.

**Tech Stack:** Python 3.13, pytest, no new dependencies.

## Global Constraints

- Branch: `feature/fabio-amt-fixes`
- Run tests with repo venv: `.venv/bin/python -m pytest`
- No new abstractions/config knobs — hardcoded constants at point of use carry a `# ponytail:` comment naming the ceiling
- Every task ends green: `pytest tests/quant -x -q` must pass before commit
- Do NOT break scorecard items (CME two-row VA, POC tiebreak, bimodal override, 5-phase session, inside-cluster stops, cushion tiers)
- Keep diffs < ~100 lines per task; deletion preferred over addition

**Source audits:** full divergence report in session log; key dead-code map:

| Dead thing | Where |
|---|---|
| RegimeDetector (squeeze, Rule 11, follow-through) | `quant/amt/market/regime.py` — zero runtime callers |
| Gate 3 squeeze phantom fields | `gates_edge.py:83-87` reads `ctx.squeeze_detected/pullback_confirmed/absorption_cluster`; nothing sets them |
| A/R engine double update | `analyzer.py:504` AND `analyzer.py:699` |
| CVD kill disabled | `exits.py:48` default `inf`; nobody overrides (`runtime.py:224`, `amt_scalping.py:39`) |
| Tick-path TP full-close bypasses tiers | `position_manager.py:293-306` vs tiered `exits.py:155-163` |
| Expiry halving unused | `runtime.py:765-767` omits `is_expiry`; logic at `risk.py:261-262` |
| Uncapped cushion bonus | `risk.py:353-356` |
| Midday phase leak | `gates_session_position.py:18-38` only guards when `setup_evidence` present |

---

### Task 1: Fix Acceptance/Rejection double-update (corruption bug)

The engine's time-to-acceptance accrues **twice per bar** because `_ar_engine.update()` runs at both `analyzer.py:504` and `analyzer.py:699`; the second call sees dt≈0 and falls back to a 60s credit, halving the effective 120s threshold. One-line deletion.

**Files:**
- Modify: `quant/amt/analyzer.py:699` (delete)
- Test: `tests/quant/amt/market/test_acceptance_rejection.py` (backend: `backend/tests/unit/domain/` has an A/R test file too — grep)

**Interfaces:**
- Consumes: existing `ar_state` variable assigned at line 504
- Produces: unchanged dict shape; downstream line 889 (`ar_state["acceptance_above"]`) keeps working off the single assignment

- [ ] **Step 1: Read both call sites to confirm identical inputs**

Run: `sed -n '495,512p' quant/amt/analyzer.py && sed -n '692,705p' quant/amt/analyzer.py`
Confirm both pass `(current, vah, val, baseline_vol)` on the same candle within one `analyze()` invocation.

- [ ] **Step 2: Write failing test capturing time-doubling**

Append to `tests/quant/amt/market/test_acceptance_rejection.py`:

```python
def test_no_double_credit_within_single_bar():
    """Regression: analyzer called update twice per bar, crediting 60s fallback twice."""
    eng = AcceptanceRejectionEngine(threshold_seconds=120.0)
    # Simulate two .update() calls for the SAME timestamp (what analyzer did):
    c = _make_candle(close_above_vah=True, ts="2026-01-01T10:00:00")
    s1 = eng.update(c, vah=100.0, val=90.0, baseline_vol=1000)
    s2 = eng.update(c, vah=100.0, val=90.0, baseline_vol=1000)
    # Second call must not advance accumulated outside-time
    acc_after_1 = max(s1["above_seconds"], s1["below_seconds"])
    acc_after_2 = max(s2["above_seconds"], s2["below_seconds"])
    assert acc_after_2 == acc_after_1, "same-bar repeat must be a no-op"
```

(Adapt helpers `_make_candle`/field names to what the existing test file already defines — reuse its fixtures.)

- [ ] **Step 3: Run to see it fail**

Run: `.venv/bin/python -m pytest tests/quant/amt/market/test_acceptance_rejection.py::test_no_double_credit_within_single_bar -v`
Expected: FAIL (seconds advanced on second call)

- [ ] **Step 4: Minimal implementation — root cause in the shared function**

In `quant/amt/market/acceptance_rejection.py`, inside `update()` where dt is computed (lines ~81-88), add same-bar guard:

```python
if last_ts is not None and dt == 0:
    return self._state_snapshot()   # ponytail: same-bar repeat = no-op (fixes analyzer double-call)
```

(Do NOT special-case the caller; all callers benefit.)

- [ ] **Step 5: Verify**

Run: `.venv/bin/python -m pytest tests/quant/amt/market/test_acceptance_rejection.py tests/quant/amt/test_analyzer.py backend/tests/unit/domain/test_amt_analyzer.py -v`
Expected: PASS (if a test pinned the fast acceptance timing, update ITS expectation in this commit with a comment citing this regression test)

- [ ] **Step 6: Commit**

```bash
git add quant/amt/market/acceptance_rejection.py tests/quant/amt/market/test_acceptance_rejection.py
git commit -m "fix: A/R engine no-op on same-bar repeat (kills 2x acceptance-speed bug)"
```

---

### Task 2a: Wire squeeze detection into analyzer + DTO

`RegimeDetector.detect_squeeze()` (`regime.py:393`) is complete and tested but never instantiated. Feed its output through `AMTResult` → DTO so the decision layer can consume real data.

**Files:**
- Modify: `quant/amt/analyzer.py` (~line 282 `__init__`, ~line 865-890 result assembly)
- Modify: `quant/contracts/value_objects.py:~251` (AMTResult fields) — check actual AMTResult home with `grep -rn "class AMTResult" quant/`
- Modify: `quant/amt/dto.py:~101` (near `gapType`/`openingBias`)
- Test: `tests/quant/amt/test_analyzer.py`

**Interfaces:**
- Consumes: `RegimeDetector().detect_squeeze(data, amt_result) -> SqueezeSignal(direction, trapped_level, recovery_price)`
- Produces: DTO keys `squeezeDirection: str`, `squeezeTrappedLevel: float` (consumed by Task 2b)

- [ ] **Step 1: Failing test**

```python
def test_dto_exposes_squeeze_fields():
    dto = _build_dto_from_fixture("fixtures/squeeze_recovery.json")  # reuse existing fixture loader pattern in this file
    assert dto["squeezeDirection"] == "LONG"
    assert dto["squeezeTrappedLevel"] > 0
```

If no squeeze fixture exists, synthesize one inline: 25 bars compressing into VA, one bar low piercing VAL, last bar closing back above VAL — mirror the scenario already asserted in `tests/quant/amt/market/test_regime.py` for `detect_squeeze`.

- [ ] **Step 2: Run — expect FAIL** (`KeyError: 'squeezeDirection'`)

Run: `.venv/bin/python -m pytest tests/quant/amt/test_analyzer.py::test_dto_exposes_squeeze_fields -v`

- [ ] **Step 3: Wire it**

`analyzer.py` `__init__` (next to `self._drive_tracker` at :282):

```python
from quant.amt.market.regime import RegimeDetector  # top imports
...
self._regime = RegimeDetector()  # ponytail: wire-up only; detector math already existed
```

In `analyze()`, after value-area fields exist on `result` (before the DTO handoff, near :867):

```python
sq = self._regime.detect_squeeze(recent_data, result)
result.squeeze_direction = sq.direction if sq else ""
result.squeeze_trapped_level = sq.trapped_level if sq else 0.0
```

Add the two fields to `AMTResult` with defaults `""` / `0.0`. In `quant/amt/dto.py` next to `gapType` (:101):

```python
"squeezeDirection": getattr(r, "squeeze_direction", ""),
"squeezeTrappedLevel": float(getattr(r, "squeeze_trapped_level", 0.0)),
```

- [ ] **Step 4: Verify parity** — run `pytest tests/quant/amt/test_analyzer.py tests/quant/runtime/test_golden_runtime.py tests/quant/test_golden_file.py -v`. If golden digests change, inspect diff: ONLY additive DTO keys allowed; regenerate goldens intentionally and say so in the commit body.

- [ ] **Step 5: Commit**

```bash
git add quant/amt/analyzer.py quant/contracts/value_objects.py quant/amt/dto.py tests/quant/amt/test_analyzer.py
git commit -m "feat: run orphaned RegimeDetector squeeze scan, expose via DTO"
```

---

### Task 2b: Populate DecisionContext + unstick Gate 3 squeeze path

Gate 3 advertises "Fabio Playbook #4: squeeze breakout pullback" (`gates_edge.py:82-87`) but reads three phantom fields. Replace with the real ones and define pullback concretely (first retest of the trapped level — Fabio's entry-on-first-pullback-to-LVN, adapted to the trapped VA edge).

**Files:**
- Modify: `quant/decision/context.py` (DecisionContext dataclass fields)
- Modify: `quant/decision/context_builder.py` (~:373-385 where stacked/contested are set)
- Modify: `quant/decision/gates_edge.py:82-87`
- Test: `tests/quant/decision/test_squeeze_pullback.py` (exists! read it first — it may already encode expected behavior; align rather than fight)

**Interfaces:**
- Consumes: DTO keys from Task 2a
- Produces: `DecisionContext.squeeze_detected: bool`, `squeeze_direction: str = ""`, `squeeze_trapped_level: float = 0.0`, `pullback_confirmed: bool`

- [ ] **Step 1: Read existing test expectations**

Run: `cat tests/quant/decision/test_squeeze_pullback.py`
It was written against phantom fields (passes trivially). Rewrite its assertions to the real field names while keeping its scenario shapes.

- [ ] **Step 2: Failing test**

```python
def test_squeeze_long_pullback_passes_gate3():
    ctx = _base_ctx(direction="LONG", cvd_slope=0.3)
    ctx.squeeze_detected = True
    ctx.squeeze_direction = "LONG"
    ctx.squeeze_trapped_level = 100.0
    ctx.bar.close = 100.10          # retesting trapped level
    ctx.tick_size = 0.05            # 2 ticks away
    r = gate_triple_a_edge(ctx)
    assert r.passed and "Squeeze" in r.reason
```

(Mirror the ctx-construction helpers already used in `test_gate_triple_a_edge.py`.)

- [ ] **Step 3: Run — expect FAIL** (gate returns "No Triple-A edge")

- [ ] **Step 4: Implement**

`context_builder.py` alongside the stacked-imbalance population block:

```python
squeeze_dir = str(amt_dto.get("squeezeDirection", ""))
trapped_lvl = float(amt_dto.get("squeezeTrappedLevel", 0.0))
pullback = False
if squeeze_dir and trapped_lvl > 0 and bar is not None:
    tick = tick_size or 0.05
    pullback = abs(float(bar.close) - trapped_lvl) <= 3.0 * tick  # ponytail: retest proxy; proper LVN-pullback when leg_lvn lands near trapped level
```

…then pass all four values into the `DecisionContext(...)` constructor call.

`context.py`: add the four fields with defaults (`False, "", 0.0, False`).

`gates_edge.py` — replace lines 82-87:

```python
    # Fabio Playbook #4: trapped-volume squeeze -> enter on first retest of trapped level
    sq_dir = getattr(ctx, "squeeze_direction", "") or ""
    if sq_dir and ctx.agent_direction == sq_dir:
        trapped = float(getattr(ctx, "squeeze_trapped_level", 0.0) or 0.0)
        tick = (ctx.tick_size if ctx.tick_size and ctx.tick_size > 0 else 0.05)
        retested = ctx.bar and trapped > 0 and abs(float(ctx.bar.close) - trapped) <= 3.0 * tick
        if retested or getattr(ctx, "pullback_confirmed", False):
            if ctx.agent_direction == "LONG" and cvd_slope >= -0.1:
                return GateResult(3, True, f"Squeeze {sq_dir} retest @{trapped:.2f}")
            if ctx.agent_direction == "SHORT" and cvd_slope <= 0.1:
                return GateResult(3, True, f"Squeeze {sq_dir} retest @{trapped:.2f}")
```

(The old `absorption_cluster` condition disappears — it was never populated.)

- [ ] **Step 5: Full suite**

Run: `.venv/bin/python -m pytest tests/quant -x -q`
Expected: green

- [ ] **Step 6: Commit**

```bash
git add quant/decision/context.py quant/decision/context_builder.py quant/decision/gates_edge.py tests/quant/decision/test_squeeze_pullback.py
git commit -m "feat: Gate 3 squeeze path consumes real detector output (unblocks Playbook #4)"
```

---

### Task 3: Enable CVD thesis-invalidation exit

The only order-flow-aware exit ships permanently OFF (`cvd_kill_threshold=inf`, `exits.py:48`; wiring passes nothing, `runtime.py:224` + `amt_scalping.py:39`).

**Files:**
- Modify: `quant/runtime.py:224`
- Modify: `quant/strategies/amt_scalping.py:39`
- Test: extend `tests/quant/execution/test_exits.py`

**Interfaces:** `ExitEngine(time_stop_bars=..., cvd_kill_threshold=<float>)` — no signature changes.

- [ ] **Step 1: Read `check_cvd_kill`** (`exit_checks.py:35-41`) to confirm sign convention (long killed when `cvd_slope < -threshold`). Value chosen: `2.0` — symmetric to the proven `cvd_be_threshold`. `# ponytail: mirror BE constant; tune from journal replay later`.

- [ ] **Step 2: Failing wiring test**

In `tests/quant/runtime/test_runtime.py` (or new `test_exit_wiring.py`):

```python
def test_engine_wires_cvd_kill():
    eng = QuantEngine(**_minimal_kwargs())
    assert eng._exits.cvd_kill_threshold == 2.0
```

- [ ] **Step 3: FAIL**, then edit both call sites:

```python
ExitEngine(time_stop_bars=time_stop_bars, cvd_kill_threshold=2.0)
```

- [ ] **Step 4:** Update any test asserting default-inf remains default only for bare constructors (`test_exits.py:85-88` stays valid — do not change the default, only the wiring).

Run: `.venv/bin/python -m pytest tests/quant/execution tests/quant/runtime -q`

- [ ] **Step 5: Commit**

```bash
git commit -am "feat: enable CVD kill exit at threshold 2.0 in runtime + strategy"
```

---

### Task 4: Tick path honors TP tiers (stops silent 50/25/25 plan destruction)

An intrabar touch of `signal.tp` **full-closes** on the tick path (`position_manager.py:293-306`), bypassing the bar-path tiered booking (`50% → 25% → runner`, `exits.py:155-163`). Whichever fires first silently rewrites the trade plan.

**Files:**
- Modify: `quant/position_manager.py:292-306`
- Test: `tests/quant/runtime/test_tick_level_exits.py`

**Interfaces:**
- Consumes: `close_partial(position, qty, ExitDecision)` (position_manager.py:198-221), `self._exits._tp_tier` / `._breakeven` maps
- Produces: tick TP behavior identical in spirit to bar path

- [ ] **Step 1: Failing test**

```python
def test_tick_tp_touch_books_first_partial_not_full_close(pm, open_position):
    open_position.size = 4
    sig_tp = open_position.order.signal.tp
    out = pm.manage_tick_exit(open_position, tick_price=sig_tp, tick_time="12:00:00")
    assert pm._position is not None                      # still alive
    assert open_position.size == 2                       # half booked
    assert pm._exits._tp_tier[open_position._id] == 1    # tier armed
    assert pm._exits._breakeven[open_position._id] == pytest.approx(open_position.order.signal.entry)
```

And a companion: second TP touch books the rest (`size` → 0, position closed) — i.e., runner closes on direct TP tag like today.

- [ ] **Step 2: FAIL**, then implement in `position_manager.py` — replace both `reason = "TP"` branches with:

```python
elif sig_tp > 0 and tick_price >= sig_tp:  # (mirrored <= for shorts)
    return self._tick_tp_touch(position, float(tick_price), tick_time)
```

New helper below `manage_tick_exit`:

```python
def _tick_tp_touch(self, position, px: float, ts: str):
    """Bar-parity TP handling on the tick path: T1 books half + arms BE;
    T2 (runner tagged at TP) closes. Mirrors ExitEngine Rule 4."""
    tier = self._exits._tp_tier.get(position._id, 0)
    entry = float(position.order.signal.entry)
    dec = ExitDecision(True, f"TP{tier + 1}", px)
    if tier == 0 and position.size >= 2:
        half = position.size // 2
        kept = self.close_partial(position, half, dec)
        self._exits._tp_tier[position._id] = 1
        self._exits._breakeven[position._id] = entry   # same effect as exits.py:160-161
        return kept
    return self._execute_full_close(position, ExitDecision(True, "TP", px), ts)
```

Reuse whatever the bar path already calls so tiers/BE stay in ONE place if a shared method exists — prefer deleting duplication over this helper if `ExitEngine` exposes something callable per-tick.

- [ ] **Step 3:** `pytest tests/quant/runtime/test_tick_level_exits.py tests/quant/execution/test_pyramid_oms.py tests/system -q` — pyramid suites exercise close_partial bookkeeping heavily; expect green.

- [ ] **Step 4: Commit**

```bash
git commit -am "fix: tick-path TP books tiered partials + arms BE (bar/tick parity)"
```

---

### Task 5: Expiry-day risk halving reaches production

`SessionRisk.position_size(..., is_expiry=...)` halves risk (`risk.py:261-262`) but the live call site omits the flag (`runtime.py:765-767`). Gamma peaks on expiry — exactly when Fabio's most defensive rule must fire.

**Files:**
- Modify: `quant/runtime.py:765-767`
- Test: `tests/quant/execution/test_lot_aware_risk.py`

**Interfaces:** no signature changes — pass the flag the function already accepts.

- [ ] **Step 1: Locate expiry knowledge upstream.** `grep -n "is_expiry\|expiry_date" quant/runtime.py quant/position_manager.py quant/amt/session/selector.py | head -30`. PositionManager resolves contract expiry at :153-166; find whether runtime holds the selected option instrument (it does — `OptionSelector` produced the traded symbol). Reuse IT.

- [ ] **Step 2: Failing test**

```python
def test_position_size_halves_on_expiry_call_site(engine_with_expiry_option):
    # engine where selected contract expires today, sized normally would give N lots
    qty_expiry = engine.quantity_for_signal(signal)   # however runtime exposes sizing; if private,
    # call the internal path exactly as _decide does
    assert qty_expiry == pytest.approx(qty_normal / 2, absterr=1)  # lot-snapping slack
```

Write it against the public seam you found in Step 1; if sizing is only reachable privately, test `SessionRisk.position_size(entry, sl, lot_size=L, is_expiry=True)` is already covered (skip engine-level) and make Step 3's diff the test.

- [ ] **Step 3: Implement** — store the flag when the option is selected, then:

```python
quantity = clamp_quantity(
    self._risk.position_size(
        signal.entry, signal.sl, lot_size=self._oms.lot_size,
        is_expiry=self._contract_is_expiry,
    )
)
```

(`self._contract_is_expiry` set wherever selector picks the strike — one assignment.)

- [ ] **Step 4:** `pytest tests/quant/execution/test_risk.py tests/quant/runtime -q`

- [ ] **Step 5: Commit**

```bash
git commit -am "fix: pass is_expiry into position sizing — activate expiry-day risk halving"
```

---

### Task 6: Cap the house-money bonus (spec §12.2 envelope)

Cushion bonus compounds uncapped (`risk.py:353-356`). Fabio's protocol: total per-trade risk never > 0.50%, and the cushioned addition never > 30% of session profit.

**Files:**
- Modify: `quant/execution/risk.py:342-356`
- Test: `tests/quant/execution/test_risk.py`

- [ ] **Step 1: Failing test**

```python
def test_house_money_bonus_capped():
    r = SessionRisk(equity=1_000_000)
    r._daily_pnl = 200_000      # huge winning day
    r._consecutive_wins = 2
    pct = r._risk_per_trade_pct()
    assert pct <= 0.005 + 1e-9, "never exceed 0.50% total"
    bonus = pct - 0.004
    assert bonus <= 0.30 * 200_000 / 1_000_000 + 1e-9, "addition never exceeds 30% of session profit"
```

(Reuse whatever existing fixtures construct SessionRisk in that file.)

- [ ] **Step 2: FAIL**, then:

```python
        base = 0.004 if tier == "MOMENTUM" else 0.0035
        cushion_bonus = min(
            (0.40 * self._daily_pnl) / self._equity,
            0.30 * abs(self._daily_pnl) / self._equity,   # ≤30% of session profit
        ) if self._equity > 0 else 0.0
        return min(base + cushion_bonus, 0.005)           # hard ceiling 0.50%
```

Update the docstring numbers to match (keep the 0.40 gross-fraction sentence + name both caps).

- [ ] **Step 3:** `pytest tests/quant/execution/test_risk.py tests/quant/test_stress_and_portfolio_risk.py -q`

- [ ] **Step 4: Commit**

```bash
git commit -am "fix: cap house-money sizing at 0.50% total / 30% of session profit"
```

---

### Task 7: Close the midday phase-permission leak

NSE_MIDDAY forbids momentum trades (`allow_trend=False`, `session/context.py:140`), but Gate 1 only enforces it when `setup_evidence` exists — raw Triple-A AGGRESSION (`gates_edge.py:62-63`) and Initiative breakout (:77-81) sail through midday unguarded.

**Files:**
- Modify: `quant/decision/context.py` (add `allow_trend: bool = True`, `allow_reversion: bool = True`)
- Modify: `quant/decision/context_builder.py` (~:290-314 where phase flags resolve — copy the two booleans from the same session source Gate 1 uses)
- Modify: `quant/decision/gates_edge.py` (`_check_setup_paths`)
- Test: `tests/quant/decision/test_gate1_phase_permissions.py` (extend, don't fork patterns)

- [ ] **Step 1: Failing test**

```python
def test_initiative_breakout_blocked_midday_without_evidence():
    ctx = _midday_ctx(direction="SHORT")            # allow_trend=False, no setup_evidence
    ctx.break_type, ctx.break_direction = "INITIATIVE", "DOWN"
    ctx.cvd_slope = -0.3                            # passes gate-3 CVD tolerance
    r = gate_triple_a_edge(ctx)
    assert not r.passed and "trend" in r.reason.lower()
```

- [ ] **Step 2: FAIL**, then in `_check_setup_paths` guard the momentum paths:

```python
    if not getattr(ctx, "allow_trend", True):
        phase = ""
        tsignal = ""
        # ponytail: gate-1 owns evidence-gated paths; here we catch the evidence-free ones
    ...
```

Concretely: wrap the Triple-A AGGRESSION block and INITIATIVE block each with `if getattr(ctx, "allow_trend", True):`. Second-drive and LVN Sniper are location/reclaim plays — leave unguarded (reversion-friendly by nature). On violation: `return GateResult(3, False, "Trend continuation blocked in reversion-only phase")`.

- [ ] **Step 3:** Populate the two flags in context_builder from the identical `session_allow_entry` resolver Gate 1 reads (so they can never disagree):

```python
allow_trend=si.allow_trend, allow_reversion=si.allow_reversion,
```

(Grep exact attribute names: `grep -n "allow_trend" quant/session_gates.py quant/decision/*.py`.)

- [ ] **Step 4:** `pytest tests/quant/decision -q && pytest tests/quant -x -q`

- [ ] **Step 5: Commit**

```bash
git commit -am "fix: evidence-free momentum entries respect reversion-only phases (midday leak)"
```

---

### Task 8: Pyramid reservation before creation (ghost adds)

The paper-mode add-on is appended and counted (`position_manager.py:392-408`) BEFORE portfolio-risk authority answers (`:416-424`) — a refusal leaves a counted-but-unreserved ghost pyramid.

**Files:**
- Modify: `quant/position_manager.py:389-428` (reorder only)
- Test: extend `tests/quant/execution/test_pyramid_integration.py`

- [ ] **Step 1: Failing test**

```python
def test_refused_add_leaves_no_ghost(caplog):
    pr = _portfolio_that_refuses()
    pm = _pm_with(portfolio_risk=pr)
    pm.add_pyramid(...)          # conditions otherwise perfect (BE armed, absorption fresh)
    assert len(pm._pyramids) == 0 and pm._pyramid_count == 0
```

- [ ] **Step 2: FAIL**, then move the `can_accept`/`register_open` block ABOVE the `add_pyramid`/append/count-increment lines; on refusal, emit nothing and return early. Pure reorder — zero logic changes.

- [ ] **Step 3:** `pytest tests/quant/execution/test_pyramid*.py -q && pytest tests/quant -x -q`

- [ ] **Step 4: Commit**

```bash
git commit -am "fix: reserve pyramid risk before creating add-on (no ghost pyramids)"
```

---

### Task 9: Honest Gate 4 RR reporting

Gate 4 computes RR against a target synthesized at exactly 2R (`gates_rr.py:28-31`), so its "RR pass" line is always true-by-construction while the shipped signal may carry structural TP at 1.5. The real protections are the stop-width cap and SignalBuilder's own min-rr qualification — the fake number is misleading telemetry.

**Files:**
- Modify: `quant/decision/gates_rr.py:24-45`
- Test: `tests/quant/decision/test_gates_rr.py`

- [ ] **Step 1: Failing test**

```python
def test_gate4_detail_reports_stop_cap_not_synthetic_rr():
    r = gate_risk_reward(_valid_ctx())
    assert "RR=" not in r.detail or "synthetic" in r.detail
    assert "risk" in r.detail.lower()
```

- [ ] **Step 2: FAIL**, then rewrite tail:

```python
    reward = risk * DEFAULT_TP_MULTIPLIER     # planning assumption, NOT measured RR
    detail = (
        f"stop={risk / tick:.0f} ticks (cap {scaled_cap_ticks:.0f}) "
        f"| signal RR enforced by SignalBuilder min_rr=1.5"
    )
    return GateResult(4, True, "Stop within cap", detail) if risk <= scaled_cap_ticks * tick else GateResult(4, False, ...)
```

Keep returning pass/fail ONLY on stop width (rename reason strings accordingly); SignalBuilder remains sole RR authority (structural targets qualify ≥1.5 else 2R fallback — already enforced at `signal_builder.py:152,197-202`).

- [ ] **Step 3:** `pytest tests/quant/decision/test_gates_rr.py tests/quant/decision/test_gate_names.py tests/quant/certification/test_signal_drop_reasons.py -q` — golden `decide` traces may embed gate detail text; regenerate those goldens with the diff noted in the commit body.

- [ ] **Step 4: Commit**

```bash
git commit -am "refactor: Gate 4 reports stop-cap truth; drops synthetic RR theater"
```

---

## Deferred (deliberately NOT in this plan — ponytail YAGNI ledger)

| Item | Why skipped | Trigger to revisit |
|---|---|---|
| Overseer prompt completeness (Gap #3: add LVN/OI/VWAP bands to MLX bridge prompt) | Advisor is advisory-only; token cost now, zero decision authority | If advisor regains authority |
| Spread-blowout on tick path (currently bar-only) | Needs tick-depth plumbing into PositionManager state; bar latency accepted for scalps | Journal shows liquidity-exit losses > X₹ |
| VWAP σ-band literal trailing | %-giveback + drift-halving already adaptive | Options-journal giveback analysis |
| Directional CVD confirmation in IMBALANCED (`compute.py:88-91`) | Consumer graph unclear; touching risk-free path without knowing readers | Trace `cvd_confirmed` consumers first |
| IB-break volume confirmation (`break_detector.py:171-186`) | Behavior change on live trigger path; deserves its own replay-based validation task | Certification harness rerun |
| Footprint `detect_absorption` + `bubble_retests` + `DriveDecay` wiring | Real signals, but no ready consumer; bolt-on invites noise | Second-drive/fade tuning sprint |
| YAML `llm_*` leftover keys, preflight script LLM gate | Config hygiene, zero behavior impact | Next config-touching task |

---

## Self-Review

- Spec coverage: audit fix-items 1-6 mapped to Tasks 1-2b/3/5/6/7; bugs 4,7,6,9→Tasks 4,8,9; items beyond (deferred table) explicitly dispositioned.
- Placeholders: Steps 2-4 of Task 5 and helper-reuse notes reference named files/lines with concrete fallback code — executor instructed to adapt fixture helpers only, never leaving TBDs.
- Type consistency: `squeeze_direction`/`squeeze_trapped_level` (snake_case on context/result) vs DTO camelCase keys declared once in Task 2a Interfaces and reused verbatim in 2b.
