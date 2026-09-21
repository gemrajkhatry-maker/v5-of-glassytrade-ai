# Agent B — Triple-A & Decision Pipeline Review vs `docs/amt`

**Scope**: Triple-A state machine (`quant/amt/triple_a.py`), the 4-gate Fabio decision
pipeline (`quant/decision/`), playbooks A/B/C, session timing §10, and the operational
master matrix §15, audited against the ONLY authoritative specs:
`docs/amt/AMT_INSTITUTIONAL_SCALPER_ALGORITHM.md` and `docs/amt/fabio_decision_pipeline.md`.

**Date**: 2026-09-21 · **Reviewer**: Agent B (Triple-A / Decisions)

## Verdict: PASS-WITH-NOTES

The Triple-A state machine and the 4-gate decision pipeline are substantially faithful to
the AMT specs. Every Gate 1–4 check documented in `fabio_decision_pipeline.md` exists in
code with the correct fail-closed semantics, and the Triple-A machine implements all four
phases with VWAP + CVD confirmation on the aggression trigger. The verdict is
PASS-WITH-NOTES rather than PASS because of: one spec-internal contradiction the code
resolves in favour of the wrong section (TP tier split, D-B1), one missing numeric guard
(CVD "expanding" is checked as "not aggressively diverging", D-B2), one spec rule with no
code counterpart at all (Playbook C RR ≥ 1:3, D-B3), and a handful of medium/low-severity
drift items detailed below. Nothing in this scope is a silent fail-open hazard: the
pipeline is fail-closed end to end.

---

## Spec-to-Code Traceability Matrix

