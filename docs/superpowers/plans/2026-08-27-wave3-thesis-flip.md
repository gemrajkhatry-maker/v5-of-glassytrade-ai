# Wave-3 Fixes Plan: Tick-Parity Completion, Thesis-Flip Exit, Hygiene

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Complete strict tick/bar exit parity (runner's final tier books a partial, never auto-kills), add Fabio thesis-invalidation (fresh contrary-approved setup flattens an open position, reason `OPPOSING_SIGNAL`), and land three hygiene items (shared TP2 geometry helper, contracts whitelist literals, paper_protocol buckets).

**Architecture:** Deterministic core unchanged. Thesis-flip reuses the EXISTING full gate pipeline (phases/rules inherited automatically); it runs after normal ExitEngine evaluation so SL/spread/time priority is preserved, and drives `_execute_full_close` — no new exit machinery.

**Tech Stack:** Python 3.13, pytest. No new dependencies.

## Global Constraints

- Branch: `fix/wave3-exits` (off current `feature/wire-money-path` HEAD)
- `.venv/bin/python -m pytest`; stage ONLY task files by explicit path; NEVER `git add -A`
- No new config knobs; `# ponytail:` comments name deliberate ceilings; tiny diffs
- Tier fractions stay 0.5/0.5-of-remaining; halt thresholds untouched
- Validation gates for behavior changes: full `tests/quant -q`, `tests/system -q` (documenting the 2 pre-existing paper-protocol failures if still red at base)

---

### Task 1: Strict parity — runner final tier books TP2 partial; shared geometry helper (MED)

Bar path at tier≥1 books another 50%-of-remainder partial at TP2 (`exit_checks.py:54-58`) and keeps a quarter runner until TRAIL/BE/TIME. Tick path currently FULL-CLOSES the runner at TP2 (`position_manager.py:320-344`). Align: tick TP2 touch books the same partial, sets tier=2; runner thereafter dies only via trail/BE/drift/TIME/session/bar-path — never by raw TP ticks.

Also de-duplicate the TP2 formula now used in two places (the drift source r2A-M1 flagged): one helper, both callers.

**Files:**
- Modify: `quant/execution/exit_checks.py` (add module-level helper near Rule 4)
- Modify: `quant/position_manager.py` (`_tick_tp_touch` tail + remove inline formula)
- Test: `tests/quant/runtime/test_tick_level_exits.py`

**Interfaces:**
- Produces: `exit_checks.tp2_level(entry: float, tp: float) -> float` — long: `entry + 2*abs(tp-entry)`; short mirrored (`entry - 2*abs(entry-tp)` … verify sign against existing Rule-4 lines and reuse EXACTLY that math). Bar path refactored to call the same helper (pure refactor, values identical).

- [ ] **Step 1: Failing tests**

```python
def test_tick_tp2_books_final_partial_not_full_close(pm_after_tp1):
    pos = pm_after_tp1                     # tier==1 runner alive
    tp2 = tp2_level(float(pos.order.signal.entry), float(pos.order.signal.tp))
    out = pm.manage_tick_exit(pos, tick_price=_beyond(tp2, pos), tick_time="12:02:00")
    assert pm._position is not None                    # quarter runner survives
    assert abs(pm._position.size) * 2 <= abs(_pre_size) # halved again
    assert pm._exits._tp_tier[pos._id] == 2
    assert pm.last_fill.reason == "TP2"

def test_runner_after_tp2_ignores_far_tp_ticks_and_exits_by_trail(pm_after_tp2):
    far = _beyond(tp2_level(entry,tp)*1.05, pos)
    out = pm.manage_tick_exit(pos, tick_price=far, tick_time="12:03:00")
    assert pm._position is not None                    # no TP semantics left
```

(Adapt fixture names to this file's post-round2 helpers — `side="SHORT"` variants exist too.)

- [ ] **Step 2: FAIL**, implement, then ALSO update the two round-2 short/long tests that asserted full-close-at-TP2 ("TP2" reason remains, but closing assertion becomes survive-with-tier-2; adjust comments honestly — these codified the divergence being fixed now).

- [ ] **Step 3:** `pytest tests/quant/runtime/test_tick_level_exits.py tests/system -q`

- [ ] **Step 4: Commit**

```bash
git commit -am "feat: tick-path TP2 books final partial, tier=2 (strict bar parity); shared tp2_level() helper"
```

---

### Task 2: Contracts bridge literals + paper_protocol buckets (LOW hygiene)

- [ ] **Files:**
- Modify: `quant/contracts/entities.py` (`Position.close()` reason whitelist ~:205-230 — add `"BREAK_EVEN"` mapping so journaled `"BREAKEVEN"` classifies BREAK_EVEN rather than geometric fallthrough; map `"TP2"` → TAKE_PROFIT path consistent with existing "TP")
- Modify: `quant/execution/exit_rules.py::classify_exit` if it owns a literal map — grep first (`grep -n '"TP"\|classify_exit' quant/contracts/entities.py quant/execution/exit_rules.py`)
- Modify: `tests/system/test_paper_protocol.py:~288` bucket tuple — route `("SL","BREAKEVEN")` vs `("TP1","TP2")` coherently with the CURRENT literal set (this repair un-breaks part of the long-standing pre-existing failure if the harness otherwise passes; leave genuinely-base-broken assertions untouched and say so)

**Test:** extend/add in whichever existing suite covers entities.close classification (grep `close(` usage in tests/quant/contracts/test_aggregates.py) —

```python
def test_close_classifies_breakeven_and_tp2_literals(base_pos_factory):
    f = base_pos_factory().close(100.0, ts="t", reason="BREAKEVEN")
    assert f.exit_kind == "BREAK_EVEN"        # adapt field/assertion to actual Fill shape
```

- Run: targeted file + `pytest tests/system -q`. Commit: `fix: contract layer recognizes BREAKEVEN/TP2 exit reasons`

---

### Task 3: Opposing-signal exit (thesis invalidation — user-confirmed FULL EXIT) (HIGH value)

While positioned, on each UNDERLYING bar close AFTER normal exit evaluation produced no exit: build the regular DecisionContext and run the UNCHANGED full pipeline with one bypass — Gate 2 (position/cooldown) skipped. If the result is a full APPROVED signal whose direction is OPPOSITE the open position → flatten immediately, reason `OPPOSING_SIGNAL` (counts as a trade via base close path). Everything inherited: phase permissions, dead-market, anti-climax, CVD guards, RR/stop cap, SignalBuilder qualification. Same-direction approvals and NO_EDGE do nothing. Risk-halted state must NOT block the flip (halts gate entries, not exits).

**Files:**
- Modify: `quant/decision/gates_session_position.py` (`gate_position_cooldown` gains `allow_positioned: bool = False`; True ⇒ passes-through when the ONLY blocker is an open position, still enforcing real cooldown seconds)
- Modify: `quant/decision/pipeline.py` (`evaluate` gains `allow_positioned: bool = False` forwarded to gate 2 — default preserves current behavior everywhere)
- Modify: `quant/runtime.py` (bar-close positioned branch: after `self._position = pm.manage_exit(...)`, if still holding → build ctx exactly as `_decide` does (reuse/refactor its ctx-building into `_build_context(bar)` helper — extract, don't duplicate) → `decision = pipeline.evaluate(ctx, allow_positioned=True)` via existing DecisionService wrapper so SignalBuilder qualification holds → flip check)
- Test: `tests/quant/runtime/test_opposing_signal_exit.py` (new)

**Interfaces:**
- Produces: `GatePipeline.evaluate(ctx, *, allow_positioned=False)`; `ExitDecision(True, "OPPOSING_SIGNAL", price)` through `_execute_full_close` (streak counts correctly because count_as_trade=True default).

- [ ] **Step 1: Failing tests (new file)**

```python
def test_contrary_approval_flattens_position(engine_long_then_short_setup):
    eng.open_long_via_test_hook()
    feed_bar(engine, bar_that_would_approve_SHORT())
    assert eng.position is None
    assert last_close_reason() == "OPPOSING_SIGNAL"
    assert eng.risk_state.trades_today_increased_by(1)

def test_same_direction_approval_holds(engine_long_then_long_setup): ...
def test_gate_failure_no_flip(engine_long_then_failed_edge): ...
def test_real_cooldown_still_blocks_even_allow_positioned(engine_post_close_within_cooldown): ...
```

Reuse whatever engine-driving fixtures exist in tests/quant/runtime (test_tick_level_exits/system paper harness patterns); bars constructed to trip specific gates following gate-test fixtures.

- [ ] **Step 2: FAIL**, implement the three files (smallest possible diffs):
  - gate fn: `if allow_positioned and only-blocker-is-open-position: return passed("thesis-flip check")`
  - pipeline: pass-through kwarg only
  - runtime: extraction of ctx-build + one ~10-line positioned-decision block. Flip executes via `self._pm._execute_full_close(pos, ExitDecision(True,"OPPOSING_SIGNAL",float(bar.close)), bar.time)`; log a loud `🔄 [THESIS FLIP]`.

- [ ] **Step 3:** Order check — spread/SL/CVD/TP/trail/time STILL evaluated first inside `manage_exit` (flip runs only when position survived), SESSION_CLOSE precedes everything as today.

- [ ] **Step 4:** `pytest tests/quant/runtime tests/quant/decision tests/quant/execution -q` then FULL `tests/quant -q`

- [ ] **Step 5: Commit**

```bash
git commit -am "feat: opposing-signal exit — fresh contrary approval flattens position (OPPOSING_SIGNAL)"
```

---

## Deferred (unchanged ledger + wave-3 additions)

| Item | Why |
|---|---|
| Regime-aware runner split (75/25 vs mean-rev 100%) | Needs setup-type plumbed to PM; own design pass |
| Theta-aware time stops; σ-band literal trailing | Journal-driven tuning later |
| Magnitude-tiered bubble response; orphaned MomentumSqueezeDetector | Low urgency |
| SessionRisk cold-start reset investigation | Ops hardening track |

## Self-Review

Coverage: F1→T1; WHITELIST/PAPER-BUCKET→T2; opposing-signal→T3 (design confirmed by user: full exit). Interfaces named once and reused (tp2_level; allow_positioned; OPPOSING_SIGNAL literal). Anchor drift expected — briefs instruct live-grep verification.
