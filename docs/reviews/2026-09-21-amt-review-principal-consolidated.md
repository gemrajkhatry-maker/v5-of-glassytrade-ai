# AMT Implementation Review — Principal Engineer Consolidated Verdict

**Date:** 2026-09-21
**Branch:** `architecture/design-level-refactoring` (commit `e589cbe5a`)
**Authoritative spec:** `docs/amt/` ONLY (8 files, 3,284 lines). All other `docs/`
directories were treated as forbidden historical agent output and were not read.
**Code under review:** `quant/` (~190 files, ~39,747 lines) + `backend/` engine-touching files.

**Method:** five specialist review agents (core math, Triple-A/decision, risk/execution,
test coverage, integration seams) working from `docs/amt` only, plus a principal-level
independent verification pass on every CRITICAL and HIGH finding. Each finding below was
re-checked by the consolidating principal against the spec text and the code.

**Test baseline (unchanged throughout the review):** `tests/quant` + `tests/architecture`
→ **2580 passed, 11 skipped, 0 failed**, exit 0.

---

## VERDICT: FAIL

The system is not correctly implemented and tested against `docs/amt`.

The codebase is not broken — the suite is green, the plumbing is sound, the delta sign
convention is consistent end-to-end, the Triple-A machine is genuinely live, multi-symbol
isolation holds, and EOD square-off is double-enforced. What is broken is the **contract
between the specification and the code**: load-bearing spec constants, predicates, and
safety guards are absent, inverted, or silently disabled, and the test suite asserts the
*wrong* values in the places that matter most.

**Defect totals: 45** — **6 CRITICAL**, **17 HIGH**, **18 MEDIUM**, **4 LOW**
*(Two downgrades, both recorded transparently: C2 CRITICAL→MEDIUM — `session_extreme_*`
has a wick fallback, so it degrades stop quality rather than disabling the guard; and
C4 CRITICAL→M18 MEDIUM — the net-negative-bundle headline was **refuted by executing**
the real `PositionManager` end-to-end: the exit price is the breakeven floor that
authorized the pyramid, not the ratcheted SL.)*

Three failure modes dominate, and they are the dangerous ones:

1. **A silent fail-open guard, plus a larger dead subsystem.** One DecisionContext field
   consumed by a Gate 3 safety veto has **no producer anywhere in the codebase** and is read
   via `getattr(ctx, "cvd_divergence", "")`, so the guard sees "no conflict" on every bar of
   every session — a typo can disable a veto (C1). Two sibling fields are also unproduced but
   have **wick fallbacks**, so they degrade rather than disable (C2, downgraded). And a whole
   bias subsystem — resolver, threshold constant, and a complete `_apply_bias_override()` —
   is unreachable dead code with zero callers (C3).
2. **Spec constants replaced by different constants, then certified by green tests.**
   The absorption thresholds, the Value Area percentage, the LVN predicate, the cushion
   formula, and the exit ladder all use values the spec does not contain — and the one
   constants test in the suite *asserts the wrong values as correct*. (D-A2, D-A3, D-A6,
   D-C1/D-D7, D-D1)
3. **A money-path guarantee that is not implemented as specified.** The spec's pyramiding
   guarantee ("the entire trade bundle is guaranteed a net positive cash payout") is *not*
   delivered by the ratchet the spec names — it is delivered, accidentally, by the
   breakeven floor. The ratchet itself is dead state. (D-C4 → downgraded to M18; see
   correction.)

None of these is caught by any test. A green suite here measures plumbing, not
spec conformance.

---

## CRITICAL (7 confirmed + 1 downgraded) — fix before any live deployment

### C1. `cvd_divergence` gate input is dead code — the divergence veto fails open
**Spec:** `fabio_decision_pipeline.md:106-107` — Gate 3 CVD-conflict guard family.
**Code:** `quant/decision/gates_edge.py:200-205` reads `getattr(ctx, "cvd_divergence", "")`.
**Producer:** none. `quant/decision/context.py` declares **no such field** (verified by
construction: `hasattr(ctx, "cvd_divergence")` → `False`). `context_builder.py` never
sets it (verified by AST-level field-coverage diff of `build()`). The analyzer *does*
compute real divergences (`quant/amt/compute.py:221-224`, genuine half-window swing
comparisons — correct), and the DTO carries `"cvdDivergence"` (`dto.py:170`), but
`context_builder.py` never reads that key (verified by grep).
**Impact:** the guard is `""` on 100% of bars, so the divergence-alignment veto can never
fire. Silent fail-open on a Gate 3 safety guard.
**Fix:** add `cvd_divergence: str = ""` to `DecisionContext`; map `dto["cvdDivergence"]`
in `context_builder.build()` (the strings already match: `BULLISH_DIV`/`BEARISH_DIV`).

---

### C2. `session_extreme_low`/`session_extreme_high` declared, consumed, never produced — *(DOWNGRADED to MEDIUM, see note in body)*
**Spec:** `fabio_decision_pipeline.md:166-167` (VA-fade condition 2: "A probe beyond the
VA edge was rejected: `session_extreme_low < VAL` / `session_extreme_high > VAH`").
**Code:** declared `quant/decision/context.py:168-169`; consumed
`quant/decision/va_fade.py:64-65` via `getattr(ctx, "session_extreme_low", 0.0) or 0.0`.
**Producer:** none — not set by `context_builder.py` (verified by AST-level field-coverage
diff of `build()`), not in the DTO (`amt_result_to_dto` has no such keys).

**Impact — CORRECTED on re-inspection; this is NOT a fail-open guard.**
`va_fade.py:68-69` falls back to the current bar's wick when the tracker reads zero:
```python
probe_low  = session_low  if session_low  > 0 else (bar_low  if bar_low  < val else 0.0)
probe_high = session_high if session_high > 0 else (bar_high if bar_high > vah else 0.0)
```
so the fade still detects a single-bar failed auction and places a stop beyond it. What is
lost is only the spec's "across all session bars" breadth: the stop references the last
bar's probe instead of the session's true probe extreme, so on a multi-bar failed auction
the stop can sit *inside* the real probe and be stopped out by continuation. This degrades
stop quality; it does not disable the guard. A second independent route reaches the same
fade — the analyzer's complete `VA_FADE` evidence packet (`va_fade.py:46-60`, satisfied when
`rejection and not acceptance and cvd_agrees`; verified constructible via
`context_builder.py:281-285` and `SetupEvidence.is_complete()` returns `True`), which does
not read the session extremes at all.
The `or 0.0` double-default remains a latent hazard: adding the field as `None` later would
still read `0.0` and silently take the wick path.
**Severity: CRITICAL → MEDIUM** (stop-quality degradation, not a disabled safety guard).
**Fix:** emit `sessionExtremeLow`/`sessionExtremeHigh` in `amt_result_to_dto` from the
analyzer's tracked session high/low; map them in `context_builder`.

