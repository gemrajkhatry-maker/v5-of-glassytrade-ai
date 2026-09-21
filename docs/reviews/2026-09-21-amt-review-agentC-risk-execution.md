# Agent C — Risk / Execution / Isolation Review vs docs/amt

**Reviewer:** Agent C (Principal Engineer review, RISK / EXECUTION / OMS / ISOLATION scope)
**Date:** 2026-09-21
**Spec baseline:** `docs/amt/AMT_INSTITUTIONAL_SCALPER_ALGORITHM.md` + `docs/amt/multi_symbol_isolation.md` (only AMT docs read; `docs/plans`, `docs/reviews`, `docs/architecture` deliberately not consulted)
**Code audited:** `quant/execution/risk.py`, `exits.py`, `exit_checks.py`, `exit_rules.py`, `exit_signal.py`, `protective_stop.py`, `oms.py`, `live_oms.py`, `oms_factory.py`, `portfolio_risk.py`, `exposure.py`, `lots.py`, `trade_costs.py`, `fills.py`, `paper_simulator.py`, `paper_reconciliation.py`, `quant/position_manager.py`, `quant/runtime.py`, `quant/multi_engine.py`, `quant/event_store.py`, `quant/state.py`, `quant/session_levels.py`, `quant/brokers/multiplexed_feed.py`, `quant/brokers/live_gateway.py`, plus the live call sites `quant/engine/submission_handler.py`, `quant/engine/exit_manager.py`, `quant/engine/decision_loop.py`, `quant/decision/stops.py`, `quant/decision/signal_builder.py`.

## Verdict: FAIL

The isolation contract (§multi_symbol_isolation) is broadly honoured and the circuit breakers are independently enforced and session-locked — that machinery is sound. But the **core money-math of §12.2 is not the spec formula**, the **§11 / §9.1 stop offset polarity is inverted relative to the spec**, the **§13.2 pyramid stop ratchet cannot deliver its documented "guaranteed net-positive bundle"**, and the **§13.3 exit ladder is 50/50 not 50/25/25**. Two of those are live-money-critical.

**Defect count: 11** — 2 CRITICAL, 5 HIGH, 3 MEDIUM, 1 LOW.

---

## Spec-to-Code Traceability Matrix

