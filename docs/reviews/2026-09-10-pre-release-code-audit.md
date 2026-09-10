# Pre-Release Code-Level Audit — Decision Integrity

> Scope: the `TIMESFM_END_TO_END` paper path on
> `feat/timesfm-paper-e2e-validation`.
> Four questions, answered from code and reproduced where possible:
> **(1)** does every model get all the information correctly, **(2)** does it
> process every decision correctly, **(3)** are there conflicting flows that can
> corrupt the logic, **(4)** what duplication / dead code / smells exist.
>
> Baseline: `8f57d171` (2026-09-10). Companion checklist:
> `docs/PRE_RELEASE_READINESS_CHECKLIST.md`.
> Reproduction probes: `scripts/audit_e2e_entry_probe.py`,
> `scripts/audit_engine_race_probe.py`.

Every finding below was read in the source and, where marked **reproduced**, was
executed. Claims I could not confirm are listed in §5 so they are not mistaken
for verified defects.

---

## 1. Verdict

| Axis | State |
|---|---|
| Information completeness | **1 blocking defect** (absent volume profile fabricates an approved entry) + 2 dead information channels |
| Decision processing | **1 blocking defect** (model exit authority silently disabled on error) + a genuine double-feed race |
| Conflicting flows | **1 blocking defect** (a close path bypasses the single release path) + 3 real dual-authority conflicts |
| Duplication / dead code / smells | Substantial, none individually blocking; the 3-4× duplicated forecast builder is the highest risk |

Blocking defects: **D-1** (VA fabrication), **D-2** (model exit swallow),
**D-3** (close path bypass). Do not go live with paper trades you intend to rely
on until these are fixed or explicitly accepted in writing.

Two prior hypotheses were tested and **disproven** — see §5. They are recorded so
they are not re-investigated.

---

## 2. Information completeness — does every model get all information?

### D-4 · HIGH · Absent volume profile fabricates an APPROVED entry
`quant/decision/timesfm_agents.py:145-150`, `:196-217`

The scanner resolves value-area levels from `ctx` with a `curr_price` fallback:

```python
poc = float(ctx.poc or (ctx.state.poc if ctx.state else curr_price))
vah = float(ctx.vah or (ctx.state.vah if ctx.state else curr_price))
val = float(ctx.val or (ctx.state.val if ctx.state else curr_price))
...
va_range = max(vah - val, curr_price * 0.001)
tol = va_range * 0.15
```

`ctx.state` is **always `None`** (`context_builder.py:394` sets `state=None`), so
the effective fallback is `curr_price`. When the AMT profile has not populated
(the `DEGRADED_EMPTY` seed status, `quant/amt_engine.py:252,285`), `vah` and
`val` both collapse to `curr_price`, and the VA-fade conditions
`curr_price <= val` / `curr_price >= vah` become trivially evaluable against a
boundary that price always satisfies.

Reproduced end-to-end (`scripts/audit_e2e_entry_probe.py`-style probe):

```
empty DTO -> poc=0.00 vah=0.00 val=0.00 close=100.00
scanner with empty VA -> setup=VA_FADE direction=LONG action=ENTER_LONG
strategy.should_enter -> approved=True reason=VA_FADE
                         signal LONG entry=100.00 sl=99.45 tp=101.50 rr=2.73
                         => WOULD SUBMIT ORDER FROM AN ABSENT VOLUME PROFILE
```

The deterministic path does **not** have this hole — the same context returns
`approved=False reason=NO_EDGE` through `AmtScalpingStrategy`. This is a
behavioural divergence between the two strategies on the same input, and it is
on the E2E path this branch exists to validate.

**Fix:** treat `vah <= 0 or val <= 0 or vah <= val` as "no profile" and return
`FLAT` before any setup branch, mirroring `DecisionService`'s handling.

### D-5 · HIGH · `legLvn` (singular) is never produced → pyramid engine is dead
`quant/position_manager.py:521`, `quant/amt/dto.py:88`