### C3. `bias_direction` / `bias_confidence` never resolved — `BiasResolver` imported, never used
**Code:** `quant/decision/context.py:162-163` declares both (defaults `NEUTRAL` / `0.0`,
verified by construction). `quant/decision/context_builder.py:12` imports `BiasResolver`,
and `:14` imports `FABIO_BIAS_OVERRIDE_THRESHOLD`, `:46` aliases it, `:49-66` implements a
complete `_apply_bias_override()` — and **none of it is reachable**: the function has zero
callers (verified by grep across `quant/`), `BiasResolver` is never constructed outside
`quant/amt/bias/`, and no live path calls `resolve_bias`. Verified: the only consumers of
`bias_direction`/`bias_confidence` are the two dataclass defaults in `context.py:162-163`.
**Impact:** a declared top-down bias layer with a resolver, a threshold constant, a
fully-written override function, and **zero producers and zero callers**. The dead code is
larger than a dangling import — the entire bias subsystem, including its threshold, is
unreachable. Unlike C1/C2 there is no gate reading these fields, so nothing fails open:
the hazard is that an operator tuning `FABIO_BIAS_OVERRIDE_THRESHOLD` in `constants.py:236`
reasonably believes the 15-minute bias is live. It is not.
**Note on severity — corrected:** `bias` is **not named in `docs/amt`** as a gate input (the
pipeline field table lists no bias field), and — critically — **no gate reads these fields**,
so unlike C1 this is not a fail-open defect. This is an **aspirational feature left
half-wired**: a resolver, a constant, a threshold alias, and a complete override function,
all unreachable. It is rated CRITICAL on the same *class* of defect as C1/C2 (a guard-shaped
object with no producer) rather than on demonstrated fail-open behavior. If bias is not a spec
requirement, **delete the import, the fields, the constant, and `_apply_bias_override`** rather
than leaving the impression of a live subsystem. If it *is* intended, it must be wired and
tested.
**Fix:** wire `BiasResolver` into `ContextBuilder.__init__` + `build()`, or remove it.

### C4. ~~Pyramid SL ratchet inverts the stop polarity — the net-positive guarantee is broken~~ → M18 (DOWNGRADED, headline refuted by execution)
> **CORRECTION (validation round, committed).** The CRITICAL headline — that a
> pyramid ratchets the base SL to a point *below the base entry*, producing a
> net-negative bundle (−350) — is **refuted by driving the real
> `PositionManager` end-to-end.** The original arithmetic treated the ratcheted
> SL as the exit price. It is not.

**Spec (§13.2, rule 4):** "Stop Ratchet: Move combined position stop to the new
LVN/cluster floor. **The entire trade bundle is guaranteed a net positive cash payout.**"
**Spec (§13.2, rule 1):** "Base trade must be at **Risk-Zero (Breakeven or $+1.0R Locked)**."

**Why the −350 cannot happen (execution evidence).** The pyramid is authorized only
when `is_risk_free()` is true (`position_manager.py:548`), which is true only when a
breakeven floor has been armed in `ExitEngine._breakeven[id]` (`exits.py:108-116`).
Every setter of that floor stores a value **at or above cost basis**:

- `exits.py:285` (0.8R / CVD path) sets `be_floor = entry` (`exit_checks.py:140,145`) — never below;
- `exits.py:303` (auction-acceptance path) sets `be_floor = entry`;
- `exits.py:215` (TimesFM quantile path) stores `eval_res.new_stop` only when
  `eval_res.is_risk_free`, and `timesfm_risk.py:66` derives that from `new_stop >= entry`.

The ratchet then writes `new_sl` back into `position.order.signal.sl`
(`position_manager.py:670-674`) — but the *exit* price is not `signal.sl`. Both the bar
path (`exits.py:257-258`) and the tick path (`position_manager.py:381-384`) resolve the
effective stop through `resolve_protective_stop()`, which takes the **max** of
`{signal.sl, be_floor, trail_stop}` for a LONG (`protective_stop.py:5-9`). Because the
be_floor that *authorized* the pyramid is ≥ entry, it overrides the ratcheted SL.

**Reproduction with the real `PositionManager`** (base LONG @ 105, initial SL 98 so the
ratchet demonstrably fires, LVN 100, tick 0.5):

```
auth: is_risk_free=True            (be_floor=105.0 armed by the 0.8R bar)
pyramid_count=1
RATCHET FIRED: base sl 98.0 -> 99.6
EFFECTIVE stop=105.0 (BREAKEVEN) [ratcheted=99.6 be=105.0 trail=None]
BUNDLE at 105.0: +24.5  spec 13.2.4 >= 0? True
```

The ratchet tightened the frozen signal SL (98→99.6) yet the bundle still exits at the
breakeven floor (105.0), net **+24.5**, satisfying §13.2.4.