| Spec § | Rule | Code Location (file:line) | Status | Notes |
|---|---|---|---|---|
| §8 | WAITING → ABSORBING on absorption detected | `triple_a.py:167-171` (`_update_waiting`) | ✅ PASS | Fires on `absorption_active` (pending cluster present). Vol ≥ 1.5× / range-compressed test itself lives in `orderflow/detectors.py:356` (uses 2.0× ATR-vol, 0.30× ATR-range — see D-B5). |
| §8 | ABSORBING → ACCUMULATING: "within 2 range steps of POC/LVN, 2+ bars elapsed, delta stabilizing" | `triple_a.py:200-210` (`_update_absorbing`) | ⚠️ PARTIAL | "2+ bars elapsed" ✅ (`_MIN_ACCUMULATION_BARS=2`, L28). "Near POC" ✅ but via 4-tick tolerance (`_is_near_poc` L249-256), not "2 range steps", and **LVN is not part of the check at all** — only `poc`. "Delta stabilizing" ❌ **not implemented** (no delta/CVD term in the transition). |
| §8 | ACCUMULATING → AGGRESSION | `triple_a.py:212-226` (`_update_accumulating`) | ✅ PASS | Requires detector-fired breakout + direction confirm. |
| §8 LONG trigger | close > cluster high AND price > VWAP AND CVD expanding | `triple_a.py:237-247` (`_confirm_direction`) | ⚠️ PARTIAL | VWAP ✅ (L242), CVD ✅-but-weakened: `cvd_slope > -0.3` is "not aggressively diverging", not "expanding" (D-B2). "Close > cluster high" is delegated to `AbsorptionDetector.detect` displacement test (`detectors.py:307`), which is a strict `>` ✅. |
| §8 SHORT trigger | mirror | `triple_a.py:244-246` | ✅ PASS | Symmetric mirror implemented. |
| §8 | SL 1–2 ticks behind absorption cluster | `decision/stops.py:84-108` (`structural_stop`, `inside_ticks=2`) | ✅ PASS | 2 ticks inside the anchor, toward entry — exactly §11's "pro stop" placement. |
| §9.1 A | Regime filter price > VWAP + breakout above compression box/VAH | `gates_edge.py:246-257` | ✅ PASS | Compression-box VAH/VAL breakout required when `compression_box_bars >= 3`. |
| §9.1 A | Absorption footprint cluster ≥ 30–40 contracts, no continuation | `orderflow/detectors.py:276-420`, `config/constants.py:239-240` | ⚠️ PARTIAL | Bubble threshold is volume-multiplier based (2.0× avg), not an absolute 30–40-contract floor (documented limitation — see D-B5). |
| §9.1 A | Trigger: full 1m close strictly above cluster high | `gates_edge.py:104-152` (`_candle_acceptance`) + `detectors.py:307` | ✅ PASS | Enforces full-body (≥0.60) close-near-extreme (≥0.75) candle; strict `>` in detector. |
| §9.1 A | Anti-whipsaw: never enter on 1st raw intra-bar spike | `gates_edge.py:104-152`, `gates_edge.py:33-34` | ✅ PASS | This is the *strongest* implementation in the repo: body-ratio + close-position + direction checks reject wick probes outright. See "Verified Correct". |
| §9.1 A | SL = cluster_low − 2×tick | `decision/stops.py:84-108` | ✅ PASS | 2 ticks inside structural anchor. |
| §9.1 A | TP1 50% @ first overhead LVN/prior swing high, RR ≥ 1:2.0 | `signal_builder.py:204-288` (`_structural_tp`), `exit_checks.py:82-102` | ❌ MISMATCH | TP selection ✅, RR floor is **1.5** not 2.0 (D-B1/D-B4); tier split is 50/50 of-remainder not 50/25/25 (D-B1). |
| §9.1 A | TP2 50% @ macro POC_prev / PDH | `signal_builder.py:244-264`, `exit_checks.py:99-101` | ⚠️ PARTIAL | `prior_poc` is a TP candidate ✅; **PDH/PDL is not a candidate anywhere** (D-B6). |
| §9.2 B | Failed auction: drive below VAL/session low | `va_fade.py:64-71` | ✅ PASS | `session_extreme_low < val` OR bar wick OR complete VA_FADE evidence packet. |
| §9.2 B | Re-accepts and closes back inside VA | `va_fade.py:44` (`inside_va = val <= close <= vah`) | ✅ PASS | Exact spec condition. |
| §9.2 B | Trigger 1m close inside VA | `va_fade.py:84, 98` | ✅ PASS | Close-based, and Gate 3 `_candle_acceptance` applies to non-fade paths only — see note in D-B9. |
| §9.2 B | SL 1 tick below failed auction low wick | `va_fade.py:87-90` | ⚠️ PARTIAL | `stop_ref - step` uses **1 tick** ✅ but `min(entry - step, stop_ref - step)` can collapse to `entry - step` when the probe is shallower than entry+1 tick; the guard at L89-90 then pins it. Spec-compliant in the common case, slightly wider than spec in the edge case. |
| §9.2 B | Target = session POC, 100% exit | `va_fade.py:91, 105`; `exit_checks.py:71-79, 86-93` (`is_terminal_tp_only`) | ✅ PASS | `tp = poc` and `is_terminal_tp_only` forces a **full close** at first TP touch for VA_Fade — 100% exit implemented and explicitly enforced. |
| §9.3 C | Impulse drive A→B, Layer 3 profile, primary internal LVN | `profile/leg_lvn.py` (`resolve_leg_lvn`), `position_manager.py:570-576` | ✅ PASS | Leg profile + primary LVN extraction present. |
| §9.3 C | Pullback into LVN ± epsilon | `gates_edge.py:261-265` (2 ticks); `position_manager.py:578-582` (adaptive tolerance) | ✅ PASS | Gate 3 sniper path uses 2 ticks; pyramid uses `leg_lvn_retest_tolerance`. |
| §9.3 C | Counter-aggression dries up + in-trend volume bubble | `gates_edge.py:266-276` | ⚠️ PARTIAL | Absorption-side agreement ✅; "counter-aggression dries up" is approximated by `cvd_slope >= -0.2`, not a drying-up/volume-bubble test. |
| §9.3 C | Trigger: 1m close in trend direction | `gates_edge.py:104-152` (acceptance) + `position_manager.py:588-591` (pyramid candle confirm) | ✅ PASS | |
| §9.3 C | SL 2 ticks behind LVN shelf | `position_manager.py:586` (`structural_stop(..., leg_lvn, tick)`) | ✅ PASS | 2 ticks inside LVN shelf. |
| §9.3 C | TP above point B, RR ≥ 1:3.0 to 1:5.0 | — | ❌ **MISSING** | No code path computes point B, and no RR floor of 1:3 exists for the sniper label. Falls back to the generic 1.5 floor / 2R TP. (D-B3) |
| §10 | Pre-market trap lock 10–20 min before open: STRICT ZERO new entries | `amt/session/context.py:127-132` (PRE_MARKET/NSE_OPENING, `allow_entry=False`); `session_gates.py:101-154` | ⚠️ PARTIAL | Zero-entry lock ✅ (Phase 1 + PRE_MARKET both `allow_entry=False`). But the window is **09:15–09:30 IST**, i.e. 15 min before the 09:30 open — spec says "10–20 min before open" which the repo's §16 acknowledges is approximated by the IST phase table. No separate 09:10–09:30 trap zone exists. Acceptable mapping to the Indian session; flagged for completeness. |
| §10 | 15–30 min discovery window | `amt/session/context.py:134-136` (NSE_PRIMARY 09:30–11:30) | ✅ PASS | Mapped to the NSE primary window. |
| §10 | Max trade window 3–4 hours | `execution/exit_rules.py:26-55` (`TIME_STOP_TABLE`, `HARD_MAX_HOLD_SECONDS=7200`) | ✅ PASS | Hard 120-min ceiling + session-aware time stops. |
| §10 | NO OVERNIGHT HOLDING | `position_manager.py:162-166`; `multi_engine.py:1163-1199` + `_eod_watchdog_loop` | ✅ PASS | **Two independent layers**: bar-driven `session_force_exit` → SESSION_CLOSE, and a wall-clock EOD watchdog that force-flattens 15 min before exchange close even on a dead feed. See "Verified Correct". |
| §10 | Tue/Wed/Thu full offensive, Mon/Fri defensive | `execution/risk.py:19-24` (`DAY_OF_WEEK_MULTIPLIER`), applied L419 & L465 | ✅ PASS | Mon/Fri = 0.5×, Tue/Wed/Thu = 1.0×, applied as a final multiplier on both sizing branches. |
| §15 row 1 | Session gate: keep engine locked outside window | `gates/gate_session_phase.py:54-79` | ✅ PASS | NSE 09:30–15:15 / MCX 09:15–23:15 IST blackout. |
| §15 row 2 | Pre-market lock: reject all orders | `gates/gate_session_phase.py:56-57` + `session_gates.py:121-142` | ✅ PASS | Hard reject, and a Gate-1 failure is a **hard** `GATE_REJECTED` (no fade) per `decision_service.py:134-138`. |
| §15 row 3 | Absorption flag: log cluster & bubbles | `orderflow/detectors.py:276-420` | ✅ PASS | Cluster bounds logged into the DTO (`analyzer.py:1126-1128`). |
| §15 row 4 | Squeeze trigger: 1m close beyond cluster; cancel if inside | `gates_edge.py:104-152`, `triple_a.py:190-198` | ✅ PASS | Breakout must be a confirmed close; an unconfirmed probe resets the machine (`triple_a.py:196-197`). |
| Pipeline | Gate 1..4 order + outcomes | `decision/pipeline.py:24-38`, `decision_service.py:100-167` | ✅ PASS | Order and the hard-vs-soft reject split exactly match `fabio_decision_pipeline.md`. |
| Pipeline | Gate 1 check 5 spread ≤ max(2×tick, 0.1%×price, ₹0.40) | `gates/gate_session_phase.py:109-123` | ❌ MISMATCH | Implements `max(4%×price, 2×tick)` — the ₹0.40 absolute term **and** the 0.1% term are both absent. (D-B4) |
| Pipeline | Gate 2 cooldown + thesis-flip | `gates/gate_position_cooldown.py:14-33` | ✅ PASS | Cooldown always enforces (L19) even when `allow_positioned` bypasses the position blocker (L29-30) — exactly the documented exception. |
| Pipeline | Gate 3 Phase A: 10 guards | `gates_edge.py:155-207` (`_check_guards`) | ✅ PASS | All 10 present, plus 2 extra (candle acceptance, CVD divergence). See D-B8 for threshold-direction error. |
| Pipeline | Gate 3 Phase B: 6 paths in priority order | `gates_edge.py:215-303` (`_check_setup_paths`) | ✅ PASS | Evidence → Triple-A → Second Drive → LVN Sniper → Initiative → Squeeze, in exact documented order. |
| Pipeline | Gate 4 stop cap = max(200, (entry×0.75%)/tick) | `gates_rr.py:26-43` | ⚠️ PARTIAL | Formula present and applied, but the option branch uses **5%** of premium instead of 0.75% (documented, deliberate — see D-B7). |
| Pipeline | Model router + cross-model block | `model_router.py:55-69`, `decision_service.py:104-116` | ✅ PASS | Enforced once in the service; VA-fade fallback gated by `allows("VA_FADE", active_model)` (L147). |
| Pipeline | VA-fade conditions 1–6 | `va_fade.py:27-110`, `decision_service.py:143-167` | ✅ PASS | All 6 conditions enforced; dead-market veto and min-stop both present at the call site. |
| Pipeline | Decision outcomes table | `decision_service.py:31-44, 65-167` | ✅ PASS | All 6 reasons emitted; `DATA_QUALITY_BLOCKED` is an extra, safer 7th. |

