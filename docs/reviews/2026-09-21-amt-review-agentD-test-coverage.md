# Agent D — Test Coverage Review vs `docs/amt`

**Scope**: `docs/amt/` only (AMT_INSTITUTIONAL_SCALPER_ALGORITHM.md, fabio_decision_pipeline.md,
multi_symbol_isolation.md) + actual source under `quant/` and `tests/`.
All other `docs/` directories were treated as forbidden historical agent output and not read.

**Reviewer**: Agent D (Test Coverage Strength vs AMT Spec)
**Date**: 2026-09-21
**Branch**: `architecture/design-level-refactoring`

---

## Test Suite Baseline (real numbers from the run)

Command: `python -m pytest tests/quant tests/architecture -q --no-header`

| Directory | Passed | Failed | Skipped | Errors |
|---|---|---|---|---|
| `tests/quant` | 2542 | 0 | 11 | 0 |
| `tests/architecture` | 38 | 0 | 0 | 0 |
| **Total** | **2580** | **0** | **11** | **0** |

Exit code 0. Wall time ~208s (`tests/quant`) + ~4.7s (`tests/architecture`).

**Failures**: none. A 2580/2580 green suite is the core problem statement of this
review: the suite is green, but as shown below, several load-bearing AMT spec
constants and threshold boundaries are *never asserted anywhere in `tests/`*.
Green here measures plumbing, not spec conformance.

---

## Verdict: FAIL

The suite is green and structurally healthy (real event-store replays, real
determinism harnesses, honest skips with written justifications). But on the
specific question this review was assigned — *does the test suite prove the AMT
spec rules hold?* — it fails on the highest-value rules in the document:

1. **Three spec constants are absent from the entire codebase**, and the one test
   file that exists for these constants asserts values that **contradict** the
   spec (`tests/quant/contracts/test_fabio_constants.py`).
2. **The spec's named CVD velocity operator does not exist in production code**
   (no EMA3/EMA9 anywhere in `quant/`), so it cannot be covered at all.
3. **Rule 14 (multi-symbol isolation) requirement 3 — PortfolioRiskAuthority
   cross-engine risk aggregation without double-counting — has no test.**
4. **Rule 16 (data-honesty) is violated by the absorption tests**: production
   runs on the delta-proxy branch, tests feed the `taker_buy_volume` branch.

The gaps are concentrated in exactly the places where a silent numeric drift
would cost money and no test would catch it.

---

## Spec Rule Coverage Matrix

Legend: **Real** = asserts the spec value on production code.
**Partial** = asserts the rule shape but not the spec constant.
**Vacuous** = passes without testing the rule.
**Missing** = no test found.