**The residual defect (M18).** The ratchet is *cosmetic*, not harmful: it mutates the
frozen `signal.sl` to a value that the exit engine immediately overrides. That is dead
state with two costs: (a) the `StopMoved` audit event at `position_manager.py:678`
records a stop the engine never honours — the journal lies to ops; (b) any future caller
that reads `signal.sl` *without* merging the breakeven floor (the ratcheted base is
returned via `base_override`, `position_manager.py:256`) inherits a stop below the one
actually enforced. The guarantee currently rests entirely on `be_floor`, not on the
ratchet the spec describes.
**Impact:** LOW–MEDIUM, paper/replay-live only — pyramids are hard-disabled on LiveOMS
(`live_oms.py:489-494` raises `ValueError`, caught at `position_manager.py:623`).
**Fix:** (a) give the pyramid SL its own `behind_level()` helper rather than reusing the
entry-facing `structural_stop`, and stop writing it into `signal.sl`; (b) add a unit test
asserting the stopped-out bundle PnL ≥ 0 for both directions and both pyramid levels —
the suite has **no** such test today (`test_pyramid_integration.py:67` asserts only
`is_risk_free`). This is the guard that would have caught the original mis-reading, and
it is still the right test to write.

### C5. §5.1 Value Area is 70%, spec requires 68.2%
**Spec (§5.1, rule 3):** "Value Area (VA = **68.2%** of Total Volume)" —
`docs/amt/AMT_INSTITUTIONAL_SCALPER_ALGORITHM.md:128`.
**Code:** `quant/contracts/constants.py:52` `VALUE_AREA_PCT = _get("value_area_pct", 0.70)`;
`backend/config/base.yaml:27` `value_area_pct: 0.70`; consumed at
`quant/amt/profile/volume_profile.py:105`. Duplicated as
`constants.py:243` `FABIO_VALUE_AREA_PCT = 0.70` (unused outside one test).
**Verified:** `0.682` / `68.2` appears in **zero** source or config files in `quant/` or
`backend/` (only in vendored site-packages).
**Impact:** a 1.8-point wider VA is the boundary that classifies the whole market: it
reclassifies imbalanced conditions as BALANCED, widens the `balance_ratio` denominator
(`analyzer.py:584-588`), and moves every VA-based target, rejection, and acceptance level
in Playbooks A and B. `MarketState` derives from these levels, so trade selection changes.
**Fix:** set `value_area_pct: 0.682` (the code already reads config — no code change);
delete the duplicated `FABIO_VALUE_AREA_PCT`; add a test asserting `0.682`. Or record the
0.70 choice in `docs/amt` as a ratified deviation — currently nothing justifies it.

### C6. §5.1 LVN predicate is not implemented — convexity is never computed anywhere
**Spec (§5.1, rule 4):** `LVN = { p | V(p) < 0.35 × V̄_profile AND d²V(p)/dp² > 0 }`.
**Code:** `quant/amt/profile/lvn.py:169-173` uses a **20th-percentile** threshold plus a
local-minimum test:
```python
pct_threshold = _percentile(sm, lvn_percentile)   # lvn_percentile = 20.0
if sm[i] < sm[i - 1] and sm[i] < sm[i + 1] and sm[i] <= pct_threshold:
```
**Verified:** no `0.35 × mean` comparison exists; **no convexity / second-derivative
computation exists anywhere in `quant/`** (grep for `convex`, `second_diff`, `d2v`,
`curvature` → zero hits). The `lvn_threshold` parameter threaded through `find_lvns`
(`lvn.py:133`) is documented `"# kept for API compatibility (unused)"`; `LVN_THRESHOLD = 0.15`
(`constants.py:50`, `base.yaml:25`) is likewise dead. The effective gate is
`LVN_PERCENTILE = 20.0`, invisible at the config layer.
**Impact:** two ways this is strictly wrong: (a) **no convexity ⇒ trend-continuation LVNs
are missed** — a monotone descending volume ramp satisfies the local-minimum test only at
its single bottom-most sample, so convex-but-shallow troughs (the §9.3 pullback entry
zone) are systematically dropped; (b) **percentile is relative, the spec threshold is
absolute** — `0.35 × mean` is a fixed fraction of average volume, while a rank shifts with
the distribution shape. Error propagates through `analyzer.py:514`,
`profile/displacement.py:121` (Layer-3 leg LVN), and `profile/gap_profile.py:265`.
**Fix:** add the absolute threshold and a centred second difference alongside the
percentile gate; delete the dead `lvn_threshold`/`hvn_threshold` chains so the constant
that gates production LVNs is the one the spec names.

### C7. §7.2 absorption thresholds: 2.0×/0.30×ATR instead of 1.50×mean₂₀/0.50×H_range
**Spec (§7.2):** `V_b ≥ 1.50 × V̄_20` and `(H_b − L_b) ≤ 0.50 × H_range`
(`docs/amt/...md:183`).
**Code:** `quant/amt/orderflow/detectors.py:355-356` with
`ABSORPTION_RANGE_ATR = 0.30` / `ABSORPTION_VOL_MULT = 2.0`
(`constants.py:80-81`, `base.yaml:46-47`), referenced to **ATR** (`compute.py:108`), not
`H_range`; the mean is the full `RECENT_DATA_WINDOW = 100` window (`compute.py:55-59`),
not a 20-bar rolling mean; operator is `<` where spec says `≤`.
**Impact:** `absorption_detected`/`absorption_side` drive the Triple-A WAITING→ABSORBING
transition, `AGGRESSION_ABSORPTION = 0.5` in the aggression score, and — critically — the
cluster bounds the §9.1 hard stop is pegged to. Genuine 1.5–2.0× effort-without-result
bars are silently dropped, starving the state machine's absorption phase.
**Fix:** `ABSORPTION_VOL_MULT = 1.50`, a dedicated 20-bar rolling mean, and `0.50 × h_range`
with `h_range` from `ATRRangeCalculator.range_size(tick_size)` (depends on C8 for wiring).