```python
# position_manager.py:521
leg_lvn = float(amt_dto.get("legLvn") or 0.0)
if leg_lvn <= 0:
    return  # No Layer 3 LVN available yet
```

The DTO emits **`legLvns`** (plural, a list, `dto.py:88`). `"legLvn"` is never
assigned anywhere in `quant/` or `backend/app`:

```
grep '\["legLvn"\]\s*=\|"legLvn":' quant backend/app  ->  (no matches)
```

Verified at runtime: `amt_result_to_dto()` contains `legLvns` and does not
contain `legLvn`. So `check_pyramid` returns on every bar in production, and the
pyramid add-on engine never runs. Tests pass because they inject
`{"legLvn": ...}` directly. (`context_builder._nearest_leg_lvn` gets this right
via the plural key, so `ctx.leg_lvn` is populated — only the pyramid read is
broken.)

**Fix:** read `legLvns[0]` (or emit the singular key) in `position_manager`.

### D-6 · MEDIUM · `optionGreekDelta` is never produced → delta always a flat 0.50
`quant/decision/context_builder.py:456-460`

> **Corrected 2026-09-10 during execution:** there is no chain-Greek producer
> available to wire. `AMTResult` (`quant/contracts/value_objects.py`) has no
> `option_greek_delta` field, so `optionGreekDelta` can never be emitted from
> `amt_result_to_dto` (an `getattr(r, "option_greek_delta", None)` emit would
> always be `None`, a no-op). And `deltaNormalizedOption` is candle
> *order-flow* delta, not a Greek, and a test exists to keep it out of the
> Greek path. The unreachable `amt_dto["optionGreekDelta"]` branch was
> therefore **removed**, not faked, in favour of a single named constant
> (`DEFAULT_OPTION_DELTA = 0.50`) that documents itself as the authoritative
> default until a real option chain is wired.

```python
option_delta=(
    float(amt_dto["optionGreekDelta"])
    if amt_dto.get("optionGreekDelta") is not None
    else (0.50 if is_option_contract(symbol) else None)
),
```

`grep optionGreekDelta` returns only these reader lines; no producer exists.
`ctx.option_delta` therefore always takes the fallback. Today the blast radius is
small because the consumer (`OptionSelector.translate_underlying_signal_to_option`)
is itself on a dead branch — see D-14 — but a 0.50 delta for an OTM strike
materially wrong-scales any premium stop if that path is ever enabled.

### D-7 · MEDIUM · Three different stop prices for one trade; the enforced one is not displayed
`quant/execution/exits.py:160-186`, `quant/decision/timesfm_risk.py:76-99`,
`quant/multi_engine.py:810,845`

| Stop | Value (LONG) | Where |
|---|---|---|
| Submitted to OMS | `min(p10_path[:5]) - tick` | `timesfm_sizing.calculate_var_stop` |
| Actually enforced after bar 1 | ratchet of `p10_path[0] - tick` | `TimesFMRiskAuthority.update_trailing_stop` |
| Shown in UI / portfolio row | the submitted `sig.sl` | `multi_engine` reads `open_p["stopLoss"]` |

Since `p10_path[0] >= min(p10_path[:5])`, the enforced stop is systematically
**tighter** than the submitted one, and the UI shows the looser submitted value.
The ratchet is monotonic upward, so there is no path back to the wider stop.
An operator cannot reconcile the displayed stop with the enforced stop.

### D-8 · MEDIUM · `dynamicSizing`: computed twice, quantity discarded, 9 of 12 keys unread
`quant/decision/timesfm_agents.py:317-344`, `quant/strategies/timesfm_strategy.py:163-171`,
`quant/execution/risk.py:333-365`

`TimesFMPositionSizer.compute_size` runs once per scanner evaluation (every bar,
including rejected ones) with `equity = ctx.equity or 100000.0` and **no**
`lot_size`/`max_lots`. A second, independent `compute_size` then runs inside
`SessionRisk.position_size` with the real `lot_size`, `max_lots` and rupee cap —
and only its quantity is submitted. The scanner's `quantity`/`lots` are never
read (only `varStop`, `targetPrice`, `payoffRatio` are). Because the scanner call
omits `lot_size`, it takes the fractional-quantity branch and can disagree with
the submitted size by an order of magnitude.

