# P2.7 Report — Split-brain unification (quant.core vs quant.amt)

**Worktree:** `/Users/apple/Documents/wt-gt-P27` · **Branch:** `migration/P27`
**Date:** 2026-08-06

## Status
COMPLETE. Analysis + test-only deliverable. No `quant/core` or `quant/amt` production files touched.

## Commit
- `6918b86` — `test(quant): split-brain comparison harness — quant.core AuctionCoordinator vs quant.amt AMTAnalyzer`
  - committed files: `tests/quant/unification/test_auction_vs_amt.py` (only)
- **Uncommitted (deliberately):** `docs/AMT_UNIFICATION.md` — the decision record, left in the worktree as required.

## Test counts
- `tests/quant/unification`: **7 passed** (verification command: `/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant/unification -q --tb=short`)
- Full `tests/quant` regression: **1455 passed, 30 skipped** (pre-existing env skips), no failures, no `# TODO(p2)` fallbacks.

## Delta table (bars 4–59, n=56; % = |core−amt|/|core|)

As-fed `_session_bars()` (`t0..t59` labels) — **B = same session, ISO timestamps (isolates harness artifact)**:

| field | max\|Δ\| (A) | max% (A) | mean% (A) | max\|Δ\| (B) | max% (B) | mean% (B) |
|---|---|---|---|---|---|---|
| poc | 0.9798 | 0.990% | 0.459% | 0.9798 | 0.990% | 0.459% |
| vah | 0.6400 | 0.638% | 0.385% | 0.6400 | 0.638% | 0.385% |
| val | 16.0682 | **16.234%** | 1.396% | 16.0682 | **16.234%** | 1.396% |
| vwap | 16.0000 | **16.000%** | 1.619% | 0.1389 | 0.137% | 0.029% |
| ib_high | 16.0000 | **15.842%** | 1.521% | 0.0000 | 0.000% | 0.000% |
| ib_low | 16.0000 | **16.162%** | 1.551% | 0.0000 | 0.000% | 0.000% |

Order flow (delta-enriched ISO session — stock session carries `delta==0` on both sides):

| field | max\|Δ\| | max% | mean% |
|---|---|---|---|
| cvd (value) | 0.0000 | 0.000% | 0.000% |
| cvd_slope | 36.6069 | 430.6%* | 82.3%* |

\* % is relative to a near-zero core slope on one bar — not meaningful; abs is the signal.

Key per-bar numbers: POC worst bar t4 (99.01 vs 99.99, +1%); VAH worst 0.64; VAL worst bar t49 (98.98 vs 82.91) — a leg-clamp bar; VWAP worst (ISO) bar t31 (101.111 vs 101.25, +0.14%).

## Decision
**KEEP BOTH.** `quant.core` remains the real-time `auction`-WS contract producer (byte-compatible with the frontend, pinned by `test_golden_file.py`/`session_a.json`); `quant.amt` remains the full decision engine. Documented divergence budget enforced by the new test.

- POC ≤ 0.99%, VAH ≤ 0.64%, VAL ≤ 0.58% **outside the intentional leg-VA clamp**; VWAP ≤ 0.14% (definitional: close- vs typical-price VWAP); IB = 0.00% on realistic timestamps; CVD value exact.
- The one field breaching the >5% trigger is **VAL (16%)**, only on trend-leg bars, and it is a **deliberate AMT feature** — the Task-2.3 session-VA-vs-leg-VA clamp (`quant/amt/analyzer.py:994-1006`) floors session VAL at the displacement-leg VAL on 27/56 bars. Not a defect ⇒ does not argue for unification.
- The apparent >5% VWAP/IB deltas are **synthetic-harness artifacts**: the golden `t0..t59` labels trigger AMT's per-bar session reset (`current.time[:10]` prefix check) and break its ISO-based IB timing. Both vanish on the ISO-timestamped clone.

