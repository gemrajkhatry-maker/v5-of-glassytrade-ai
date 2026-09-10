# Pre-Release Readiness Checklist — Decision Integrity

> Run before any paper or live session on `TIMESFM_END_TO_END`.
> Question this answers: **does every model get complete, correct information,
> and does exactly one authority decide, with no competing flow that can
> disagree?**
>
> Branch: `feat/timesfm-paper-e2e-validation` · Baseline: `8f57d171`
> Findings: `docs/reviews/2026-09-10-pre-release-code-audit.md`
> Automated half: `scripts/pre_release_decision_check.py`
>
> Exit code **0** = every FAIL-level check passed. `WARN` rows are known
> residuals (§4.4) and do not fail the run.

```bash
PYTHONPATH=. .venv/bin/python scripts/pre_release_decision_check.py
PYTHONPATH=. .venv/bin/python scripts/pre_release_decision_check.py --skip-suites
PYTHONPATH=. .venv/bin/python scripts/pre_release_decision_check.py --json out/pre_release.json
```

A release is **blocked** if any of these is true:

- script exit code ≠ 0,
- any §5 pre-session observation fails twice on the same session,
- a §4.4 residual is changed without re-running this checklist,
- a §2 BLOCKING defect is neither fixed nor signed off in §6.

---

## 1. Blocking defects (fix or sign off before paper)

| ID | Defect | Severity | Check | Fixed |
|---|---|---|---|---|
| D-2 | Model exit authority silently swallowed (`exits.py:195-197`) — a raising risk authority disables **all** model exits and stop-tightening with no log | BLOCKING | automated | ☐ |
| D-3 | A close path bypasses `_execute_full_close`, so no `exit_source` stamp and no double-close guard (`runtime.py:1402-1411`) | BLOCKING | automated | ☐ |
| D-4 | Absent volume profile fabricates an **approved** VA_FADE entry (`timesfm_agents.py:145-150`) — reproduced | BLOCKING | automated | ☐ |
| D-10 | Shared TimesFM engine can double-feed the model window (data race **and** async-lag ordering) — reproduced | HIGH | automated | ☐ |

Rationale for each in the audit §2–§4. Until these are closed, treat paper
results as non-representative.

---

## 2. Model information completeness

### 2.1 AMT DTO → `DecisionContext` contract

| Consumer | Fields it must receive | Producer |
|---|---|---|
| `DecisionService` (gates 1–4) | `bar`, `session_open`, `warmup_complete`, `position_open`, `cooldown_remaining_sec`, `risk_halted`, `poc/vah/val`, `cvd_slope`, `absorption_side`, `stacked_imbalance_*`, `obi`, `drive_number`, `data_quality`, `market_state` | `DecisionContextBuilder.build()` ← AMT DTO |
| `TimesFMScanningAgent` | above + `session_phase`, `allow_trend/reversion`, `equity`, `npoc_above/below`, `prior_poc` | same |
| `TimesFMPositionAgent` (advisory) | `position_*` set, `position_bars_held`, `position_sl/tp`, `cvd_slope`, `absorption_side` | `DecisionContextBuilder._extract_position()` |
| `TimesFMRiskAuthority` (real exits) | `TimesFMForecast.p10_path/p90_path/p50_path`, `asof_bar` | `TimesFMTradingStrategy.get_latest_forecast()` |
| `TimesFMPositionSizer` | `forecast`, `equity`, structural targets | `DecisionContext` + scanner payload |

Automated:

- [ ] `[PASS] every DecisionContext field has an AMT DTO producer`
- [ ] `[PASS] DEAD market maps to MarketState enum`
- [ ] `[PASS] shared engine records a bar exactly once` *(sequential case only — see D-10)*
- [ ] `[PASS] absent volume profile cannot fabricate a setup` — **new, closes D-4**
- [ ] `[PASS] pyramid leg LVN key matches the AMT DTO` — **new, closes D-5**

Manual, first paper session, one bar:

- [ ] AMT DTO carries `poc`, `valueAreaHigh`, `valueAreaLow`, `cvdSlope`, `absorptionSide`, `marketState`, `dataQuality` — log the first DTO and read it.
- [ ] `valueAreaHigh > valueAreaLow > 0`. If either is zero, the profile is empty → the scanner must emit `FLAT` (D-4).
- [ ] `absorptionSide` arrives in `_ABSORBED` form, not bare `BUY`/`SELL`.
- [ ] forecast payload logs `source=TIMESFM_3.0_NATIVE` on a healthy session, never `TIMESFM_FALLBACK`.
- [ ] `ctx.equity` equals the paper account equity (not `0.0`, not `100000.0`, not `1000000.0`).
- [ ] **D-5:** `GET`/log the AMT DTO and confirm whether `legLvn` exists. It currently does **not**; pyramids are therefore inert. Confirm the intended state before assuming add-ons can fire.

### 2.2 Forecast contract (shared by 4 consumers)

`TimesFMForecast` is the spine: scanner, position agent, risk authority and sizer
all read it. Any field change must be re-checked here.

- [ ] `p50_path`, `p10_path`, `p90_path`, `q_spread`, `mean_forecast`, `pct_change`, `forecast_steps`, `curr_price`, `lat_ms`, `asof_bar` all set on every forecast that reaches a consumer.
- [ ] `asof_bar` stamped with the bar that produced it; a forecast older than 1 bar is dropped (`[STALE FORECAST]`) before `ExitEngine`.
- [ ] Inference failure yields **no** forecast (`MODEL_UNAVAILABLE`), never a synthetic flat forecast cached for exits.
- [ ] **D-18/D-19:** the quantile index contract (`4`=p50, `0`=p10, `8`=p90) is currently asserted by comment in four builders and checked nowhere. Confirm the model still returns 9 quantiles before relying on the E2E path.

### 2.3 Stop-price consistency

- [ ] **D-7:** for one open position, confirm the number shown as `stopLoss` in the UI equals the stop `ExitEngine` is enforcing. They differ today (submitted `min(p10[:5])-tick` vs enforced ratchet `p10[0]-tick`). Log both and compare on the first trade.

---

## 3. Decision processing correctness

### 3.1 Entry

- [ ] Exactly one entry seam: `strategy.should_enter(ctx)`; the runtime never calls `DecisionService.evaluate()` directly. *(automated: PASS)*
- [ ] In `TIMESFM_END_TO_END` the TimesFM scanner decision is followed through; the canonical AMT `GatePipeline` is not consulted for E2E approval. *(automated: PASS)*
- [ ] Gates 1–2 are hard rejects for the deterministic `DecisionService` path.
- [ ] **Verified:** the E2E strategy **does** honour `session_open`, `warmup_complete`, `OPENING`/`PRE_OPEN`/`CLOSE`/`POST_MARKET` phases. No bypass. (Re-run `scripts/audit_e2e_entry_probe.py` after any strategy change.)
- [ ] Momentum entries (`MODEL_MOMENTUM`) enter on the model's decision without a canonical AMT setup. *(automated: PASS)*
- [ ] `DATA_QUALITY_BLOCKED` fires for inferred/proxy provenance at conviction `0.65` on the **deterministic** path; the E2E model path is not gated on provenance.

### 3.2 Exit

- [ ] Real exits come only from `ExitEngine.evaluate()` → `TimesFMRiskAuthority` (or deterministic rules), and every close stamps a source: `TIMESFM_RISK_AUTHORITY:<reason>` or `DETERMINISTIC:<reason>`. *(automated: PASS)*
- [ ] **D-2:** force a failure inside `TimesFMRiskAuthority.evaluate_exit` (e.g. pass a forecast with an empty `p10_path`) and confirm it is **logged**, not silently swallowed. Today it is not.
- [ ] **D-3:** confirm every close emits `[POSITION CLOSED] ... exit_source=`. The pyramid-only path at `runtime.py:1402` does not.
- [ ] `TimesFMPositionAgent` EXIT is advisory/UI only; it must never be assumed to have closed the position. *(verified: no code path acts on its `EXIT`/`TIGHTEN_SL`)*
- [ ] **D-13:** on a bar that pierces both the raw SL and the trail, confirm the booked `exit_source` is not `SL` at the worse price while the tick path would book `TRAIL`.
- [ ] Session-close / EOD force close reports `DETERMINISTIC:SESSION_CLOSE` (or the EOD reason), never a stale source.

### 3.3 Sizing