| # | Spec Rule | Test File(s) | Real / Vacuous / Missing | Boundary cases? | Notes |
|---|---|---|---|---|---|
| 1 | §4 Range bars: quantize {5,10,25,50,100,200}; close High−Low≥H; next open=prior close | `tests/quant/amt/profile/test_range_bars.py:94-107` (`TestQuantize`), `:181-252` (`TestDynamicRangeBarAggregator`) | **Partial / Vacuous** | No | `_quantize` ladder tested only with a truncated `(5,10,25)` tuple, never the production `(2,5,10,25,50,100,200)` ladder. Close rule asserted only via `DynamicRangeBarAggregator` on **ticks**, and `DynamicRangeBarAggregator` is wired to **nothing** in production (zero non-test importers). `next_open = prior_close` never asserted. §16 admits range bars are not the decision driver — so the spec's §4 core is untested-in-production. |
| 2 | §5.1 POC=argmax; VA=68.2%; LVN 0.35×mean AND convexity | `tests/quant/amt/profile/test_volume_profile.py:63-167`; `tests/quant/amt/profile/test_lvn_detector.py:110-240` | **VA: Missing. POC: Real. LVN: Missing** | No | **`0.682` / `68.2` appears in zero test files and zero source files.** Every VA test passes `value_area_pct=0.70` explicitly or relies on the 0.70 default. LVN `0.35×mean` is gone too: `find_lvns` `lvn_threshold=0.15` is documented "kept for API compatibility (unused)" (`quant/amt/profile/lvn.py:133`), detection is now percentile-based (25th pct). `LVN_THRESHOLD=0.15` in config, spec says 0.35. Convexity (`d²V/dp²>0`) is absent from source and tests (grep for "convex" returns nothing). |
| 3 | §6.1 VWAP volume-weighted, sigma volume-weighted, bands ±1σ/±2σ | `tests/quant/amt/test_analyzer.py:365-402` (`TestVWAPBands`), `:828-870` (`TestVWAPSigmaBounds`); source `quant/amt/profile/vwap.py:196-216` | **Partial** | No | Band *ordering* is asserted (`u2≥u1≥vwap≥l1≥l2`) — real but weak. No test asserts the volume-weighted σ *formula* against an independently computed value, and no test asserts band *widths* equal 1σ/2σ. Bands are clamped (`min_std=max(1.0, vwap*0.001)`, `max_std=vwap*0.03`, deviation clamped to ±4σ — `vwap.py:150-211`); the clamp is tested for bounds but the σ formula itself is not. |
| 4 | §6.2 CVD velocity = EMA3−EMA9; LL/HL & HH/LH divergences | `tests/quant/amt/orderflow/test_cvd.py:45-53`; `quant/amt/compute.py:203-225` | **Missing (velocity) / Vacuous (divergence)** | No | **No EMA3/EMA9 exists in `quant/`** (grep for `ema`/`span=3`/`span=9` in `cvd.py` returns nothing; verified by inspection of `CVDTracker`). Velocity is a rolling linear slope instead. `test_divergence_bearish` (test_cvd.py:45-53) constructs arbitrary deltas and then asserts only `divergence_type in ("BEARISH_DIV","BULLISH_DIV","NONE")` — a **set-membership tautology** that cannot fail. No test constructs an actual LL+HL or HH+LH pattern and asserts the specific label. |
| 5 | §7.2 Absorption vol≥1.5×mean20, range≤0.5×H_range, 60% + close-position | `tests/quant/amt/orderflow/test_detectors.py:165-211`; `test_absorption_semantics_preserved.py:42-90`; source `detectors.py:356-394` | **Vacuous on constants / Partial on 60%** | **No** | The spec numbers are *not* the code numbers: production uses `ABSORPTION_VOL_MULT=2.0` and `ABSORPTION_RANGE_ATR=0.30` (constants.py:80-81), spec §7.2 says **1.5×** and **0.5×H_range**. Tests use `atr=1.0, avg_vol=200, volume=500` → vol_ratio 2.5, range_ratio 0.28: comfortably past both thresholds, never at/above/below. **No test anywhere asserts `0.60`** (grep for `0.60` in tests returns only unrelated option-delta comments). Close-position-in-bar (`close≥low+0.5×range`) is implemented (`detectors.py:382-388`) but untested. |
| 6 | §8 Triple-A: ALL THREE aggression conditions (close>cluster, VWAP side, CVD expanding) | `tests/quant/test_production_correctness.py:237-272` (`test_triple_a_machine_requires_cluster_close`); `quant/amt/triple_a.py:237-247` | **Partial** | No | The happy-path 4-phase progression is tested and is genuinely good. But the **joint-condition logic is undertested**: `_confirm_direction` requires `close>vwap` AND `cvd_slope>-0.3` for LONG. There is **no test where 2 of 3 conditions hold** (e.g. close>cluster AND close>vwap but cvd_slope=−0.5) asserting the machine resets instead of firing. The reset-on-non-confirm branch (`triple_a.py:196-197, 226`) has no dedicated test. |
| 7 | §9.1/9.2/9.3 SL = cluster±2×tick; RR≥1:2 (A); target=POC (B); RR≥1:3..1:5 (C) | `tests/quant/decision/test_signal_builder_sl.py:30-66`; `test_signal_builder.py:28-36`; `test_strategy_behavior.py:273-349` | **Real but weakened** | No | SL = anchor ∓ 2×tick is asserted numerically (`102.10`, `98.0−0.10`) — real. **But `assert s.rr >= 1.0`** (test_signal_builder.py:32) is weaker than spec's **1:2** for Playbook A; `MIN_RR_RATIO = 1.5` in constants, and `test_strategy_behavior.py:349` asserts only `tp in (129.9, 119.9)`. **No test asserts Playbook A RR≥2.0, Playbook C RR≥3.0, or Playbook B target==POC** as spec constants. |
| 8 | §10 Session timing: pre-market no-trade lock; EOD square-off; Mon/Fri defensive | `tests/quant/decision/test_gate1_exchange_clock.py:29-90`; `tests/quant/test_eod_square_off.py`; `tests/quant/execution/test_risk.py:134-155` | **Partial** (pre-market lock Missing as such) | No | Clock blackouts are well tested (boundary times included). But there is **no "pre-market trap lock = zero new entries" test**: the blackout is a side effect of the exchange-clock window, and Gate 1's setup-permission table is tested for trend/reversion but not for the strict no-trade rule. EOD square-off is genuinely well tested. Mon/Fri 0.5× is **Real** (`test_risk.py:134-155`, includes the Mon==Fri==0.5×Tue relation). |
| 9 | §12.2 Cushion: defensive min() clamp branch AND offensive 0.40×cushion branch; floor sizing | `tests/quant/execution/test_risk.py:25-131`; `test_sizing_invariants.py:54-91`; `test_certification.py:140-160` | **Partial / Vacuous on the spec formula** | No | **Neither spec branch is tested.** Production implements a different, tier-based scheme (`risk.py:533-600`): CONSERVATIVE 0.25%, CUSHION_TIER_1 0.35%+20%profit (cap 0.50%), MOMENTUM 0.40%. Spec §12.2 says offensive = `E0×0.0025 + 0.40×cushion` and defensive = `min(E0×0.0025, MDL−|cushion|)`. **No test asserts `0.40` as a cushion fraction** (grep finds `0.40` only as the MOMENTUM *percent* literal, a different quantity). The `min()` defensive clamp branch and `floor()` position-size formula are untested as spec formulas. |
| 10 | Circuit breakers: −2.0% MDL AND 3 consecutive losses, lock until next session | `tests/quant/execution/test_risk.py:25-36`; `test_strategy_behavior.py:352+` | **Partial** | No | 3-consecutive-loss halt is **Real** (`test_max_streak_halts`, incl. the subtle "partial fills don't reset the streak" and scratch cases — good). The **−2.0% MDL is not asserted as the number**: `test_max_loss_halts` uses `max_daily_loss_pct=0.03` and asserts a "kill switch" fired *earlier*, i.e. it proves a *different* (undocumented 2%) threshold exists rather than asserting `0.020`. `MAX_DAILY_LOSS_PCT=0.020` (constants.py:134) is never asserted by any test. "Lock until next session" (no re-arm intra-session) has no test. |
| 11 | §13.1 risk-zero at +0.8R | `tests/quant/execution/test_exits.py:201-212` (`test_breakeven_arms_at_08r_profit`); `test_certification.py:276,337` | **Real** | **No** | `risk=2.0; bar_close=101.7 → 0.8R=1.6` asserts BE arms. Genuinely good. Missing the boundary: `bar_close` at exactly 101.6 (=0.8R) and just below (1.59) to prove `>=` vs `>`. |
| 12 | §13.2 pyramiding: risk-free authorization, 50%/25% sizing, SL ratchet, net-positive bundle | `tests/quant/test_pyramid_certification.py:53-195` (E9/E10/E11); `position_manager.py:608-609` | **Real on invariants, Missing on 50/25** | No | E9/E10/E11 are the best-written tests in the suite (ghost prevention, SL ratchet, portfolio risk reservation). **But the 50%/25% sizing ratios are never asserted.** `fraction = 0.50 if pyramid_count == 0 else 0.25` (position_manager.py:608) is exercised only incidentally; no test asserts pyramid-1 size == 0.5×base and pyramid-2 == 0.25×base. "Net-positive bundle guarantee" is asserted only as an SL-equality proxy (E10). |
| 13 | §13.3 partial exits 50/25/25 | `tests/quant/execution/test_exits.py:28-49` | **Partial / Contradicts spec** | No | `TP1 partial_fraction == 0.5` and `TP2 partial_fraction == 0.5` are asserted — but that yields **50/50/0**, not spec's **50/25/25**: TP2 takes the *remaining* 50%, and there is no third 25% runner tier in `check_take_profit_tiers` (`exit_checks.py:82-111`; tier 2 is terminal). The tier-3 runner is a trailed stop, not a 25% partial. No test asserts the 25/25 split. |
| 14 | `multi_symbol_isolation.md` requirements 1-5 | `tests/quant/coordinator/test_multi_symbol_isolation.py:87-218` (req 1,2,5); `test_eod_square_off.py:134-162` (req 4) | **Req 3 Missing. Req 5 weakened** | n/a | Req 1 (state independence) **Real**; req 2 (decision independence) **Real**; req 4 (no EOD cross-contamination) **Real** (mixed-markets test, `test_eod_square_off_mixed_markets_only_flattens_past_due`). **Req 3 — PortfolioRiskAuthority aggregates without double-counting — has NO test** (grep finds no test asserting summed open risk across engines vs the ceiling; only single-engine register calls in `test_pyramid_certification.py:177-195`). Req 5 determinism exists but `_trace_fingerprint` (test_multi_symbol_isolation.py:69-75) **drops `AgentDecisionProduced` events and retains only (type, time)** — not byte-identical event traces as the spec requires. |
| 15 | `fabio_decision_pipeline.md`: Gate 1 five checks; Gate 2 thesis-flip cooldown; Gate 3 ten guards + six paths in priority order; Gate 4 stop cap; VA-fade | `test_gates_1_2.py`; `test_gate1_exchange_clock.py`; `test_gate1_phase_permissions.py`; `test_gate_pipeline_matrix.py:142-154`; `test_gate_triple_a_edge.py`; `test_gates_rr.py`; `test_va_fade.py` | **Real (mostly)** | Partial | Strongest-covered area. Gate 1's 5 checks all present; Gate 2 thesis-flip + cooldown-enforced tested (`test_gate_pipeline_matrix.py:142-154`) — **Real and correct**. Gate 3 guards and all six paths are tested, and CVD-slope guards have **genuine boundary cases** (−0.25 allowed / −0.35 blocked MCX; −0.40 allowed / −0.55 blocked NSE — `test_gate_triple_a_edge.py:168-222`, the only place in the suite with real at/above/below threshold discipline). **Missing: path PRIORITY order** — no test asserts path 1 preempts path 6 when both are complete. Gate 4's `max(200, entry×0.75%/tick)` cap formula is **not** asserted numerically (tests monkeypatch `structural_anchor`, `test_gates_rr.py:11,32`). VA-fade conditions 1-6 are covered. |
| 16 | §16 documented limitations: candle-delta proxy honesty | `test_detectors.py`, `test_absorption_semantics_preserved.py`, `test_footprint.py` | **Vacuous / Dishonest** | n/a | See next section. Tests exercise the `taker_buy_volume` branch, production runs the delta-proxy branch. |