---

## Defects Found

### D-B1 [HIGH] — TP tier split is 50/50-of-remainder, not the spec's 50/25/25

- **Spec says:** §9.1 Playbook A: "*TP₁ (50%): First overhead major LVN or prior swing high …
  TP₂ (50%): Macro Session POC_prev or PDH.*" And §13.3 Multi-Tier Partial Exits:
  "*Tier 1 (50% Size) … Tier 2 (25% Size) … Tier 3 (25% Runner) …*"
  These two sections **contradict each other** (50+50 = 100% with no runner, vs 50+25+25).
- **Code does:** `quant/execution/exit_checks.py:95-102`:
  ```python
  if tp_tier == 0:
      if (long and high >= tp) or (not long and low <= tp):
          return ExitDecision(True, "TP1", tp, partial_fraction=0.5), 1
  elif tp_tier == 1:
      tp2 = tp2_level(entry, tp)
      if (long and high >= tp2) or (not long and low <= tp2):
          return ExitDecision(True, "TP2", tp2, partial_fraction=0.5), 2
  ```
  The second tier closes a further **0.5 of the remaining** size
  (`position_manager.py:495-511` `_book_tick_tp2_partial` mirrors this on the tick path),
  i.e. 50% → 25% → 25% runner. That is precisely the §13.3 ladder, and *not* §9.1's 50/50.