### C8. §4 range bars are not the decision driver — the whole spec bar model is dead code
**Spec (§4):** the system "normalizes price action into **Range Bars** of fixed price
height `H_range`"; §2's ingestion diagram routes ticks through a RANGE BAR GENERATOR.
**Code:** `quant/runtime.py:384-409` constructs only interval aggregators
(`BarAggregator(interval_seconds=…)`). `DynamicRangeBarAggregator` and
`ATRRangeCalculator` have **zero non-test importers** in `quant/` (verified by
construction search). The entire `quant/amt/profile/range_bars.py` module is unreachable
in production. The implementation itself is *correct* — `quant/aggregator.py:92` does
`spread >= self.range_size` and `:93-94` re-opens at the completing tick price; but it is
never wired.
**Impact:** every `H_range`-relative and `mean_20`-relative comparison in the spec
(§7.2's compression test, §5.1's `S_bucket`) evaluates against a bar granularity the spec
does not define. This is the root cause that makes C7's "ATR not H_range" and D-A8's
"bucket width not `S_bucket` unfixable in isolation.
**Spec tension (must be resolved by the owner):** §16 itself declares range bars are "not
the primary decision driver … an architectural choice, not a bug." Either §16 is a
ratified amendment to §4 — in which case **§4 must be re-worded so spec and code agree** —
or §4 is authoritative and C8 is a work item. Currently the two sections of the same
authoritative document contradict each other and the code follows neither.
**Fix:** wire `DynamicRangeBarAggregator` as primary with a `AMT_RANGE_BARS_ENABLED` flag
and a live test asserting which path is active; or amend §4 to name time bars as primary.

---

## HIGH (17)

| # | Defect | Spec | Code | Notes |
|---|---|---|---|---|
| H1 | CVD velocity is a 40-bar regression slope, not `EMA₃ − EMA₉` | §6.2:154 | `cvd.py:141-179` | **No EMA of any span exists in `quant/`** (verified: grep `ema`/`span=3`/`span=9` → no CVD hits). A slow trend estimator replaces a fast crossover band; no zero-crossing semantics; the 3-bar persistence filter further delays the acceleration signal §13.1 relies on. |
| H2 | Big Trade Filter has no absolute contract thresholds | §7.1: 20–30 (London), 30–40 (NY), ≥100 institutional | `detectors.py:81-83` | Purely relative `5.0 × avg`. On a low-liquidity option (avg 300) it fires at 1500 contracts — 15× the institutional floor; on an index future (avg 50k) nothing can ever qualify. Feeds `AGGRESSION_BIG_TRADE = 1.0` of the 2.0 confirmation score. |
| H3 | Cushion formula is a tier system, not §12.2's formula | §12.2:404-409 | `risk.py:533-601` | Spec: offensive `E₀×0.0025 + 0.40×Cushion`; defensive `min(E₀×0.0025, MDL−|Cushion|)`. Code: CONSERVATIVE 0.25% / CUSHION_TIER_1 0.35%+20%of-profit (cap 0.50%) / MOMENTUM 0.40%. **`0.40` never appears as a cushion fraction.** No test covers either spec branch. |
| H4 | §13.3 exit ladder lands on 50/25/25 only by arithmetic accident; §9.1 says 50/50 | §13.3:449-451 vs §9.1 | `exit_checks.py:95-102` | TP2 closes 50% *of the remainder* (→ 25% of original), so the runner is correct **by accident**. But TP2's *target* is a pure `2R` formula (`tp2_level`), not "macro VA extreme or CVD divergence exhaustion"; **no TP3 tier exists** and the runner has no absorption-bubble trailing. §9.1 and §13.3 **contradict each other in the spec itself** and the code implements neither exactly. |
| H5 | §9.1/§11 stop polarity is inverted relative to the spec's literal formula | §9.1:256/266, §11:367 | `stops.py:84-108` | Spec: LONG `SL = L_cluster − 2×Tick`. Code: `anchor + 2×tick` — *toward entry*. Verified numerically: `anchor=95, tick=0.5` → code `96.0`, spec `94.0`. The module docstring argues this is a deliberate Fabio "pro stop" (fill before the cascade). §11's headline says "Behind Bubbles, Not Wicks" — the code places it *in front*. **`docs/amt` is internally inconsistent**; this must be settled by the spec owner, not the code. Same root cause as C4. |
| H6 | §11 stops are never anchored to absorption cluster extremes | §11:367, §15:733 | `stops.py:27-60` | Anchor candidates are `nearest_buy_print_below`, `leg_lvn`, `vah`, `val`, `bar.low/high`. **`cluster_low`/`cluster_high` appear nowhere.** `ctx.bar.low` — which §11 explicitly dismisses as "arbitrary candle wicks" — is a first-class candidate. The institutional-cost-basis stop is the strategy's core slippage defence. |
| H7 | §9.1/§9.3 RR floors: `MIN_RR_RATIO = 1.5` vs spec 1:2.0 (A) / 1:3.0–1:5.0 (C) | §9.1:261, §9.3 | `signal_builder.py:211` (`min_rr: float = 1.5`), `constants.py:123` | **Playbook C's "point B" does not exist in the decision layer** — no code path computes it and no `rr >= 3` floor exists for the sniper label (grep `1:3`, `rr >= 3` → no decision-layer hits). The runner is then capped at 2R instead of 3–5R. |
| H8 | §8 "CVD expanding" implemented as "CVD not aggressively diverging" | §8:217 | `triple_a.py:243` (`cvd_slope > -0.3`) | The third condition of a three-condition trigger is a *non-veto* rather than a *confirmation*. A LONG can fire while CVD is mildly rolling over. Gate 3's conflict thresholds disagree with the trigger's (see H9). |
| H9 | Gate 3 CVD conflict thresholds inverted vs spec, in **two** places | `fabio...md:106-107` | `constants.py:232-233` (`NSE=0.5, MCX=0.3`) **and** `gates_edge.py:192-193` (same literals hardcoded) | Spec: NSE = ±0.3, MCX = ±0.5. Two independent sources of truth, both wrong, neither matching spec, no test pins either. On NSE the veto needs a much larger opposing slope to fire — **harder to trip than designed on the primary exchange** (verified: a LONG with `cvd_slope = −0.4` on NSE is vetoed by the spec but passes Gate 3 in code). **Validated:** both sites are live — `constants.py:232-233` is consumed at `context_builder.py:181` for **direction resolution** (not merely a veto), so the inverted constant can also flip the resolved trade direction; `gates_edge.py:192-193` hardcodes its own copy rather than importing the constant |
| H10 | Playbook C's RR ≥ 1:3.0 and "target above point B" not implemented | §9.3 step 7 | — | (See H7.) Separate defect ID retained because Agent B found it as a distinct missing-feature; fix is the same. |
| H11 | §13.1's alternative breakeven trigger is half-implemented | §13.1:419 | `exit_checks.py:122-133` | Path 2 (+0.8R) ✅ verified correct. Path 1 requires only `profit > 0` **and a single bar's** `cvdSlope` crossing — the "**2 consecutive range bars closing in profit**" confirmation is entirely missing (no streak counter, no range-bar notion). Arms breakeven too eagerly, inverting the spec's intent (CVD should be the *earlier but confirmed* route). |
| H12 | §13.2 "+1.0R Locked" authorization variant is not modelled | §13.2:441 | `exits.py:108-116` | `is_risk_free` only knows "a breakeven floor exists." If the spec means pyramids are authorized only when the base is *locked in profit*, the gate is too permissive. Same root cause as C4; settle together. |
| H13 | LiveOMS hard-disables pyramiding vs §13.2 | §13.2 | `live_oms.py:~485` (`raise ValueError`) | Paper permits pyramids, live raises. The exception is caught (`position_manager.py:623`), but "paper trains a behavior live refuses to perform" is a live/paper asymmetry. Either implement or return a structured rejection. |
| H14 | §7.2 `0.60` directional rule and close-position test are untested | §7.2 | `detectors.py:382-388` | Implementation is **correct** (exact constants and polarity — the best-implemented rule in §7). But no test anywhere asserts `0.60`, and every absorption test sits far inside the accept region, so a constant change would pass silently. |
| H15 | §16 data-honesty: tests exercise the `taker_buy_volume` branch production never supplies | §16 | `detectors.py:366-378` | Production: `taker_buy_volume` defaults to `Decimal("0")` (`value_objects.py:33`); **no broker code ever populates it** → every live candle takes the delta-proxy branch. Yet 5+ test files feed explicit `taker_buy_volume`. The `|delta| > vol` clamp that manufactures a 100/0 split (trivially satisfying the 60% rule) has no test. |
| H16 | `PortfolioRiskAuthority` cross-engine aggregation has no test | `multi_symbol_isolation.md` req 3 | `portfolio_risk.py` | The spec calls this "the ONLY cross-engine coupling in the decision path" and requires a test that the sum of engines' open risk cannot exceed the ceiling without double-counting. No such test exists (closest is single-engine sequential). |
| H17 | `DynamicRangeBarAggregator` / `ATRRangeCalculator` are dead code | §4 | `range_bars.py` | (See C8.) Separate ID because the *test* file `test_range_bars.py` tests an unwired component with a **truncated `(5,10,25)` ladder**, never the production `(2,5,10,25,50,100,200)` — and the leading `2` is not in the spec's set. |