| Spec § | Rule | Code Location (file:line) | Status | Notes |
|---|---|---|---|---|
| §12.1 | `Cushion_t = Σ realized session PnL` | `quant/execution/risk.py:228` (`self._daily_pnl += pnl`) | **PARTIAL** | Cushion is `daily_pnl`, correct; but it is mixed with a `peak_daily_pnl` retracement-veto (risk.py:544) that has no spec counterpart. |
| §12.1 | MDL hard stop = 2.0% of E_0 | `quant/execution/risk.py:253` | **PASS** | Hard-coded `-0.02 * starting_equity` fires regardless of the configured `max_daily_loss_pct`; verified empirically. |
| §12.1 | 3 consecutive losses → terminate day | `quant/execution/risk.py:259` | **PASS** | Independent of MDL check; both enforced. |
| §15 row 9 | Once tripped, locked until next SESSION | `quant/execution/risk.py:247-249` + `can_trade` 275-286 | **PASS** | A winning trade does NOT clear the halt (verified); `_load` only unhalts benign "max trades"/"SIGTERM" reasons (risk.py:157-174). |
| §12.2 | Defensive: `RiskDollars = min(E₀·0.0025, MDL − |Cushion|)` | `quant/execution/risk.py:563-601` | **FAIL** | No `min()` clamp against `MDL − |Cushion|` anywhere. See **D-C1**. |
| §12.2 | Offensive: `RiskDollars = (E₀·0.0025) + 0.40·Cushion` | `quant/execution/risk.py:581-585` | **FAIL** | Implemented as `0.0035 + 0.20·profit/E₀` capped at 0.50%, further crushed by a "never > 30% of session profit" cap (risk.py:594-596). See **D-C2**. |
| §12.2 | `PositionSize = floor(RiskDollars / (\|entry−SL\| · Multiplier))` | `quant/execution/risk.py:429-473` | **FAIL** | No `floor()`; `Multiplier` (point value) is never in the denominator; quantity is a raw float and can be unbounded. See **D-C3**. |
| §12.1 | Session reset: gains merge into E₀, Cushion → 0 | `quant/execution/risk.py:503-516` (`reset_session`) | **PASS** | `reset_session` zeroes pnl/streaks/halt and restores `_equity = _starting_equity`. Date-keyed store (`daily_risk:SYM:date`) makes the reset natural across days. |
| §10.4 | Day-of-week multiplier (Mon/Fri defensive) | `quant/execution/risk.py:19-25, 465` | **PASS** | 0.5 Mon/Fri, 1.0 Tue–Thu, applied after sizing; matches spec §16's documented 0.5x. |
| §13.1 | SL→breakeven at +0.8R | `quant/execution/exit_checks.py:132` | **PASS** | `profit >= risk * 0.8` arms `be_floor = entry`; verified 0.75R does not arm, 0.8R does. |
| §13.1 | Alternative: CVD expands + 2 consecutive range bars closing in profit | `quant/execution/exit_checks.py:122-129` | **PARTIAL** | Only the CVD half exists (`cvdSlope` vs `cvd_be_threshold`); the "2 consecutive range bars closing in profit" clause is NOT implemented — a single bar's CVD slope suffices. See **D-C8**. |
| §13.1 | Risk becomes strictly $0.00 | `quant/execution/exit_checks.py:132-133` + `resolve_protective_stop` (protective_stop.py:38-47) | **PASS** | BE floor tightens the effective stop to entry; `ExitEngine.is_risk_free` (exits.py:108-116) exposes it to the pyramid gate. |
| §13.2 | Authorization: base at Risk-Zero (BE or +1.0R locked) | `quant/position_manager.py:253, 548` | **PARTIAL** | `is_risk_free` only checks that a BE floor exists, never that it is ≥ entry (+1.0R locked is not modelled). Acceptable for BE; the "+1.0R locked" variant is absent. |
| §13.2 | Pyramid1 = 0.50 × base, Pyramid2 = 0.25 × base | `quant/position_manager.py:606-609` | **PASS** | `fraction = 0.50 if pyramid_count == 0 else 0.25`; max 2 add-ons (541). |
| §13.2 | SL ratchet → bundle guaranteed net positive | `quant/position_manager.py:611-612, 664-677` | **FAIL** | `new_sl = structural_stop(...)` places the stop on the *wrong side* of the LVN, and even with the correct side the base SL is ratcheted to a level that can still be below base entry → bundle can lose. See **D-C4**. |
| §13.2 | Pyramid trigger: LVN retest + new absorption + 1m close | `quant/position_manager.py:565-604` | **PASS** | Leg-LVN tolerance (leg_lvn.py:39), `absorptionSide` freshness + direction agreement, and candle-close direction all checked. |
| §13.3 | Tier1 50% / Tier2 25% / Tier3 25% runner | `quant/execution/exit_checks.py:95-102`; `position_manager.py:445-512` | **FAIL** | Implemented as TP1 50% then TP2 = **50% of the remainder** (i.e. 50/25 of original, runner 25% only as an arithmetic side-effect) — the tier fractions are 0.5/0.5-of-remainder, not 0.5/0.25, and there is no third tier at all. Plus §9.1 says TP1 50% + TP2 50%. See **D-C5**. |
| §11 / §15 row 5 | Stop at cluster extreme ± 2 ticks, correct side per direction | `quant/decision/stops.py:84-108`; `quant/decision/signal_builder.py:122` | **FAIL** | LONG stop is `anchor + 2·tick` (inside/above the cluster low); spec §9.1 says `L_cluster − 2·tick`. SHORT stop is `anchor − 2·tick`; spec says `H_cluster + 2·tick`. See **D-C6**. |
| §11 | Stops behind the executed bubble cluster, not wicks | `quant/decision/stops.py:27-60` | **FAIL** | Anchor candidates are leg-LVN / VAH / VAL / nearest buy/sell print / bar high/low — there is no `AbsorptionCluster.cluster_low/cluster_high` in the anchor set at all. See **D-C7**. |
| §11 | "1–2 ticks inside" TP shield | `quant/decision/signal_builder.py:173-202` | **PASS** | `_shield_tp` pulls the TP 2 ticks inside the structural level toward entry, with inversion guard. |
| §15 row 5 | Hard SL registered at exchange, zero discretion | `quant/execution/live_oms.py:167-224` | **PASS (with note)** | Contingent SL-M placed immediately after fill; on failure the position is emergency-flattened and `EmergencyFlattenError` raised. `NotImplementedError` on legacy brokers is aliased to `"mock_pass"` (live_oms.py:181-183) — see **D-C11**. |
| §16 | No false advertising about tick aggression / L2 depth | `quant/amt/orderflow/footprint.py:127-160`; `quant/amt_engine.py:156,216`; `quant/contracts/value_objects.py:243` | **FAIL** | `TickFootprintAccumulator` docstring claims "Accumulates **real** tick-level footprint data" using "the tick rule", but it is fed from a 5-level depth snapshot with no aggressor flag (spec §16 says candle-delta/5-level are proxies). See **D-C9**. |
| isolation table | EventStore / EngineState / PositionManager / SessionRisk / AMTEngine / DecisionService / BarAggregator / bar history per-engine | `quant/runtime.py:439, 450, 484-495, 509, 529, 575, 1158-1171` | **PASS** | All constructed in `QuantEngine.__init__` per instance; `_trace` is a per-engine bounded deque. |
| isolation table | StateProjector per-engine | (state projection is in `runtime._emit` → `apply_event`) | **PASS** | `self.state` is folded from `self.event_store` only; no shared projector object exists. |
| isolation doc | PortfolioRiskAuthority is the ONLY cross-engine coupling | `quant/multi_engine.py:455`; `submission_handler.py:326-339`; `position_manager.py:639-647` | **PASS (with note)** | Verified: entries reserve via `can_accept`/`register_open`, pyramids too, releases via `record_close`/`release`. Two extra shared resources exist (`Portfolio`, `SessionLevelStore`) — both documented as shared in the isolation doc, and `MODEL_RISK_FAILURES` is a module-global counter (see **D-C10**). |
| isolation doc | Per-symbol reader queues in MultiplexedMarketFeed | `quant/brokers/multiplexed_feed.py:60-61, 185-236` | **PASS** | `_queues[symbol]` + `add_reader`/`remove_reader`; `stop()` poisons every queue with `None`. |
| isolation doc | EOD square-off force-closes ALL positions | `quant/multi_engine.py:1163-1200`; `quant/engine/exit_manager.py:393-431` | **PASS** | Base + lingering pyramids both flattened; idempotent; `_close_lock` serializes against bar/tick exits. |
| isolation doc | switch_symbol discards old engine state | `quant/multi_engine.py:565-590` | **PASS** | Refuses while the old engine holds a position; `_lifecycle_lock` serializes. |
| method §9 | Division by zero when entry == SL | `quant/execution/risk.py:381, 429-431` | **PASS** | `entry == sl` and `loss_per_unit <= 0` both return 0.0. |
| method §9 | Sizing cannot go negative or infinity | `quant/execution/risk.py:429-473` | **FAIL** | Verified `entry=100, sl=99.99` → qty 12,500 with no cap. See **D-C3**. |
| method §9 | Risk dollars cannot exceed MDL | `quant/execution/risk.py:563-601` | **FAIL** | Verified cushion=−1900 (MDL budget left = 100) still risks 250. See **D-C1**. |
| method §9 | No silent exception swallow in the order path | `quant/position_manager.py:623-627`; `quant/engine/submission_handler.py:197-230`; `quant/engine/exit_manager.py:244-253` | **PARTIAL** | All failures are logged loudly and the engine stays alive; `check_pyramid` catches bare `Exception` (with logging) and `live_oms.py:218` has a genuinely silent `except Exception: pass` — but only around the audit-emit inside an emergency flatten. Acceptable. |

---

## Defects Found

### D-C1 [CRITICAL] — §12.2 defensive-mode clamp `min(E₀·0.0025, MDL − |Cushion|)` is not implemented