- **Impact:** The code resolves the spec contradiction in favour of §13.3. This is the
  safer of the two readings (it keeps a 25% runner), so the practical consequence is small,
  but §9.1 is the playbook-level spec for the primary engine and any reviewer/operator
  comparing the two will find the divergence. There is no mode or flag that reproduces a
  pure 50/50 two-tier exit.
- **Suggested fix:** Reconcile the spec: amend §9.1 to read "TP₁ (50%), TP₂ (25%), runner
  (25%)" so §9.1 and §13.3 agree, and make the ladder explicit as
  `partial_fraction=0.5` at TP1 and `0.5`-of-remainder at TP2 with the surviving 25%
  trailed. If a genuine 50/50 Playbook-A exit is desired, gate it on
  `model_label == "Triple-A"` the way `is_terminal_tp_only` gates VA_Fade.

### D-B2 [HIGH] — §8 "CVD expanding" is implemented as "CVD not aggressively diverging"

- **Spec says:** §8: "[LONG]: Full 1m candle CLOSE > Swing High / Absorption Bar **AND**
  Price > VWAP **AND CVD expanding**" — three *simultaneous* conditions, the third being a
  positive confirmation that CVD is expanding in the trade direction.
- **Code does:** `quant/amt/triple_a.py:237-247`:
  ```python
  if signal == "LONG":
      vwap_ok = vwap > 0 and close > vwap
      cvd_ok = cvd_slope > -0.3  # not aggressively diverging
  ```
  The comment itself admits the semantics is "not aggressively diverging". A flat or
  slightly negative CVD slope (e.g. −0.25) passes the LONG trigger.
- **Impact:** The aggression trigger fires on three conditions where the third is a
  *non-veto* rather than a *confirmation*. In live trading a LONG can fire while CVD is
  mildly rolling over, which is precisely the "aggression without follow-through" case the
  spec's third condition exists to filter. The strict CVD polarity gate does exist, but
  only downstream in Gate 3 (`gates_edge.py:190-197`), which uses a *different* threshold
  pair (−0.5 NSE / −0.3 MCX — see D-B8), so the two layers disagree about what "conflict"
  means and neither requires positive expansion.
- **Suggested fix:** In `_confirm_direction`, require signed expansion, e.g.
  `cvd_ok = cvd_slope > 0` (or a normalised `cvd_slope > +epsilon` with epsilon small), and
  keep the existing asymmetric veto as a separate guard. Reuse `direction_of_signed`
  (`orderflow/cvd.py:25-49`) so the sign convention is the single canonical one.

### D-B3 [HIGH] — Playbook C's RR ≥ 1:3.0–1:5.0 and "target above point B" are not implemented

- **Spec says:** §9.3 step 7: "*Take-Profit: Breakout above Point B targeting R:R ≥ 1:3.0
  to 1:5.0.*"
- **Code does:** There is no "point B" concept in the decision layer. `SignalBuilder` picks
  the TP from `npoc_above` / `prior_poc` / `vah` (`signal_builder.py:244-264`) with
  `min_rr: float = 1.5` (L211), and the fixed fallback is 2R (`tp_multiplier=2.0`, L92).
  Grep for `1:3`, `rr >= 3`, `RR >= 3` returns no decision-layer hits.
