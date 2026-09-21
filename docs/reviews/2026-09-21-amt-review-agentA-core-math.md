# Agent A — Core Mathematics Review vs docs/amt

**Auditor:** Agent A (core-mathematics assignment)
**Date:** 2026-09-21
**Spec under review:** `docs/amt/AMT_INSTITUTIONAL_SCALPER_ALGORITHM.md` (sections §4, §5.1, §5.2, §6.1, §6.2, §7.1, §7.2)
**Code under review:** `quant/amt/profile/*`, `quant/amt/orderflow/*`, `quant/amt/analyzer.py`, `quant/amt/compute.py`, `quant/aggregator.py`, `quant/contracts/constants.py`

## Verdict: FAIL

The CVD/divergence and VWAP core math is genuinely and correctly implemented, and the four profile layers exist as four distinct anchored detectors. But **five spec rules have no faithful implementation**: the LVN definition, the CVD velocity, the big-trade contract thresholds, the absorption thresholds, and the range-bar primary path. Two of the five are CRITICAL (missing mathematical predicate + wrong constants in the live signal path), one is a documented-but-unactioned spec contradiction, and the remainder are HIGH/MEDIUM divergences of constants or operators.

**Defect count: 11** — 3 CRITICAL, 5 HIGH, 3 MEDIUM

---

## Spec-to-Code Traceability Matrix

| Spec § | Rule | Code Location (file:line) | Status | Notes |
|---|---|---|---|---|
| §4 | Close when `High−Low >= H_range` | `quant/aggregator.py:92` | **PASS** | `if spread >= self.range_size:` — exact `>=` operator, spread computed inclusively of the new tick. |
| §4 | Next bar opens at prior close | `quant/aggregator.py:93-94` | **PASS** | `closed = self._bar; self._start(tick, None)` — next bar's `open=tick.price` = prior close (the tick that completed the range). |
| §4 | `H_raw = ATR_14(1m) × kappa` | `quant/amt/profile/range_bars.py:136` | **PASS** | `h_raw = atr * self._scale` with `self._scale` clamped to `[0.1, ∞)` (`:89`); ATR is SMA of True Range over 14 bars (`:103-117`). |
| §4 | Quantize to `{5,10,25,50,100,200}` | `quant/amt/profile/range_bars.py:46,139` | **MEDIUM** | Ladder is `(2,5,10,25,50,100,200)` — adds a `2` step the spec does not list. See **D-A8**. |
| §4 | Range bars are the decision driver | `quant/runtime.py:384-409` | **FAIL** | Live engine constructs plain interval `BarAggregator(interval_seconds=…)`. `DynamicRangeBarAggregator` is never constructed outside tests. See **D-A1**. |
| §5.1 | `V(p) = Σ V_buy(p) + V_sell(p)` | `quant/amt/profile/volume_profile.py:314,316` | **PASS (proxy)** | Volume binned by bucket; buy/sell split inferred from `taker_buy_volume` or `delta` (`:282-294`). Spec-level tick binning is a proxy — spec §16 acknowledges this. |
| §5.1 | `POC = argmax V(p)` | `quant/amt/profile/volume_profile.py:56,57` | **PASS** | `max_vol = max(...)`; `poc_candidates = [i for i,p if p.volume == max_vol]`; tie-break to nearest VWAP (`:62`) is a sensible superset of the spec. |
| §5.1 | Value Area = 68.2% from POC | `quant/amt/profile/volume_profile.py:99-102,105` | **FAIL** | `VALUE_AREA_PCT = 0.70` (70%), not 0.682. See **D-A3**. |
| §5.1 | VA expand from POC iteratively | `quant/amt/profile/volume_profile.py:111-168` | **PASS (variant)** | CME two-row-pairs expansion from POC, with documented deviation (averages, 2-row steps, gap guard). A different, defensible algorithm than the spec's single-row expansion. |
| §5.1 | `LVN: V(p) < 0.35 × mean AND d²V/dp² > 0` | `quant/amt/profile/lvn.py:169-173` | **FAIL** | Uses `lvn_percentile` (20th pct) + local-minimum test. The `0.35 × mean` threshold is absent and **convexity is never computed anywhere**. See **D-A2**. |
| §5.2 | Layer 1 Macro Session Profile | `quant/amt/analyzer.py:466-489,514-516` | **PASS** | Full-session profile via `IncrementalVolumeProfile` / `create_profile`, POC + CME VA. |
| §5.2 | Layer 2 Compression Box Profile | `quant/amt/profile/compression_box.py:42-73,113-156` | **PASS** | Distinct detector, own micro-POC/VAH/VAL, close-based breakout (`:59-63`). `max_lookback=30` matches the spec's "15-30m". |
| §5.2 | Layer 3 Impulse / Leg Profile | `quant/amt/profile/displacement.py:39-186` | **PASS** | Anchored on the last directional run; own profile, own POC/VA/VAL/LVN, `profile_source` distinguishes `TICK_FOOTPRINT` vs `CANDLE_DISTRIBUTED`. |
| §5.2 | Layer 4 Gap Profile | `quant/amt/profile/gap_profile.py:46-105,108-249` | **PASS** | Distinct detector, gap zone isolated from `prior_close`→`session_open`, own POC/VAH/VAL/LVNs. |
| §5.2 | 4 layers are distinct, not one reused | the four files above | **PASS** | Four separate classes with separate anchors and separate output types. See "Verified Correct". |
| §6.1 | `VWAP = Σ(TP·V)/ΣV`, `TP=(H+L+C)/3` | `quant/amt/profile/vwap.py:61-64,133-141` | **PASS** | `self._cum_quote_vol += typical_price * vol`; typical price `(H+L+C)/3` at `analyzer.py:601`. |
| §6.1 | `σ = sqrt(Σ(TP−VWAP)²·V / ΣV)` | `quant/amt/profile/vwap.py:106-110` | **PASS** | Shifted-variance identity `E[X²w]−(E[Xw])²` is algebraically exact; `_shift` is numerical-stability only. |
| §6.1 | Bands at ±1.0σ and ±2.0σ | `quant/amt/profile/vwap.py:196-199` | **PASS** | `vwap ± vwap_std` and `vwap ± 2*vwap_std`. Exactly the spec multipliers 1.0 and 2.0. |
| §6.2 | `Delta = V_buy − V_sell`; `CVD = cumsum` | `quant/amt/orderflow/cvd.py:111-113` | **PASS** | `self._cvd += float(candle.delta)`; delta is `buy_volume − sell_volume` (`aggregator.py:132-133`). |
| §6.2 | `CVD Velocity = EMA_3 − EMA_9` | — | **FAIL** | **No implementation exists.** Velocity is replaced by a 40-bar linear-regression slope with a 3-bar sign-persistence filter. See **D-A4**. |
| §6.2 | Bullish absorption divergence (price LL + CVD HL) | `quant/amt/compute.py:221-224` | **PASS** | Genuine half-window swing comparison: `p2_min < p1_min and c2_min > c1_min`. Not a stub. |
| §6.2 | Bearish exhaustion divergence (price HH + CVD LH) | `quant/amt/compute.py:221-222` | **PASS** | `p2_max > p1_max and c2_max < c1_max`. Real swing comparison. |
| §7.1 | London/low-vol threshold 20-30 contracts | — | **FAIL** | No contract-count threshold exists. Replaced by a relative `5.0 × avg` multiplier with no session/volatility branching. See **D-A5**. |
| §7.1 | NY/high-vol threshold 30-40; institutional flag ≥100 | — | **FAIL** | Same — no absolute contract counts, no ≥100 institutional flag. |
| §7.2 | `V_b >= 1.50 × mean20` | `quant/amt/orderflow/detectors.py:356` | **FAIL** | `ABSORPTION_VOL_MULT = 2.0` and the average is full-window (`compute.py:55-59`), not the spec's rolling 20-bar mean. See **D-A6**. |
| §7.2 | `(H−L) <= 0.50 × H_range` | `quant/amt/orderflow/detectors.py:352,356` | **FAIL** | `range_ratio < ABSORPTION_RANGE_ATR` where `ABSORPTION_RANGE_ATR = 0.30` and the denominator is ATR, not `H_range`. See **D-A6**. |
| §7.2 | BUY abs: `V_sell >= 0.60·V_b` AND `close >= low + 0.50(H−L)` | `quant/amt/orderflow/detectors.py:385` | **PASS** | `sell_vol >= 0.60 * candle_vol and close_px >= mid_low` with `mid_low = low + 0.5*rng` (`:382`). Exact constant and operator; correct bullish polarity (`SELL_ABSORBED`). |
| §7.2 | SELL abs: `V_buy >= 0.60·V_b` AND `close <= high − 0.50(H−L)` | `quant/amt/orderflow/detectors.py:387` | **PASS** | `buy_vol >= 0.60 * candle_vol and close_px <= mid_high` with `mid_high = high − 0.5*rng` (`:383`). Correct bearish polarity. |
| — | Silent-fallback patterns | `quant/amt/profile/gap_profile.py:264-274` | **MEDIUM** | `try: … except Exception: return []` swallows all LVN errors inside the gap path. See **D-A11**. |