### D-9 · LOW · Equity fallbacks disagree three ways
`quant/decision/timesfm_agents.py:323` (`100000.0`),
`quant/decision/timesfm_client.py:115` (`200000.0`),
`quant/contracts/aggregates.py:28` (`INITIAL_CAPITAL = 1_000_000`). Every other
module imports `INITIAL_CAPITAL`; these two hard-code different literals.

---

## 3. Decision processing correctness

### D-2 · BLOCKING · The entire model exit authority is silently swallowed
`quant/execution/exits.py:160-197`

```python
if timesfm_forecast is not None:
    try:
        ...
        eval_res = self._timesfm_risk.evaluate_exit(...)
        ...
        if eval_res.should_exit:
            self.last_exit_source = f"TIMESFM_RISK_AUTHORITY:{...}"
            return ExitDecision(True, eval_res.reason, close, trail_stop=eval_res.new_stop)
    except Exception as exc:
        # Graceful fallback to deterministic exit rules on error
        pass
```

A ~35-line block — dynamic VaR stop, trajectory-inflection take-profit,
velocity-decay exit, and the monotonic quantile **stop ratchet** — is wrapped in
a swallow with no log and an unused `exc`. Any exception disables every
model-driven exit *and* stop-tightening for that bar, silently, with the
position continuing on weaker deterministic stops. A degraded session is
indistinguishable from a healthy one.

**Fix:** log at `warning` with `exc_info=True` and increment a counter surfaced
in `/health`. Do not let a failing risk authority fail silently.

### D-10 · HIGH · The shared TimesFM engine can still double-feed (race + ordering)
`quant/decision/timesfm_engine.py:186-201`

In `TIMESFM_END_TO_END` the advisor worker thread and the strategy's engine
thread share **one** `TimesFMEngine` (constructed at `runtime.py:335-336`). The
per-bar dedup is check-then-act with no lock:

```python
if bar_index >= 0 and self._last_context_bar.get(symbol) == bar_index:
    return self._context_window(buf)
buf.append(price)
self._last_context_bar[symbol] = bar_index
```

**Reproduced, two ways** (`scripts/audit_engine_race_probe.py`):

```
A. two threads on the same bar (forced interleave)
   expected buffer depth: 1
   actual   buffer depth: 2   contents [100.5, 100.5]
   => DOUBLE-FEED

B. advisor lagging its queue (async), 3 bars delivered by both consumers
   buffer = [100.0, 101.0, 102.0, 100.0, 101.0, 102.0]
   => DOUBLE-FEED (length 6 for 3 bars)
```

Case A is a genuine data race; case B is deterministic and needs no timing luck
(violates the "shared engine records a bar exactly once" checklist item). This is
the same class of defect as regression-lock C1 in the existing checklist, which
only covers the *sequential* case.

Related: `model.predict` is called from multiple threads
(`timesfm_engine.py:347`, `timesfm_strategy.py:311`, `multi_engine.py:1453`,
`scanner.py:463`) against the shared singleton, with no lock held during
inference (`_TIMESFM_LOCK` only guards model *loading*).

**Fix:** guard `add_context`/buffer access with a lock, and drop any bar whose
`bar_index` is not strictly greater than the last recorded one.

### D-11 · HIGH · Two full inferences per bar (advisory + strategy)
`quant/decision/timesfm_engine.py:340-347`, `quant/strategies/timesfm_strategy.py:301-311`

The advisor engine and the strategy each run `model.predict` for the same bar,
and the two results can differ. This is latent residual R2 in the existing
checklist; combined with D-10 it is the mechanism by which the two consumers
diverge. Correctness-neutral only while the strategy's forecast is the sole
decision input.

### D-12 · MEDIUM · Sizing policy silently switches on a forecasting exception
`quant/execution/risk.py:333-392`