- **Spec says (§12.2):**
  > `RiskDollars_k = min(E₀ × 0.0025, MDL − |Cushion_t|)` if `Cushion_t ≤ 0` (Defensive Mode)

- **Code does (`quant/execution/risk.py:563-601`):**
  ```python
  def _risk_per_trade_pct(self) -> float:
      ...
      tier = self._cushion_tier()
      if tier == "BASE_RETRACEMENT_VETO":
          risk = 0.0025            # 0.25%
      elif tier == "MOMENTUM":
          risk = 0.0040            # 0.40% Momentum Day
      elif tier == "CUSHION_TIER_1":
          cushion = 0.0035
          profit_share = max(0.0, self._daily_pnl) * 0.20 / self._starting_equity
          risk = min(cushion + profit_share, 0.0050)
      else:
          risk = 0.0025            # 0.25%
      risk = min(risk, 0.0050)
      if self._daily_pnl > 0:
          max_from_profit = self._daily_pnl * 0.30 / self._starting_equity
          risk = min(risk, max_from_profit)
  ```
  There is **no reference to `MDL` (`_max_daily_loss_pct`) or to `MDL − |Cushion|` anywhere in the sizing path.** Verified empirically with `starting_equity=100000, max_daily_loss_pct=0.02`:

  | Cushion | Remaining MDL budget | Spec RiskDollars | Code RiskDollars |
  |---|---|---|---|
  | 0 | 2000 | 250 | 250 |
  | −100 | 1900 | 250 | 250 |
  | −1900 | **100** | **100** | **250** ← over budget |
  | −3000 (halt already tripped) | −1000 | 0 | 250 (halts block `can_trade`, so not traded) |

- **Impact:** Live-money. After losing 1.9% of the session, the spec's whole point — that the *remaining* daily-loss budget caps the next trade so the 2.0% MDL can never be exceeded by a single subsequent trade — is absent. The code will risk the full 0.25% (₹250 on ₹100k) when only ₹100 of daily budget remains; a stop-out then breaches the 2.0% MDL by 1.5×. The MDL halt fires only *after* the trade is booked, so the loss is already realized. On a thin-stop fill (see D-C3) this is unbounded.