---

## Defects Found

### D-A1 [CRITICAL] — Range bars are not the decision driver; the §4 aggregator is dead code

- **Spec says (§4):** "the system normalizes price action into **Range Bars** of fixed price height H_range" and the ingestion pipeline diagram (§2) routes ticks through the "**RANGE BAR GENERATOR**". §4 rules 1-3 govern the bars the whole engine reasons on.
- **Code does:** `quant/runtime.py:384-409` constructs only interval aggregators:
  ```python
  self._aggregator = BarAggregator(interval_seconds=interval_seconds)
  ```
  A repo-wide construction search (`grep -rn "BarAggregator(" --include=*.py`, excluding tests) returns exactly seven live sites: `range_bars.py:187` (the wrapper itself) and six `runtime.py` interval-mode calls. `DynamicRangeBarAggregator` is referenced only inside its own file and inside `tests/`. The entire `quant/amt/profile/range_bars.py` module is therefore unreachable in production.
- **Impact:** The §4 rule set that everything downstream is specified against (fixed-price-height bars with `Open_{t+1} = Close_t`) never executes in live trading. Every downstream detector (absorption, VA, CVD) evaluates on 1-minute time bars, whose `H_range`-relative and `mean_20`-relative comparisons are therefore evaluated against a bar granularity the spec does not define. This is the single largest spec-to-runtime gap in the audited surface.
- **Note on good faith:** The implementation itself is correct — `quant/aggregator.py:92` implements `spread >= self.range_size` and `:93-94` re-opens at the completing tick price. `range_bars.py:136` implements `h_raw = atr * self._scale`. The defect is wiring, not math. Spec §16 documents this as "an architectural choice, not a bug"; this review records it as a CRITICAL spec-vs-code divergence regardless, because §4's own rules are silent about the fallback and the assignment is "verify the spec is implemented in actual code."
- **Suggested fix:** Wire `DynamicRangeBarAggregator` as the primary aggregator in `quant/runtime.py` (with `kappa` and the quantization ladder from §4), or add an explicit `AMT_RANGE_BARS_ENABLED` flag plus a live test asserting which path is active. As-is, a reader cannot distinguish "deliberately time-barred" from "range bars unfinished."