If the TimesFM sizing call raises, the code falls through (`warning` only) to a
**structurally different** policy: a flat 50%-of-equity deployment that ignores
`max_rupee_risk_cap` and is not risk-equivalent to the Kelly path. One failed
inference can size an order orders of magnitude larger.

The forecast branch also **ignores `is_expiry` and `DAY_OF_WEEK_MULTIPLIER`**,
which apply only to the static branches (`risk.py:377,423`). On the E2E path
(forecast always present when fresh) expiry-day halving and the Mon/Fri
defensive cut never apply.

---

## 4. Conflicting flows — can two authorities disagree?

### D-3 · BLOCKING · A close path bypasses the single release path and stamps no `exit_source`
`quant/runtime.py:1402-1411`

```python
else:
    # Base already gone but pyramid add-ons linger
    for pyr_pos in list(pm.pyramid_positions):
        pyr_fill = pm._oms.close(pyr_pos, price, ts, reason + "_PYRAMID")
        ...
```

This calls `_oms.close` directly instead of `_execute_full_close`, so it skips:
the central `DETERMINISTIC:<reason>` stamp (`position_manager.py:267-269`), the
`[POSITION CLOSED] ... exit_source=` log, the `_closed_ids` guard, and the
id-validity check. It contradicts the module's own stated invariant that
`_execute_full_close` is "the ONLY full-close release path" (`runtime.py:1321-1329`).
Reachable from `multi_engine.eod_square_off` and `emergency_halt`.

### D-13 · HIGH · Bar path and tick path disagree on the stop price for the same breach
`quant/execution/exit_checks.py:26-32` vs `quant/position_manager.py:334-338`

The bar path checks the **raw frozen SL** (`position.order.signal.sl`) and books
`SL` at `sl`. The tick path first merges `trail_stop`/`be_floor` into
`effective_sl` and books `TRAIL`/`BREAKEVEN`. Rule 2 runs before Rule 4b
(`exits.py:200` before `:227`), so a bar that pierces both the raw SL and the
trail books `SL` at the worse price, while the identical tick breach books
`TRAIL` at the trail. Same economic event, two exit prices and two
`exit_source` values depending on which feed arrives first.

### D-15 · MEDIUM · The double-close guard resets on every call
`quant/position_manager.py:144-145`

```python
# Double-close guard: position _ids that have already been fully closed.
self._closed_ids: set[str] = set()
```

Rebuilt at the top of `manage_exit`, so it cannot block a re-close across calls,
contradicting its own docstring (`:242`). The repo's own chaos suite documents
this (`tests/quant/chaos/test_crash_recovery.py:556-621`,
`test_manage_exit_resets_closed_ids`). It is also not consulted by the D-3 loop.

### D-16 · MEDIUM · Two trailing-stop stores, never reconciled
`quant/execution/exits.py:183-188` and `quant/execution/exit_checks.py:148-151`

`ExitEngine._trail` (written by the TimesFM ratchet) and
`TimesFMRiskAuthority._trail_stops` are parallel stores for one position. They
agree today only because both re-cap against the active SL so neither can loosen;
`timesfm_risk.py`'s docstring claims it *replaces* the deterministic 0.8R/20%
rules, but the code stacks both. A future change to either ratchet yields a
first-writer-wins stop for the same bar.

### D-17 · HIGH · `LLM_ADVISOR_ENABLED=false` does not do what it says
`quant/wiring_advisor.py:67-72` vs `backend/app/application/di/composition_root.py:163-164`

`composition_root` treats the flag as one arm of an OR-enable; `wiring_advisor`
treats it as a hard disable that short-circuits before TimesFM is considered:

```python
"advisor_enabled": (
    os.getenv("LLM_ADVISOR_ENABLED", "false")... in ("true","1","yes")
    or os.getenv("TIMESFM_ADVISOR_ENABLED", "false")... in ("true","1","yes")
),
```

With `LLM_ADVISOR_ENABLED=false` and `TIMESFM_ADVISOR_ENABLED=true` the
coordinator records `advisor_enabled=True` while `build_live_advisor()` returns
`None` — the two subsystems disagree about whether an advisor exists. (In the
current `.env` both are `true`, so this is latent, but it is a live footgun.)