## Concerns / follow-ups
1. **Task-2.3 VAL clamp is the only >5% divergence** — intentional, but should be validated against a live trending NIFTY session before any future unification work. If it ever distorts frontend VAL, gate it to an AMT-only path (no `quant.core` change).
2. **Latent bug found:** `OHLC.create()` Decimal coercion breaks `AMTAnalyzer` (`AcceptanceRejectionEngine` compares Decimal volume vs float → `TypeError`). Harness builds `OHLC` with raw floats. Worth its own ticket (not fixed here — no production changes allowed in P2.7).
3. **IB model mismatch (by design):** `quant.core` = 6-bar count window; `quant.amt` = 30-min wall clock. They coincide on 5-min bars (both 101/99), would diverge on irregular cadence.
4. **Cheap future unification:** a shared `create_profile`/`compute_value_area` (adopted by `quant.core` from `quant.amt.profile`) would collapse the sub-1% POC/VAH/VAL bucketing divergence without changing the WS shape.

---

## `docs/AMT_UNIFICATION.md` (worktree, uncommitted) — full content

Path: `/Users/apple/Documents/wt-gt-P27/docs/AMT_UNIFICATION.md`

```markdown
# AMT Unification Decision Record — `quant.core` (`AuctionCoordinator`) vs `quant.amt` (`AMTAnalyzer`)

Status: **DECISION RECORD** (analysis only — no production code changed)
Date: 2026-08-06 · Track: P2.7 (split-brain unification) · Branch: `migration/P27`
Author: P2.7 automation (opencode)

## 1. The question

The codebase has two overlapping brain modules that both compute auction/market-analysis
outputs (POC, VAH/VAL, VWAP, CVD, IB):

- **`quant.coordinator.AuctionCoordinator`** (`quant.core` family) — the pure, frozen-snapshot
  pipeline that drives the real-time `auction` WebSocket producer. It is pinned byte-for-byte
  to the frontend contract by `tests/quant/test_golden_file.py` + `tests/quant/fixtures/session_a.json`.
- **`quant.amt.analyzer.AMTAnalyzer`** — the full AMT decision engine (LVN/HVN, aggression,
  market state, leg analysis, IB-break, drive tracking, NPOC, setup identification, …).

Both are stateful. Both are production-live. This record measures how far apart they are on the
overlapping outputs and decides whether to keep both, or unify.

## 2. Comparison method

The harness is `tests/quant/unification/test_auction_vs_amt.py` (the only code changed by this
track). It feeds the **exact** 60-bar synthetic session from `tests/quant/test_golden_file.py`
(`_session_bars()`) through **fresh** instances of both engines and compares, per bar:

| overlap field | `quant.core` source | `quant.amt` source |
|---|---|---|
| POC / VAH / VAL | `state.volume_profile.{poc,vah,val}` | `AMTResult.{poc,value_area_high,value_area_low}` |
| VWAP value | `state.vwap.value` | `AMTResult.session_vwap` |
| CVD | `state.order_flow.cvd` | `AMTAnalyzer._cvd_tracker.state().value` (internal — not on `AMTResult`) |
| CVD slope | `state.order_flow.cvd_slope` | `AMTResult.cvd_slope` |
| IB high / low | `state.location.{ib_high,ib_low}` | `AMTResult.{ib_high,ib_low}` |

Deltas are measured from bar 4 (AMTAnalyzer returns empty until ≥5 bars). Relative % is
`|core − amt| / |core|`.

### Harness artifact that had to be isolated
`_session_bars()` labels bars `t0..t59` (non-ISO). `AMTAnalyzer._update_session_vwap` treats a
bar as a new session when `current.time[:10] != last_time[:10]` (so every `t{i}` bar resets the
session VWAP *and* the IB tracker), and its IB engine needs ISO times for `fromisoformat`. With
the stock labels this produces spurious ~16% VWAP/IB "divergence". To separate harness artifact
from genuine engine divergence, every measurement was re-run on an **ISO-timestamped clone**
(identical OHLCV, 5-min bars from `2026-01-05T09:15`) — column B in the tables below.

## 3. Measured deltas (bars 4–59, n=56)

### 3a. Session as fed (exact `_session_bars()`, `t0..t59` labels)

| field | max \|Δ\| | max % | mean % |
|---|---|---|---|
| poc | 0.9798 | 0.990% | 0.459% |
| vah | 0.6400 | 0.638% | 0.385% |
| val | 16.0682 | **16.234%** | 1.396% |
| vwap | 16.0000 | **16.000%** | 1.619% |
| ib_high | 16.0000 | **15.842%** | 1.521% |
| ib_low | 16.0000 | **16.162%** | 1.551% |

### 3b. Same session, ISO timestamps (genuine engine divergence)

| field | max \|Δ\| | max % | mean % |
|---|---|---|---|
| poc | 0.9798 | 0.990% | 0.459% |
| vah | 0.6400 | 0.638% | 0.385% |
| val | 16.0682 | **16.234%** | 1.396% |
| vwap | 0.1389 | 0.137% | 0.029% |
| ib_high | 0.0000 | 0.000% | 0.000% |
| ib_low | 0.0000 | 0.000% | 0.000% |

### 3c. Order flow — delta-enriched ISO session (stock session carries `delta == 0` on both sides)

| field | max \|Δ\| | max % | mean % |
|---|---|---|---|
| cvd (value) | 0.0000 | 0.000% | 0.000% |
| cvd_slope | 36.6069 | 430.6%* | 82.3%* |

\* % is relative to a near-zero `quant.core` slope on a bar (core ≈ −31.5, AMT ≈ +5.1 at bar 49),
so the % column is not meaningful for slope; the absolute numbers are the signal.

### 3d. Representative per-bar sample (exact `_session_bars()`)

| bar | core POC/VAH/VAL | amt POC/VAH/VAL | core VWAP | amt VWAP | core IB-H/L | amt IB-H/L |
|---|---|---|---|---|---|---|
| t4  | 99.01 / 100.38 / 99.00 | 99.99 / 101.02 / 99.57 | 100.00 | 100.00 | 101/99 | 101/99 |
| t25 | 100.01 / 101.00 / 99.76 | 100.01 / 101.02 / 99.71 | 100.00 | 100.00 | 101/99 | 100/100* |
| t28 | 99.99 / 100.98 / 99.72 | 100.01 / 101.02 / 99.61 | 100.12 | 104.00* | 101/99 | 105/103* |
| t31 | 99.99 / 101.16 / 99.54 | 100.01 / 100.93 / 99.19 | 101.11 | 116.00* | 101/99 | 117/115* |
| t45 | 99.95 / 100.94 / 99.40 | 100.05 / 101.06 / 96.17 | 100.67 | 96.00* | 101/99 | 97/95* |
| t48 | 99.83 / 100.68 / 98.98 | 100.17 / 101.04 / 88.03 | 100.00 | 84.00* | 101/99 | 85/83* |
| t49 | 99.83 / 100.68 / 98.98 | 100.17 / 101.04 / 82.91 | 100.00 | 100.00 | 101/99 | 101/99 |

\* `t{i}`-label artifacts: AMT's VWAP/IB reset per bar → equal current-bar typical price / range.

## 4. Interpretation (root causes)

1. **POC / VAH (≤1%, all bars).** Structural, small: AMT `create_profile` adds a 1% price buffer
   to min/max before bucketing and uses `VALUE_AREA_PCT = 0.70`; `quant.core` buckets without the
   buffer at `VALUE_AREA_PCT = 0.68`. Different bin edges ⇒ slightly different POC/VAH on every
   bar. This is a *bucketing-parameter* difference, not a math conflict.

2. **VAL (16% on trend-leg bars, <0.6% everywhere else).** AMTAnalyzer applies the **Task 2.3
   session-VA-vs-leg-VA clamp** (`quant/amt/analyzer.py:994-1006`): when the displacement-leg VAL
   is lower than the session VAL, session VAL is replaced by the leg VAL. On this session the clamp
   is active on bars 31–42 and 45–59 (27 of 56 bars), flooring VAL at the leg VAL (82.91 at bar 49)
   vs core 98.98. **This is a deliberate AMT decision-engine feature** (`quant.core` has no leg
   analysis at all). Excluding clamp bars, VAL max divergence is 0.577% (mean 0.459%).

3. **VWAP (16% as-fed → 0.14% with ISO times).** The as-fed 16% is entirely the non-ISO `t{i}`
   artifact (per-bar session reset). Genuine divergence is 0.14% and comes from **definition**:
   `quant.core` is close-weighted VWAP (`Σ close·vol / Σ vol`), `quant.amt` is typical-price-weighted
   (`Σ (H+L+C)/3·vol / Σ vol`).

4. **IB high/low (16% as-fed → 0% with ISO times).** Same artifact; with realistic timestamps both
   engines compute the identical IB (101/99 from the first 6 5-min bars). The two *models* differ
   (`quant.core`: bar-count window = 6 bars; `quant.amt`: wall-clock 30-min window) — they coincide
   on 5-min bars but would diverge on irregular bar cadence. `quant.core` also marks IB complete one
   bar earlier (55/56 vs 50/56 bars on the ISO run).

5. **CVD / delta.** The stock synthetic session carries `delta == 0` on every bar, so raw CVD is 0 on
   both sides (agreement, trivially). With `delta = buy − sell` enriched, **CVD value matches exactly**
   (both are running sums of bar delta). CVD **slope** diverges because the windows/filters differ
   (`quant.core`: OLS over 20 bars, no filter; `quant.amt`: OLS over 40 bars + sign-persistence
   filter). Per-bar delta is not a valid cross-engine overlap: `quant.core` exposes last-bar delta via
   `OrderFlowState.delta`; `AMTResult` exposes no comparable per-bar delta (`delta_normalized_option`
   is option-tick-only).

6. **Incidental finding.** `OHLC.create()` (Decimal coercion) breaks `AMTAnalyzer` —
   `AcceptanceRejectionEngine` compares `candle.volume` (Decimal) with a float and raises
   `TypeError`. The harness must build `OHLC` with raw floats (as `tests/quant/amt/test_analyzer.py`
   does). Latent bug worth its own ticket, not fixed here (no production changes allowed).

## 5. Decision

**KEEP BOTH**, with a documented divergence budget. No unification.

Rationale:
- `quant.core` is the byte-compatible real-time `auction`-WS producer, frozen by the golden-file
  test — replacing it with `quant.amt` would change the frontend contract (different POC/VAH bin
  edges, different VWAP definition, different IB timing).
- `quant.amt` is the full-featured decision engine (leg analysis, LVN/HVN, aggression, NPOC, drives,
  IB-break). Its extra outputs have no `quant.core` counterpart.
- On the overlapping core math the two agree well: POC ≤ 0.99%, VAH ≤ 0.64%, VAL ≤ 0.58% outside the
  intentional leg-VA clamp. VWAP agrees to 0.14% (definitional difference only). IB agrees to 0% on
  realistic timestamps. CVD value agrees exactly.
- The only field breaching the >5% trigger is **VAL**, and only on trend-leg bars, and the cause is a
  **deliberate** AMT feature (Task 2.3 leg-VA clamp), not a defect — so it does not argue for
  unification. The apparent >5% VWAP/IB deltas are synthetic-harness artifacts (non-ISO `t{i}` labels).

### Divergence budget (enforced by `tests/quant/unification/test_auction_vs_amt.py`)

| field | budget | note |
|---|---|---|
| poc | ≤ 5% | measured 0.99% max |
| vah | ≤ 5% | measured 0.64% max |
| val | ≤ 5% *except* Task-2.3 leg-VA clamp bars | measured 0.58% max outside clamp bars |
| vwap | ≤ 1% (ISO-timestamped reference) | measured 0.14% max (close- vs typical-price VWAP) |
| ib_high / ib_low | ≤ 0.1% (ISO reference) | measured 0.00% |
| cvd value | exact (≤ 1e-6) | measured 0.00 |
| cvd_slope | no % budget (scale-invariant) | measured max \|Δ\| 36.6 — window/filter config difference |
| delta | n/a | not a valid overlap — `AMTResult` exposes no per-bar delta |

### Open item (recommended follow-up, not a blocker)
- Track the Task-2.3 leg-VA VAL clamp (`analyzer.py:994-1006`) as the single known >5% divergence.
  Validate its behavior against a live trending NIFTY session before any future unification work. If
  it is ever found to distort VAL for the frontend, gate it behind an AMT-only path rather than
  changing `quant.core`.
- Fix `OHLC.create()` Decimal/float incompatibility with the AMT engine (separate ticket).
- When a shared contract layer is desired later, the cheap unification is a shared `create_profile`/
  `compute_value_area` in `quant.amt.profile` (or `quant.contracts`) adopted by `quant.core` — it
  would collapse the sub-1% POC/VAH/VAL bucketing divergence without touching the WS shape.

## 6. Reproduce

```bash
cd /Users/apple/Documents/wt-gt-P27
/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant/unification -q --tb=short -s
```

(`-s` prints the delta table in §3.)
```