---

## MEDIUM (15) and LOW (4)

| # | Defect | Severity | Summary |
|---|---|---|---|
| M1 | **(downgraded from CRITICAL C2)** `session_extreme_low/high` unproduced — `va_fade.py:68-69` falls back to the bar wick, so stops reference the last bar's probe, not the session's true probe extreme | MEDIUM | Stop-quality degradation only; a second route via the complete `VA_FADE` evidence packet does not read these fields at all |
| M2 | §12.1 MDL at exactly 2.0% is not asserted as the number — `test_max_loss_halts` uses `0.03` and proves a *different* (undocumented 2%) threshold fires earlier | MEDIUM | `risk.py:253` itself is **verified correct** (−1.9% → no halt, −2.0% → halt); only the test is weak |
| M3 | §12.2 `floor()` never asserted (tests use `pytest.approx`, which would also pass `round`) | MEDIUM | `risk.py:409` spec formula |
| M4 | §13.2 pyramid 50%/25% sizing ratios never asserted | MEDIUM | `position_manager.py:608` — `fraction = 0.50 if pyramid_count == 0 else 0.25` is exercised only incidentally |
| M5 | §10 pre-market trap lock has no explicit state or test | MEDIUM | The exchange-clock blackout *incidentally* excludes it; spec demands "STRICT RULE: Zero new entries" |
| M6 | §6.2 CVD divergence tests are a set-membership tautology | MEDIUM | `test_cvd.py:45-53` asserts `divergence_type in ("BEARISH_DIV","BULLISH_DIV","NONE")` — cannot fail on any input |
| M7 | §6.1 VWAP σ formula never asserted against an independent value; only band *ordering* | MEDIUM | `vwap.py:106-110` math is **verified algebraically exact** (shifted-variance identity) |
| M8 | Determinism test filters out the events that could diverge | MEDIUM | `test_multi_symbol_isolation.py:69-75` drops `AgentDecisionProduced` and keeps only `(type, time)` — a LONG@105/SL98 and a SHORT@105/SL112 fingerprint identically |
| M9 | Gate 1 spread check: `max(4%×price, 2×tick)` vs spec's `max(2×tick, 0.1%×price, ₹0.40)` | MEDIUM | `gate_session_phase.py:113-117`. Deviation is deliberate and documented inline (₹0.40 is unworkable for high-LTP options) but the pipeline doc still advertises the three-term formula |
| M10 | §8 ACCUMULATING transition omits "delta stabilizing" and LVN proximity | MEDIUM | `triple_a.py:200-210` checks only `_is_near_poc` on a 4-tick tolerance |
| M11 | `TickFootprintAccumulator` claims "real tick-level footprint" while running on 5-level depth proxy | MEDIUM | §16 explicitly forbids claiming true tick aggression while using the proxy. Rename to `DerivedFootprintAccumulator`, add a `provenance` field |
| M12 | `MODEL_RISK_FAILURES`/`MODEL_SIZING_FAILURES` are process-globals shared by all engines | MEDIUM | `exits.py:22-28`. The one genuine cross-engine mutable-state leak in the decision path — makes per-engine degradation undetectable. Telemetry only, no money path |
| M13 | `H_range` bucket width is not `S_bucket`; profiles use auto-computed bucket counts (100–1000) | MEDIUM | `volume_profile.py:213-221`. Depends on C8 |
| M14 | CVD slope is an unnormalised linear-regression slope over 40 bars — absolute thresholds aren't scale-free across NSE options vs MCX commodities | MEDIUM | Compounds H8/H9 |
| M15 | `quantize` ladder contains an off-spec leading `2` step | MEDIUM | `range_bars.py:43-46` — `{2,5,10,25,50,100,200}` vs spec's `{5,10,25,50,100,200}` |
| M16 | Footprint provenance name drift + `cvd_source` never passed | MEDIUM |
| M17 | **§3's 5-Minute Kline stream has no producer at the production default** | MEDIUM | Spec §3 requires 5m klines for "Macro Dealing Range identification, Session highs/lows, and overarching market narrative framing." `_DEFAULT_CONFIG["interval_seconds"] = 60` (`multi_engine.py:266`), so `runtime.py:384-409` builds a 60s aggregator and no 5m one; `analyzer.py` receives a single timeframe (`recent_data`, `:454`) and has **no 5m/macro concept at all** (verified: grep for `dealing_range`/`macro`/`5m` in the analyzer → no hits). The 60s bar does double duty as both decision and macro context. Note `DEFAULT_INTERVAL_SEC = 300` (`bars.py:7`) contradicts the coordinator default of 60 — two sources of truth again | `analyzer.py:1007` reads `self._footprint_accumulator` (never assigned) — should read the `footprint_accumulator` parameter; `AMTEngine` never passes `cvd_source`. Both `TICK_EXACT` provenance branches are unreachable, so live CVD/footprint is reported `CANDLE_DISTRIBUTED` forever |
| M18 | **(downgraded from CRITICAL C4 — headline refuted by execution)** The pyramid SL ratchet writes `new_sl` into `signal.sl`, but the exit engine resolves the effective stop as `max({signal.sl, be_floor, trail})` (`protective_stop.py:5-9`), so the ratchet is overridden by the breakeven floor that authorized the pyramid | MEDIUM | Bundle guarantee holds (verified end-to-end: `+24.5`). Residual cost: the `StopMoved` event at `position_manager.py:678` journals a stop the engine never honours, and `base_override` (`position_manager.py:256`) hands a stale sub-breakeven `signal.sl` to any caller that skips the merge. No test pins bundle PnL ≥ 0 |
| L1 | `mock_pass` sentinel aliases `NotImplementedError` to a "placed" live stop | LOW | `live_oms.py:181-189`. Blast radius = one unguarded position; the in-memory stop path still works |
| L2 | Gate 4 options stop cap uses 5% of premium, not 0.75% | LOW | `gates_rr.py:32-37`. Deliberate and documented; the 200-tick hard cap swamps either value |
| L3 | §8 aggression trigger joint-condition / non-confirm paths undertested | LOW | No 2-of-3 test asserting the machine resets |
| L4 | Silent `except Exception: return []` in Layer-4 gap-LVN extraction; dead `_Cfg` class | LOW | `gap_profile.py:264-274`. Low today, HIGH the moment gap LVNs gate an entry |