- [ ] One sizing authority: `SessionRisk.position_size()` + `clamp_quantity()`. The strategy's `TimesFMPositionSizer` only qualifies the entry.
- [ ] `equity` fed to sizing is the account equity, not a literal. *(D-9: two sites hard-code `100000.0`/`200000.0` while `INITIAL_CAPITAL` is `1000000`.)*
- [ ] **D-12:** confirm what happens to order size if the TimesFM sizing call raises. Today it silently falls through to a 50%-of-equity deployment that ignores the rupee cap.
- [ ] **D-12:** confirm expiry-day halving and the Mon/Fri defensive multiplier. Today both are applied only on the static branches, so they do **not** apply when a fresh forecast is present (the E2E path).

---

## 4. Conflicting-flow audit

### 4.1 Authority registry (must stay exclusive)

| Decision | Sole authority | Must NOT also run |
|---|---|---|
| Entry approve/reject (E2E) | `strategy.should_enter` (TimesFM scanner decision) | canonical `GatePipeline` override |
| Entry approve/reject (deterministic) | `DecisionService` → `GatePipeline` | shadow gate booleans, second decision service |
| Gate truth shown in UI | scanner model gate results | a second, competing decision service |
| Real exit | `ExitEngine` → `TimesFMRiskAuthority` | advisory `PositionAgent` (UI) |
| Sizing | `SessionRisk` + `clamp_quantity` | strategy-local quantity math |
| Market state | `MarketState` enum | raw `"DEAD"` string |
| Absorption semantics | `SELL_ABSORBED=LONG`, `BUY_ABSORBED=SHORT` | bare `BUY`/`SELL` compares |
| Trailing stop | `ExitEngine._trail` | a second independent trail store |

Automated checks (all must pass):

- [ ] `[PASS] single entry seam`
- [ ] `[PASS] model entry decision is authoritative (no canonical override)`
- [ ] `[PASS] no bare absorption string compares`
- [ ] `[PASS] forecast cached only after success + freshness stamped`
- [ ] `[PASS] one sizing authority`
- [ ] `[PASS] every full close routes through the single release path` — **new, closes D-3**
- [ ] `[PASS] model-risk failure is observable, not swallowed` — **new, closes D-2**
- [ ] `[PASS] shared engine dedup survives concurrency` — **new, closes D-10**

### 4.2 Fixed on this branch (regression-locked)

| ID | Conflict | Fix | Test |
|---|---|---|---|
| C1 | Native advisor + E2E strategy shared one engine and both appended the same bar → duplicated model input | `add_context` idempotent per stamped `bar_index` | `test_add_context_is_idempotent_within_a_stamped_bar`, `test_shared_engine_advisor_plus_strategy_records_bar_once` |
| C2 | Rule-based fallback compared bare `"BUY"`/`"SELL"` (dead + inverted) | substring match with canonical direction | `test_timesfm_engine_fallback_mode_*` |
| C3 | Thesis-flip / EOD / tick-TP closes logged a stale or empty `exit_source` | central stamp in `_execute_full_close` | `test_exit_source.py` |
| C4 | Two stale runtime gate-1 tests assumed one decision per bar | assert the warmup transition instead of a fixed index | `test_runtime.py` |

> **C1 is incomplete.** It locks the *sequential* double-feed only. D-10
> reproduces two concurrent/ordering double-feeds that C1 does not catch.

### 4.3 Open conflicting flows

| ID | Conflict | Where | Automated |
|---|---|---|---|
| D-3 | Pyramid-only close bypasses the single release path | `runtime.py:1402-1411` | yes |
| D-13 | Bar path books `SL` at the raw SL; tick path books `TRAIL` at the trail | `exit_checks.py:26` vs `position_manager.py:334` | manual |
| D-15 | `_closed_ids` double-close guard resets every call | `position_manager.py:144` | manual |
| D-16 | Two trailing-stop stores, never reconciled | `exits.py:183` vs `exit_checks.py:148` | manual |
| D-17 | `LLM_ADVISOR_ENABLED=false` hard-disables in one module, OR-enables in another | `wiring_advisor.py:67` vs `composition_root.py:163` | yes |
| D-14 | Coupled/underlying execution flow is dead by construction | `multi_engine.py:1682` | manual |