### D-14 · LOW · Dead coupled-execution flow
`quant/multi_engine.py:1682-1685` hard-codes `underlying_gateway = None` with an
explicit comment, yet `quant/runtime.py` carries 17 references to it, including
the entire option-premium translation block (`:949-978`), the option AMT engine,
the merged-AMT option-scale merge (`_OPTION_SCALE_KEYS`) and the micro
aggregators. None of it can execute in the coordinator. Intentional per the
comment, but it is a large untested surface and a maintenance trap.

---

## 5. Claims tested and DISPROVEN

Recorded so they are not re-investigated.

1. **"The E2E strategy bypasses session/warmup/opening gates."** **False.**
   Probe: with a strongly bullish stubbed forecast, `should_enter` correctly
   blocks on `session_open=False`, `warmup_complete=False`, and
   `session_phase` in `OPENING`/`PRE_OPEN`/`CLOSE`/`POST_MARKET`. The scanner's
   gate 1 (`timesfm_agents.py:256`) is enforced because `all_gates_passed` is
   required. No bypass.

2. **"`timesfm_agents.py` contradicts `context_builder.py` on absorption sign."**
   **False.** `BUY_ABSORBED` is bearish in both: the scanner's
   `side == "LONG" and absorption in ("BUY","BUY_ABSORBED")` correctly flags an
   opposing condition for a long. The real finding at that site is duplication
   (D-20), not inversion.

3. **"`ctx.state.poc` fallbacks are reachable."** **Partially false.** `state` is
   always `None`, so the fallback is `curr_price`, not the state's POC. The
   hazard is therefore the `curr_price` collapse (D-4), not a stale state read.

---

## 6. Duplication, dead code, smells

### Highest-risk duplication

- **D-18 · HIGH · The TimesFM forecast builder exists 3-4 times.** The block
  slicing `quantiles[:, 4] / [:, 0] / [:, 8]`, computing `q_spread` and building
  `forecast_steps` is repeated at `multi_engine.py:1456-1481`,
  `amt/session/scanner.py:466-495`, `strategies/timesfm_strategy.py:313-341`, and
  consumed again at `decision/timesfm_engine.py:362-365`. The quantile index
  contract (`4`=p50, `0`=p10, `8`=p90) is asserted by comment in four places and
  checked nowhere. The fallback constants already disagree (`*0.998/1.002` vs
  `± curr_price*0.002`).
- **D-19 · HIGH · `TimesFMForecast(...)` built at 5 sites with divergent
  `forecast_steps` semantics.** `multi_engine.py:1477` and `scanner.py:487` emit
  binary `LONG`/`SHORT` and **never** `FLAT`; `timesfm_strategy.py:328` emits a
  ternary including `FLAT`; `timesfm_engine.py:373-380` uses VAH/VAL bands;
  `timesfm_strategy.py:296` compares against `p50_path[0]` instead of
  `curr_price`. Consumers in `timesfm_agents.py:229-231` and `risk.py:345` count
  by label and assume `FLAT` is possible.
- **D-20 · MEDIUM · Absorption-direction mapping written 5 ways**
  (`context_builder.py:121`, `:218`, `timesfm_engine.py:434`,
  `position_manager.py:538`, `timesfm_agents.py:501`). Semantics agree (see §5)
  but the sign convention is re-derived each time.
- **D-21 · MEDIUM · Option `CALL/CE`/`PUT/PE` detection written 4 ways**
  (`selector.py:478`, `runtime.py:1276`, `_dhan_common.py:66`,
  `amt/analyzer.py:350`). The analyzer variant is **not** gated on
  `is_option_contract` and uses a different regex.
- **D-22 · MEDIUM · Session-phase substring checks written 6 times**, and already
  inconsistent within one file: `timesfm_agents.py:74` omits `"PRE_MARKET"` while
  `:59` and `:254` include it.