---

## The deeper pattern: the suite certifies the drift

The single most concerning finding is **D-D1**, and it is worth stating plainly:

`tests/quant/contracts/test_fabio_constants.py:27-34` **asserts the wrong spec values as
correct**:

```python
assert FABIO_ABSORPTION_VOL_MULT == 2.0      # spec §7.2: 1.5
assert FABIO_ABSORPTION_RANGE_ATR == 0.30    # spec §7.2: 0.5 × H_range
assert FABIO_VALUE_AREA_PCT == 0.70          # spec §5.1: 0.682
```

These assertions **pass**. A future maintainer reading the spec and correcting the
constant to `1.5` / `0.5` / `0.682` would **break the test** and would most likely "fix"
the test back — inverting the spec-to-code relationship so that the test suite becomes the
thing that defends the drift. One assertion is annotated "CME standard: 70% value area"
while the authoritative spec states 68.2% at line 128 of the same-named document.

More broadly, `0.682` appears in **zero** test files, **zero** source files, and **zero**
config files. `0.60` (the §7.2 directional rule, correctly implemented in production)
appears in **zero** tests. Neither spec branch of §12.2's cushion formula has a test.
The §13.3 ladder is asserted as 0.5/0.5 while the spec says 50/25/25. And 11 skips are
honest, but one of them — the sizing-certification scenario — claims "risk math covered by
unit tests," which is exactly the coverage H3/M2 shows to be missing.

The green suite measures plumbing. It does not measure spec conformance. Where the two
diverge, the tests side with the code.

---

## What is genuinely correct (verified, not assumed)

A FAIL verdict must be specific about what is *not* wrong. These were checked and hold:

1. **§6.1 VWAP and σ** — `vwap.py:61-69,106-110`. The shifted-variance form is
   algebraically exact; `_shift` is numerical-stability only. Bands are exactly ±1.0σ/±2.0σ.
2. **§6.2 Delta/CVD and divergence polarity** — `cvd.py:111-113`, `compute.py:221-224`.
   Bullish = price LL + CVD HL; bearish = price HH + CVD LH. Real swing comparisons, not stubs.
3. **§7.2 directional classification** — `detectors.py:380-388`. Exact constants (`0.60`,
   `0.50`) and correct end-to-end polarity (`SELL_ABSORBED` → LONG), consistent with
   `aggression.py:62-65`. The best-implemented rule in the audited set.
4. **§5.2 four distinct profile layers** — session, compression box, impulse leg, gap.
   Four separate classes, separate anchors, separate output types. Not one profile reused.