### 4.4 Known residuals (WARN — do not silently ignore)

| ID | Residual | Impact | Disposition |
|---|---|---|---|
| R1 | Native advisor / AMT panel can show a different view than the TimesFM model decision, since the model is the entry authority in E2E | Operator may read the AMT/Quant panel as a veto when it is informational | By design. The `DecisionProduced` card and `[SIGNAL EXECUTED]` / `[POSITION CLOSED]` logs are the truth. |
| R2 | Two forecast inferences per bar (advisor engine + strategy) | latency/cost, and the two payloads can differ (D-11) | Resolved by Task 12b — one inference per bar; the advisor and the strategy share the engine's forecast for the current `bar_index`. |
| R3 | The deterministic-only `DecisionContext` fields (`contested_bubble_zone`, `squeeze_*`, `pullback_confirmed`, `drive_*`, `vars_result`, `absorption_cluster_*`, `break_*`) are computed on every bar but read only by the `GatePipeline`, which E2E does not run | wasted per-bar computation; misleading to readers | Accepted for now; strip when the deterministic strategy is retired. |
| R4 | `ctx.state` is always `None`, so `ctx.state.poc` fallbacks are unreachable | the effective fallback is `curr_price` (D-4 root cause) | Being fixed under D-4. |

---

## 5. Pre-session operator observations (paper/live)

Run these on the **first session** of the release and tick each.

- [ ] `GET /health` → `status: "ok"`, TimesFM model loaded, contracts monitored.
- [ ] First `amt_dto` after bar 15: `poc`/`valueAreaHigh`/`valueAreaLow` non-zero.
- [ ] `cvdSlope` non-zero once order flow is present.
- [ ] `absorptionSide` ∈ {`BUY_ABSORBED`, `SELL_ABSORBED`, `""`} — never bare.
- [ ] Env confirms the intended path: `TIMESFM_END_TO_END`, `TIMESFM_ADVISOR_ENABLED`, `TIMESFM_NATIVE`, `LLM_ADVISOR_ENABLED`, `QUANT_EXECUTION_MODE`, `TRADING_MODE`.
- [ ] **D-10:** grep the session log for the model input line and confirm no bar price appears twice in the window.
- [ ] Every approved entry has a matching `TIMESFM APPROVAL ... Model: TimesFM-<setup>` line.
- [ ] Every approved entry has `valueAreaHigh > valueAreaLow > 0` on the same bar (D-4 guard).
- [ ] Every close has `exit_source=` populated and matching the close reason.
- [ ] No trade is opened without an approved `DecisionProduced` on the same bar.
- [ ] No trade is opened while the last decision reason is `DATA_QUALITY_BLOCKED`.
- [ ] After session end, run the §6 acceptance gate over the day's journals.

---

## 6. Sign-off

| Gate | Command / evidence | Result | Date | By |
|---|---|---|---|---|
| Code-level audit | `docs/reviews/2026-09-10-pre-release-code-audit.md` | 3 blocking, 10 high, 12 med/low | 2026-09-10 | agent |
| Entry-gate probe | `scripts/audit_e2e_entry_probe.py` | no bypass (hypothesis disproven) | 2026-09-10 | agent |
| Engine double-feed probe | `scripts/audit_engine_race_probe.py` | **2 double-feeds reproduced (D-10)** | 2026-09-10 | agent |
| Static + behaviour probes | `scripts/pre_release_decision_check.py --skip-suites` | ☐ | | |
| Decision + strategy + exit + runtime suites | `pytest tests/quant/decision tests/quant/strategies tests/quant/execution/test_exit_source.py tests/quant/runtime/test_runtime.py` | ☐ | | |
| Broader affected suites | `pytest tests/quant/decision tests/quant/execution tests/quant/strategies` | ☐ | | |
| Pre-session observations (§5) | paper session log | ☐ | | |
| Acceptance gate | `backend/scripts/acceptance_gate.py` | ☐ | | |

### Blocking sign-off

D-2, D-3, D-4, D-10 each need **either** a merged fix **or** this line completed:

```
I accept <ID> for this paper session because <reason>.
Risk if it fires: <consequence>.  Monitor: <signal>.  Owner: <name>.
```

No blocking defect may be left both unfixed and unsigned.