---

## Defects Found

### D-D1 [CRITICAL] — The suite's one "constants" test asserts values that contradict the AMT spec

- **Spec rule:** §5.1 "Value Area (VA = 68.2% of Total Volume)"; §5.1 "LVN = {p | V(p) < 0.35×V̄_profile AND d²V/dp² > 0}"; §7.2 "V_b ≥ 1.50 × V̄_20" and "(H_b − L_b) ≤ 0.50 × H_range".
- **Coverage gap:** `tests/quant/contracts/test_fabio_constants.py:27-34` asserts:
  ```python
  assert FABIO_ABSORPTION_VOL_MULT == 2.0      # spec §7.2: 1.5
  assert FABIO_ABSORPTION_RANGE_ATR == 0.30    # spec §7.2: 0.5 × H_range
  assert FABIO_VALUE_AREA_PCT == 0.70          # spec §5.1: 0.682
  ```
  Every one of these three assertions **passes** while encoding a value the spec
  does not contain. This is worse than no test: it is a green test that
  *certifies* the drift. A future maintainer reading the spec and "fixing" the
  constant to 1.5 / 0.5 / 0.682 would **break this test** and likely "fix" the
  test back, inverting the spec-to-code relationship.
- **Why the existing test does not prove it:** it asserts against `constants.py`
  literals, not against the spec. Two of the three are annotated with a
  rationale that is actively wrong about the source document
  (`test_value_area_percentage` says "CME standard: 70% value area" — the AMT
  spec under review states 68.2% at `docs/amt/AMT_INSTITUTIONAL_SCALPER_ALGORITHM.md:128-130`).