- **Suggested fix:** in `_risk_per_trade_pct` (or better, a new `_risk_dollars()` returning rupees, matching the spec's units), add:
  ```python
  mdl = self._max_daily_loss_pct * self._starting_equity
  remaining = mdl - abs(min(self._daily_pnl, 0.0))
  base = self._starting_equity * 0.0025
  if self._daily_pnl <= 0:
      risk_rupees = min(base, max(0.0, remaining))
  ```
  and have `position_size` consume rupees rather than a percentage, so the clamp is arithmetically impossible to bypass by a tier rewrite.

---

### D-C2 [HIGH] — §12.2 offensive-mode coefficients are 0.35%/20% instead of 0.25% + 40% of cushion

- **Spec says (§12.2):**
  > `RiskDollars_k = (E₀ × 0.0025) + (0.40 × Cushion_t)` if `Cushion_t > 0` (Offensive Mode)

  and §12 narrative:
  > Risk = 0.25% Base + 40% of Cushion = $250 + $250 = $500 Risk

- **Code does (`quant/execution/risk.py:581-585`):**
  ```python
  elif tier == "CUSHION_TIER_1":
      # 0.35% + 20% of session profit, capped at 0.50%
      cushion = 0.0035
      profit_share = max(0.0, self._daily_pnl) * 0.20 / self._starting_equity
      risk = min(cushion + profit_share, 0.0050)
  ```
  Verified: with cushion = ₹1,000 the spec wants ₹250 + ₹400 = **₹650**; the code returns ₹300. With cushion = ₹5,000 the spec wants ₹2,250; the code returns ₹400. Two further spec-invented caps then compound the suppression: `min(risk, 0.0050)` (never > 0.50%) and `min(risk, daily_pnl*0.30/starting_equity)` (never > 30% of session profit, risk.py:594-596), plus a `peak_daily_pnl` retracement-veto tier (risk.py:544) that has no spec counterpart.

- **Impact:** The "House Money" offensive mode is the strategy's compounding engine. It is currently ~2–5× more conservative than specified, so winning sessions do not scale. This is a performance defect, not a loss defect — the direction of error is safe (undersized), but the strategy no longer matches its stated edge, and the docstring at `risk.py:533-542` asserts the implementation is "per Fabio spec" while quoting different numbers than §12.2.

- **Suggested fix:** implement the spec formula literally:
  ```python
  risk_rupees = (self._starting_equity * 0.0025) + (0.40 * self._daily_pnl)
  ```
  then apply only caps the spec actually authorizes (the 0.50% ceiling in §12 "Base Risk: 0.25%–0.50%" is a defensible read; the 30%-of-profit and retracement-veto caps are not in the spec and should be deleted or made explicit config). Update the `_cushion_tier` docstring to match §12.2 or file a spec amendment.

---

### D-C3 [HIGH] — `PositionSize` is not `floor(RiskDollars / (|entry−SL| × Multiplier))`; unbounded and non-integral

- **Spec says (§12.2):**
  > `PositionSize_k = ⌊ RiskDollars_k / (|P_entry − P_SL| × Multiplier) ⌋`

- **Code does (`quant/execution/risk.py:429-473`):**
  ```python
  loss_per_unit = abs(entry - sl)
  if loss_per_unit <= 0:
      return 0.0
  raw_qty = risk_amount / loss_per_unit
  if lot_size and lot_size > 1.0:
      qty = snap_to_lot(raw_qty, lot_size)
  ...
  qty *= DAY_OF_WEEK_MULTIPLIER.get(self._day_of_week, 1.0)
  ```
  1. **No `Multiplier` (point value / contract multiplier) in the denominator.** `loss_per_unit` is a pure price distance; `risk_amount` is rupees. For a derivative where 1 point = ₹N, `risk_amount / price_distance` over-sizes by the multiplier — or, when `entry` is an option premium and the PnL is premium-scaled while risk is capital-scaled, the ratio is unit-incoherent. The `_DERIVATIVE_MARGIN_FRACTION` hack (risk.py:405) only exists in the ≥5% aggressive branch and does not fix the non-derivative path.
  2. **No `floor()`.** With `lot_size=1.0` the returned quantity is a raw float (`62.5`, `12500.0`), not an integer lot count. Verified: `entry=100, sl=99.99, lot=1` → **12,500 units**, bounded only by the stop distance; there is no max-quantity ceiling in the non-aggressive branch.
  3. `DAY_OF_WEEK_MULTIPLIER` is applied *after* the risk computation (risk.py:465), so on Mondays the realized rupee risk is exactly half the number `_risk_per_trade_pct()` promised — sizing and risk-budget accounting disagree by 2× on Mon/Fri, which also desyncs the MDL arithmetic in D-C1.

- **Impact:** Live-money. A degenerate or stale quote producing a sub-tick `entry − sl` yields a position size in the tens of thousands. `SubmissionHandler.submit` (submission_handler.py:179-186) only calls `clamp_quantity`, and `PortfolioRiskAuthority.can_accept` (submission_handler.py:325) uses `|entry−sl| × max(1, quantity)` — that ceiling *does* catch it (25% of capital), so this is defense-in-depth-fails-safe rather than an open hole; but the sizing authority itself is not spec-shaped and its output is not integer lots.

- **Suggested fix:**
  ```python
  lots = math.floor(risk_rupees / (loss_per_unit * multiplier)) if multiplier > 0 else 0
  lots = max(0, min(lots, max_lots or lots))
  qty = lots * lot_size * DAY_OF_WEEK_MULTIPLIER[self._day_of_week]
  ```
  Derive `multiplier` from the `ContractRef` (instrument registry already knows point value), and make `_risk_per_trade_pct` and `position_size` agree on the same rupee figure.

---

### D-C4 [CRITICAL] — §13.2 pyramid stop ratchet places the stop on the wrong side of the LVN, and the "guaranteed net-positive bundle" does not hold

- **Spec says (§13.2):**
  > **Stop Ratchet:** Move combined position stop to the new LVN/cluster floor. **The entire trade bundle is guaranteed a net positive cash payout.**

  and §9.3:
  > **Stop-Loss:** 2 ticks behind the LVN shelf.

  "Behind" for a LONG means *below* the LVN.

- **Code does (`quant/position_manager.py:611-612`):**
  ```python
  # New SL behind the LVN shelf
  new_sl = structural_stop("LONG" if long else "SHORT", price, leg_lvn, tick)
  ```
  and `quant/decision/stops.py:96-108`:
  ```python
  if str(side).upper() == "LONG":
      sl = anchor + offset          # leg_lvn + 2*tick  → ABOVE the LVN
      ...
  sl = anchor - offset              # leg_lvn - 2*tick  → BELOW the LVN (short)
  ```
  Verified: LONG pyramid at `leg_lvn=100, tick=0.5` yields `new_sl = 100.5` (spec: `100 − 1.0 = 99.0`). SHORT pyramid yields `99.5` (spec: `101.0`).

  Separately, the ratchet guard at `position_manager.py:664-677` is:
  ```python
  if (long and new_sl > cur_sl) or (not long and new_sl < cur_sl):
      ratcheted = _dc_replace(position, order=..., signal=...sl=new_base_sl)
  ```
  Because `structural_stop` returns a *tighter* price (toward entry) than the spec's "behind the level" price, the ratchet always fires and moves the **base** SL to `leg_lvn ± 2·tick` — which for a LONG pyramid entered at 105 with the LVN at 100 puts the base SL at 99.5, still **5.5 points below the base entry**. Worked example (pyramid1 = 50% of base, both stopped at 99.5):

  | Leg | Entry | SL | Size | PnL at SL |
  |---|---|---|---|---|
  | Base | 105.0 | 99.5 | 100 | **−550** |
  | Pyramid1 | 100.0 | 99.5 | 50 | **−25** |
  | **Bundle** | | | | **−575** |

  The bundle is **net negative**, contradicting the spec's guarantee. The guarantee is only achievable if the base SL is ratcheted to ≥ base entry (i.e. locked-in-profit, the "+1.0R locked" branch of §13.2's authorization), which the code never does — `is_risk_free` (exits.py:108-116) merely checks that *some* breakeven floor exists.

- **Impact:** Live-money, and the most dangerous of the set: pyramiding is presented as a risk-free add-on ("base trade must be at Risk-Zero"), but the ratchet can move a base position from a wide stop to a *tighter* stop that is still below entry, converting a winning-but-unrealized base into a guaranteed loss while adding a second losing leg. On LiveOMS pyramids are currently disabled (`live_oms.py:490-494` raises `ValueError`, caught at `position_manager.py:623`), so this is paper/replay-live today — but the `add_pyramid` docstring at `oms.py:195-206` still asserts the guarantee that the code cannot make.

- **Suggested fix:**
  1. Fix the pyramid SL geometry: `new_sl = leg_lvn − inside·tick` for LONG and `leg_lvn + inside·tick` for SHORT (a dedicated `behind_level()` helper, not the entry-facing `structural_stop`). Better: reuse the same cluster-anchored stop as entries (D-C6/D-C7) so one function owns the polarity.
  2. Make the guarantee structural, not incidental: only ratchet the base SL when `new_sl` is on the profitable side of `base.open_price` (LONG: `new_sl >= base.open_price`; SHORT: `new_sl <= base.open_price`); otherwise leave the base SL alone and reject/skip the add-on, or move the base to breakeven only. Add an assertion + unit test that the stopped-out bundle PnL is ≥ 0 for both directions and both pyramid levels.

---

### D-C5 [HIGH] — §13.3 exit ladder is 50 / 50-of-remainder, not 50 / 25 / 25; and §9.1 conflicts with §13.3

- **Spec says (§13.3):**
  > **Tier 1 (50% Size):** At +2.0R / First overhead LVN / Round Number.
  > **Tier 2 (25% Size):** At Macro Value Area extreme or upon CVD divergence exhaustion.
  > **Tier 3 (25% Runner):** Trailed behind 1m absorption bubbles until full session close.

  but §9.1 says:
  > TP₁ (50%): First overhead major LVN or prior swing high (R:R ≥ 1:2.0). TP₂ (50%): Macro Session POC_prev or Previous Day High (PDH).