- **Impact:** The LVN Sniper (the spec's "sniper continuation", explicitly called out in
  the pipeline doc as a distinct approved outcome) is sized and targeted identically to a
  generic squeeze breakout. On a sniper entry the structural stop is only 2 ticks behind the
  LVN, so the realised R:R is large in *ticks* but the code never asserts the spec's
  1:3 floor — the 1.5 floor can be met by a very near structural target, and the runner is
  then capped at TP2 = 2R (`exit_checks.py:58-63, 99-101`) rather than the spec's 3–5R.
- **Suggested fix:** Thread the impulse-leg high ("point B") into `DecisionContext`
  (the leg profile already exists in `amt_dto["legProfile"]`, consumed in
  `position_manager.py:577-584`), and in `_structural_tp` add a `LVN_SNIPER` branch that
  requires `reward/risk >= 3.0` against point B, falling back to the 3R fixed target.

### D-B4 [MEDIUM] — Gate 1 spread check does not compute the documented three-term max

- **Spec says:** `fabio_decision_pipeline.md` Gate 1 check 5:
  "Spread ≤ max(2× tick, 0.1% of price, ₹0.40)".
- **Code does:** `quant/decision/gates/gate_session_phase.py:113-117`:
  ```python
  pct_threshold = close_px * 0.04 if close_px > 0 else float("inf")
  tick_floor = 2.0 * tick
  max_spread = max(pct_threshold, tick_floor)
  ```
  The percentage term is **4%** (not 0.1%) and the **₹0.40 absolute term is absent**. The
  block comment at L104-108 explains the deviation: the old ₹0.40 floor blocked
  low-premium options (BANKNIFTY 56400 PUT @ ₹460, ₹1.65 spread = 0.36%).
- **Impact:** The gate is *looser* than spec: a ₹100 premium with a ₹4 spread (4%) passes,
  while spec's max(2×tick, ₹0.10, ₹0.40) would reject it (₹4 > ₹0.40). The deviation is
  deliberate and documented inline, and for high-LTP options the spec's ₹0.40 floor is
  unworkable — but the *pipeline doc* still advertises the three-term formula, so the
  documentation and the implementation have drifted apart, and 4% is a wide spread for a
  scalper whose edge is measured in ticks.
- **Suggested fix:** Update `fabio_decision_pipeline.md` check 5 to the implemented
  formula, and consider tightening the percentage term for low-premium contracts (e.g.
  `max(2×tick, 0.5%×price)` with a separate high-LTP branch), or make the terms
  instrument-aware via `quant.config`.

### D-B5 [MEDIUM] — Absorption thresholds use ATR multiples, not spec's 1.5× volume / 0.5× range

- **Spec says:** §7.2 absorption event: `V_b ≥ 1.50 × V̄_20` and
  `(H_b − L_b) ≤ 0.50 × H_range`.
- **Code does:** `quant/amt/orderflow/detectors.py:355-356`:
  ```python
  if range_ratio < ABSORPTION_RANGE_ATR and vol_ratio >= ABSORPTION_VOL_MULT:
  ```
  with `ABSORPTION_RANGE_ATR = 0.30` and `ABSORPTION_VOL_MULT = 2.0`
  (`contracts/constants.py:80-81`). The reference is ATR, not `V̄_20` / `H_range`.
  `triple_a.py` itself documents the spec thresholds in its module docstring (L5-7) but
  the numeric guards live in the detector.
- **Impact:** Functionally similar (effort-without-result filtering) but strictly tighter
  on volume (2.0× vs 1.5×) and referenced to ATR. Some genuine 1.6–1.9× absorption events
  the spec would flag are missed, which starves the Triple-A machine's WAITING→ABSORBING
  transition. Also, `ABSORPTION_MAX_AGE_BARS`/`OBI_AGGRESSION_THRESHOLD` are imported into
  `gates_edge.py:4-7` but **only ever referenced in comments** — dead imports that imply a
  freshness/aggression gate which is not actually applied.
- **Suggested fix:** Either align the constants to the spec (1.5× / 0.5× against the
  20-bar mean volume and `H_range`) or record the ATR-referenced choice in the spec. Remove
  the unused imports from `gates_edge.py` (or implement the absorption-age freshness check
  they imply).

### D-B6 [MEDIUM] — PDH/PDL is not a TP candidate anywhere

- **Spec says:** §9.1 TP₂: "Macro Session POC_prev or **Previous Day High (PDH)**";
  §9.1 SELL: "First support LVN / Macro POC_prev / **PDL**".
