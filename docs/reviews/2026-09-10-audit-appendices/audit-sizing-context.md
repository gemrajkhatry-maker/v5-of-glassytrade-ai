# Audit: Sizing Authority & Information Completeness

Repo: `/Users/apple/Documents/v5-of-glassytrade-ai`
Branch: `feat/timesfm-paper-e2e-validation`
Scope: A (sizing authority) + B (information completeness). Read-only; no files modified except this report.
Date: 2026-09-10

---

## SCOPE A — SIZING AUTHORITY

### A.0 Inventory: how many independent quantity / stop / target computations exist?

There are **five** distinct code paths that compute quantity and/or stop/target prices. Three are live on the TimesFM E2E path, two are alternates.

| # | Path | Entry | Computes | Live on E2E? |
|---|------|-------|----------|--------------|
| 1 | `TimesFMPositionSizer.compute_size` (sizing) | `quant/decision/timesfm_sizing.py:143` | qty, lots, var_stop, target_price, payoff | YES — twice per entry (see A.1) |
| 2 | `SessionRisk.position_size` → forecast branch → re-enters #1 | `quant/execution/risk.py:333-365` | qty only | YES — the actual submitted size |
| 3 | `SessionRisk.position_size` static branches (aggressive-deployment / fractional-risk) | `quant/execution/risk.py:367-423` | qty only | Only when forecast is None |
| 4 | `TimesFMTradingStrategy._size_entry` | `quant/strategies/timesfm_strategy.py:221` | var_stop, target, payoff | Fallback only (see A.1) |
| 5 | `SignalBuilder.build_or_reason` + `structural_stop` | `quant/decision/signal_builder.py:100`, `quant/decision/stops.py:56` | sl, tp, rr | Only on the non-TimesFM AMT strategy path |

Plus two stop *management* engines that override the submitted stop:

| # | Path | Entry | Role |
|---|------|-------|------|
| 6 | `TimesFMRiskAuthority` via `ExitEngine.evaluate` | `quant/decision/timesfm_risk.py:110`, `quant/execution/exits.py:160-186` | Trails the stop off the forecast p10/p90 — **replaces the submitted SL after bar 1** |
| 7 | `check_trailing_stop` (deterministic) | `quant/execution/exit_checks.py:90` | Trails off bar prices/0.8R — used when forecast is stale |