- **What test to add:** a spec-authoritative test that reads the spec-declared
  constants and asserts the *production* constants equal them, e.g.
  `tests/quant/contracts/test_amt_spec_constants.py`:
  ```python
  # Spec §5.1
  assert VALUE_AREA_PCT == pytest.approx(0.682, abs=1e-6)
  # Spec §5.1 LVN
  assert LVN_THRESHOLD == pytest.approx(0.35, abs=1e-6)
  # Spec §7.2
  assert FABIO_ABSORPTION_VOL_MULT == pytest.approx(1.5)
  assert FABIO_ABSORPTION_RANGE_ATR == pytest.approx(0.50)
  ```
  Then either fix `constants.py`/`backend/config/base.yaml:25-27` to the spec
  values, or amend `docs/amt/` with a documented, dated deviation. **The current
  state — code at 2.0/0.30/0.70, spec at 1.5/0.5/0.682, tests certifying the
  code — is an unresolved spec contradiction with money on the line.**

### D-D2 [CRITICAL] — §6.2 CVD velocity (EMA3 − EMA9) does not exist in production, so it cannot be covered

- **Spec rule:** §6.2 "CVD Velocity = EMA₃(CVD) − EMA₉(CVD)"; bullish absorption divergence
  (price LL, CVD HL); bearish exhaustion divergence (price HH, CVD LH).
- **Coverage gap:** `quant/amt/orderflow/cvd.py` contains **no EMA of any span**
  (verified: `CVDTracker` holds `_cvd`, `_history`, `_price_history`,
  `_slope_window`; velocity is `_compute_slope()`, a rolling linear slope).
  Grep for `ema`, `EMA`, `span=3`, `span=9` across all of `quant/` returns **zero
  matches**. The spec's named operator is unimplemented.
- **Why the existing test does not prove it:** `tests/quant/amt/orderflow/test_cvd.py:45-53`
  (`test_divergence_bearish`) is **vacuous**:
  ```python
  assert state.divergence_type in ("BEARISH_DIV", "BULLISH_DIV", "NONE")
  ```
  This is a set-membership tautology — `_detect_divergence` can only ever return
  one of those three strings, so the assertion cannot fail on any input. The
  test constructs arbitrary deltas (`20-i`, `10-3i`) that do not form a real
  HH/LH or LL/HL structure, and never asserts which label results.
- **What test to add:** (a) implement EMA3/EMA9 velocity in `CVDTracker` or
  document the substitution in `docs/amt/` §16; (b) add
  `tests/quant/amt/orderflow/test_cvd_velocity.py` asserting
  `velocity == ema3 − ema9` against an independent EMA implementation on a
  hand-computed series; (c) replace the tautological divergence assertion with
  two fixture-driven tests: price LL + CVD HL → `BULLISH_DIV`, price HH + CVD LH
  → `BEARISH_DIV`, plus a no-divergence control.

### D-D3 [HIGH] — §7.2 absorption thresholds have zero boundary coverage, and the 60% directional rule is untested

- **Spec rule:** §7.2 `V_b ≥ 1.50×V̄_20`, `(H_b−L_b) ≤ 0.50×H_range`,
  `V_sell,b ≥ 0.60×V_b and Close_b ≥ Low_b + 0.50(H_b−L_b)`.
