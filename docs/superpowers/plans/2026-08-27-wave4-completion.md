# Wave-4 Completion Plan: Accounting Dedupe, Alias Parity, Regime-Aware Exits

> **For agentic workers:** REQUIRED SUB-SKILL: subagent-driven-development (single sequential lane — tasks share runtime.py/position_manager.py). Checkbox tracking.

**Goal:** Close every item ledgered by the wave-3 review plus the last structural Fabio gap: (1) pyramid realized-PnL booked exactly once across ALL close paths, (2) `OPPOSING_SIGNAL` recognized by the contracts layer, (3) thesis-flip evaluated on the same context basis as entries (underlying, for option-mode engines), (4) mean-reversion setups (VA_FADE) exit at first TP with NO partials/runner — trend setups keep today's 50/25/25 ladder until journal tuning says otherwise.

**Architecture:** One unified risk-release/bookkeeping helper owned by PositionManager consumed by runtime for every terminal + partial path. No new knobs. Fractions other than "fade disables laddering" unchanged (journal-driven tuning remains deferred).

**Tech Stack:** Python 3.13, pytest. No new dependencies.

## Global Constraints

- Branch: `fix/wave4-accounting-regime`
- `.venv/bin/python -m pytest`; stage ONLY explicit paths; NEVER `git add -A`
- No config knobs; `# ponytail:` comments on deliberate ceilings; tiny diffs
- Validation: targeted suites + FULL `tests/quant -q` green (document base pre-existing system failure only)

---

### Task 1: Pyramid realized-PnL booked ONCE (unified helper)

Today: natural/flipped closes double-book add-on PnL — `_execute_full_close` E11 loop (`record_close(risk_i, pyr_fill.pnl)` per pyramid) AND runtime's post-close release ALSO passes `record_close(0.0, last_pyramid_pnl)` (runtime ~:547-556, tick path now included); flip path books once. Three variants of truth.

**Files:** `quant/runtime.py` (post-close release block + tick path), `quant/position_manager.py` (E11 loop), tests new `tests/quant/runtime/test_pyramid_accounting_parity.py`

**Interfaces:** Produces one canonical sequence — either E11-only (helper suppressed when `last_pyramid_pnl == already_released`) or helper-only (E11 stops calling record_close) — implementer picks the smaller diff after reading both; SPY TEST dictates outcome:

- [ ] **Step 1: Failing spy test** — drive all THREE sequences (natural TP close with 2 pyramids; tick-path TP2 partial→later close with 1 pyramid; OPPOSING_SIGNAL flip with 1 pyramid): assert `PortfolioRiskAuthority.realized_calls` pnl multiset == exactly each add-on fill.pnl once; reserve sums == released residual R.
- [ ] **Step 2:** red → dedupe (choose site, delete the other bookkeeping, keep cumulative logging truthful) → green.
- [ ] **Step 3:** suites `tests/quant/runtime -q tests/quant/execution -q`. Commit: `fix: pyramid realized pnl booked once across natural/tick/flip closes`

### Task 2: OPPOSING_SIGNAL contracts alias

**Files:** `quant/contracts/entities.py` (same mechanism as round-3's BREAKEVEN/TP2 additions ~:212-230), classification test beside round-3's.

Map `OPPOSING_SIGNAL → ADVERSE_EXIT` family (exit_rules.classify_exit hosts the Fabio taxonomy). Assertion mirrors round-3 literal tests. Commit: `fix: classify OPPOSING_SIGNAL as adverse exit in contracts layer`

### Task 3: Thesis-flip on underlying basis (option-mode parity)

Live-check first: does `_check_thesis_flip` (runtime) build ctx from the OPTION bar/dto while entries qualify via UNDERLYING paths (~:465/:485)? If yes for any wired mode → flip could trigger on option-side noise never qualified upstream.

**Files:** `quant/runtime.py`; test in `test_opposing_signal_exit.py` extension.

Rule: flip must consume the IDENTICAL context source as entry qualification; if unavailable in a mode → SKIP flip (one INFO log, ponytailed ceiling) instead of guessing. Test constructs divergence (option-dto approves SHORT, underlying flat/fails) asserting NO flip on option basis after fix; plus happy-path unaffected.

Commit: `fix: thesis-flip qualifies on underlying context, matching entry basis`

### Task 4: Regime-aware terminals — VA_FADE fully closes at first TP

Signal already carries its canonical type (verify field: grep `class .*Signal` in quant/decision — `type`/`setup`). MAPPING (ponytailed): canonical `VA_FADE` ⇒ mean-rev ⇒ DISABLE tick T1/T2 tiering AND bar-path Rule-4 partials — first TP touch (either path) = full close `reason="TP"`; BE-arm behavior replaced by intrinsic zero-duration (n/a — trade ends); trailing/time still guard the leg BEFORE tp hit. All other types (incl. absent/legacy) ⇒ unchanged ladder (fractions frozen until journal tuning).

**Files:** `quant/position_manager.py` (tick touch + _tick_tp_touch early branch reading signal type), `quant/execution/exit_checks.py::check_take_profit_tiers` (skip tiering when flagged — thread signal.type or a boolean `terminal_tp_only` through Evaluate; prefer deriving inside from `position.order.signal` so signature stays), tests extending `test_tick_level_exits.py` (+bar-path counterpart in execution tests):

```python
def test_va_fade_signal_full_closes_at_first_tp_touch(pm_va_fade_position): ...  # size intact until TP, then None
def test_trend_signal_still_ladders(pm_trend_position): ...                      # regression pin (today's behavior)
```

Goldens/decide traces shouldn't move (builder untouched). Suites: runtime + execution + system(-q, note base failures). Commit: `feat: mean-rev setups exit terminal at first TP (VA_FADE regime-awareness)`

## Deferred (unchanged)
Theta-aware stops; σ-band trailing; fraction retune 75/25 (journal data needed); bubble magnitude tiers; SessionRisk cold-start reset investigation; harness id-keying.

## Self-Review
Ledger items w3-1/w3-2/w3-3 → Tasks 1/2/3; regime split → Task 4 (minimal VA_FADE form;fractions deferred). Shared-file sequencing locked to single lane; interface additions are internal helpers/kwarg-free reads. Anchors drift-tolerant via grep-first instructions.