### D-A2 [CRITICAL] — LVN convexity predicate is missing; the 0.35×mean threshold is not used

- **Spec says (§5.1, rule 4):**
  > LVN = { p | V(p) < 0.35 × V̄_profile  AND  d²V(p)/dp² > 0 }
- **Code does:** `quant/amt/profile/lvn.py:169-173`
  ```python
  pct_threshold = _percentile(sm, lvn_percentile)   # lvn_percentile = 20.0
  ...
  if sm[i] < sm[i - 1] and sm[i] < sm[i + 1] and sm[i] <= pct_threshold:
  ```
  There is no `0.35 × mean` comparison and **no second-derivative computation anywhere in the codebase.** Searches for `0.35`, `convex`, `d2v`, `d²`, `curvature`, and `second derivative` across `quant/` return only unrelated matches (`risk.py` risk percentages, `timesfm_sizing.py` Kelly/dispersion constants). The `lvn_threshold` parameter still threaded through `find_lvns` (`lvn.py:133`) is explicitly labelled dead: `"# kept for API compatibility (unused)"`. `LVN_THRESHOLD = 0.15` in `constants.py:50` and `analyzer.py:143` is also unused — `LVN_PERCENTILE = 20.0` is the effective gate.
- **Impact:** The two spec conditions are not equivalent, and the code's is strictly weaker in the way that matters:
  - **No convexity ⇒ trend-continuation LVNs are missed.** A monotone descending volume ramp (V strictly decreasing into a low-volume tail, e.g. prices grinding into a genuine liquidity void) satisfies the code's `sm[i] < sm[i-1] and sm[i] < sm[i+1]` only at the single bottom-most sample, and only if that sample happens to fall under the 20th percentile. Spec LVNs on convex-but-shallow troughs are systematically dropped — exactly the "pullback entry zone" the Layer-3 retest playbook (§9.3) depends on.
  - **Percentile is relative, the spec threshold is absolute.** `0.35 × mean` is a fixed fraction of average profile volume; the 20th percentile is a rank that shifts with the shape of the distribution. In a profile with many near-empty bins (a wide, thin session), the 20th percentile can sit far above `0.35 × mean`, admitting bins the spec would reject; in a profile with a few extreme HVNs, it can sit below, rejecting bins the spec would accept.
  - Because `find_lvns` feeds `quant/amt/analyzer.py:514`, `profile/displacement.py:121` (Layer 3 leg LVN), and `profile/gap_profile.py:265` (Layer 4 gap LVN), the error propagates to all retest and target logic.