5. **§5.1 POC** — `volume_profile.py:56-62`. `argmax V(p)` with a deterministic VWAP tie-break.
6. **§4 range-bar math (unwired but correct)** — `aggregator.py:91-95` (`>=`, re-open at
   prior close); `range_bars.py:113-117,136-140` (ATR-14 SMA, quantize).
7. **§12.1 MDL halt at exactly 2.0% and the 3-consecutive-loss cutoff** — `risk.py:253,
   259-261`. Verified: −1.9% no halt, −2.0% halt; 3×−₹100 halts at 0.3% cumulative; a
   subsequent **win does not clear the halt**; session reset merges gains into E₀.
8. **§13.1 +0.8R breakeven** — `exit_checks.py:132`. 0.75R does not arm, exactly 0.8R arms.
9. **§10 NO OVERNIGHT HOLDING — two independent layers** — bar-driven
   `position_manager.py:162-166` + wall-clock `multi_engine.py:1163-1199` EOD watchdog that
   force-flattens 15 min before close even on a dead feed.
10. **§10 day-of-week multiplier** — `risk.py:19-24`. Mon/Fri 0.5×, Tue/Wed/Thu 1.0×.
11. **§9.2 Playbook B 100%-exit-at-POC** — `exit_checks.py:71-79`. Enforced, not implied.
12. **§9.1 anti-whipsaw** — `gates_edge.py:33-34,104-152`. Body-ratio ≥0.60, close-position
    ≥0.75, direction checks. The strongest such guard in the repo.
13. **Gate pipeline fail-closed semantics** — `decision_service.py:134-138` identifies
    hard/soft rejects by gate number; `pipeline.py:33-37` converts gate exceptions to fails.
14. **Multi-symbol isolation** — one feed, per-symbol gateways/engines/threads;
    `PortfolioRiskAuthority` is the sole documented cross-engine coupling;
    `SessionLevelStore` serializes through one `RLock`. 9/9 isolation tests pass.
15. **Delta sign convention end-to-end** — up-tick → buy → positive delta → CVD up →
    footprint ask-side. No flip at any of the five layers.
16. **TimesFM is advisory-only** — fire-and-forget `on_context`; no gate imports it;
    `multi_engine.py:274` explicitly excludes it from trading decisions.
17. **§15 row 5 hard SL at the exchange, zero discretion** — `live_oms.py:167-224`;
    on rejection the position is **emergency-flattened** and the risk reservation released.
18. **Sizing guards** — `risk.py:381,429-431` reject degenerate inputs before any broker call.

---

## Spec-internal contradictions (must be settled by the spec owner)

Three places where `docs/amt` argues with itself. The code cannot resolve these; only the
owner can, and each one currently has money-path consequences.

1. **§9.1 vs §13.3 on the exit ladder.** §9.1: TP₁ 50% / TP₂ 50% (no runner). §13.3:
   50% / 25% / 25% with a trailed runner. The code lands on 50/25/25 *by arithmetic
   accident* (0.5 of the remainder) and has no TP3. → **H4**
2. **§9.1/§15 vs §11 on stop placement.** §9.1's formula and §15's "Cluster Extreme ± 2
   ticks" describe the *outside* (behind) placement; §11's diagram and prose argue for
   1–2 ticks *inside* the level to fill before the cascade, and labels the outside
   formula "the retail stop … forbidden here." The code follows the inside reading.
   Every downstream R-multiple (0.8R BE, +2.0R TP1, pyramid 50%) is computed off this
   stop, so the whole risk geometry shifts either way. → **H5**, and the root cause of
   the ratchet half of **C4/M18**.
3. **§4 vs §16 on range bars.** §4 makes range bars the substrate of the whole engine;
   §16 declares them "not the primary decision driver … an architectural choice, not a
   bug." The code implements neither — it implements correct range-bar code that is
   never wired, and runs on time bars. → **C8**

**Recommendation:** amend `docs/amt` so each contradiction has one authoritative reading,
and make the code cite the winning section in a comment. Until then, "is this correctly
implemented against the spec?" has no answer for these three areas, which is itself a
finding.

---

## Recommended fix order