- **Code does (`quant/execution/exit_checks.py:95-102`):**
  ```python
  if tp_tier == 0:
      if (long and high >= tp) or (not long and low <= tp):
          return ExitDecision(True, "TP1", tp, partial_fraction=0.5), 1
  elif tp_tier == 1:
      tp2 = tp2_level(entry, tp)          # entry ± 2·|tp−entry|  → 2R past entry
      if (long and high >= tp2) or (not long and low <= tp2):
          return ExitDecision(True, "TP2", tp2, partial_fraction=0.5), 2
  ```
  TP2 closes **50% of what remains** (0.5 → 25% of the original position), so the arithmetic *lands* on 50/25/25 only by accident of the remainder, and the tier-3 runner is whatever is left over with no third rule, no "macro VA extreme / CVD divergence exhaustion" target, and no "trailed behind 1m absorption bubbles" trailing logic (the runner is trailed by the generic `check_trailing_stop` giveback, exit_checks.py:140-165). The `max_tier` is 2 (`tp2_level` is the last target), so a TP3 does not exist. `position_manager.py:481-512` mirrors this on the tick path (`_book_tick_tp2_partial`).

  The spec tension between §9.1 (50/50, two tiers) and §13.3 (50/25/25, three tiers) is **real and unresolved in the code or the docs**. The code implements neither exactly.

- **Impact:** Position-management divergence from spec. The runner is 25% of size as §13.3 intends (good), but the TP2 *target* is a pure `2R` formula (`tp2_level`), not "macro VA extreme or CVD divergence exhaustion", and the runner has no absorption-bubble trailing — both are named in §13.3. Medium money impact: on strong trend days the runner exits on a generic 20% giveback instead of the structural trailing, leaving R:R on the table.

- **Suggested fix:** (a) make the fractions explicit — `partial_fraction=0.50` for TP1, `0.25 / remaining` for TP2 so the runner is exactly 25% of the *original* size regardless of rounding; (b) add the TP3 runner tier with an absorption-bubble trailing rule; (c) resolve the §9.1 vs §13.3 contradiction in `docs/amt` (single authoritative ladder) and have `exit_checks.py` cite the winning section. `PaperOMS.close_partial`'s docstring (oms.py:246-251) already claims 50/25/25 while the caller passes 0.5/0.5.

---

### D-C6 [CRITICAL-adjacent → rated HIGH] — §11 / §9.1 stop offset polarity is inverted relative to the spec

- **Spec says (§9.1, LONG):**
  > `SL = L_cluster − (2 × TickSize)` — 1–2 ticks **below** the absorption cluster low.

  (§9.1, SHORT):
  > `SL = H_cluster + (2 × TickSize)` — 1–2 ticks **above** the absorption cluster high.

- **Code does (`quant/decision/stops.py:84-108`, called from `signal_builder.py:122` and `position_manager.py:612`):**
  ```python
  def structural_stop(side, entry, anchor, tick, inside_ticks=2):
      """Return the stop price ``inside_ticks`` inside ``anchor`` toward ``entry``.
      LONG (support below):  sl = anchor + n*tick, still strictly below entry.
      SHORT (resistance above): sl = anchor - n*tick, still strictly above entry.
      """
      offset = inside_ticks * step
      if str(side).upper() == "LONG":
          sl = anchor + offset        # anchor + 2·tick  → ABOVE the anchor
  ```
  Verified: LONG with `anchor=95, tick=0.5` → `sl = 96.0` (spec: `95 − 1.0 = 94.0`). SHORT with `anchor=95` → `94.0` (spec: `96.0`).

  **Note on intent:** the module docstring (`stops.py:1-7`) argues this is deliberate — Fabio's *live* placement puts the stop 1–2 ticks *inside* the level "toward the market, so the stop fills before the liquidity cascade through the cluster", and explicitly labels `anchor − 2·tick` on a long "the *outside* retail stop — that formula is forbidden here." So the sign is not an accident; it is a conscious deviation from §9.1's literal formula. But §11's diagram and §15 row 5 ("Cluster extreme ± 2 ticks") both describe the *outside* placement, and §11's headline rule is "Stop Placed Behind Bubbles, Not Wicks" — the code implements "in front of the level", which is the opposite of "behind the cluster". The two documents inside `docs/amt` are internally inconsistent, and the code follows the unwritten reading.