- **Coverage gap:** grep for `0.60` across `tests/` returns only unrelated
  option-delta comments — **the 60% concentration rule is never asserted**.
  `quant/amt/orderflow/detectors.py:385-388` implements it (plus the
  close-position-in-bar test at `:382-388`), but no test covers it. Every
  absorption test sits far inside the accept region
  (`test_detectors.py:172`: vol 500 / avg 200 = 2.5×; range 0.28 / ATR 1.0 = 0.28×).
  No test exists at `vol_ratio == 2.0`, `2.0±ε`, `range_ratio == 0.30`, `0.30±ε`,
  `sell_vol == 0.60×vol`, `0.59×`, `0.61×`.
- **Why the existing test does not prove it:** `test_detects_absorption`
  (`test_detectors.py:168-179`) proves "a strongly obvious absorption is
  detected", which would also pass if the thresholds were 1.1×/0.9×/0.5 — it
  does not pin the numbers. `test_no_absorption_low_volume` uses vol 200 vs
  avg 200 (ratio exactly 1.0), which is far below both 1.5 and 2.0, so it cannot
  discriminate between them.
- **What test to add:** a parametrized boundary matrix in
  `tests/quant/amt/orderflow/test_absorption_thresholds.py`:
  ```python
  @pytest.mark.parametrize("vol_ratio", [1.99, 2.0, 2.01])   # ±ε at the code threshold
  @pytest.mark.parametrize("range_ratio", [0.29, 0.30, 0.31])
  @pytest.mark.parametrize("sell_frac", [0.59, 0.60, 0.61])
  ```
  with explicit expected `detected`/`active` outcomes per cell, plus a
  close-position case where `sell_vol≥0.60` but close is in the *lower* half
  (must NOT classify, per `detectors.py:385-388`).

### D-D4 [HIGH] — §16 data-honesty violation: absorption tests exercise the `taker_buy_volume` branch that production never supplies

- **Spec rule:** §16 "Known Data Limitations — Tick-Level Footprint: The current
  implementation uses **candle delta** (close-to-close) as a proxy for buy/sell
  volume. True trade-level aggression flags require a tick feed not available
  from the current Dhan integration."
- **Coverage gap:** `quant/amt/orderflow/detectors.py:366-378` branches:
  ```python
  taker_buy = float(getattr(candle, "taker_buy_volume", 0.0) or 0.0)
  if 0.0 < taker_buy < candle_vol:
      buy_vol = taker_buy; sell_vol = candle_vol - taker_buy   # LIVE branch
  else:
      delta_val = float(candle.delta)                          # PRODUCTION branch
      buy_vol = (candle_vol + delta_val) / 2.0
      sell_vol = (candle_vol - delta_val) / 2.0
  ```
  Grep confirms **no broker-layer code ever populates `taker_buy_volume`**
  (`brokers/` has zero references; the only producers are `quant/amt_engine.py`
  reading it from history dicts, `quant/state.py:154` writing it from
  `bar.buy_volume`, and test fixtures). In production the field defaults to
  `Decimal("0")` (`value_objects.py:33`), so **every live candle takes the
  delta-proxy branch**. Yet the tests that cover the 60% directional rule feed
  `taker_buy_volume` explicitly:
  - `tests/quant/amt/orderflow/test_footprint.py:20,46,55` (`600`, `3000`, `8000`)
  - `tests/quant/amt/orderflow/test_analyzer_flow_propagation.py:20`
  - `tests/quant/amt/orderflow/test_directional_compute.py:25`
  - `tests/quant/amt/test_amt_engine_properties.py:42`
  - `tests/quant/amt/test_analyzer.py:42,431`
- **Why this is the "tests that could be lying" case from the assignment:** the
  tests construct buy/sell splits that are internally consistent
  (`taker_buy=600, delta=200` ⇒ buy 600 / sell 400, matching delta). Production
  data has `taker_buy_volume=0`, so the split is *derived*: `buy=(vol+delta)/2`.
  For a real candle with `vol=500, delta=−400` production computes
  buy=50/sell=450 (9:1), whereas the test path would report whatever the
  (nonexistent) feed said. **The 60% rule is therefore validated on data shapes
  production can never receive.** Worse, the proxy has a known pathology the
  tests never probe: when `|delta| > vol` the code clamps
  (`detectors.py:374-378`), which silently manufactures a 100/0 split and
  trivially satisfies the 60% condition.
- **What test to add:** `tests/quant/amt/orderflow/test_absorption_production_data.py`
  that runs `AbsorptionDetector` with `taker_buy_volume` **absent/zero** only,
  covering: (a) a normal delta candle; (b) `|delta| == vol` (clamped to 100/0 —
  assert whether a one-sided classification is desirable, and that it is what
  production will see); (c) `delta` and `taker_buy_volume` *disagreeing*, to
  document which wins. Add an assertion in the existing footprint tests that
  they are testing the live-data branch and a companion test for the proxy branch.