- **Code does:** `signal_builder.py:244-264` collects `npoc_above/below`, `prior_poc`,
  `vah/val` — no PDH/PDL field exists in `DecisionContext` (`decision/context.py`), and
  `grep` for PDH/PDL in the decision layer returns nothing.
- **Impact:** The second-tier target can only be a POC or VA edge. On a strong trend day
  the macro POC may sit well behind price, so TP₂ is set closer than the spec intends,
  truncating the runner.
- **Suggested fix:** Add `prior_day_high` / `prior_day_low` to `DecisionContext` (the
  prior-session profile is already persisted at `amt/session/context.py:402-455`), and add
  them as LONG/SHORT TP candidates in `_structural_tp`.

### D-B7 [LOW] — Gate 4 stop cap deviates from the documented 0.75% for options

- **Spec says:** `fabio_decision_pipeline.md` Gate 4:
  `scaled_cap_ticks = max(200, (entry × 0.75%) / tick)`.
- **Code does:** `quant/decision/gates_rr.py:32-37`:
  ```python
  if is_option_contract(ctx.symbol):
      dynamic_factor = entry * 0.05 / tick   # 5% of option premium in ticks
  else:
      dynamic_factor = entry * 0.0075 / tick # 0.75% of futures price in ticks
  ```
- **Impact:** Deliberate and documented inline (options priced 150–300 give ~39 ticks at
  0.75%, always swamped by the 200-tick hard cap). The deviation widens the allowable stop
  for options, which is the intended effect. Low severity — flagged only because the
  pipeline doc states the single formula without the option branch.
- **Suggested fix:** Document the two-branch cap in `fabio_decision_pipeline.md`.

### D-B8 [LOW] — Gate 3 CVD conflict thresholds are inverted between market and spec

- **Spec says:** `fabio_decision_pipeline.md` Gate 3: "CVD conflict (LONG):
  `cvd_slope < −0.3` (NSE) or `< −0.5` (MCX)".
- **Code does:** `quant/decision/gates_edge.py:192-193`:
  ```python
  cvd_block_neg = -0.3 if str(market).upper() == "MCX" else -0.5
  cvd_block_pos = 0.3 if str(market).upper() == "MCX" else 0.5
  ```
  The NSE/MCX thresholds are **swapped** relative to the doc (code: NSE = 0.5, MCX = 0.3;
  doc: NSE = 0.3, MCX = 0.5). Note `contracts/constants.py:232-233` defines
  `FABIO_CVD_THRESHOLD_NSE = 0.5` / `FABIO_CVD_THRESHOLD_MCX = 0.3`, i.e. the constants
  agree with the *code*, so the doc appears to be the side in error — but the doc is the
  authoritative spec for this review.
- **Impact:** MCX entries are blocked slightly sooner and NSE slightly later than the doc
  states. Minor in effect (a 0.3-vs-0.5 slope on an unnormalised linear-regression CVD
  slope is a coarse filter either way), but it is an unambiguous doc/code disagreement.
- **Suggested fix:** Import `FABIO_CVD_THRESHOLD_NSE`/`_MCX` into `gates_edge.py` instead
  of hardcoding, and correct the doc table (or the constants) so there is one source.

### D-B9 [LOW] — §8 ACCUMULATING transition omits "delta stabilizing" and LVN proximity

- **Spec says:** §8: "Price consolidates **within 2 range steps of POC/LVN**
  (2+ bars elapsed, **delta stabilizing**)".
- **Code does:** `triple_a.py:200-210` checks `_is_near_poc(close, poc, tick_size)` only;
  `_is_near_poc` (L249-256) uses `max(tick_size * 4.0, 0.05)` — a fixed tick tolerance,
  not "2 range steps", and LVN is never consulted. No delta/CVD term appears anywhere in
  the ABSORBING→ACCUMULATING transition.
- **Impact:** The state machine can enter ACCUMULATING while delta is still accelerating
  against the position, and the 4-tick tolerance is a much tighter band than 2 range steps
  (for a 5-point range bar that is 10 points), so the machine is *stricter* on proximity
  and *looser* on delta. Net effect: some accumulation phases the spec would recognise are
  never declared, so the aggression trigger fires from ABSORBING via the direct-breakout
  branch instead (which is still VWAP+CVD confirmed) — a path deviation, not a safety hole.
- **Suggested fix:** Accept `lvn` in `update()` and test `min(|close−poc|, |close−lvn|)`
  against `2 * range_size`; add a "delta stabilizing" test (e.g. `|cvd_slope|` below a
  threshold or slope magnitude decaying) as a third conjunction.