- **Impact:** Live-money-critical *if* the spec's literal reading is the intended one. The current behaviour is a legitimate trader's choice (retail stops sit exactly at `L_cluster`, so stepping 2 ticks inside avoids being the liquidity cascade's first target), but it means the stop is *closer to entry* than spec → smaller R → different sizing via `position_size` → different TP geometry via `tp_multiplier`. Every downstream R-multiple (0.8R breakeven, +2.0R TP1, pyramid 50%) is computed off this stop, so the whole risk geometry shifts. This must be resolved by the spec owner, not by the code.

- **Suggested fix:** Decide in `docs/amt` which placement is authoritative. If §9.1/§11 literal ("behind the cluster"), flip `structural_stop` to `anchor − n·tick` (LONG) / `anchor + n·tick` (SHORT) and re-pin the R:R tests. If the inside placement is intended, amend §9.1/§11/§15 to say so and delete the "behind" language, then rename the function (`structural_stop_inside`) so the polarity is unambiguous at the call site. Either way, D-C4's pyramid ratchet must use the same resolver.

---

### D-C7 [HIGH] — §11 stops are anchored to VA/LVN/bar levels, never to the absorption cluster extremes

- **Spec says (§11):**
  > **Stop Placed Behind Bubbles, Not Wicks:** Stop-loss is pegged 1–2 ticks behind the big executed bubble cluster, which represents the institutional cost basis.

  and §15 row 5:
  > Stop-Loss | Cluster Extreme ± 2 ticks | Hard Stop-Loss registered at exchange.

- **Code does (`quant/decision/stops.py:27-60`):** the anchor candidate list is:
  ```python
  if side == "LONG":
      buy = getattr(ctx, "nearest_buy_print_below", 0.0) or 0.0
      if buy > 0 and entry > buy: out.append(float(buy))
      if ctx.leg_lvn ...: out.append(float(ctx.leg_lvn))
      if vah/val ...: out.append(...)
      if ctx.bar ... float(ctx.bar.low) < entry: out.append(float(ctx.bar.low))
  ```
  — `nearest_buy_print_below`, `leg_lvn`, `vah`, `val`, `bar.low/high`. **`AbsorptionCluster.cluster_low` / `cluster_high` (spec §14 dataclass, lines 500-507) appear nowhere in the anchor set.** The spec's own reference implementation (§14, `evaluate_and_execute`) does use them:
  ```python
  sl = latest_abs.cluster_low - (2 * self.tick_size)
  ```
  but `AbsorptionCluster` is defined only inside the spec's illustrative Python; `quant/` has no such type and the DTO carries `absorptionSide`/`absorptionStrength` (a direction + strength), not cluster bounds. `ctx.bar.low` — explicitly dismissed by §11 as "arbitrary candle wicks" — is a first-class candidate.

- **Impact:** The institutional-cost-basis stop is the strategy's core slippage defence. Anchoring to a bar low or a VA edge instead means the stop is frequently *tighter than the cluster* (stopped out by noise the spec says to sit through) or *wider than the cluster* (risking more than the sizing formula assumed). Combined with D-C6's polarity, entry stops are structurally different from the spec's design.

- **Suggested fix:** add `cluster_low`/`cluster_high` (and `cluster_volume`) to the AMT DTO and to `DecisionContext`, make `_anchor_candidates` prefer the nearest absorption cluster extreme in the trade direction over VA/bar levels, and gate on §7.2's absorption classification (volume ≥ 1.5× avg, range ≤ 0.5·H_range) so a weak cluster cannot become the anchor.

---

### D-C8 [MEDIUM] — §13.1's alternative breakeven trigger is half-implemented (no "2 consecutive range bars")

- **Spec says (§13.1):**
  > As soon as: 1. CVD expands with **2 consecutive range bars closing in profit**, OR 2. Price breaks the local swing high/low of the entry candle (+0.8R advance): SL ← P_entry (Breakeven)

- **Code does (`quant/execution/exit_checks.py:122-133`):**
  ```python
  # CVD-based early breakeven
  if be_floor is None and profit > 0:
      cvd_slope = float(dto.get("cvdSlope") or 0.0)
      cvd_confirms = ((long and cvd_slope > cvd_be_threshold)
                      or (not long and cvd_slope < -cvd_be_threshold))
      if cvd_confirms:
          be_floor = entry
  # Standard 0.8R breakeven
  if be_floor is None and profit >= risk * 0.8:
      be_floor = entry
  ```
  Path 2's +0.8R is implemented and verified. Path 1 requires only `profit > 0` **and a single bar's** `cvdSlope` crossing `cvd_be_threshold` (default 2.0). The "2 consecutive range bars closing in profit" condition — the whole point of requiring *confirmation* before removing the stop — is missing; there is no consecutive-bar counter, no range-bar notion, and `ExitEngine._breakeven` is a per-position scalar, not a bar streak.

- **Impact:** The CVD path arms breakeven too eagerly (any profitable bar with a strong CVD slope), which tightens the stop earlier than specified and can scratch trades that would have run. It also makes the CVD path strictly weaker than the 0.8R path in terms of confirmation, inverting the spec's intent (the CVD trigger is supposed to be the *earlier* but *confirmed* route).

- **Suggested fix:** add a `_be_confirm_bars: dict[str, int]` streak counter to `ExitEngine`; arm `be_floor` only when the CVD-confirmation condition holds on 2 consecutive evaluations with the position in profit, resetting to 0 on any adverse bar. Emit a `StopMoved` with reason `BREAKEVEN_ARMED_CVD` so the two paths are distinguishable in the journal.

---

### D-C9 [MEDIUM] — §16 violation: `TickFootprintAccumulator` claims "real tick-level footprint" while running on 5-level depth proxy data

- **Spec says (§16, Known Data Limitations):**
  > The spec describes tick-level footprint data with trade-level aggression flags. The current implementation uses **candle delta** (close-to-close) as a proxy for buy/sell volume. True trade-level aggression flags require a tick feed not available from the current Dhan integration.
  > ... The current implementation uses **5-level depth snapshots** from Dhan. Full L2 depth is not available from the current feed.

- **Code does (`quant/amt/orderflow/footprint.py:127-135`):**
  ```python
  class TickFootprintAccumulator:
      """Accumulates real tick-level footprint data per candle period.

      Uses the tick rule to classify each trade as buy/sell aggression
      based on trade price vs best bid/ask from order book depth.
      """
  ```
  fed from `quant/amt_engine.py:205-224`, where `best_bid`/`best_ask` are read off `tick.depth` (the **5-level** snapshot), not from an aggressor flag. The docstring's word "real" directly contradicts §16's own admission that no aggression flags exist. Similarly `quant/contracts/value_objects.py:243` labels the input "live 5-level depth snapshot — gate 3's order-flow aggression (A3) input", and `quant/llm/bridge.py:26` advertises "tick aggression sigma" to the LLM. `quant/brokers/multiplexed_feed.py:149` is the one place that is honest: "Dhan WS carries no aggressor flag and its total_buy_qty/total_sell_qty…".

- **Impact:** Not a money bug — but §16's explicit instruction is that the code must **not claim true tick aggression while using the proxy**. The tick-rule inference from 5-level best bid/ask is a *derived* estimate, and naming it "real tick-level footprint" / "tick aggression" misleads every downstream consumer (the LLM prompt, gate 3's order-flow aggression, the footprint candle API) into treating an estimate as ground truth. It also poisons auditability: a reviewer cannot tell which CVD number is measured vs inferred.

- **Suggested fix:** rename to `DerivedFootprintAccumulator` / `ProxyFootprintAccumulator`; change the docstring to "Estimates buy/sell aggression via the tick rule against 5-level depth snapshots (spec §16 proxy — Dhan carries no aggressor flag)"; and rename the LLM feature from "tick aggression sigma" to "inferred aggression sigma". Add a `provenance` field on footprint candles so gate 3 can distinguish measured vs estimated delta.