### D-D5 [HIGH] — Rule 14 req 3: PortfolioRiskAuthority cross-engine aggregation has no test

- **Spec rule:** `multi_symbol_isolation.md` "Testing requirements ... 3. **Risk
  aggregation correctness**: PortfolioRiskAuthority correctly aggregates risk
  across engines without double-counting"; and "The sum of all engines' open
  risk must not exceed the portfolio ceiling. This is the ONLY cross-engine
  coupling in the decision path."
- **Coverage gap:** no test asserts the aggregate invariant. The closest tests
  are single-engine: `tests/quant/test_pyramid_certification.py:149-195` (one
  pyramid registering with one authority) and `test_stress_and_portfolio_risk.py`.
  There is no test with two or more engines drawing against one
  `PortfolioRiskAuthority` asserting (a) `sum(open_risk) <= ceiling`, (b) no
  double-counting of the same position across `register_open`/`record_exit`.
- **Why the existing test does not prove it:** `test_e11_portfolio_cap_blocks_over_pyramid_exposure`
  (`test_pyramid_certification.py:177-195`) registers base + P1 + P2
  **sequentially on one engine** and asserts each `can_accept` — it proves the
  cap decrements, not that two engines concurrently can't overspend the shared
  ceiling (the actual isolation hazard, since the authority is the sole
  cross-engine coupling and is shared by design).
- **What test to add:** `tests/quant/coordinator/test_portfolio_risk_aggregation.py`:
  build N=4 fake engines sharing one `PortfolioRiskAuthority`, each requesting
  `ceiling/N + ε`; assert exactly N−1 succeed, `open_risk == Σ registered`, no
  entry is counted twice after a partial close, and `record_exit` releases
  exactly the reserved amount.

### D-D6 [MEDIUM] — Rule 14 req 5: determinism test filters out the events that matter

- **Spec rule:** `multi_symbol_isolation.md` req 5: "**Determinism**: Two runs
  with the same per-symbol tick streams produce identical event traces per symbol."
- **Coverage gap:** `tests/quant/coordinator/test_multi_symbol_isolation.py:69-75`:
  ```python
  def _trace_fingerprint(trace: list) -> str:
      sync = [e for e in trace if not isinstance(e, AgentDecisionProduced)]
      payload = json.dumps([(type(e).__name__, getattr(e, "time", "")) for e in sync], sort_keys=True)
  ```
  It (a) **drops** `AgentDecisionProduced` — precisely the events where a
  decision could diverge, and (b) retains only `(type_name, time)`, discarding
  every field: entry/sl/tp/size/reason. Two runs producing a LONG at 105 with SL
  98 and a SHORT at 105 with SL 112 at the same timestamp fingerprint
  **identically**. `tests/determinism/test_golden_tape_replay.py:109-131` is
  byte-identical (SHA-256 over `last_checksum`) but only replays a
  hand-authored tape of 6 events (`create_golden_tape`, `:38-106`) — it never
  runs an engine, so it proves the EventStore hash is stable, not that the
  decision pipeline is.
- **What test to add:** hash the **full serialized event payload** (all fields)
  including `AgentDecisionProduced`, over a replay that actually produces a
  trade, e.g. reuse `tests/quant/test_certification.py:162-177` (`test_s13_ten_run_determinism`,
  which does hash decision records) and extend it to assert signal fields
  (entry/sl/tp/size) match across runs.

### D-D7 [MEDIUM] — §12.2 cushion formula: neither spec branch is tested

- **Spec rule:** §12.2
  `RiskDollars = min(E0×0.0025, MDL−|Cushion|)` if `Cushion ≤ 0`;
  `= (E0×0.0025) + 0.40×Cushion` if `Cushion > 0`;
  `PositionSize = floor(RiskDollars / (|entry−SL| × Multiplier))`.
- **Coverage gap:** production implements a different tier system
  (`quant/execution/risk.py:533-600`: CONSERVATIVE 0.25% / CUSHION_TIER_1
  0.35%+20%profit capped 0.50% / MOMENTUM 0.40% / BASE_RETRACEMENT_VETO 0.25%).
  No test asserts `0.40` as a *cushion fraction* (grep finds `0.40` only as the
  MOMENTUM percent literal at `test_risk.py:129-131`, a different quantity).
  The defensive `min(...)` clamp branch is never exercised: no test sets
  `daily_pnl < 0` and asserts risk is *reduced* by the remaining MDL budget.
  `floor()` is never asserted (tests use `pytest.approx`, which would also pass
  a `round()`; `test_risk.py:44,61`).
- **What test to add:** a test per branch: (a) cushion>0 → assert
  `risk_dollars == E0*0.0025 + 0.40*cushion` exactly; (b) cushion<0 with
  `|cushion|` near MDL → assert the `min()` clamps to the remaining budget and
  *not* to base risk; (c) `position_size` with an integral and a fractional
  risk/per-unit ratio → assert `floor`, not `round`. Then reconcile with the spec
  (the tier system and the spec formula are not equivalent — this must be
  resolved in `docs/amt/` or `risk.py`).