### D-B10 [LOW] — Pipeline catches gate exceptions and converts them to a fail, but masks the cause

- **Spec says:** `fabio_decision_pipeline.md` implies deterministic gate outcomes; the
  outcomes table has no "gate errored" row.
- **Code does:** `quant/decision/pipeline.py:33-37`:
  ```python
  try:
      results.append(run())
  except Exception as exc:
      results.append(GateResult(gate_no, False, f"error: {exc}"))
  ```
- **Impact:** Fail-closed, which is correct and safe. But the exception is reduced to a
  string, so a systematic `AttributeError` inside Gate 3 (e.g. a malformed DTO field) would
  present as a permanent `NO_EDGE` with only a reason string to diagnose. In live trading
  this is a silent strategy shutdown rather than a noisy one.
- **Suggested fix:** Log the exception with `exc_info` (as `context_builder.py:441-453`
  does for session resolution) and emit a telemetry counter so an erroring gate is visible
  on the dashboard, not just in the decision reason.

---

## Verified Correct (with code quotes)

**1. The §8 three-condition aggression trigger really is three conditions.**
`triple_a.py:241-247`:
```python
if signal == "LONG":
    vwap_ok = vwap > 0 and close > vwap
    cvd_ok = cvd_slope > -0.3
...
return vwap_ok and cvd_ok
```
combined with the strict breakout in `orderflow/detectors.py:307`
(`displaced_bullish = float(candle.close) > float(self._pending_candle.high)`). All three
spec terms are checked; only the third is weakened (D-B2).

**2. Anti-whipsaw is a real, strong guard — not just a closing-price check.**
`gates_edge.py:33-34` defines `_FULL_BODY_MIN_RATIO = 0.6` / `_CLOSE_NEAR_EXTREME_MIN = 0.75`
and `_candle_acceptance` (L104-152) rejects, in order: a bar closing against the trade
direction, a close not in the outer 75% of the range ("Wick probe rejected"), and a body
under 60% of range ("Mid-candle probe rejected"). This directly implements §9.1's
"Never enter on the 1st raw intra-bar spike."

**3. NO OVERNIGHT HOLDING is enforced by two independent layers.**
Bar-driven: `position_manager.py:162-166`:
```python
if session_force_exit(bar.time, market=self._market, contract_expiry=self._contract_expiry):
    exit_dec = ExitDecision(True, "SESSION_CLOSE", bar.close)
```
with Phase 5 (`amt/session/context.py:150-151`) setting `force_exit=True` and
POST_MARKET/PRE_MARKET (L128, L154) also `force_exit=True`. Wall-clock backstop:
`multi_engine.py:1163-1199` `eod_square_off()` force-flattens any engine past
`close − 15 min`, run from `_eod_watchdog_loop` (L1308-1366) on a 30s daemon poll, so a
dead feed cannot carry a position overnight.

**4. Mon/Fri defensive sizing exists.** `execution/risk.py:19-24`:
```python
DAY_OF_WEEK_MULTIPLIER = {0: 0.5, 1: 1.0, 2: 1.0, 3: 1.0, 4: 0.5}
```
applied after both sizing branches (`risk.py:419` and `risk.py:465`) — matching §16's
documented 0.5×/1.0× mapping to §10's day-of-week variance.

**5. Gate 2's thesis-flip exception is exactly as documented.**
`gates/gate_position_cooldown.py:19-30`: cooldown seconds block unconditionally (L19-24);
`position_open` is bypassed only when `allow_positioned` (L29-30) and returns
`reason="thesis-flip check"` — the cooldown-still-enforces rule is literally implemented.

**6. Gate 3 Phase A has all 10 documented guards**, in `gates_edge.py:155-207`: no bar
(L157-158), opposing stacked imbalance (L166-172), contested bubble zone (L173-174), no
direction (L175-176), dead market (L177-179), anti-climax LONG/SHORT at ±2σ (L181-184),
drive exhausted (L188-189), CVD conflict both directions (L190-197) — plus two extras:
1-minute candle acceptance (L185-187) and CVD-divergence alignment (L200-205).

**7. Gate 3 Phase B has all 6 paths in the documented priority order.**
`gates_edge.py:215-303`: (1) Setup Evidence (L217-222), (2) Triple-A AGGRESSION (L223-258),
(3) Second Drive (L259-260), (4) LVN Sniper (L261-276), (5) Initiative Breakout
(L277-287), (6) Squeeze Retest (L288-302). Each returns `_pass(...)` with the correct
`setup_key` for the model router.