- **D-23 · MEDIUM · Env-var drift.** `SCANNER_TOP_N` has three defaults
  (`4`/`4`/`8`) across two authorities; `SCANNER_UNDERLYINGS`,
  `SCANNER_EXPIRY_INDEX`, `STRIKES_AROUND_ATM`, `SCANNER_OPTION_TYPE` and
  `TIMESFM_SERVICE_URL` are each read twice from independent parsers. The
  `TIMESFM_CONTRACT_SELECTION or TIMESFM_ADVISOR_ENABLED` enable-latch is copied
  verbatim in three modules.

### Dead code (each verified: no non-test caller)

- `quant/execution/exit_rules.py:111` `update_peak_profit`, `:234` `is_valid_rr` — zero callers anywhere.
- `quant/execution/exit_rules.py:84` `update_excursions` — tests only; MAE/MFE tracking is not wired into the exit path.
- `quant/amt/session/selector.py:319,339` `compute_lot_size` / `compute_option_lot_size` — tests only; production sizing does not use them.
- `quant/runtime.py:1525` `_check_pyramid` — tests only; pyramids are driven from `manage_exit:232`.
- `quant/decision/timesfm_client.py` (`TimesFMClient`, `TimesFMSnapshotBuffer`, `context_to_snapshot`) — unreachable when `TIMESFM_NATIVE=true` (the default), which is the only production setting.
- `quant/runtime.py:133` `_DETERMINISTIC_CONVICTION` and `:138` `_WARMUP_BARS` — defined, never used. (`_WARMUP_BARS` is a duplicate of `context_builder`'s `warmup_bars = 15`.)
- `quant/strategy.py` `TradingStrategy` Protocol — neither implementation inherits it and nothing checks it.
- `quantv2/` — 62 files, 100% `.pyc`, no `.py`, no importers, untracked.
- `quant/decision/timesfm_sizing.py:232` leverage constants `2.5x`/`3.0x`, `signal_builder.py:13` `MAX_POSITION_QUANTITY=1000`, Kelly/risk-ceiling constructor defaults — hard-coded, not config.

### Smells

- **D-24 · HIGH · 47 bare `except Exception: pass` blocks** across `quant/` and
  `backend/app/` (machine-counted). Live-path examples:
  `decision/context_builder.py:347,351` (session-info resolution feeding
  `session_phase`), `execution/live_oms.py:139,223,447` (order/audit state),
  `runtime.py:565,571,587` (engine init). `quant/execution/exits.py:195` is the
  worst (D-2).
- **D-25 · MEDIUM · 31 functions > 120 lines**, largest `amt/analyzer.py:389`
  `analyze` at 477 lines; live-decision monoliths at
  `decision/timesfm_agents.py:93` (324), `runtime.py:861` `_decide` (318).
- **D-26 · HIGH · 235 generated graphify files committed** in
  `backend/graphify-out/` (~10 MB), while root and `quant/` counterparts are
  correctly gitignored. Generated tool output tracked as source.
- **D-27 · LOW · Tracked throwaway clutter**: `scratch/` (4),
  `.freebuff/` (17), `runtime_audit/` (13), `.kilo/`, `.commandcode/`,
  `amt_dataset/` (6 datasets). Plus untracked leftovers `quantv2/`, empty
  `poc_temp/`, empty `live_trading_logs/`.
- **D-28 · MEDIUM · Unnamed duplicate literals on the hot path**: `0.998`/`1.002`
  (5 sites), `0.65` vs the existing `CONFIDENCE_HIGH_THRESHOLD`
  (`contracts/constants.py:182`, 3 sites), `3.0 * tick` (4 sites), `horizon=32`
  hard-coded in all four forecast builders, `1.4` used for two unrelated concepts.

---

## 7. Release gate

Machine-checkable checks for D-2, D-3, D-4, D-5 and D-10 have been added to
`scripts/pre_release_decision_check.py`, so these cannot silently regress. Run:

```bash
PYTHONPATH=. .venv/bin/python scripts/pre_release_decision_check.py
```

Then work through `docs/PRE_RELEASE_READINESS_CHECKLIST.md`.