### D-D8 [MEDIUM] — §9 playbooks: RR ratios and POC target never asserted as spec constants

- **Spec rule:** §9.1 TP1 `R:R ≥ 1:2.0`; §9.3 `R:R ≥ 1:3.0` to `1:5.0`;
  §9.2 target = Session POC, 100% exit.
- **Coverage gap:** `tests/quant/decision/test_signal_builder.py:32` asserts
  `s.rr >= 1.0`; `MIN_RR_RATIO = 1.5` (constants.py:123) is the production
  guard. **No test asserts `rr >= 2.0` for Playbook A, `rr >= 3.0` for
  Playbook C, or `tp == poc` for Playbook B.** `test_strategy_behavior.py:310-349`
  asserts `tp in (129.9, 119.9)` (structural + shielded) but never `rr >= 3.0`.
- **What test to add:** playbook-parametrized tests asserting the minimum RR per
  playbook and, for B, `signal.tp == pytest.approx(poc)` with a documented
  shield offset.

### D-D9 [MEDIUM] — §13.3 partial-exit ladder is 50/50/0 in code, not 50/25/25 in spec

- **Spec rule:** §13.3 "Tier 1 (50% Size) ... Tier 2 (25% Size) ... Tier 3 (25% Runner)".
- **Coverage gap:** `quant/execution/exit_checks.py:82-111` returns
  `partial_fraction=0.5` at both TP1 and TP2, and tier 2 is terminal (no third
  partial). `tests/quant/execution/test_exits.py:28-41` asserts both 0.5s — so
  the tests confirm a **50/50/0** ladder while the spec says **50/25/25**.
  After TP1 the remaining 50% exits wholly at TP2; the 25% runner is a trailed
  stop, not a partial tier.
- **What test to add:** assert the residual-size arithmetic: after TP1 the
  position retains 50%; after TP2 it should retain 25% and a runner tier should
  exist. Either implement the third tier or document the deviation in §16.

### D-D10 [MEDIUM] — §10 pre-market trap lock: no test asserts the strict no-trade rule

- **Spec rule:** §10 / §15 row 2: "Pre-Market Lock (10–20 Minutes Before Open):
  **STRICT RULE: Zero new entries permitted.**"
- **Coverage gap:** `tests/quant/decision/test_gate1_exchange_clock.py:29-52`
  tests the exchange clock window (NSE 09:30–15:15, MCX 09:15–23:15), which
  *incidentally* excludes pre-market. But Gate 1 has **no explicit pre-market
  lock state** — the spec's 10–20 minute pre-open trap zone is not modeled as a
  distinct rule, and no test asserts "an otherwise-perfect setup is rejected
  solely because current time is in the pre-market trap window."
- **What test to add:** a test constructing a fully-passing DecisionContext
  whose only failure is `time_str` inside the pre-open window, asserting
  rejection with a "pre-market" reason; or amend `docs/amt/` §16 to record that
  the exchange-clock blackout subsumes the pre-market lock.

### D-D11 [LOW] — §8 aggression trigger: joint-condition and non-confirm paths undertested

- **Spec rule:** §8 ACCUMULATING→AGGRESSION requires **all three**: close beyond
  cluster AND price on the correct VWAP side AND CVD expanding.
- **Coverage gap:** `tests/quant/test_production_correctness.py:237-272` covers
  the all-three-conditions happy path. There is no test for 2-of-3 (e.g.
  breakout beyond cluster and close > VWAP, but `cvd_slope = −0.5`) asserting
  the machine **resets** rather than firing — the branch at
  `quant/amt/triple_a.py:196-197` and `:226`. `_confirm_direction`'s CVD bounds
  (`> -0.3` LONG / `< 0.3` SHORT, `triple_a.py:243-246`) are hardcoded and
  untested, unlike the Gate 3 CVD guards which are properly parameterized
  (`test_gate_triple_a_edge.py:168-222`).
- **What test to add:** a parametrized test over `(close_vs_cluster,
  close_vs_vwap, cvd_slope)` with the 6 non-trivial combinations asserting
  AGGRESSION or reset, plus boundary CVD slopes at −0.3/+0.3.

### D-D12 [LOW] — §1 quantize ladder tested with the wrong tuple; range bars unwired

- **Spec rule:** §4 `H_range = Quantize(H_raw, {5,10,25,50,100,200})`.
- **Coverage gap:** `tests/quant/amt/profile/test_range_bars.py:94-107` tests
  `_quantize` only against `(5,10,25)`. The production ladder is
  `_DEFAULT_QUANT_STEPS = (2, 5, 10, 25, 50, 100, 200)` — note the leading **2**,
  which is not in the spec's set and is never asserted. Separately,
  `DynamicRangeBarAggregator` and `ATRRangeCalculator` have **zero non-test
  importers** in `quant/`, and §16 states range bars are not the decision driver;
  so `test_range_bars.py` is testing an unwired component.
- **What test to add:** assert `_quantize` against the production tuple (and
  decide whether `2` belongs), plus a test that `open_{t+1} == close_t` on bar
  formation. If range bars are intentionally off the decision path, record it
  in §16 (it partially is) and mark these tests as component-level.