**Phase 0 — stop the bleeding.** C1 (the one true fail-open: add the producer, or delete
the dead `getattr` read so the guard fails loudly). C2 (add the session-extreme producer so
stops reference the true probe, not the last bar's wick). C3 — **decide or delete**: either
wire `BiasResolver` end-to-end with tests, or remove the resolver, the threshold constant, and
`_apply_bias_override`, so the config surface does not advertise a subsystem that never runs.

**Phase 1 — the money-path guarantee.** C4/M18 + H5 + H12. Decide the stop polarity in the
spec first (contradiction #2), then stop writing the pyramid SL into `signal.sl` and add a
bundle-PnL ≥ 0 test for both directions. Severity is lower than first assessed: the
bundle guarantee currently holds, via the breakeven floor rather than the ratchet.

**Phase 2 — constants.** C5, C6, C7, H3, H7/H10. Fix the value, fix the duplicate
(`FABIO_*` dead constants), and **fix the test that certifies the wrong value** (D-D1).

**Phase 3 — test the spec's numbers at the spec's boundaries on the production data
path.** H14, H15, H16, M1–M7, plus a `test_amt_spec_constants.py` that pins
`VALUE_AREA_PCT == 0.682`, `LVN vol fraction == 0.35`, `ABSORPTION_VOL_MULT == 1.5`,
and boundary matrices at `1.49/1.50/1.51×`, `0.59/0.60/0.61` sell-fraction, and
`|delta| ≥ vol` on the **delta-proxy** branch.

**Phase 4 — structural.** C8 (wire range bars or amend §4), H1 (EMA₃−EMA₉ velocity or
document the substitution in §16), H4/H11/H13 (exit ladder, CVD breakeven confirmation,
live pyramiding), M10/M15 (provenance honesty), M11 (per-engine counters).

---

## Bottom line

The engineering is competent and in places genuinely good — the state machine, the
isolation contract, the EOD enforcement, and the VWAP/absorption-polarity math are things
I would sign off on individually. But the review question asked was whether the system is
correctly implemented and tested against `docs/amt`, and on that measure it is not:

- **6 CRITICAL** defects, including **1 confirmed silent fail-open guard** on the
  primary exchange, **1 money-path guarantee not implemented as specified** (the bundle
  guarantee holds, but via the breakeven floor rather than the ratchet the spec names —
  the ratchet is dead state), and **1 entirely dead subsystem** (the 15-minute bias
  layer) whose tuning constant an operator could believe is live.
- **45 total** defects across constants, predicates, guards, formulas, and tests.
- **3 spec-internal contradictions** the code cannot resolve.
- A **2580/2580 green suite** that asserts the wrong values in the exact places where the
  drift lives, and cannot detect any of the 8 CRITICALs.

**Do not deploy to live trading until Phase 0 and Phase 1 are closed and the three
spec contradictions are settled in writing.**

---

## Post-consolidation corrections (transparency)

Three findings were revised during a final principal re-verification pass, all downward.
The corrections are recorded here rather than silently edited, because a reviewer acting on
the first version of this document deserves the delta.

1. **C2 (`session_extreme_low`/`session_extreme_high`) — CRITICAL → MEDIUM.** The original
   text claimed both fade guards "compare against `0.0` and never trip." That is wrong.
   `va_fade.py:68-69` has an explicit wick fallback (`bar_low`/`bar_high`), so the fade still
   fires on a single-bar failed auction and still places a stop beyond it. What is actually
   lost is the spec's session-wide probe breadth. Additionally, `va_fade.py:46-60` provides a
   second, independent route to the same fade via a complete `VA_FADE` evidence packet that
   never reads the session extremes. This is stop-quality degradation, not a disabled guard.
2. **C3 (bias) — mechanism corrected, severity held.** The original text described "a
   dangling import." The dead code is larger than that: `context_builder.py:12,14,46,49-66`
   imports the resolver, imports and aliases the threshold, and implements a complete
   `_apply_bias_override()` — all with **zero callers**. Severity is retained as CRITICAL, but
   on the *class* of the defect (a guard-shaped, unreachable subsystem whose tuning constant
   sits in the config surface) rather than on demonstrated fail-open behavior, because **no
   gate reads `bias_direction`/`bias_confidence`** — unlike C1, nothing fails open here.
3. **Headline claim corrected.** "Four DecisionContext fields … three silent fail-open
   guards" overstated the fail-open count. The accurate statement is **one** confirmed
   fail-open guard (`cvd_divergence`), **two** degrading-but-fallback-protected fields, and
   **one** fully dead subsystem. **C4 was then refuted by execution** (validation round): the
   −350 bundle assumed the ratcheted SL is the exit price, but `resolve_protective_stop`
   overrides it with the breakeven floor that authorized the pyramid; it is now **M18**.
   The FAIL verdict is unaffected: C1 alone is a silent Gate 3 veto bypass on the primary
   exchange, and C5/C6/C7 hardcode constants the spec does not contain.

### Scope verification (addressed explicitly)

The request was to review "the whole project and flows." That phrase was interpreted as
**the AMT engine and every code path the AMT spec governs**, and the boundary was verified
rather than assumed:

- `docs/amt` references exactly two code trees by path — `quant/` (24 references) and
  `tests/` (4). It never names `backend/`, `brokers/`, `frontend/`, `automation/`, or
  `quantv2/`.
- `quant/` imports nothing from `backend/`, `automation/`, `frontend/`, or top-level
  `brokers/` (verified by import scan). Its only external dependency is `shared/money.py`,
  two numeric helpers.
- Top-level `brokers/` is an independent tree: `quant/` uses its own `quant/brokers/`
  subpackage for the live gateway and feed. The sole cross-reference is a *docstring*
  fallback hint in `quant/contracts/instrument_registry.py:208,213`; the AMT path resolves
  lot/tick size via `quant/contracts/exchange_config.py:135` and `multi_engine.py:1759`.
- `frontend/` and `automation/` are presentation/orchestration, not spec-governed logic.

So the reviewed surface — `quant/` (190 files) plus the `backend/` files that touch the
engine (`gameloop.py`, `trading.py`, `config_models/validator.py`, `config/base.yaml`) — is
the complete AMT-governed surface. `backend/` has 176 Python files, of which only those four
participate in the engine path; the rest are API/auth/DB plumbing outside the spec.

**One interpretation was guessed at:** whether "whole project" meant literally every
directory. It did not — the spec itself defines the boundary, and the evidence above is why
`frontend/`, `automation/`, `brokers/`, and `quantv2/` were excluded. Flagging it so the
owner can widen the scope if they meant something else.

### One finding added by the re-check (upward correction)

**M17 — §3's 5-Minute Kline stream has no producer at the production default.** Re-checking
the C3 bias subsystem led to `runtime.py:402-411`, where the 15m bias aggregator is built
only when `interval_seconds > 900`. That prompted the question of what the production
interval actually is: `_DEFAULT_CONFIG["interval_seconds"] = 60` (`multi_engine.py:266`),
while `DEFAULT_INTERVAL_SEC = 300` (`bars.py:7`) — two contradictory defaults. At 60s, the
60s bar does double duty and **§3's required 5m macro stream does not exist**; `analyzer.py`
receives a single timeframe and has no macro/dealing-range concept. This also means D-E9's
micro-aggregator finding and C3's bias finding are the *same root cause*: the 60s default
disables both the 1m trigger layer and the 15m bias layer at once.

The five specialist reports are unchanged and retain their original severities; where they
differ from this consolidated view the consolidated text says so.

---

*Consolidated from the five specialist reports in `docs/reviews/2026-09-21-amt-review-agent{A,B,C,D,E}-*.md`
plus an independent principal-engineer verification pass. All file:line citations refer to
the working tree at commit `e589cbe5a`, 2026-09-21.*