**8. The model router is enforced exactly once, at the service.**
`decision_service.py:104-116` blocks a Gate-3 approval whose `setup_key` belongs to the
other model and falls through to the reversion fallback; the fallback itself is gated by
`allows("VA_FADE", active_model)` (L147). `model_router.py:55-64` maps IMBALANCED→TREND,
BALANCED→MEAN_REVERSION with evidence/initiative override.

**9. Playbook B's 100%-exit-at-POC is enforced, not just implied.**
`exit_checks.py:71-79` `is_terminal_tp_only()` returns True for `model_label == "VA_FADE"`
and `check_take_profit_tiers` (L86-93) then returns a **full-close** `ExitDecision` with no
`partial_fraction` on the first TP touch — matching §9.2's "Full exit (100%) at POC".

**10. The hard/soft reject split is identified by gate number, not list position.**
`decision_service.py:134-138` tests `r.gate in (1, 2)` so a Gate 1/2 failure is a hard
`GATE_REJECTED` with no fade, exactly the documented "Gate 1 or 2 failed → hard reject"
and robust to pipeline reordering (the code comment cites the prior positional-indexing
defect).

**11. Fail-closed defaults dominate.** `DecisionContext` defaults
(`decision/context.py:24-25, 112`) are `session_open=True`, `warmup_complete=True`,
`allow_trend=True` — but these are always overwritten by
`context_builder.py:545-563`, and `_resolve_session_open` (L500-511) returns
`session_info.allow_entry` when the time string is empty rather than silently True.
Gate 1 still fails closed on `session_open=False`/`warmup_complete=False`.

---

## Suspicious / Needs Human Eyes

1. **Duplicate gate modules with divergent docstrings.** `quant/decision/gates_edge.py`
   (326 lines, canonical) and `quant/decision/gates/gate_edge.py` (17 lines, alias) coexist,
   as do `gates_rr.py` and `gates/gate_risk_reward.py`. The pipeline imports the
   `gates/` package (`pipeline.py:11-16`), which re-exports the canonical implementations,
   so behaviour is correct — but `gates/gate_risk_reward.py:1-6` still documents a
   "Greek-adjusted R:R ≥ 1.5 via Delta" transform that its own body does not perform (it
   delegates to `gates_rr.py`, which is stop-width-only). The stale docstring describes a
   behaviour that no longer exists, and `OptionConverter` is imported there and nowhere
   else in the codebase. Recommend deleting the stale docstring and the unused import.

2. **`_ABSORPTION_MAX_AGE_BARS` / `_OBI_AGGRESSION_THRESHOLD` are imported but unused** in
   `gates_edge.py:4-7` — they are referenced only in comments. Either the freshness window
   and OBI aggression confirmation they describe were removed (leaving the guard set
   weaker than the module's own comments claim) or they were never wired. Worth confirming
   intent: §9.1's absorption footprint has a freshness implication that nothing currently
   enforces at Gate 3.

3. **`rescore_aggression_with_direction` is computed and then discarded.**
   `gates_edge.py:320` computes `aggression_score` at the top of `gate_triple_a_edge` and
   never uses it in `_check_guards` or `_check_setup_paths`. It appears to be a telemetry/
   audit value only. If it was meant to be a gate input (Fabio's A3 aggression
   confirmation), that gating is currently inert.

4. **CVD slope is an unnormalised linear-regression slope over a 40-bar window**
   (`cvd.py:141-180`). Its magnitude therefore scales with the instrument's contract size
   and volume, so absolute thresholds like 0.3/0.5 (D-B8) and −0.3 (D-B2) are not
   comparable across NSE index options vs MCX commodities. The thresholds are used as
   coarse polarity filters, but a human should confirm the intended semantics per
   instrument — the spec's "CVD expanding/collapsing" is qualitative and the code's
   numeric stand-in is not scale-free.

5. **`va_fade.py:84` requires `close < poc` for the LONG fade** (and `close > poc` for
   SHORT). §9.2 only requires the close to be *inside the VA*; the extra POC-side
   condition is a sensible filter (ensures room to the target) but it silently excludes
   fades that re-accept above the POC. Confirm this is intended and not an unintended
   narrowing of Playbook B.

6. **`detect_gap_fill_fade` exists but is not called from `DecisionService.evaluate()`.**
   Only `detect_va_fade` is wired (`decision_service.py:149`). If the gap fade is meant to
   be a live fallback (spec §5.2 Layer 4 Gap Profile), it is currently dead code in the
   decision path.