So: **one** stop/target pair is produced for the UI (sizing #1 or #4), a **second** stop/target pair is what OMS actually stores (whatever `Signal.sl/tp` was, produced by #1 or #4 — same source), and the stop is then **replaced** at bar 2 by #6/#7. Quantity has **two** independent computations that are both executed, with #2 discarding #1's output.

---

### A.1 CRITICAL — dynamicSizing is computed twice per entry; the scanner's copy is only conditionally used for SL/TP, and its quantity is discarded entirely

**Severity: HIGH**

`quant/decision/timesfm_agents.py:317-338`
```python
        dynamic_sizing = None
        if direction != "FLAT":
            try:
                from quant.decision.timesfm_sizing import TimesFMPositionSizer
                sizer = TimesFMPositionSizer()
                sizing_res = sizer.compute_size(
                    equity=float(getattr(ctx, "equity", None) or 100000.0),
                    entry=curr_price,
                    side=direction,
                    forecast=forecast,
                    override_tp=structural_target,
                    is_aggressive=is_high_conviction,
                )
                dynamic_sizing = {
                    "lots": sizing_res.lots,
                    "quantity": sizing_res.quantity,
                    ...
                    "varStop": sizing_res.var_stop,
                    "targetPrice": sizing_res.target_price,
                    ...
```

`quant/strategies/timesfm_strategy.py:163-171`
```python
            sizing = scan_res.get("dynamicSizing")
            if sizing and sizing.get("varStop") and sizing.get("targetPrice"):
                var_stop = float(sizing["varStop"])
                target = float(sizing["targetPrice"])
                payoff = float(sizing["payoffRatio"])
            else:
                var_stop, target, payoff = self._size_entry(curr_price, direction, forecast, setup, ctx)
```

`quant/runtime.py:1055-1064`
```python
            tfm_fc = self._fresh_forecast()
            quantity = clamp_quantity(
                self._risk.position_size(
                    signal.entry, signal.sl, lot_size=self._oms.lot_size,
                    is_expiry=self._contract_is_expiry,
                    max_lots=self._max_lots,
                    forecast=tfm_fc,
                    side=signal.type,
                )
            )
```

**Why it matters:**
- The scanner runs `compute_size` on every non-FLAT evaluation, and `should_enter` runs on **every bar** including bars where the entry is rejected. On `allow_positioned=True` (thesis-flip path) it also runs. So `compute_size` is invoked far more often than entries occur. It is pure CPU (numpy min/max/erf), but it is duplicated work per bar per symbol in an 8-engine coordinator.
- The quantity in `dynamic_sizing["quantity"]` is **never read by anyone**. `grep -rn "dynamicSizing"` returns only `timesfm_agents.py:406` (producer) and `timesfm_strategy.py:165` (consumer). The strategy reads only `varStop`/`targetPrice`/`payoffRatio`. The UI/WS contract (`quant/ws_contract.py:44-56`, `frontend/types.ts:47`) has **no** `dynamicSizing` field. The real quantity comes from a *second* `compute_size` call inside `SessionRisk.position_size` (`risk.py:334-365`) whose return value is what gets submitted.
- The two `compute_size` calls use **different inputs**, so they can disagree:
  - Scanner call: `equity = ctx.equity or 100000.0`, `is_aggressive = is_high_conviction` (confidence_score >= 0.80), no `max_lots`, no `max_rupee_risk_cap`, no `lot_size` (defaults to 1.0).
  - Risk-authority call: `equity = sizing_equity` (portfolio-adjusted), `is_aggressive = base_risk_pct>=0.02 OR concordance>=0.70 OR cushion`, `lot_size = self._oms.lot_size`, `max_lots = self._max_lots`, `max_rupee_risk_cap=max_rupee_risk_cap`.
  - With `lot_size=1.0` in the scanner call, the `lot_size > 1.0` branch is skipped and it falls into `quantity = risk_budget / loss_distance`, producing a **fractional** quantity; the risk-authority call with real lot_size snaps to whole lots. The two "quantities" for the same entry can differ by an order of magnitude, and only the risk-authority one is used.

**Real bug vs intentional:** Mixed. The "runtime owns final sizing" intent is documented (`timesfm_strategy.py:225-232`) and is deliberate. But the dead `dynamic_sizing["quantity"]`/`lots`/`riskPct`/`winProb`/`dispersionMultiplier`/`velocityMultiplier`/`expectedPeakStep`/`rationale` fields are **dead information** (see B.7), and the duplicated compute is an unintended cost. The differing-input divergence between the two `compute_size` calls (esp. `lot_size` default 1.0 vs real) is an unintended inconsistency.

---

### A.2 HIGH — Two different VaR stops can be produced for the same entry, and the one submitted is not always the one the scanner computed

**Severity: HIGH**

`quant/strategies/timesfm_strategy.py:165-167`
```python
            sizing = scan_res.get("dynamicSizing")
            if sizing and sizing.get("varStop") and sizing.get("targetPrice"):
```
versus
`quant/strategies/timesfm_strategy.py:238-241, 271-280`
```python
        structural_target = None
        if direction == "LONG":
            if setup == "VA_FADE" and poc > curr_price:
                structural_target = poc
            elif setup in ("BREAKOUT", "MODEL_MOMENTUM"):
                structural_target = (
                    float(getattr(ctx, "npoc_above", 0.0) or 0.0)
                    or float(getattr(ctx, "prior_poc", 0.0) or 0.0)
                    or vah
                    or None
                )
        ...
        var_stop = float(sizer.calculate_var_stop(curr_price, direction, forecast))
```

**Why it matters:**
- The scanner's `structural_target` logic (`timesfm_agents.py:271-315`) and `_size_entry`'s (`timesfm_strategy.py:238-267`) are **not identical**. The scanner applies `_valid_target()` (20% scale clamp) and, for `TRIPLE_A`, prefers `vah` before `prior_poc`; `_size_entry` has no scale clamp and prefers `npoc_above`→`prior_poc`→`vah`. For the same setup, the two functions can select *different* structural targets, hence different `target_price` and different `payoffRatio`.
- Because the scanner's `dynamicSizing` is used **whenever it is truthy** (`varStop and targetPrice` non-zero), the *scanner* target wins on the normal path; `_size_entry` is reached only when `compute_size` returned `_zero_result` (varStop=0.0) — i.e. exactly the error/zero-loss-distance case where the fallback is least trustworthy either way.
- Both paths call `calculate_var_stop` with default `tick_size=0.05`, so the VaR stop itself usually matches; the **target** is where they diverge. That target is what gets written into `Signal.tp` and shown in the UI.

**Real bug vs intentional:** Unintended. Two functions encode the same "structural target" rule with drift between them. Neither is marked as the authority.

---

### A.3 HIGH — The stop submitted to the OMS is NOT the stop ExitEngine trails after the first bar; the UI can display a third value

**Severity: HIGH**

Submitted stop: `quant/runtime.py:1056-1064` passes `signal.sl` (the VaR stop) into `position_size`; `quote/execution/oms` stores `Signal.sl` on the `Order` (`quant/execution/order.py:8-10`, `position_to_row` at `:69` sets `"stop_loss": sig.sl`).

Then on every subsequent bar, `ExitEngine.evaluate` runs the TimesFM risk authority first:
`quant/execution/exits.py:156-186`
```python
        if timesfm_forecast is not None:
            try:
                if self._timesfm_risk is None:
                    from quant.decision.timesfm_risk import TimesFMRiskAuthority
                    self._timesfm_risk = TimesFMRiskAuthority()
                side = "LONG" if long else "SHORT"
                tr = self._trail.get(position._id)
                current_active_sl = tr.stop if (tr and tr.active and tr.stop is not None) else sl
                eval_res = self._timesfm_risk.evaluate_exit(...)
                if eval_res.new_stop is not None:
                    ...
                    tr.stop = eval_res.new_stop
```
and `TimesFMRiskAuthority.update_trailing_stop` (`quant/decision/timesfm_risk.py:76-99`) computes `candidate = p10_path[0] - tick_size` (LONG) / `p90_path[0] + tick_size` (SHORT).

**Why it matters:**
- The **hard stop actually enforced** after bar 1 is `p10_path[0] - tick`, not the submitted VaR stop (which used `min(p10_path[:5]) - tick`). `p10_path[0]` is the *first* forecast step, `min(p10_path[:5])` is the minimum over *five* steps, so `p10_path[0] >= min(p10_path[:5])` and the trailed stop is systematically **tighter (closer to entry) on a LONG** than the submitted stop. The position can therefore be stopped out at a level the UI never showed and the risk math never budgeted.
- Worse, the ratchet is monotonic *upward only* (`new_stop = max(prior_stop, candidate)` then `max(new_stop, current_sl)`), but on the first evaluation `prior_stop` defaults to `current_sl = sl` (the submitted stop), so the very first ratchet can only tighten, never loosen. There is no path that keeps the wider submitted VaR stop.
- The UI "Trail SL" comes from a **third** source. `quant/multi_engine.py:810,845` reads `open_p.get("stopLoss")` from the portfolio row, which is `sig.sl` (`quant/state.py:102`, `quant/state.py:209,221` read `pos.sl` / `sig.sl`) — i.e., the *original submitted* stop, **not** the ratcheted `tr.stop`. So: OMS order carries `sig.sl`; ExitEngine enforces `tr.stop`; portfolio/UI displays `sig.sl` again. Three different quantities for one number, and the enforced one is the one nobody displays.

**Real bug vs intentional:** Unintended divergence. Stop-tightening itself is intentional; the failure to propagate the ratcheted stop into the position/portfolio DTO (so the UI shows the real enforced stop) is a real display/audit defect.

---

### A.4 MEDIUM — `_size_entry` is effectively dead code on the normal path

**Severity: MEDIUM**

`quant/strategies/timesfm_strategy.py:165-171` — `_size_entry` is called only when `sizing` is falsy or `varStop`/`targetPrice` is 0. The scanner sets `dynamic_sizing` for every `direction != "FLAT"` (`timesfm_agents.py:318`), and a valid entry implies `direction != "FLAT"` (gate 3, `timesfm_agents.py:349`). The only way `dynamic_sizing` is None on an approved entry is the `except` at `timesfm_agents.py:339-340` (swallowed with `logger.debug`), or `compute_size` returning `_zero_result` (varStrop=0.0). So on a healthy path `_size_entry` never runs.

**Why it matters:** the docstring at `timesfm_strategy.py:225-232` describes `_size_entry` as "the single, lightweight size math used to qualify an entry signal," but it is the exceptional path, and it disagrees with the primary path (A.2). A reader will mis-model which function is authoritative.

**Real bug vs intentional:** Unintended (stale documentation + divergent duplicate).

---

### A.5 MEDIUM — `SessionRisk.position_size` silently falls through to the static 50%-deployment branch when the forecast call fails

**Severity: MEDIUM**

`quant/execution/risk.py:336-366`
```python
            if forecast is not None:
                try:
                    ...
                    res = sizer.compute_size(...)
                    return float(res.quantity)
                except Exception as exc:
                    logger.warning("TimesFM dynamic sizing error (%s) — falling back to deterministic risk", exc)
            # Aggressive mode (>= 5% risk): deploy 50% of available equity ...
            if self._base_risk_pct >= 0.05:
```

**Why it matters:** the TimesFM branch and the static branch below it are two entirely different sizing policies (continuous Kelly vs. a flat 50%-of-equity deployment). If the exception fires (e.g., a forecast object whose `p10_path` is empty/shorter than expected, raising inside numpy), the code silently switches policy for that entry with only a `warning`. The 50%-deployment branch then ignores `max_rupee_risk_cap` and uses `cost_per_unit = entry` (notional), so a single failed inference can size an order ~200x larger than the Kelly path would have. There is no metric/alert distinguishing "Kelly sized" from "deployment sized."

**Real bug vs intentional:** Intentional fallback, but the fallback is not risk-equivalent to the primary path and is only logged at `warning`. This is a latent money-path hazard.

Note also: the forecast branch **ignores `is_expiry`** and **ignores `DAY_OF_WEEK_MULTIPLIER`** (`risk.py:392,423` apply the multiplier only to the static branches). So expiry-day halving and Mon/Fri defensive cuts silently do not apply when a forecast is present — i.e., on the E2E path. `compute_size` has no expiry parameter at all.

---

### A.6 LOW — `clock` risk in `calculate_var_stop`: no lookahead validation that forecast is fresh, but `asof_bar` exists and is unchecked by the sizer

**Severity: LOW**

`quant/decision/timesfm_sizing.py:90-100` consumes `forecast.p10_path[:bars]` directly. `TimesFMForecast` has an `asof_bar` field (`timesfm_agents.py:45`) and `runtime._fresh_forecast` (`runtime.py:1420-1441`) does reject stale forecasts — so the entry path is guarded. But `TimesFMScanningAgent.evaluate` is also invoked from the advisor/native engine path with a freshly-built forecast, and `compute_size` itself performs no freshness check. Any future caller that passes a cached forecast directly would silently size off an arbitrarily old path. Defensive-only; low risk today.

**Real bug vs intentional:** Intentional layering (caller guards freshness); flagged as a latent coupling.

---

### A.7 Answer: hardcoded lot / equity numbers

Yes. Found:

1. `quant/decision/timesfm_agents.py:323`
```python
                    equity=float(getattr(ctx, "equity", None) or 100000.0),
```
Hardcoded fallback equity ₹1,00,000. Note `ctx.equity` defaults to `INITIAL_CAPITAL` = **1,000,000** (`quant/contracts/aggregates.py:28`), and `context_builder.py:443` sets `equity=risk_state.equity`. So the `or 100000.0` branch is only reachable if equity is exactly 0.0/None. But if it *is* reached, the scanner's displayed dynamicSizing is computed off ₹1L while the actual order is sized off real equity.

2. `quant/decision/timesfm_client.py:115`
```python
        "equity": float(ctx.equity or 200000.0),
```
A **second, different** hardcoded equity fallback (₹2,00,000) in the snapshot builder that feeds the advisor/service.

3. `quant/decision/timesfm_sizing.py:230-233` — hardcoded leverage cap:
```python
            if entry > 0:
                notional_per_lot = entry * lot_size
                max_dep_lots = max(1, int((equity * 2.5) // notional_per_lot)) if notional_per_lot <= (equity * 3.0) else 0
```
`2.5x` leverage and `3.0x` scale constant are magic numbers, not config.

4. `quant/execution/risk.py:376-388` — hardcoded `deployment_pct = 0.50`, `is_expiry *0.5`, and the `target_capital >= cost_per_lot * 0.3` / `available_capital > sizing_equity*0.1` thresholds.

5. `quant/execution/risk.py:18-24` — `DAY_OF_WEEK_MULTIPLIER` 0.5 Mon/Fri is a hardcoded table (and is bypassed on the forecast path, see A.5).

6. `quant/decision/signal_builder.py:13` — `MAX_POSITION_QUANTITY = 1000` hard cap applied in `runtime.py:1056`. Module-level, not config; for MCX (lot 1-2) irrelevant, for NSE options (lot 15-75) caps at 1000 qty ≈ 13-66 lots, potentially binding.

7. `quant/decision/timesfm_sizing.py:60-65` — `base_kelly_fraction=0.35`, `min/max_risk_pct`, `aggressive_max_risk_pct=0.05`, `baseline_dispersion=0.0035` are constructor defaults; `risk.py:338-341` constructs `TimesFMPositionSizer()` with **all defaults** and caches it on the SessionRisk instance, so these are effectively hardcoded for the live path (not read from `backend/config/*.yaml`).

---

## SCOPE B — INFORMATION COMPLETENESS

Method: extracted every `ctx.<attr>` and `getattr(ctx, "<attr>")` read across `quant/` and `backend/app` (excluding `backend/venv`), and every `DecisionContext(...)` field set in `context_builder.py:393-478`, then diffed by hand. Also diffed every `amt_dto.get("<key>")` read against the keys emitted by `quant/amt/dto.py`.

### B.1 CRITICAL — `amt_dto["legLvn"]` and `amt_dto["optionGreekDelta"]` are read but never produced; two features are dead-by-construction

**Severity: HIGH**

Readers:
`quant/decision/context_builder.py:155`
```python
        if amt_dto.get("legLvn"):
            return float(amt_dto.get("legLvn"))
```
`quant/position_manager.py:521`
```python
        leg_lvn = float(amt_dto.get("legLvn") or 0.0)
        if leg_lvn <= 0:
            return  # No Layer 3 LVN available yet
```
`quant/decision/context_builder.py:456-460`
```python
            option_delta=(
                float(amt_dto["optionGreekDelta"])
                if amt_dto.get("optionGreekDelta") is not None
                else (0.50 if is_option_contract(symbol) else None)
            ),
```

Producer check: `grep -rn '"legLvn"' quant backend/app` returns only *readers* (`runtime.py:936` reads it for a cert trace; `context_builder.py:155-156`; `position_manager.py:521`) plus tests. `quant/amt/dto.py:88` emits **`"legLvns"` (plural, a list)** — not `legLvn`. `grep -rn "optionGreekDelta"` returns only the two reader lines in `context_builder.py`; `dto.py` never emits it.

**Why it matters:**
- `ctx.leg_lvn` is therefore **always the fallback value**: `_nearest_leg_lvn` gets `legLvns` (plural) which *is* present, and returns the nearest — so `ctx.leg_lvn` is populated via the plural path. Good. But `position_manager.check_pyramid` reads the **singular** `legLvn`, which never exists, so `leg_lvn` is always 0.0 and the pyramid add-on path **returns early on every bar** (`position_manager.py:521-523`). The pyramid engine is dead in live operation. Tests pass because they inject `{"legLvn": 100.0}` directly (`tests/quant/test_pyramid_certification.py:68` etc.).
- `ctx.option_delta` therefore **always** takes the fallback: `0.50` for options, `None` for futures. The `float(amt_dto["optionGreekDelta"])` branch is unreachable. Since real NSE option deltas for ATM are ~0.5, the 0.50 fallback is "accidentally right" for ATM and **wrong for OTM**, where the runtime's option-premium stop translation (`runtime.py:955` → `selector.translate_underlying_signal_to_option`) scales stop distance by delta.

**Real bug vs intentional:** Real bug. `_nearest_leg_lvn`'s docstring even says "from legLvns list or legLvn float," implying both were expected.

---

### B.2 HIGH — Underlying→option premium translation path is dead in live wiring (`underlying_gateway = None`); the option-scale keys never carry real values

**Severity: MEDIUM**

`quant/multi_engine.py:1682-1685`
```python
        gateway = LiveGateway(self._feed, symbol)
        # Every instrument (futures and options) trades independently as a self-contained scalper.
        # No underlying gateway coupling or cross-feed translation.
        underlying_gateway = None
```
`quant/runtime.py:949` gates all option translation on `self._underlying_gateway is not None`.

**Why it matters:** `runtime.py:953-978` (the `OptionSelector.translate_underlying_signal_to_option` call) never executes in the coordinator live path — the `_underlying_gateways` dict is only ever populated under `if underlying_gateway is not None` (`multi_engine.py:1876`), which is never true. This is currently *consistent* (options use `INDEPENDENT` execution and their own option-scale AMT feed), but it means: (a) the elaborate `_OPTION_SCALE_KEYS` merge machinery (`runtime.py:114-132`) is untested in production, and (b) if an operator ever sets `execution_model` to a coupled mode, the delta path would use the unreachable-entry fallback 0.50 for all strikes. Flagging the dead branch, not the current decision.

**Real bug vs intentional:** Intentional (comment is explicit), but the dead branch is a maintenance hazard.

---

### B.3 MEDIUM — Fields read but never populated: `absorption_cluster_high/low`, `contested_bubble_zone`, `squeeze_detected`, `pullback_confirmed`, `balance_ratio` (dead-ish), `vars_result` (low)

**Severity: MEDIUM**

The following `DecisionContext` fields are populated by `context_builder.py` (so they are not dead *at construction*), but **no consumer reads them**:

- `absorption_cluster_high` / `absorption_cluster_low` — set at `context_builder.py:471-472`; `grep -rn "ctx.absorption_cluster"` → **0 reads**. DTO keys `absorptionClusterHigh/Low` are produced (`dto.py:145-146`) and are in `_OPTION_SCALE_KEYS` (`runtime.py:130`), then dropped after context build. Dead information.
- `contested_bubble_zone` — set at `context_builder.py:465` (`contested_bubble_zone=bool(amt_dto.get("contestedZone") or False)`). `getattr(ctx, "contested_bubble_zone")` **is** read at `quant/decision/gates_edge.py:30`, but `gates_edge.py` is part of the canonical `GatePipeline` used by `DecisionService` — **not** by `TimesFMTradingStrategy` (which uses only the scanner's own gates). So on the E2E path it is dead.
- `squeeze_detected` / `pullback_confirmed` — set at `context_builder.py:474,477`; read only in `gates_edge.py:97-102`, same E2E-dead situation. Read by `timesfm_client.py:124,127` for the snapshot, so not fully dead.
- `balance_ratio` — set at `context_builder.py:425`; only consumer is `timesfm_client.py:102` (snapshot). No decision reads it.
- `vars_result` — set at `context_builder.py:476`; only consumer `va_fade.py:49`, which is only reached from `DecisionService` (`decision_service.py:127`), again **not** on the E2E path.
- `profile_shape` — set at `context_builder.py:451`; only consumer `llm/bridge.py:54`.

**Why it matters:** On the E2E strategy (`TIMESFM_END_TO_END=1`, the branch under test in this PR), the entire `GatePipeline`/`gates_edge.py`/`va_fade.py`/`DecisionService` stack is bypassed (`runtime.py:946` calls `self._strategy.should_enter`, not `DecisionService.evaluate`). Therefore **every field whose only consumer is in `gates_edge.py`/`va_fade.py`/`decision_service.py` is dead information on the E2E path**, including `contested_bubble_zone`, `squeeze_*`, `pullback_confirmed`, `drive_number`, `drive_entry_valid`, `vars_result`, `break_direction`, `break_type`, `leg_lvn` (except pyramid, which is itself dead per B.1), `nearest_buy_print_below`, `nearest_sell_print_above`, `absorption_cluster_*`.

This is a large amount of per-bar computation (footprint scan in `_latest_stacked_imbalance`, aggressive-print scan in `_print_levels_from_dto`, squeeze detection) whose outputs are computed and then not consumed on the only path that matters.

**Real bug vs intentional:** Unintended *interaction*: two decision stacks (deterministic GatePipeline vs TimesFM scanner) coexist and context_builder serves both, but only one runs. Not a correctness bug, but a significant efficiency/clarity defect and a trap for future readers who assume the populated fields are authoritative.

---

### B.4 MEDIUM — `ctx.state` is always `None`, yet five call sites read it as a fallback

**Severity: LOW/MEDIUM**

`quant/decision/context_builder.py:394`
```python
        return DecisionContext(
            state=None,
```
Readers treating it as possibly-live:
`quant/decision/timesfm_agents.py:109-111` (and `:439`)
```python
        poc = float(ctx.poc or (ctx.state.poc if ctx.state else curr_price))
        vah = float(ctx.vah or (ctx.state.vah if ctx.state else curr_price))
        val = float(ctx.val or (ctx.state.val if ctx.state else curr_price))
```
`quant/decision/timesfm_engine.py:187, 371-372`; `quant/decision/timesfm_advisor.py:73`; `quant/decision/timesfm_client.py:28`.

**Why it matters:** the `ctx.state.poc` fallbacks are unreachable (always `None`), so the effective fallback is `curr_price` — meaning if the AMT VA is unavailable, `vah == val == curr_price`, and the scanner computes `va_range = max(vah-val, curr_price*0.001) = curr_price*0.001`, `tol = va_range*0.15`. Setups A/B/C/D then key off `curr_price <= val + tol` etc. — i.e. **degenerate VA conditions silently fabricate a setup** (price always equals both boundaries within tolerance means the long-fade branch `curr_price <= val` is trivially true). This is a money-path hazard when the AMT profile is empty.

Also `ctx.state` being permanently None makes the `state` field itself dead information.

**Real bug vs intentional:** Unintended. The `ctx.state` compatibility shim was meant as a fallback but the producer unconditionally sets None.

---

### B.5 MEDIUM — `TimesFMScanningAgent` dynamicSizing equity uses a different hardcoded fallback than every other consumer

**Severity: LOW**

Covered under A.7 item 1/2. Restated here for Scope B completeness: the scanner (`timesfm_agents.py:323`, `…/100000.0`) and the snapshot client (`timesfm_client.py:115`, `…/200000.0`) disagree on the equity fallback, and both differ from `INITIAL_CAPITAL` (1,000,000). A consumer reading "displayed dynamicSizing" vs "snapshot equity" vs "real sizing equity" can see three different numbers.

**Real bug vs intentional:** Unintended inconsistency.

---

### B.6 LOW — `TimesFMScanningAgent.evaluate` does not guard `ctx.bar is None` before `dynamicSizing`, but scanner is only reached with a bar

**Severity: LOW**

`timesfm_agents.py:105`
```python
        curr_price = float(ctx.bar.close if ctx.bar else forecast.curr_price)
```
This is guarded. But `TimesFMTradingStrategy.should_enter` returns early on `ctx.bar is None` (`timesfm_strategy.py:97-105`), while `TimesFMEngine.analyze` → `scanning_agent.evaluate` (`timesfm_engine.py:380`) can pass a ctx with `bar=None` only if the engine is called directly. Low risk. Noted because `context_to_snapshot` (`timesfm_client.py`) then reads many `ctx.bar.*` fields.

**Real bug vs intentional:** Defensive gap only.

---

### B.7 LOW — Dead information: `dynamicSizing` payload fields never leave the process

**Severity: LOW**

`quant/decision/timesfm_agents.py:330-344` builds a 12-key `dynamic_sizing` dict. Only 3 keys (`varStop`, `targetPrice`, `payoffRatio`) are ever read (`timesfm_strategy.py:166-169`). The other 9 (`lots`, `quantity`, `riskPct`, `riskAmount`, `winProb`, `dispersionMultiplier`, `velocityMultiplier`, `expectedPeakStep`, `rationale`) have **no reader anywhere** — verified against `quant/ws_contract.py` (`WS_AGENT_DECISION_KEYS`, lines 147-155), `frontend/types.ts:47-81` (`AgentDecision` interface), and `frontend/components/ai/AIAdvisorCard.tsx` (reads `dynamicTrailStop`, `activePosition`, `forecastSteps`, etc., but never `dynamicSizing`).

The dashboard feature this PR is presumably validating ("dynamic Kelly sizing visible in UI") is therefore **not wired to the UI**. `winProb`, `payoffRatio`, `riskPct`, `dispersionMultiplier`, `velocityMultiplier` are the most interesting model outputs and none reach the screen.

**Real bug vs intentional:** Unintended (incomplete wiring). Likely the key deliverable gap for this branch.

---

### B.8 LOW — `sizeFraction` is emitted but only one path uses it, and `quant/ws_contract.py` declares a different value

**Severity: LOW**

`quant/decision/timesfm_agents.py:414`
```python
            "sizeFraction": 1.0 if direction != "FLAT" else 0.0,
```
vs `quant/multi_engine.py:858` sets `"sizeFraction": 1.0` for the fabricated POSITION_MANAGEMENT payload, while `timesfm_engine.py:258,293,329,491` set `0.0` for gate-blocked/fallback payloads. `quant/ws_contract.py:97` projects `sizeFraction` from the `WSAgentDecision` dataclass, whose default is `0.0` (`ws_contract.py:48`) — and the projection only happens when `agentDecision` is an `WSAgentDecision` *instance* (`ws_contract.py:82-96`); for dict payloads it passes the raw dict. So the same nominal field can be 0.0 or 1.0 depending on which producer ran last, and the multi_engine override (`:858`) unconditionally forces 1.0 even for a fabricated hold. No consumer branches on it (`grep sizeFraction` → only producers + contract), so it is dead information with a misleading name.

**Real bug vs intentional:** Unintended (dead field with inconsistent producers).

---

## Direct answers to the posed questions

**Q: How many independent quantity/stop/target computations exist?**
Five quantity/stop/target computations (A.0 table), of which **two quantity computations execute for every E2E entry** (scanner `compute_size` + `SessionRisk.position_size`→`compute_size`), and **two target computations** (`_size_entry` vs scanner, mutually exclusive but divergent), plus **two stop-trailing engines** that run after entry (`TimesFMRiskAuthority`, `check_trailing_stop`). Net: 3 independent SL prices can exist for one trade over its life (submitted VaR stop, first-ratchet `p10[0]-tick` trail, portfolio-row `sig.sl`).

**Q: Does dynamicSizing in the scanner override `_size_entry`?**
For stop/target: **yes**, whenever `varStop` and `targetPrice` are non-zero (the normal case). `_size_entry` runs only on the scanner's exception/zero-result path. For quantity: **no** — the scanner's quantity is discarded; the real quantity is computed independently in `SessionRisk.position_size`.

**Q: Can two of them produce conflicting SL/TP for the same entry (one shown in UI, one actually used)?**
**Yes.** (1) Scanner target vs `_size_entry` target use different structural-target preference orders and the scanner alone applies a 20% scale clamp (A.2). (2) The submitted `signal.sl`/`tp` (from whichever of those ran) is overwritten at runtime by `TimesFMRiskAuthority`'s p10/p90 trail, which is `p10_path[0] ∈ p10_path[:5]` — a systematically tighter stop (A.3). (3) The UI reads `stopLoss` from the portfolio row (= `sig.sl`, the original submission) at `multi_engine.py:810/845`, so the UI shows the widest/original stop while the engine enforces the tightened one, and `dynamicTrailStop` falls back to `openPos?.stopLoss` in `AIAdvisorCard.tsx` (line via `rawDecision.dynamicTrailStop || openPos?.stopLoss`) — again the original, not the ratchet.

**Q: Is the stop the ExitEngine later trails the same stop that was submitted?**
**No.** Submitted stop = `min(p10_path[:5]) - tick` (VaR, from `calculate_var_stop`, LONG). Trailed stop = `max(submitted, p10_path[0] - tick)` ratcheted monotonically, i.e. starts at the tighter `p10_path[0] - tick`. They coincide only when `p10_path[0] == min(p10_path[:5])`, i.e. when the first forecast step is the horizon minimum — rare.

**Q: Any hardcoded lot/equity numbers?**
**Yes** — 7 sites enumerated in A.7: equity fallbacks 100000.0 (`timesfm_agents.py:323`) and 200000.0 (`timesfm_client.py:115`); leverage 2.5x/3.0x (`timesfm_sizing.py:232`); deployment 50%, expiry 0.5, thresholds 0.3/0.1, Mon/Fri 0.5 table (`risk.py:18-24, 376-423`); `MAX_POSITION_QUANTITY=1000` (`signal_builder.py:13`); Kelly/risk-ceiling constructor defaults constructed with no config (`risk.py:338-341` → `timesfm_sizing.py:60-65`).

**Q: Every ctx field read via getattr that context_builder never populates?**
None. Every `getattr(ctx, "<attr>")` target is also a declared `DecisionContext` field and is assigned in `context_builder.py:393-478` (`allow_trend`, `allow_reversion`, `bar_index`, `break_direction`, `break_type`, `contested_bubble_zone`, `drive_entry_valid`, `drive_number`, `equity`, `leg_lvn`, `market`, `nearest_buy_print_below`, `nearest_sell_print_above`, `npoc_above`, `npoc_below`, `option_delta`, `poc`, `prior_poc`, `pullback_confirmed`, `setup_evidence`, `squeeze_detected`, `squeeze_direction`, `squeeze_trapped_level`, `stacked_imbalance_*`, `tick_size`, `triple_a_phase`, `triple_a_signal`, `vah`, `val`). The **populated-from-a-dead-fallback** cases are B.1: `leg_lvn` singular read (pyramid) and `option_delta` (Greek branch unreachable) — the fields exist and are set, but the read sites that matter see only fallbacks.

**Q: Fields set in context_builder that nothing reads (dead information)?**
Direct zero-consumer sets: `absorption_cluster_high`, `absorption_cluster_low` (B.3). Effectively dead on the E2E path (only canonical-pipeline consumers): `contested_bubble_zone`, `squeeze_detected`, `squeeze_direction`, `squeeze_trapped_level`, `pullback_confirmed`, `vars_result`, `break_direction`, `break_type`, `drive_entry_valid`, `drive_number`, `balance_ratio`, `profile_shape`, plus `state` (always None). Plus the 9 unread `dynamicSizing` keys (B.7) and `sizeFraction` (B.8).

---

## Severity-ranked summary

| # | Severity | Title | Location |
|---|----------|-------|----------|
| A.3 | HIGH | Submitted stop ≠ trailed stop ≠ displayed stop (three SLs) | `exits.py:156-186`, `timesfm_risk.py:76-99`, `multi_engine.py:810/845`, `state.py:102` |
| A.1 | HIGH | dynamicSizing computed twice/entry; scanner quantity discarded; inputs diverge | `timesfm_agents.py:317-344`, `risk.py:333-365` |
| A.2 | HIGH | Divergent structural-target rules → conflicting TP for same entry | `timesfm_agents.py:271-315` vs `timesfm_strategy.py:238-280` |
| B.1 | HIGH | `legLvn` (singular) & `optionGreekDelta` never produced → pyramid dead, delta fallback | `context_builder.py:155,456-460`, `position_manager.py:521`, `dto.py:88` |
| A.5 | MEDIUM | Forecast-exception silently switches to 50%-deployment sizing; also drops expiry/Mon-Fri cuts | `risk.py:336-392` |
| A.4 | MEDIUM | `_size_entry` effectively dead; doc claims it is authoritative | `timesfm_strategy.py:165-171,221-232` |
| B.3 | MEDIUM | Large set of populated fields unread on E2E path (dead computation) | `context_builder.py:425-477` + `gates_edge.py` |
| B.4 | MEDIUM | `ctx.state` always None; degenerate-VA fallback can fabricate setups | `context_builder.py:394`, `timesfm_agents.py:109-111` |
| B.2 | MEDIUM | Underlying→option translation branch dead (`underlying_gateway=None`) | `multi_engine.py:1682-1685`, `runtime.py:949` |
| A.7 | LOW | Hardcoded equity/lot/leverage numbers (7 sites) | see A.7 |
| B.7 | LOW | 9 `dynamicSizing` keys emitted, never consumed (no UI wiring) | `timesfm_agents.py:330-344` |
| B.5 | LOW | Equity fallbacks disagree (100000 / 200000 / 1000000) | `timesfm_agents.py:323`, `timesfm_client.py:115` |
| B.8 | LOW | `sizeFraction` dead + inconsistent producers | `timesfm_agents.py:414`, `multi_engine.py:858`, `ws_contract.py:48` |
| A.6 | LOW | Sizer does not validate forecast freshness internally | `timesfm_sizing.py:90-100` |
| B.6 | LOW | Scanner `bar=None` guard only partial vs engine direct call | `timesfm_agents.py:105` |