- **Suggested fix:** Add the convexity predicate to `find_lvns` alongside the percentile gate (a centred second difference on the smoothed series is sufficient and matches the spec's discrete formulation):
  ```python
  mean_vol = sum(sm) / len(sm)
  ...
  def _second_diff_positive(sm, i):
      if i <= 0 or i >= len(sm) - 1:
          return False
      return (sm[i + 1] - 2 * sm[i] + sm[i - 1]) > 0
  ...
  if (sm[i] < sm[i - 1] and sm[i] < sm[i + 1]
          and sm[i] < LVN_VOL_FRACTION * mean_vol      # 0.35 per spec
          and _second_diff_positive(sm, i)):
  ```
  Then remove the unused `lvn_threshold` parameter chain (`lvn.py:133`, `analyzer.py:143,217`, `displacement.py:26`, `gap_profile.py:261-267`) so the constant that gates production LVNs is the one the spec names.

### D-A3 [CRITICAL] — Value Area is 70%, spec requires 68.2%

- **Spec says (§5.1, rule 3):** "Value Area (VA = **68.2%** of Total Volume)"; the inequality is `V(POC) + Σ_{VAL}^{VAH} V(p) ≥ 0.682 × Σ V(p)`.
- **Code does:** `quant/contracts/constants.py:52`
  ```python
  VALUE_AREA_PCT = _get("value_area_pct", 0.70)
  ```
  and `backend/config/base.yaml:27` `value_area_pct: 0.70`, consumed at `quant/amt/profile/volume_profile.py:105` (`target_volume = total_volume * value_area_pct`). Every call site inherits it: session profile (`analyzer.py:489`), compression box (`compression_box.py:183`, which passes no pct and gets the 0.70 default at `volume_profile.py:99-102`), gap profile (`gap_profile.py:232`), and the leg profile's own inlined VA loop (`displacement.py:142`, `target_volume = total_volume * VALUE_AREA_PCT`). `FABIO_VALUE_AREA_PCT = 0.70` at `constants.py:243` repeats the same wrong constant under a "Fabio" label.
- **Impact:** A 1.8-percentage-point wider Value Area is not a rounding matter — it is the boundary that classifies the whole market. Spec §1 states price rotates between VAL and VAH ~70-80% of the time; inflating the VA band systematically (a) reclassifies genuinely imbalanced conditions as BALANCED, (b) widens the `balance_ratio` denominator (`analyzer.py:584-588` counts closes inside `[val, vah]`), and (c) moves every VA-based target, rejection, and acceptance/rejection level in Playbooks A and B. `state_result.zone` and `MarketState` both derive from these levels, so the misclassification changes trade selection, not just drawing.
- **Suggested fix:** Set `value_area_pct: 0.682` in `backend/config/base.yaml` (the code already reads config, so no code change is needed), delete the duplicated `FABIO_VALUE_AREA_PCT`, and add a test asserting `VALUE_AREA_PCT == 0.682`. If 0.70 is a deliberate CME-standard choice, record it in `docs/amt/` as a ratified deviation — currently nothing in the authoritative spec directory justifies it.

### D-A4 [HIGH] — CVD velocity is a 40-bar regression slope, not EMA_3 − EMA_9

- **Spec says (§6.2):**
  > CVD Velocity = EMA_3(CVD) − EMA_9(CVD)
- **Code does:** `quant/amt/orderflow/cvd.py:141-179` computes a linear-regression slope over a 40-bar window with a 3-bar sign-persistence filter:
  ```python
  window = self._history[-self._slope_window :]     # CVD_SLOPE_EXTENDED_WINDOW = 40
  raw_slope = mc.linreg_slope(window)
  ...
  recent_signs = self._slope_sign_history[-CVD_SLOPE_PERSISTENCE_BARS:]
  if all(s == current_sign for s in recent_signs):
  ```
  No EMA_3 or EMA_9 exists. Searches for `EMA_3`, `ema.*[39]`, `period=3`, `period=9` across `quant/` return nothing relevant; the only "velocity" in the CVD path is this slope.
- **Impact:** This is a real, working momentum measure, but it is not the spec's, and it differs in the properties that matter for the absorption/exhaustion mechanics in §6.2:
  - **Wrong time constant.** EMA_3 − EMA_9 is a fast crossover band (~2-9 bar effective lag) tuned to catch acceleration at the exact moment of an absorption squeeze. A 40-bar regression slope is a slow trend estimator; by construction it lags precisely the sharp CVD thrusts that §13.1 uses for the instant risk-zero ratchet ("CVD expands with 2 consecutive range bars closing in profit").
  - **Not a difference of EMAs ⇒ no zero-crossing semantics.** The spec's form is a band-difference, whose sign flips exactly when the fast mean reverts through the slow one — the literal "delta stabilizing" language of the §8 ABSORBING→ACCUMULATING transition. A regression slope's sign flip means something different.
  - **The persistence filter is undocumented in the spec.** It deliberately suppresses sign changes for 3 bars (`cvd.py:172-176`). Whatever its anti-flicker merit, it further delays the acceleration signal the spec wants to be fast.
- **Suggested fix:** Add a `velocity` to `CVDState` computed exactly as specified:
  ```python
  def _ema(self, series, period):
      a = 2.0 / (period + 1)
      e = series[0]
      for v in series[1:]:
          e = a * v + (1 - a) * e
      return e
  velocity = self._ema(self._history, 3) - self._ema(self._history, 9)
  ```
  Emit it alongside `slope` so downstream gates can use the spec metric, and either document why the 40-bar slope is preferred for the emitted `slope` or switch `cvd_confirmed` to the velocity.

### D-A5 [HIGH] — Big Trade Filter has no contract-count thresholds and no session/volatility branching

- **Spec says (§7.1):**
  > London Session / Low Volatility: Bubble filter threshold = 20–30 Contracts.
  > New York Session / High Volatility: Bubble filter threshold = 30–40 Contracts (Large Institutional Flag ≥ 100 Contracts).
- **Code does:** `quant/amt/orderflow/detectors.py:81-83`
  ```python
  vol_ratio = float(candle.volume) / avg_candle_vol
  if vol_ratio < self._multiplier * 0.5:  # Must be at least 2.5x avg
      return None
  ```
  with `BIG_TRADE_MULTIPLIER = 5.0` (`constants.py:82`, `base.yaml:48`). The gate is purely relative (5× a rolling average) — there is no absolute contract count, no London/NY branching, no volatility-state branching, and no ≥100 institutional flag. The sibling bubble detector (`detectors.py:165`) is also relative: `if sigma < VOLUME_BUBBLE_SIGMA` with `VOLUME_BUBBLE_SIGMA = 2.0`. The absolute-contract language that does exist lives only in the spec's own reference implementation (`AMT_INSTITUTIONAL_SCALPER_ALGORITHM.md:586`, `if current_bar.volume >= 30.0`), which is documentation, not code.
- **Impact:** A relative-only filter cannot implement the spec's intent, because the spec's thresholds are *absolute liquidity* thresholds: 20-40 contracts means "this print is institutionally sized for this market." On a low-liquidity Indian option contract where the average candle is 300 contracts, `5.0 × avg` fires at 1500 contracts — 15× the spec's institutional floor — so retail noise is mislabelled institutional. On a high-liquid index future where the average candle is 50,000 contracts, `5.0 × avg` requires 250,000 contracts and no print can ever qualify, so genuine institutional clusters are missed entirely. Both failure modes fall in the live signal path: `big_trade_confirmed` feeds `AggressionScorer` (`aggression.py:160-164`) as `AGGRESSION_BIG_TRADE = 1.0`, a full point of the 2.0 minimum confirmation score.
- **Suggested fix:** Add an absolute floor in contract units, branched by session and volatility state as the spec specifies:
  ```python
  BIG_TRADE_MIN_CONTRACTS = {"LONDON": 20.0, "NY": 30.0, "INSTITUTIONAL": 100.0}
  if candle.volume < self._min_contracts(session, volatility_state): return None
  if vol_ratio < self._multiplier: return None
  ```
  At minimum, add an absolute-contract floor so the relative multiplier can never fire on sub-institutional volume.

### D-A6 [HIGH] — Absorption thresholds: 2.0×mean (full window) instead of 1.50×mean_20, and 0.30×ATR instead of 0.50×H_range

- **Spec says (§7.2):**
  > 1. V_b ≥ 1.50 × V̄_20 (Volume is ≥ 150% of 20-bar rolling average).
  > 2. (H_b − L_b) ≤ 0.50 × H_range (Price range is compressed; effort without result).
- **Code does:** `quant/amt/orderflow/detectors.py:352-356`
  ```python
  range_ratio = candle_range / atr
  vol_ratio = candle_vol / avg_vol
  if range_ratio < ABSORPTION_RANGE_ATR and vol_ratio >= ABSORPTION_VOL_MULT:
  ```
  with `ABSORPTION_RANGE_ATR = 0.30` and `ABSORPTION_VOL_MULT = 2.0` (`constants.py:80-81`, `base.yaml:46-47`). Two separate divergences:
  1. **Volume threshold: 2.0 vs 1.50.** A stricter constant, so the code fires on strictly fewer bars than the spec allows. On the margin, genuine 1.5-2.0× effort-without-result bars are silently dropped from the Triple-A WAITING→ABSORBING transition.
  2. **The reference is ATR, not H_range.** The spec's denominator is the quantized range-bar height; the code divides by a 14-period ATR. These coincide only if `H_range` were the ATR-quantized bar (see **D-A1** — it is not, since range bars are not live). Because ATR is a 14-bar average of true range while `H_range` is a quantized single volatility snapshot, the ratio's meaning differs, and with `ABSORPTION_RANGE_ATR = 0.30` the effective compression requirement is *tighter* than the spec's 0.50 for typical ATR > 0.6 × H_range.
  3. **The mean is not the 20-bar rolling mean.** `quant/amt/orderflow/compute.py:55-59` computes the average over the whole `recent_data` window (up to `RECENT_DATA_WINDOW = 100` candles, `constants.py:211`), not a 20-bar rolling mean. A full-window mean is dominated by older regime volume, so after a volume regime change the threshold drifts and absorption detection becomes regime-dependent.
  4. **Operator: `<` vs `<=`.** Spec uses `≤`; code uses `range_ratio < 0.30` (`detectors.py:356`). A bar whose range is exactly `0.30 × ATR` is excluded. Minor, but it is the exact operator divergence the assignment asks to catch.
- **Impact:** `absorption_detected` and `absorption_side` are the primary input to the Triple-A state machine (`analyzer.py:814-826`), to `AGGRESSION_ABSORPTION = 0.5` in the aggression score, and — critically — to the stop-loss placement of §9.1 (`SL = L_cluster − 2 × TickSize`) via `absorption_cluster_high/low`. Getting the volume constant and the range reference wrong misplaces the cluster bounds that the hard stop is pegged to.
- **Suggested fix:** Introduce `ABSORPTION_VOL_MULT = 1.50` and a dedicated 20-bar rolling mean:
  ```python
  mean20 = sum(d.volume for d in recent_data[-20:]) / max(1, len(recent_data[-20:]))
  if vol_ratio >= ABSORPTION_VOL_MULT and candle_range <= 0.50 * h_range:
  ```
  passing the live `h_range` (from `ATRRangeCalculator.range_size(tick_size)`) instead of ATR once range bars are wired.

### D-A7 [HIGH] — Range-bar quantization ladder contains an off-spec `2` step

- **Spec says (§4):** `H_range = Quantize(H_raw, {5, 10, 25, 50, 100, 200})`.
- **Code does:** `quant/amt/profile/range_bars.py:43-46`
  ```python
  # Spec §4 quantization steps for H_range (price units). These are the CME
  # standard range-bar steps; Indian instruments use the same ladder scaled by
  # tick. The steps are applied per-tick: e.g. step=10 with tick=0.05 -> 0.5.
  _DEFAULT_QUANT_STEPS = (2, 5, 10, 25, 50, 100, 200)
  ```
- **Impact:** For any instrument whose `H_raw/tick_size < 5`, the code selects step `2` where the spec's floor is `5` — a range bar 2.5× narrower than the spec permits. That regime is exactly the low-volatility case (tight Indian option premiums, summer compression, the spec §10 "Mondays & Fridays: Defensive size" sessions) where over-narrow bars produce many small bars and inflate every per-bar metric (bubble counts, aggression persistence, the `mean_20` reference). The comment claims the steps are "per-tick" and CME-standard, which is a reasonable Indian-market adaptation, but it is not what §4 enumerates.
- **Suggested fix:** Either drop `2` to match the spec ladder, or add `RangeBarConfig(quant_steps=…)` per instrument and document the Indian-market scaling in `docs/amt/`. The comment at `:43-45` already half-justifies it; make the deviation explicit and configurable rather than baked into the default.

### D-A8 [HIGH] — `H_range` bucket width is not `S_bucket`; profiles use auto-computed bucket counts

- **Spec says (§5.1):** "discretized into price bins of width `S_bucket = H_range`".
- **Code does:** `quant/amt/profile/volume_profile.py:213-221`
  ```python
  def compute_optimal_buckets(price_range: float, tick_size: float = 0.05) -> int:
      ticks_in_range = price_range / tick_size
      return max(100, min(int(ticks_in_range), 1000))
  ```
  and `create_profile(...)` at `:249-262` calls it whenever `buckets <= 0`, which is the default path in `analyzer.py:475` (`profile = create_profile(recent_data)`). Bucket width is therefore `price_range / compute_optimal_buckets(...)` — a data-dependent 100-1000 buckets clamped by tick count — not `H_range`. `DELTA_PROFILE_BUCKETS = 200` (`constants.py:61`) is used only for the leg profile (`displacement.py:111`).
- **Impact:** The profile's price resolution is decoupled from the volatility-normalized range height. The LVN/HVN/POC/VA levels the strategy trades are computed at a resolution the spec does not specify, and — because `min(1000, ticks_in_range)` is the binding constraint on liquid instruments — the bucket count changes as the session's range grows, so a profile early in the session has coarser bins than the same profile later. LVN "retest tolerance" (§9.3, `P ∈ [LVN ± ε]`) is then measured against a moving grid. `leg_lvn.py:39-46` already carries a bounded retest tolerance in tick/bucket/span units, which is a good mitigation, but the underlying grid drift remains.
- **Suggested fix:** Thread `h_range` from `ATRRangeCalculator.range_size(tick_size)` into `create_profile`/`IncrementalVolumeProfile` and set `step = h_range` when it is available, falling back to `compute_optimal_buckets` only before the first ATR reading.

### D-A9 [MEDIUM] — `kappa_scale` default is 1.0 and is never set from spec or config

- **Spec says (§4):** `H_raw = ATR_14(1m Klines) × κ_scale`.
- **Code does:** `quant/amt/profile/range_bars.py:84` `scale_factor: float = 1.0`, clamped at `:89` (`self._scale = max(0.1, scale_factor)`). No config key, no symbol-specific override, and no call site passes a value (the only construction is inside the dead-code module; see D-A1).
- **Impact:** With `κ = 1.0` the range height equals the raw ATR with no volatility adjustment. The spec names κ as a tunable parameter, implying per-instrument or per-session calibration; with the current wiring it is effectively a constant the operator cannot change without editing code. Low impact today only because the module is unreachable.
- **Suggested fix:** Expose `kappa_scale` in `backend/config/base.yaml` globals (e.g. `range_bar_kappa_scale: 1.0`) with per-symbol overrides, and assert it in a test.

### D-A10 [MEDIUM] — CVD divergence requires ≥4 bars of window but no swing-structure validation

- **Spec says (§6.2):** "Price makes **Lower Lows**, but CVD makes **Higher Lows**" — a statement about swing structure, and §15 row 4 requires a full candle **close** beyond the cluster.
- **Code does:** `quant/amt/compute.py:203-225`
  ```python
  w = len(prices)
  if w < 4 or len(cvds) < w:
      return "NONE", 0.0
  half = w // 2
  p1_max = max(prices[:half]); p2_max = max(prices[half:])
  ...
  if p2_max > p1_max and c2_max < c1_max:
      return "BEARISH_DIV", abs(p2_max - p1_max) / price_std
  if p2_min < p1_min and c2_min > c1_min:
      return "BULLISH_DIV", abs(p2_min - p1_min) / price_std
  ```
  The comparison is real and correctly oriented (verified: bullish = price lower-low `p2_min < p1_min` with CVD higher-low `c2_min > c1_min`; bearish = price higher-high with CVD lower-high). But the "swings" are unconditional half-window maxima/minima, not validated pivots: there is no requirement that the extreme be a local turning point, no minimum separation, and no check that the two halves contain comparable structure. With `divergence_window = 20` (`cvd.py:78`) and the call at `cvd.py:186-188`, a monotone trend whose second half simply trends further can satisfy the inequality without any swing existing.
- **Impact:** False-positive divergences on trending windows — precisely the condition the spec's bearish-exhaustion signal is meant to detect, so the two are confusable. The emitted `divergence_type` feeds `cvd_confirmed` (`compute.py:96-101`) and `cvd_div` (`analyzer.py:680-683`), which feed the aggression score and the Triple-A machine. Test coverage is thin here: `tests/quant/amt/orderflow/test_cvd.py:45-53` only asserts the result is one of the three enum strings.
- **Suggested fix:** Require that the half-window extremes be local pivots (e.g. `prices.index(p2_min)` strictly inside the second half, not at its boundary), and add tests with real LL/HL and LL/LL sequences asserting BULLISH_DIV vs NONE.

### D-A11 [MEDIUM] — Silent fallback in Layer 4 gap-LVN extraction

- **Spec says (§5.1, rule 4):** LVNs are defined by a specific two-condition predicate (see D-A2). The assignment additionally asks to flag `try/except: pass` and silent-fallback patterns.
- **Code does:** `quant/amt/profile/gap_profile.py:264-274`
  ```python
  try:
      levels = _find_lvns_raw(profile, lvn_threshold=_Cfg.LVN_THRESHOLD, ...)
      return [lvn.price for lvn in levels]
  except Exception:
      return []
  ```
  A bare `except Exception` returning `[]` converts any failure — including a future bug in `find_lvns` or a malformed `VolumeProfileLevel` list — into "no gap liquidity voids," with only the module logger available. Also note the `_Cfg` class at `:260-262` hardcodes `LVN_THRESHOLD = 0.15` / `LVN_SMOOTHING = 3` locally, which is then passed as the parameter that `find_lvns` ignores (D-A2) — so this local config object is doubly dead.
- **Impact:** A Layer-4 LVN failure degrades silently to "no voids," and because `gap_lvns` is only surfaced (not currently a decision gate in the analyzer path — `analyzer.py:904-906` emits `gap_profile_poc/vah/val` only), the practical trading impact is low today. It becomes HIGH the moment gap LVNs are wired into an entry gate. The pattern also sets a precedent: a swallowed exception in a spec-math path is indistinguishable from a correct "no LVNs" answer.
- **Suggested fix:** Narrow the except to the specific expected failure modes (or remove it — `find_lvns` has no documented exception contract), log at WARNING with the profile length and bucket count, and return the sentinel `GapProfile` with `is_gapped=True` and empty `gap_lvns` so the caller can distinguish "computed, none found" from "failed."

---

## Verified Correct (with code quotes)

**§4 Range bar closure and re-open — `quant/aggregator.py:91-95`**
```python
spread = max(self._bar.high, tick.price) - min(self._bar.low, tick.price)
if spread >= self.range_size:
    closed = self._bar
    self._start(tick, None)
    return closed
```
`>=` matches §4 rule 1 exactly, and `_start` sets `open=tick.price` (`:109`), which is the prior bar's completing close, matching rule 2.

**§4 ATR and quantization — `quant/amt/profile/range_bars.py:113-117,136-140`**
```python
def raw_atr(self) -> float:
    if not self._true_ranges:
        return 0.0
    return sum(self._true_ranges) / len(self._true_ranges)
...
h_raw = atr * self._scale
step_units = _quantize(h_raw / tick_size, self._steps)
h_range = step_units * tick_size
```
ATR(14) is a rolling SMA of True Range with the buffer trimmed to `_period` (`:106-107`), `_true_range` is the correct three-term max (`:49-51`), and `_quantize` returns "the smallest step that is >= value" (`:60-63`) — a defensible reading of "Quantize".

**§5.1 POC — `quant/amt/profile/volume_profile.py:56-62`**
```python
max_vol = max(p.volume for p in profile)
poc_candidates = [i for i, p in enumerate(profile) if p.volume == max_vol]
...
idx = min(poc_candidates, key=lambda i: abs(profile[i].price - vwap_ref))
```
`argmax V(p)` with a deterministic VWAP tie-break.

**§5.1 Value-area expansion from POC — `quant/amt/profile/volume_profile.py:107-157`**
```python
current_volume = profile[poc_index].volume
up_idx = poc_index
down_idx = poc_index
while current_volume < target_volume:
```
Starts at POC and expands iteratively upward and downward, comparing the two candidate sides per step, with a `while current_volume < target_volume` loop condition that matches the spec's `≥ target` termination and a `break` when both sides are exhausted (`:133-134`). The two-row-pairs variant with average comparison (`:81-89`, `:154-155`) and the 1%-of-POC gap guard (`:142-147`) are documented deviations from the spec's single-row expansion, and the code says so explicitly in the docstring at `:74-95` and the CRUDEOIL comment at `:136-141`.

**§5.2 Four distinct profile layers** — four separate classes with separate anchors, confirmed by reading each file:
1. Layer 1 Macro Session — `IncrementalVolumeProfile` (`volume_profile.py:321-518`) + `compute_poc`/`compute_value_area`, wired at `analyzer.py:466-489`.
2. Layer 2 Compression Box — `CompressionBoxDetector` (`compression_box.py:95-194`), anchored inside the last ≤30 bars, emits its own `micro_poc/micro_vah/micro_val`, and `is_broken_out` requires a close beyond the box (`:59-63`) — matching §5.2's "true out-of-balance condition requires a 1m candle close outside this box."
3. Layer 3 Impulse Leg — `detect_displacement_leg` (`displacement.py:39-186`), anchored on the last directional run with 1-reversal-candle tolerance (`:72-83`), builds its own profile, and tags `profile_source` as `TICK_FOOTPRINT` or `CANDLE_DISTRIBUTED` (`:102-112`).
4. Layer 4 Gap — `GapProfileDetector` (`gap_profile.py:108-249`), anchored across `prior_close`→`session_open` (`:160-192`), isolates gap-overlapping candles (`:196-199`), and emits its own `gap_poc/gap_vah/gap_val/gap_lvns`.

These are four genuinely different anchored profiles, not one generic profile reused — the architecture requirement of the assignment is satisfied.

**§6.1 VWAP and σ — `quant/amt/profile/vwap.py:61-69,106-110`**
```python
self._cum_vol += vol
self._cum_quote_vol += typical_price * vol
...
shifted = typical_price - self._shift
self._cum_sq_vol += shifted * shifted * vol
...
variance = max(0.0, self._cum_sq_vol / self._cum_vol - (self.vwap_value - self._shift) ** 2)
return math.sqrt(variance)
```
The shifted form is the identity `Σ(TP−s)²V/ΣV − (VWAP−s)² = Σ(TP−VWAP)²V/ΣV`; `_shift` is purely for floating-point stability and does not alter the value. Typical price `(H+L+C)/3` is computed at `analyzer.py:601` and `vwap.py:134`.

**§6.1 Bands — `quant/amt/profile/vwap.py:196-199`**
```python
vwap_upper_1 = session_vwap + vwap_std
vwap_lower_1 = session_vwap - vwap_std
vwap_upper_2 = session_vwap + 2 * vwap_std
vwap_lower_2 = session_vwap - 2 * vwap_std
```
Exactly ±1.0σ and ±2.0σ as specified.

**§6.2 Delta and CVD — `quant/amt/orderflow/cvd.py:111-113`, `quant/aggregator.py:132-133`**
```python
self._cvd += float(candle.delta)
self._history.append(self._cvd)
```
with `delta=(bar.buy_volume + tick.buy_volume) - (bar.sell_volume + tick.sell_volume)` — `V_buy − V_sell`, cumulated.

**§6.2 Divergences are real swing comparisons, not stubs — `quant/amt/compute.py:221-224`**
```python
if p2_max > p1_max and c2_max < c1_max:
    return "BEARISH_DIV", abs(p2_max - p1_max) / price_std
if p2_min < p1_min and c2_min > c1_min:
    return "BULLISH_DIV", abs(p2_min - p1_min) / price_std
```
Both spec cases are implemented with the correct polarity: bullish absorption divergence is genuinely price lower-lows with CVD higher-lows; bearish exhaustion is price higher-highs with CVD lower-highs. The z-score normalization is an extra not in the spec. (Structural weakness only: see D-A10.)

**§7.2 Directional classification — `quant/amt/orderflow/detectors.py:380-388`**
```python
rng = float(candle.high - candle.low)
close_px = float(candle.close)
mid_low = float(candle.low) + 0.5 * rng
mid_high = float(candle.high) - 0.5 * rng

if sell_vol >= 0.60 * candle_vol and close_px >= mid_low:
    self._pending_side = "SELL_ABSORBED"  # Sellers absorbed by hidden buyers -> bullish
elif buy_vol >= 0.60 * candle_vol and close_px <= mid_high:
    self._pending_side = "BUY_ABSORBED"   # Buyers absorbed by hidden sellers -> bearish
```
This is the best-implemented rule in the audited set. Both spec constants are exact (`0.60`, `0.50`), both comparison operators match (`>=`, `>=` / `<=`), and the buy/sell polarity is correct: heavy *sell* aggression absorbed by a passive buy wall is labelled bullish (`SELL_ABSORBED`), matching §7.2's "Sellers punched a passive buy wall." The `canonical_absorption_direction` map in `aggression.py:62-65` agrees (`"SELL_ABSORBED" → "LONG"`), so the polarity is consistent end-to-end into the aggression score. The buy/sell split correctly prefers reported `taker_buy_volume` and falls back to a delta-derived split clamped to ±volume (`detectors.py:366-378`).

**§15 / §8 Displacement requirement — `quant/amt/orderflow/detectors.py:303-331`**
Absorption is not confirmed on the signature bar; it is stored as pending and only emitted once a later candle closes beyond the cluster high/low, with a 3-candle expiry and wrong-way invalidation. This correctly implements §15 row 4 ("1m candle CLOSES beyond Cluster") and §8's ABSORBING→ACCUMULATING progression, and the emitted `cluster_high/cluster_low` are exactly what §9.1's `SL = L_cluster − 2 × TickSize` needs.

---

## Suspicious / Needs Human Eyes

1. **The `0.30` ATR / `2.0` volume pair in `base.yaml:46-47` vs the spec's `0.50 H_range` / `1.50 mean20`.** `constants.py:239-240` defines `FABIO_ABSORPTION_VOL_MULT = 2.0` and `FABIO_ABSORPTION_RANGE_ATR = 0.30` under a "Fabio AMT Methodology Parameters" heading, and `constants.py:243` `FABIO_VALUE_AREA_PCT = 0.70` — a second source of truth that duplicates and contradicts `ABSORPTION_VOL_MULT`/`ABSORPTION_RANGE_ATR`/`VALUE_AREA_PCT`. The `FABIO_*` constants appear unused by `detectors.py` (which imports the non-prefixed names). Either the Fabio values are authoritative and the spec constants are stale, or the reverse. A human must decide which; the dead duplicates should then be deleted so there is one constant per concept.

2. **Spec §16 self-declarations.** The spec's own final section (§16, `AMT_INSTITUTIONAL_SCALPER_ALGORITHM.md:741-756`) acknowledges range bars are not the primary driver, tick-level aggression is a candle-delta proxy, and L2 depth is 5-level not 20-50 level. These are honest disclosures, but they mean D-A1, and parts of D-A5/D-A6, are *known and accepted* divergences rather than oversights. Someone needs to decide whether this repo treats §16 as a ratified amendment to §4/§3 or as a debt ledger to be paid down. If the former, §4's rules should be re-worded in the spec so the code and the spec agree; if the latter, D-A1 and D-A5 become work items.

3. **The two dead parameter chains.** `lvn_threshold` is threaded through `find_lvns` (`lvn.py:133`), `analyzer.py:143,217`, `displacement.py:26`, and `gap_profile.py:261-267` (the last as a locally-hardcoded `_Cfg` class) and is used nowhere; `hvn_threshold` likewise (`lvn.py:201`). Combined with `LVN_THRESHOLD = 0.15` being exported from `constants.py:50` and `base.yaml:25`, an operator could reasonably believe tuning `lvn_threshold` changes LVN detection. It does not. This is the exact "hardcoded values substituted for spec values" hazard the assignment flags — here the hardcoded value (the 20th percentile) is not even visible at the config layer.

4. **`H_range` is never available to the detectors.** Because range bars are not wired, `AbsorptionDetector` receives ATR (`compute.py:108`) and there is no live source of `H_range` anywhere in the analyzer path. D-A6's fix depends on D-A1's fix; fixing the absorption range reference without wiring range bars would substitute one proxy for another.

5. **`backend/app/api/websocket/gameloop.py` and `backend/app/api/routers/trading.py` are modified in the working tree** (per `git status`) but were outside this assignment's file list. If either changes the bar interval or the aggregator construction, it could silently affect the §4 wiring that D-A1 concerns. Worth a confirmatory look by whoever owns the engine path.

---

*All file:line citations refer to the working tree at branch `architecture/design-level-refactoring`, commit `e589cbe5a`, 2026-09-21. Tests were run to confirm the audited modules import cleanly: `tests/quant/amt/profile/test_range_bars.py` and `tests/quant/amt/orderflow/test_detectors.py` → 46 passed.*
