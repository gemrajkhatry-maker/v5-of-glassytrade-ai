# WS-GATECONS Report — Gate/exit/risk stack divergence measurement

Date: 2026-08-07 · Branch: `migration/ws-gatecons` · Worktree: `/Users/apple/Documents/wt-ws-gatecons`

## Status

Complete. Differential harness added and green, review doc produced, one commit landed. No production code changed.

## Commits

- `bef0e54 test(quant): gate/exit stack divergence measurement` — adds `tests/quant/consolidation/test_gate_divergence.py` (472 lines). `docs/GATE_CONSOLIDATION_REVIEW.md`, `.superpowers/`, and `docs/*.md` intentionally NOT committed.

## Test counts

- New: `tests/quant/consolidation/test_gate_divergence.py` — **4 passed** (golden-session gate verdicts, gentle-session signal divergence, SL/TP geometry, exit divergence).
- Full `tests/quant`: **1391 passed, 30 skipped** (pre-existing 1 RuntimeWarning only; no regressions).

## Agreement rates (canonical 60-bar `_session_bars()` + gentle breakout + exits)

| measurement | result |
|---|---|
| gate pass/fail agreement (golden session) | 60/60 = **100%** (both stacks reject every bar) |
| same-blocking-gate (golden session) | **0/60 = 0%** — the stacks NEVER fail the same gate on any bar |
| gate pass/fail agreement (gentle breakout) | 59/60 = **98.3%** (single divergence = the AGGRESSION bar) |
| exit decision agreement (bars 29–59) | 3/31 = **9.7%** |

## Divergence cases

1. **ABSORBING/ACCUMULATING bars (25–27, 42–44):** greenfield blocks gate 3 ("No direction"); production blocks gate 2 ("PROBING without high aggression (0.0 < 2.0)"). Green fail dist: g3×58, g5×2. Prod fail dist: g1×2, g2×8, g4×50.
2. **AGGRESSION bars (28, 45):** greenfield blocks gate 5 (structural stop 86–103 ticks > 20-tick budget); production blocks gate 4 (price 60–68 ticks from VA boundary > 3-tick max).
3. **Gentle breakout, bar 28:** greenfield PASSES all 5 gates → **LONG signal**; production rejects (gate 2 with greenfield-derived aggression=0; gate 4 "9.2 ticks from level" even with aggression=3.0).
4. **SL/TP geometry (same bar, LONG @100.30):** greenfield SL 99.82 / 2.0R; production SL 98.75 / ~1.1R — production stop **3.2× wider** (1.5% ATR floor vs one-VP-step structural stop).
5. **Exits:** greenfield is **intrabar-aware** → SL exit at bar 32 (low 99 ≤ 99.82); production is **close-based** (`check_position` takes no bar high/low, 120s min-hold) → holds the whole window. A bar-extreme SL pierce that greenfield trades is invisible to production.
6. **Risk stacks** (mapped in doc): `risk.py.SessionRisk` (geometric shrink) vs production `risk_manager`/`risk_tier`/`circuit_breakers`/`loss_tracker` (A/B/C/HALT tiers, non-overridable breakers, dynamic risk). No shared code.

## Verdict

**KEEP BOTH** with a documented divergence budget. The divergence is real **and intentional** — two different decision models (deterministic intrabar-exact paper/WS engine vs Fabio-playbook close-based live engine), not duplicated logic. 0/60 same-blocking-gate is the proof: a merge would change live trade selection, stop geometry, and exit timing in one move, violating P2.7's no-behavior-change constraint. Concrete merge plan (files to delete + tests to keep) is written up for the flip condition only — none of its preconditions hold.

Divergence budget (now enforced by the test): pass/fail agreement ≥ 95%, **0 cross-fire bars**, same-blocking-gate = 0 (expected), greenfield first-exit ≤ production first-exit, SL risk ratio ≥ 2.5× (measured 3.2×).

## AMT_UNIFICATION-relevant note

Companion to `docs/AMT_UNIFICATION.md` (same P2.7 track): the analysis kernel agrees closely (POC ≤ 0.99%, VAH ≤ 0.64%, VWAP ≤ 0.14%; VAL on leg bars + CVD slope are the deliberate deltas), but the **decision layer diverges categorically** (0/60 same gate, 9.7% exit agreement). Kernel unification would therefore NOT yield one gate/exit stack; the cheapest future convergence is the exit layer (close-based vs intrabar), and the gate layers should be treated as two products, not two bugs.

## Doc path

`/Users/apple/Documents/wt-ws-gatecons/docs/GATE_CONSOLIDATION_REVIEW.md` (in the worktree, uncommitted as instructed).

## Concerns

- The gate differential depends on an adapter (`AuctionState → AMTResult/GateContext`) that mirrors `gate_runner.run_gate_pipeline`; the harness cross-checks its reason string against the real entry point so drift is caught, but a future threshold change (e.g. `max_distance_to_level_ticks`, `MIN_AGGRESSION_SCORE`) will shift the asserted distributions and require updating the test — that is by design (it is the divergence guard).
- Production's `check_position` has no TP check and no intrabar input; if live behavior is meant to be bar-exact on SL pierces, that is a live-path capability gap the differential exposes but this task did not fix.
- `aggression`/`drive_number`/`market_state` have no greenfield analog; the adapter feeds neutral values, so the production gate-2 aggression path is only partially exercised (flagged in the doc).