---

## Tests That Could Be Lying (production-data mismatch)

The clearest instance is **D-D4** above. Summary of every test file that feeds
data production can never receive, and the honest production alternative:

| Test file:line | What it feeds | Production reality |
|---|---|---|
| `tests/quant/amt/orderflow/test_footprint.py:20,46,55` | `taker_buy_volume=600/3000/8000` with matching delta | `taker_buy_volume` is `Decimal("0")` by default (`value_objects.py:33`); no broker code sets it |
| `tests/quant/amt/orderflow/test_analyzer_flow_propagation.py:20` | `taker_buy_volume=50.0` | same |
| `tests/quant/amt/orderflow/test_directional_compute.py:25` | `taker_buy_volume=50.0` | same |
| `tests/quant/amt/test_amt_engine_properties.py:42` | `taker_buy_volume=600.0` | same |
| `tests/quant/amt/test_analyzer.py:42,431` | `taker_buy_volume=(volume+delta)/2` — **derived to be consistent with delta by construction** | production derives from delta anyway; the test's value adds nothing but makes the fixture look richer than the feed |
| `tests/quant/amt/market/test_structure.py:23`, `test_lvn_play.py:11`, `test_break.py:11`, `test_opening.py:11` | `taker_buy_volume=0.0` (honest) | these are the honest ones |

The `taker_buy_volume`-based footprint/absorption tests are not *wrong* — they
would be correct if the Dhan feed supplied taker volume. They are
**premature**: they lock in behavior for a data path that does not exist, while
the path that actually runs (the delta proxy, including its `|delta|>vol` clamp
that manufactures a 100/0 split) has no dedicated test. §16 is explicit that the
proxy is the production reality; the tests should be organized the same way.

A second, milder honesty issue: `tests/quant/test_portfolio_risk_guard.py:62,110`
and several `tests/quant/execution/*` tests construct `ExitDecision` via
`MagicMock` return values — acceptable for OMS plumbing, but they do not
constitute exit-rule coverage and are not counted as such in the matrix above.

---

## Summary of Skip Reasons

All 11 skips, with file:line and the reason text from the run:

| # | Location | Reason (verbatim/condensed) | Spec area affected |
|---|---|---|---|
| 1 | `tests/quant/amt/market/test_state_engine.py:135` | "Zone classification boundary changed" | §5 profile zone logic — the skip is a *symptom* of the boundary drift this review flags in D-D1/D-D3 |
| 2 | `tests/quant/amt/session/test_scanner.py:304` | "Pre-existing option scanner assertion (NIFTY auto-detects as NFO)" | §3 data ingestion (option scanner) |
| 3 | `tests/quant/chaos/test_crash_recovery.py:378` | "Synthetic torn-state probe: ... Python cannot prevent direct internal mutation ... EventStore documented not thread-safe" | event-store integrity; honest, well-argued |
| 4-5 | `tests/quant/contracts/test_aggregates.py:323,328` | "check_time_stop_with_price deleted; covered by exit_checks tests" | §13.3 exits — deletion, covered elsewhere |
| 6-9 | `tests/quant/performance/test_load.py:104,166,271,464` | Timing aspirations (<5µs, <1µs) unmet on shared hardware due to HMAC-SHA256 / uuid4 / frozen-dataclass costs; "Environment-bound, not a correctness defect" | performance, not spec |
| 10 | `tests/quant/probability/test_feature_alignment.py:20` | "poc3 indicator parquets not available" (skipif) | TimesFM advisory layer |
| 11 | `tests/quant/test_certification.py:141` | "scenario did not fill; risk math covered by unit tests" | **§12.2 sizing** — the one spec-relevant skip. It is the sizing-certification scenario, and the fallback claim ("risk math covered by unit tests") is exactly the coverage D-D7 shows to be incomplete. |

**No `xfail` markers** were found in `tests/quant`, `tests/architecture`, or
`tests/determinism`. One module-level skipif exists (`tests/quant/test_property_based.py:18`,
`hypothesis not installed`) — outside the two reviewed directories but relevant:
the property-based test module is entirely inert, so the suite has **no
randomized threshold probing** anywhere, which is part of why the boundary gaps
in D-D1/D-D3/D-D7 went unnoticed.

---

## Closing note on what the suite does well

To be fair to the maintainers: the weakest areas above are numeric-threshold
areas. The state-machine and plumbing areas are genuinely strong —
`test_pyramid_certification.py` (E9/E10/E11) tests real money-critical
invariants with the OMS rather than mocks; `test_eod_square_off.py` tests
idempotency, error swallowing, and mixed-market deadlines properly;
`test_gate_triple_a_edge.py:168-222` is the single best example of boundary
discipline in the repo; `test_golden_tape_replay.py` and
`test_multi_symbol_isolation.py` are real replay harnesses, not mock theatres.
The skips carry written justifications rather than silent `pass`.

The failure is concentrated and fixable: **assert the spec's numbers, at the
spec's boundaries, on the production data path.**
