# Audit Round-2 Fixes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Fix the 7 issues found in the 2026-08-27 deep re-audit — one HIGH risk-core correctness bug (partials mutating loss-streaks), one runner-design defeat on the tick path, and five smaller semantic/dead-field fixes — each as the smallest possible root-cause diff.

**Architecture:** Same deterministic core (`quant/decision`, `quant/execution`, `quant/amt`). No new modules; all edits are guards/one-liners inside existing functions, plus one small persistence-key addition (`SessionLevelStore` close).

**Tech Stack:** Python 3.13, pytest. No new dependencies.

## Global Constraints

- Branch: `fix/audit-round2-risk-core`
- Test runner: `.venv/bin/python -m pytest` (full `tests/quant -q` takes ~60–90s; use timeout ≥300s)
- Stage ONLY task files by explicit path — NEVER `git add -A` / `git add .`
- No new config knobs; hardcoded values get a short `# ponytail:` comment naming the ceiling
- Do not alter tier fractions (0.5/0.5), min_rr semantics, halt thresholds (2%/3-loss/6-trade)
- Every task ends green before commit

**Source findings** (2026-08-27 re-audit, severity-ranked):

| # | Sev | Finding | Site |
|---|-----|---------|------|
| 1 | HIGH | Partials mutate win/loss streaks despite `count_as_trade=False` → real losers never trip 3-loss halt; cushion escalates off uncounted partials | `quant/execution/risk.py:159-166` |
| 2 | MED-HIGH | Tick tier≥1 full-closes at `sig_tp`; next tick ≥ sig_tp kills runner instantly → 50%@1R+50%@1R instead of running to entry+2R | `quant/position_manager.py:296-302,339` |
| 3 | MEDIUM | E11 release loop reuses stale `pyr_fill.pnl` (last pyramid's) for every released add-on → PortfolioRisk realized double-counts P2/drops P1 | `quant/position_manager.py:253-256` |
| 4 | MEDIUM | `classify_gap` fed `prior_close=prior_poc` → gap-size classes semantically wrong whenever POC ≠ settlement | `quant/amt/analyzer.py:880-892`, `quant/amt_engine.py`, `quant/session_levels.py` |
| 5 | LOW-MED | BE-floor hits journal as `"SL"` on tick path → distorts loss stats halts reason about | `quant/position_manager.py:288-300` |
| 6 | LOW | LVN Sniper raw gate path unguarded by `allow_trend` at midday | `quant/decision/gates_edge.py:69-77` |
| 7 | LOW | `price_velocity` always 0.0 on live bars (consumed from duration=0 second A/R pass) | `quant/amt/analyzer.py:506,701,907` |

---

### Task 1: Streak updates only for real trades (HIGH — risk-core correctness)

`record_trade()` increments/resets win-loss streaks on EVERY call, but partial fills are recorded with `count_as_trade=False`. A profitable TP1 partial resets `_consecutive_losses` mid-trade, so three genuine losers that each booked a winning partial never trip the 3-consecutive-loss halt — and `_cushion_tier()` escalates to MOMENTUM off trades that never counted.

**Files:**
- Modify: `quant/execution/risk.py:159-166`
- Test: `tests/quant/execution/test_risk.py`

**Interfaces:** no signature changes. Callers verified: PM partials/pyramids already pass `count_as_trade=False`; base closes and multi_engine fill paths use the True default.

- [ ] **Step 1: Failing test**

```python
def test_partial_fills_do_not_reset_loss_streak():
    r = SessionRisk(equity=1_000_000)
    r.record_trade(-1000.0); r.record_trade(-1000.0)          # 2 real losses
    r.record_trade(+500.0, count_as_trade=False)              # TP1 partial "win"
    st = r.state()
    assert st.consecutive_losses == 2, "partial must not reset the loss streak"
    r.record_trade(-1000.0)                                    # 3rd real loss
    assert r.state().halted, "3 consecutive REAL losses must trip the halt"
    assert "consecutive" in r._halt_reason
```

(Adapt constructor/fixtures to how existing tests build SessionRisk.)

- [ ] **Step 2: Run to see it fail**

Run: `.venv/bin/python -m pytest tests/quant/execution/test_risk.py::test_partial_fills_do_not_reset_loss_streak -v`
Expected: FAIL (`consecutive_losses == 0` after the partial)

- [ ] **Step 3: Implement — one condition wrap**

```python
            if count_as_trade:
                if pnl > 0.0:
                    self._consecutive_losses = 0
                    self._consecutive_wins += 1
                elif pnl < 0.0:
                    self._consecutive_losses += 1
                    self._consecutive_wins = 0
            # ponytail: partials/bookkeeping fills don't count as trades;
            # letting them move streaks would blind the 3-loss halt and
            # inflate cushion tiers off wins that were never round-trips.
```

(daily_pnl/equity accumulation stays unconditional — money always counts)

- [ ] **Step 4: Run suites**

Run: `.venv/bin/python -m pytest tests/quant/execution/test_risk.py tests/quant/execution/test_lot_aware_risk.py tests/quant/runtime -q`
Expected: PASS (if an existing test asserted partials changing streaks, it codified the bug — update it citing this regression test)

- [ ] **Step 5: Commit**

```bash
git commit -am "fix: partial fills no longer mutate win/loss streaks (halt integrity)"
```

---

### Task 2: Tick-path runner exits at TP2, not sig_tp (MED-HIGH)

After TP1 arms (tier=1), the very next tick ≥ sig_tp routes to `_tick_tp_touch` → falls through to full close at sig_tp. Runner never runs. Bar path books TP2 at `entry ± 2×(tp−entry)` (`exit_checks.py:54-58`) — tick path must use the SAME target once tier≥1.

**Files:**
- Modify: `quant/position_manager.py:292-307` (manage_tick_exit) and `_tick_tp_touch:309-339`
- Test: `tests/quant/runtime/test_tick_level_exits.py`

**Interfaces:** consumes signal.entry/signal.tp; mirrors `exit_checks.check_take_profit_tiers` geometry.

- [ ] **Step 1: Failing tests**

```python
def test_runner_not_killed_at_sig_tp_on_tick_path(pm, open_position_after_tp1):
    pos = open_position_after_tp1           # tier==1, half booked, BE armed
    tp1_price = float(pos.order.signal.tp)
    entry = float(pos.order.signal.entry)
    out = pm.manage_tick_exit(pos, tick_price=tp1_price + 0.05, tick_time="12:01:00")
    assert pm._position is not None         # runner STILL ALIVE at sig_tp touch

def test_runner_closes_at_tp2_on_tick_path(pm, open_position_after_tp1):
    pos = open_position_after_tp1
    entry = float(pos.order.signal.entry)
    long = pos.size > 0
    tp2 = entry + 2.0 * (float(pos.order.signal.tp) - entry) if long else \
          entry - 2.0 * (entry - float(pos.order.signal.tp))
    out = pm.manage_tick_exit(pos, tick_price=tp2, tick_time="12:02:00")
    assert pm._position is None             # runner closes at the real TP2
```

(Reuse this file's existing fixtures/helpers for constructing the post-TP1 state; if none exist yet, derive from the Task-4-of-wave-1 tests that already produce tier==1 state.)

- [ ] **Step 2: FAIL**, then implement:

In `manage_tick_exit`, compute the tier-aware profit target once:

```python
        # Tier-aware tick targets: T1 tags at sig_tp; runner (tier>=1) waits
        # for TP2 — same geometry as ExitEngine Rule 4, else ticks kill the
        # runner instantly at sig_tp.  # ponytail: mirror of exit_checks.py
        tp2_level = 0.0
        if sig_tp > 0:
            sl_ref = sig_sl if sig_sl > 0 else entry_guard(sig_tp)
            entry_px = float(position.order.signal.entry) if position.order and position.order.signal else 0.0
            if entry_px > 0:
                off = abs(tp1_offset := (sig_tp - entry_px)) * 2.0
                tp2_level = sig_tp + off if is_long else sig_tp - off
```

…then route LONG touches:

```python
            elif sig_tp > 0 and tick_price >= sig_tp:
                if self._exits._tp_tier.get(position._id, 0) >= 1:
                    if tp2_level > 0 and tick_price >= tp2_level:
                        return self._execute_full_close(position, ExitDecision(True, "TP2", float(tick_price)), tick_time)
                    return position                      # runner keeps running
                return self._tick_tp_touch(position, float(tick_price), tick_time)
```

…and mirror `<=`/`<= tp2_level` for SHORT. Clean up the walrus to plain lines if lint objects. `_tick_tp_touch`'s own tail (`return self._execute_full_close(... "TP" ...)` at :339) becomes unreachable-from-tick-touch for tier≥1 but keep it as the size<2 degenerate guard.

- [ ] **Step 3:** `pytest tests/quant/runtime/test_tick_level_exits.py tests/system -q` (system suite exercises tick+bar interplay; expect green or the same 2 pre-existing paper-protocol failures documented at base)

- [ ] **Step 4: Commit**

```bash
git commit -am "fix: tick-path runner survives sig_tp, closes at TP2 (bar parity restored)"
```

---

### Task 3: Pyramid E11 release uses each pyramid's OWN pnl (MEDIUM)

The release loop rebinds `pyr_fill` from the *earlier* close loop's leftover — every `record_close(risk_i, ...)` gets the LAST pyramid's pnl.

**Files:**
- Modify: `quant/position_manager.py:239-256`
- Test: `tests/quant/execution/test_pyramid_integration.py`

- [ ] **Step 1: Failing test**

```python
def test_pyramid_release_uses_each_pyr_pnl(pm_with_two_pyramids, spied_portfolio):
    pm_with_two_pyramids._execute_full_close(base_pos, ExitDecision(True, "TP", px), ts)
    realized = spied_portfolio.realized_calls        # [(risk_i, pnl_i), ...]
    assert len(realized) == 2
    pnls = sorted(p for _, p in realized)
    assert pnls == sorted([float(f1.pnl), float(f2.pnl)]), "each release must carry its own fill pnl"
```

(Spy PortfolioRiskAuthority by subclass/wrapper capturing record_close args; fixtures adapted from existing pyramid tests.)

- [ ] **Step 2: FAIL**, then implement — pure data-flow fix:

```python
        closed_pyrs: list[tuple[object, object]] = []   # (pyr_pos, its_fill)
        for pyr_pos in self.pyramid_positions:
            pyr_fill = self._oms.close(...)
            ...
            closed_pyrs.append((pyr_pos, pyr_fill))
        ...
        for pyr_pos, pyr_fill in closed_pyrs:
            risk_i = self._pyramid_open_risk.pop(pyr_pos._id, 0.0)
            self._portfolio_risk.record_close(risk_i, float(pyr_fill.pnl))
            released += risk_i
```

- [ ] **Step 3:** `pytest tests/quant/execution/test_pyramid_integration.py tests/quant/execution/test_pyramid_oms.py -q`

- [ ] **Step 4: Commit**

```bash
git commit -am "fix: pyramid risk releases pair each add-on with its own realized pnl"
```

---

### Task 4: Persist prior CLOSE so gap classification measures against settlement (MEDIUM)

`classify_gap(open, prior_close=prior_poc, ...)` mislabels gaps whenever POC ≠ prior close. Store the last bar close of the finished session in SessionLevelStore and plumb it through.

**Files:**
- Modify: `quant/session_levels.py` (save_levels/close key, load passthrough)
- Modify: `quant/amt_engine.py` (capture last close at rollover; pass to analyze)
- Modify: `quant/amt/analyzer.py` (~:310-316, ~:397-403 signatures + ~:884 classify_gap call)
- Test: `tests/quant/amt/test_cold_start_prior_levels.py` (extend) + new analyzer assertion

**Interfaces:**
- Produces: `SessionLevelStore.save_levels(symbol, date, poc, vah, val, close=0.0)`; levels dict gains `"close"` key; `analyze(..., prior_close: float = 0.0)` optional kwarg (default keeps all existing callers valid).

- [ ] **Step 1: Failing test**

```python
def test_save_and_load_roundtrip_close(store):
    store.save_levels("NIFTY", "2026-08-26", 100.0, 102.0, 98.0, close=101.4)
    lv = store.load_levels("NIFTY")
    assert lv["close"] == pytest.approx(101.4)

def test_gap_classified_against_prior_close_not_poc():
    # prior close 26000, POC 25000; open 26100 => vs-close tiny gap vs vs-poc huge gap
    g = classify_gap(open_price=26100.0, prior_close=26000.0,
                     prior_range=(26000*1.01 - 26000*0.99))
    assert g != "LARGE"
```

- [ ] **Step 2: FAIL**, then implement:

- `session_levels.py`: `save_levels(self, symbol, date, poc, vah, val, close: float = 0.0)` stores `"close": float(close)` alongside poc/vah/val (additive JSON key — old files without it load as missing → `.get("close", 0.0)`).
- `amt_engine.py`: track `self._last_underlying_close = float(bar.close)` wherever aggregated bars land (grep the single assignment point used for `_last_amt_dto`); at rollover pass `close=self._last_underlying_close` to `save_levels`.
- `analyzer.py`: `analyze(...)` accepts `prior_close: float = 0.0`; `classify_gap(open_price=session_open_price, prior_close=(prior_close if prior_close > 0 else prior_poc), ...)` — fallback keeps old behavior when close absent.

Wire the two call sites that forward priors (`amt_engine.py:~312` cold-start path and `:~397` steady-state).

- [ ] **Step 3:** `pytest tests/quant/amt/test_cold_start_prior_levels.py tests/quant/amt/test_analyzer.py tests/quant/runtime -q` (goldens unchanged expected — gapType display-only unless a fixture covers rollover; regen intentionally only if a golden asserts the new key)

- [ ] **Step 4: Commit**

```bash
git commit -am "fix: gap sizing measures prior close/settlement, not prior POC"
```

---

### Task 5: BE-floor tick hits journal as BREAKEVEN (LOW-MED)

When `effective_sl` came solely from the armed BE floor, reason reports "SL".

**Files:**
- Modify: `quant/position_manager.py:286-303`
- Test: `tests/quant/runtime/test_tick_level_exits.py`

- [ ] **Step 1: Failing test**

```python
def test_be_floor_hit_journals_breakeven_not_sl(pm, positioned_at_be):
    out = pm.manage_tick_exit(positioned_at_be, tick_price=positioned_at_be.order.signal.entry - 0.05, tick_time="12:03:00")
    assert out is None                                  # closed
    assert pm.last_exit_reason == "BREAKEVEN"
```

(Field name for last reason — grep how manage_exit surfaces reasons; adapt accessor.)

- [ ] **Step 2: FAIL**, then mirror the TRAIL discrimination:

```python
                if trail_stop is not None and effective_sl == float(trail_stop):
                    reason = "TRAIL"
                elif be_floor is not None and effective_sl == float(be_floor):
                    reason = "BREAKEVEN"                 # journal truth: scratch, not a stop-out
                else:
                    reason = "SL"
```

(mirror for shorts). Any dashboard/test mapping reasons must tolerate the new literal — grep `"SL"` consumers in `state.py`/frontend types before renaming; extend rather than replace known literals.

- [ ] **Step 3:** `pytest tests/quant/runtime tests/quant/execution -q`

- [ ] **Step 4: Commit**

```bash
git commit -am "fix: breakeven-floor exits journal as BREAKEVEN, not SL"
```

---

### Task 6: LVN Sniper respects reversion-only phases (LOW)

Raw Gate-3 LVN path bypasses the allow_trend screen that AGGRESSION/INITIATIVE/SQUEEZE now honor.

**Files:**
- Modify: `quant/decision/gates_edge.py:73-77`
- Test: `tests/quant/decision/test_gate1_phase_permissions.py`

- [ ] **Step 1: Failing test**

```python
def test_lvn_sniper_blocked_midday_without_evidence():
    ctx = _midday_ctx(direction="LONG")                 # allow_trend=False, no evidence
    ctx.leg_lvn = ctx.bar.close
    ctx.absorption_side = "SELL_ABSORBED"
    ctx.cvd_slope = 0.0
    r = gate_triple_a_edge(ctx)
    assert not r.passed and "trend" in r.reason.lower()
```

(Mirror existing midday-veto helpers in that file.)

- [ ] **Step 2: FAIL**, then wrap:

```python
            if ctx.absorption_side == "SELL_ABSORBED" and ctx.agent_direction == "LONG" and cvd_slope >= -0.2:
                if not getattr(ctx, "allow_trend", True):
                    return GateResult(3, False, "Trend continuation blocked in reversion-only phase")
                return GateResult(3, True, f"LVN Sniper LONG @ {leg_lvn:.2f}")
```

(mirror SHORT case with its `<= 0.2` branch)

- [ ] **Step 3:** `pytest tests/quant/decision -q && pytest tests/quant -x -q`

- [ ] **Step 4: Commit**

```bash
git commit -am "fix: LVN Sniper evidence-free path honors reversion-only phases"
```

---

### Task 7: Resurrect price_velocity (LOW — dead DTO field)

Live bars consume the SECOND A/R update (dt=0 → duration=0 → velocity 0). Keep the first-pass velocity.

**Files:**
- Modify: `quant/amt/analyzer.py` (~:506 first `ar_state` assignment; :907 emission)
- Test: `tests/quant/amt/market/test_acceptance_rejection.py` or `test_analyzer.py`

- [ ] **Step 1: Failing test**

```python
def test_dto_price_velocity_nonzero_for_real_bar(analyzer_with_moving_bars):
    dto = analyzer_with_moving_bars.emit_for(_trending_sequence())
    assert dto["priceVelocity"] > 0.0
```

(If emissions aren't directly callable in the existing harness, assert on `AMTResult.price_velocity` after analyze — same guarantee.)

- [ ] **Step 2: FAIL**, then two-line fix at the analyzer's dual-call site:

```python
        ar_state_first = self._ar_engine.update(...)   # existing first call (~:506) — KEEP its existing binding too
```

Store first-call velocity and emit it:

```python
            price_velocity=ar_state_first["price_velocity"],   # :907 — first pass carries the real duration
```

(Note the first call's variable name in situ — it may already be bound and discarded; reuse instead of adding a duplicate update.)

- [ ] **Step 3:** `pytest tests/quant/amt -q` — confirm velocity>0 while credit behavior stays pinned by `test_no_double_credit_within_single_bar`.

- [ ] **Step 4: Commit**

```bash
git commit -am "fix: emit first-pass price_velocity (field was zeroed by dt=0 repeat)"
```

---

## Deferred (re-audit ledger — NOT this wave)

| Item | Why deferred |
|---|---|
| Opposing-signal exit while positioned (#1 open spec gap) | Architecture decision needed (decisions gate runs flat-only); deserves own design pass |
| Regime-aware runner split (75/25 vs mean-rev 100%) | Needs setup-type plumbed into PositionManager; behavior change worth replay validation |
| Theta-aware time stops; literal σ-band trailing | Enhancement, journal-driven tuning first |
| Magnitude-tiered bubble response; orphaned MomentumSqueezeDetector cleanup | Low urgency; deletion candidate needs owner decision |
| SessionRisk cold-start counter reset on restart (live watch item) | Persistence exists via kv; investigate why load failed ×8 at boot separately |
| Dhan boot seed rate-limits; WS StopAsyncIteration spam | Ops hardening, not strategy code |

---

## Self-Review

- Spec coverage: findings 1–7 → Tasks 1–7, one-to-one, same severity order.
- Placeholders: every step carries concrete code or exact edit instructions with named anchors; fixture adaptations reference existing files/patterns explicitly.
- Type consistency: TP2 formula matches `exit_checks.py:54-58` geometry; `save_levels(close=)` kwargs consistent across Task 4 steps; `count_as_trade` contract unchanged (streak-only change).