---

### D-C10 [MEDIUM] — `MODEL_RISK_FAILURES` / `MODEL_SIZING_FAILURES` are process-global counters leaking across engines

- **Isolation spec says (§ "No shared mutable state in the decision path"):**
  > `DecisionService` is stateless. `GatePipeline` operates on a per-call `DecisionContext`. `AMTEngine.analyze()` uses only per-engine state.

- **Code does (`quant/execution/exits.py:22-28`):**
  ```python
  # Model-risk failures observed since process start.
  MODEL_RISK_FAILURES = 0
  MODEL_SIZING_FAILURES = 0
  ```
  mutated by `ExitEngine.evaluate` at `exits.py:149,231` via `global`, and read by `quant/execution/coordinator_metrics.py:79-80` to expose per-engine telemetry:
  ```python
  "model_risk_failures": exits_mod.MODEL_RISK_FAILURES,
  "model_sizing_failures": exits_mod.MODEL_SIZING_FAILURES,
  ```
  Every `ExitEngine` in every engine increments the *same* two module-level integers. `ExitEngine.model_risk_failures` (exits.py:123-126) returns the global, so a per-engine property reports a process-wide sum.

- **Impact:** Telemetry/observability only — no trading decision reads these counters, so money safety is unaffected. But the counter makes per-engine degradation undetectable (8 engines sharing one counter means "engine C degraded" looks identical to "all engines degraded"), which matters precisely because the counters exist to make degradation *visible*. This is the one genuine cross-engine mutable-state leak in the decision path; everything else (strategy, DecisionService) is stateless per call.

- **Suggested fix:** move the counters to instance attributes (`self._model_risk_failures = 0`), keep `coordinator_metrics` reading `engine._exits.model_risk_failures`, and add a process-level aggregator in the coordinator if a total is needed for ops.

---

### D-C11 [LOW] — Contingent SL-M fallback aliases `NotImplementedError` to `"mock_pass"`, which can mask a real failure as a placed stop

- **Spec says (§15 row 5):**
  > Stop-Loss | Cluster Extreme ± 2 ticks | Hard Stop-Loss registered at exchange. | **Strict zero-discretion execution.**

- **Code does (`quant/execution/live_oms.py:181-189`):**
  ```python
  except NotImplementedError:
      # Pre-v6 broker double / test mock without native SL-M support
      stop_order_id = "mock_pass"
  except Exception as exc:
      logger.critical("LiveOMS Phase 2 contingent stop placement failed for %s: %s", ...)
      stop_order_id = None
  ```
  A broker adapter that raises `NotImplementedError` for a genuine reason (uninstrumented symbol, unmapped product code, transient broker library gap) is treated as a *successfully placed* stop. The position then carries no exchange-side stop while the engine believes one is registered — and the emergency-flatten guard never fires, because `stop_order_id` is truthy.

- **Impact:** Live-money, but low likelihood: the production adapter implements `place_stop_loss`, so this branch is only reachable on an adapter regression or a new contract type. The blast radius is one unguarded position until the engine's in-memory stop logic triggers `manage_tick_exit` (which does work independently). Still, "mock_pass" as a sentinel for a live order is the kind of string that silently becomes truth.

- **Suggested fix:** restrict the alias to an explicit opt-in capability check — `hasattr(self._broker, "place_stop_loss")` before calling, and treat `NotImplementedError` from a broker that *has* the method as a hard failure (`stop_order_id = None` → emergency flatten). Alternatively return a distinct `StopNotSupported` result and let the engine decide whether its own tick-level stop is sufficient.

---

## Verified Correct (with code quotes)

1. **§12.1 MDL halt at exactly 2.0% of E₀** — `quant/execution/risk.py:253`:
   ```python
   if self._daily_pnl <= -0.02 * self._starting_equity:
       self._halted = True
       self._halt_reason = "session kill switch: cumulative loss reaches 2.0% of equity"
   ```
   Verified: −1.9% → not halted; −2.0% → halted; `can_trade()` returns `(False, ...)`.

2. **§12.1 three-consecutive-loss cutoff, independent of MDL** — `risk.py:259-261`:
   ```python
   elif self._consecutive_losses >= self._max_consecutive_losses:
       self._halted = True
       self._halt_reason = "max consecutive losses reached"
   ```
   Verified: 3 × −₹100 losses halt the session even though cumulative loss is only 0.3%.

3. **§15 row 9 — halt is session-locked, not trade-locked** — `risk.py:247-249` short-circuits an already-halted session, and `can_trade()` (275-286) is the entry gate consulted by `quant/engine/decision_loop.py:297` *before* any context is built. Verified that a subsequent **win** does not clear the halt (`record_trade(+500)` left `halted=True`).

4. **§12.1 session reset merges gains into E₀ and zeroes the cushion** — `risk.py:503-516`:
   ```python
   self._daily_pnl = 0.0; self._peak_daily_pnl = 0.0
   self._consecutive_losses = 0; self._trades_today = 0
   self._halted = False; self._halt_reason = ""
   self._equity = self._starting_equity
   ```
   Plus per-symbol date-keyed storage (`daily_risk:SYM:2026-09-21`, verified distinct for NIFTY vs BANKNIFTY) so a new session starts clean.

5. **§10.4 / §16 day-of-week multiplier** — `risk.py:19-25, 465`; verified `dow=0 → 62.50`, `dow=2 → 125.00` on identical inputs (0.5× Mon/Fri).

6. **§13.1 +0.8R breakeven** — `exit_checks.py:132`: `if be_floor is None and profit >= risk * 0.8: be_floor = entry`. Verified: 0.75R does not arm, exactly 0.8R arms.

7. **§13.1 downside risk → $0.00** — `quant/execution/protective_stop.py:38-47` resolves the *tightest* of raw SL / breakeven floor / trail per direction, and `ExitEngine.is_risk_free` (exits.py:108-116) is the pyramid authorization predicate.

8. **§13.2 pyramid sizing 50% / 25% and max 2 add-ons** — `position_manager.py:606-609`:
   ```python
   fraction = 0.50 if self.pyramid_count == 0 else 0.25
   pyramid_size = base_size * fraction
   ```
   with `if self.pyramid_count >= 2: return` (541). Authorization gate is enforced *inside* `check_pyramid` (548), not just at the caller, so a direct invocation cannot bypass it.

9. **§13.2 portfolio ceiling on pyramid add-ons** — `position_manager.py:638-647` reserves add-on risk through the shared `PortfolioRiskAuthority` (`can_accept` → `register_open`, both with `is_pyramid=True`), and `_execute_full_close` (323-332) releases each add-on's reservation paired with its own fill PnL.

10. **§15 row 5 hard SL registered at the exchange with zero discretion** — `live_oms.py:167-224`: the contingent SL-M is placed in the same `submit()` call as the entry; on rejection the position is **emergency-flattened** and `EmergencyFlattenError` raised so the engine unwinds the risk reservation (submission_handler.py:197-230) rather than carrying a naked position.

11. **§11 TP shield 1–2 ticks inside the structural level** — `signal_builder.py:173-202` (`_shield_tp`) with explicit inversion guards (`if shielded <= entry: return tp`).

12. **Isolation: all 9 per-symbol state items are per-engine instances** — `quant/runtime.py` constructs `EventStore()` (439), `EngineState(symbol=...)` (450), `AMTEngine(...)` (460/472/484), `DecisionService(...)` (495), `ExitEngine(...)` (509), `SessionRisk(...)` (529), `BarAggregator(...)` (384-409), `PositionManager` (1158, lazily per engine), and per-engine bounded deques `_trace` (575), `cert_records` (426) inside `QuantEngine.__init__`. `_spawn_engine` (multi_engine.py:1874) passes only shared resources (`portfolio_risk`, `session_levels`, `strategy`) plus per-symbol identity.

13. **`PortfolioRiskAuthority` is the only cross-engine coupling in the decision path** — verified at every call site: `submission_handler.py:326/332` (entries), `position_manager.py:640/644` (pyramids), `exit_manager.py:448-452/472-477` (releases). `Portfolio` and `SessionLevelStore` are shared but documented as such in the isolation doc; `SessionLevelStore` serializes all access through one `RLock` (session_levels.py:44) and `SessionRisk` keys its state per symbol+date.

14. **MultiplexedMarketFeed per-symbol isolation** — `multiplexed_feed.py:60-61` (`_queues`, `_readers` per symbol), `add_reader`/`remove_reader` (222-236), and `stop()` poisoning every queue with `None` (239-257) so no reader blocks forever.

15. **EOD square-off force-closes everything (no overnight holding)** — `multi_engine.py:1163-1200` iterates all engines past their per-market deadline (1152-1161) and calls `force_close_position`; `exit_manager.py:393-431` closes the base *and* `close_lingering_pyramids` (43-109) for add-ons whose base is already gone, all under `_close_lock` and idempotent.

16. **Division-by-zero and degenerate-input guards in sizing** — `risk.py:381` (`if entry == sl or entry <= 0: return 0.0`) and `risk.py:429-431` (`loss_per_unit <= 0 → 0.0`); `live_oms.py:102-108` rejects non-finite/non-positive quantity before any broker call.

17. **Order-path failures are loud, not silent** — `submission_handler.py:218-230` logs an exception, latches a `SignalBlocked`, and releases the portfolio reservation; `exit_manager.py:244-253` keeps the position open and retries next bar. The one silent `except Exception: pass` (live_oms.py:218) guards only the audit-emit *inside* an emergency flatten whose raise must not be suppressed — acceptable.

---

## Suspicious / Needs Human Eyes

1. **`unhalt()` clears `_consecutive_losses` and decrements `trades_today`** (`risk.py:320-328`). It is operator-facing, but a 3-consecutive-loss halt is spec-mandated to terminate the *day*; an operator `unhalt()` mid-session can revive trading after the §12.1 cutoff. There is no auth/confirmation gate and no `StopMoved`-style audit event for it. Verify the runbook intent.

2. **`risk.py:155-174` un-halts on restart** for `"max trades/session reached"` and `"SIGTERM shutdown"` reasons, with guards against "emergency". A halt persisted as `"max consecutive losses reached"` correctly survives (verified), but the branch that *does* revive depends on string-matching `halt_reason`. A future rename of a reason string silently changes restart safety. Consider an explicit `halt_kind` enum.

3. **`risk.py:392-419` "aggressive mode" branch** is a completely different sizing algorithm (50% capital deployment, 15% derivative margin fraction, `lots = 1` fallback) triggered by `base_risk_pct >= 0.05`. The coordinator's default is `risk_per_trade_pct=0.05` (multi_engine.py:1890) while the typed `RiskConfig` default is `0.005` and the live validator caps live risk at 2% (`backend/app/config_models/validator.py:49-51`). So **paper defaults into the aggressive branch and live does not** — meaning the sizing path exercised all day in paper is not the one that runs live. This is the single largest paper/live divergence in the system and deserves a deliberate decision.

4. **`paper_simulator.py` / `paper_reconciliation.py`** were in scope but the money-path findings are all upstream; a dedicated reconciliation review would be worthwhile given `ReconciliationRequiredError` paths in `live_oms.py` and the partial-fill exposure state machine.

5. **§13.2's "+1.0R Locked" authorization variant is not modelled anywhere** — `is_risk_free` only knows "a breakeven floor exists". If the spec intends pyramids to be authorized only after the base is *locked in profit* (not merely at breakeven), the current gate is too permissive. This is the same root cause as D-C4's broken guarantee and should be settled together with it.

6. **§16's range-bar caveat** ("Range bars are available via `quant/aggregator.py` but are not the primary decision driver") is honoured — the pipeline is 1m time bars — but the AMT DTO still surfaces range-bar-derived concepts (`legLvns`, `H_range`-scaled absorption thresholds in §7.2) computed on time bars. Not a defect per §16's own "architectural choice, not a bug" carve-out; flagged only because §7.2's `0.50 × H_range` compression test is being evaluated on a different bar type than it was specified for.
