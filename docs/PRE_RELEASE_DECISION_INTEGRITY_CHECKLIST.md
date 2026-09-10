# Pre-Release Decision-Integrity Checklist

> Scope: before any paper or live release on `TIMESFM_END_TO_END`.
> Question this answers: **does every model get complete, correct information —
> and does exactly one authority decide, with no competing flow that can
> disagree?**
>
> Branch: `feat/timesfm-paper-e2e-validation` · Baseline: `725a330b` (2026-09-10)
> Automated half: `scripts/pre_release_decision_check.py`

---

## 0. How to run

```bash
PYTHONPATH=. .venv/bin/python scripts/pre_release_decision_check.py
# static + behaviour probes only (no pytest):
PYTHONPATH=. .venv/bin/python scripts/pre_release_decision_check.py --skip-suites
# machine-readable:
PYTHONPATH=. .venv/bin/python scripts/pre_release_decision_check.py --json out/pre_release.json
```

Exit code **0** = every FAIL-level check passed. `WARN` rows are known residuals
(listed in §3.4) and do not fail the run.

A release is **blocked** if any of these are true:

- script exit code ≠ 0,
- any pre-session observation in §4 fails twice on the same session,
- a §3.4 residual is resolved *without* re-running this checklist.

---

## 1. Model information completeness

Every consumer must receive the fields it uses, with the right type and the
right semantics. Producers are listed so a missing field has an owner.

### 1.1 AMT → `DecisionContext` contract

| Consumer | Fields it must receive | Producer |
|---|---|---|
| `DecisionService` (gates 1–4) | `bar`, `session_open`, `warmup_complete`, `position_open`, `cooldown_remaining_sec`, `risk_halted`, `poc/vah/val`, `cvd_slope`, `absorption_side`, `stacked_imbalance_*`, `obi`, `drive_number`, `data_quality`, `market_state` | `DecisionContextBuilder.build()` ← AMT DTO |
| `TimesFMScanningAgent` | above + `session_phase`, `allow_trend/reversion`, `equity`, `npoc_above/below`, `prior_poc` | same |
| `TimesFMPositionAgent` (advisory) | `position_*` set, `position_bars_held`, `position_sl/tp`, `cvd_slope`, `absorption_side` | `DecisionContextBuilder._extract_position()` |
| `TimesFMRiskAuthority` (real exits) | `TimesFMForecast.p10_path/p90_path/p50_path`, `asof_bar` | `TimesFMTradingStrategy.get_latest_forecast()` |
| `TimesFMPositionSizer` | `forecast`, `equity`, structural targets | `DecisionContext` + scanner payload |

Automated:

- [ ] `[PASS] every DecisionContext field has an AMT DTO producer` — consumed 46,
      produced 126, unexplained 0. Known fallback aliases (`acceptance`,
      `rejection`, `legLvn`, `data_quality`, `optionGreekDelta`) are allowlisted
      in the script; they are `or`-fallbacks, not live contract gaps.
- [ ] `[PASS] DEAD market maps to MarketState enum` — `"DEAD"` DTO must produce
      `MarketState.DEAD` (identity, not just equality), or the VA-fade gate never fires.
- [ ] `[PASS] shared engine records a bar exactly once` — the native advisor and
      the E2E strategy share one `TimesFMEngine`; a double `add_context` would
      feed every price twice to the model window.

Manual (first paper session, one bar):

- [ ] AMT DTO carries `poc`, `valueAreaHigh`, `valueAreaLow`, `cvdSlope`,
      `absorptionSide`, `marketState`, `dataQuality` — log the first DTO and read it.
- [ ] `absorptionSide` arrives in `_ABSORBED` form (`BUY_ABSORBED`/`SELL_ABSORBED`),
      not bare `BUY`/`SELL`.
- [ ] forecast payload logs `source=TIMESFM_3.0_NATIVE` (model loaded), never
      `TIMESFM_FALLBACK`, on a healthy session.
- [ ] `ctx.equity` equals the paper account equity (not `0.0`, not `100000.0`).

### 1.2 Forecast contract (shared by 4 consumers)

`TimesFMForecast` is the spine: scanner, position agent, risk authority and
sizer all read it. Any field change must be re-checked here.

- [ ] `p50_path`, `p10_path`, `p90_path`, `q_spread`, `mean_forecast`,
      `pct_change`, `forecast_steps`, `curr_price`, `lat_ms`, `asof_bar` all set
      on every forecast that reaches a consumer.
- [ ] `asof_bar` is stamped with the bar that produced the forecast; a forecast
      older than 1 bar must be dropped (`[STALE FORECAST]` log) before it reaches
      `ExitEngine`.
- [ ] inference failure yields **no** forecast (`MODEL_UNAVAILABLE`), never a
      synthetic flat forecast cached for exits.

---

## 2. Decision processing correctness

### 2.1 Entry

- [ ] Exactly one entry seam: `strategy.should_enter(ctx)`; the runtime never
      calls `DecisionService.evaluate()` directly. *(automated: PASS)*
- [ ] In `TIMESFM_END_TO_END`, the TimesFM model is the **central intelligence**:
      its scanner decision is followed through. The canonical AMT `GatePipeline`
      is **not** consulted for E2E approval and cannot override the model.
      *(automated: PASS — `model entry decision is authoritative`)*
- [ ] Gates 1–2 are hard rejects for the deterministic `DecisionService` path.
- [ ] Momentum entries (`MODEL_MOMENTUM`) enter on the model's decision without
      requiring a canonical AMT setup. *(automated: PASS)*
- [ ] `DATA_QUALITY_BLOCKED` fires for inferred/proxy provenance at conviction
      threshold `0.65`; `TICK_EXACT`/`CANDLE_DISTRIBUTED` pass. *(automated: PASS)*

### 2.2 Exit

- [ ] Real exits come only from `ExitEngine.evaluate()` → `TimesFMRiskAuthority`
      (or the deterministic rules), and every close stamps a source:
      `TIMESFM_RISK_AUTHORITY:<reason>` or `DETERMINISTIC:<reason>`.
      *(automated: PASS — central stamp in `PositionManager._execute_full_close`)*
- [ ] `TimesFMPositionAgent` EXIT is advisory/UI only; it must never be assumed
      to have closed the position. Verify: `[POSITION CLOSED] ... exit_source=...`
      exists for every close.
- [ ] Stop-loss tightening on the advisory path must coincide with a real
      `ExitEngine` trail update (no advisory-only stop moves).
- [ ] Session-close / EOD force close reports `DETERMINISTIC:SESSION_CLOSE`
      (or the EOD reason), never a stale source.

### 2.3 Sizing

- [ ] One sizing authority: `SessionRisk.position_size()` + `clamp_quantity()`.
      The strategy's `TimesFMPositionSizer` only qualifies the entry.
      *(automated: PASS; `TradeIntent`/`FixedRiskSizer` scaffolding deleted)*
- [ ] `equity` fed to sizing is the account equity, not a literal.

---

## 3. Conflicting-flow audit

### 3.1 Authority registry (must stay exclusive)

| Decision | Sole authority | Must NOT also run |
|---|---|---|
| Entry approve/reject (E2E) | `strategy.should_enter` (TimesFM scanner decision) | canonical `GatePipeline` override |
| Entry approve/reject (deterministic) | `DecisionService` → `GatePipeline` | shadow gate booleans, second decision service |
| Gate truth shown in UI | scanner model gate results | a second, competing decision service |
| Real exit | `ExitEngine` → `TimesFMRiskAuthority` | advisory `PositionAgent` (UI) |
| Sizing | `SessionRisk` + `clamp_quantity` | strategy-local quantity math |
| Market state | `MarketState` enum | raw `"DEAD"` string |
| Absorption semantics | `SELL_ABSORBED=LONG`, `BUY_ABSORBED=SHORT` | bare `BUY`/`SELL` compares |

Automated checks (all must pass):

- [ ] `[PASS] single entry seam`
- [ ] `[PASS] model entry decision is authoritative (no canonical override)`
- [ ] `[PASS] no bare absorption string compares`
- [ ] `[PASS] forecast cached only after success + freshness stamped`
- [ ] `[PASS] closes bypassing ExitEngine stamp an exit source`
- [ ] `[PASS] one sizing authority`

### 3.2 Fixed on this branch (regression-locked)

| ID | Conflict | Fix | Test |
|---|---|---|---|
| C1 | Native advisor + E2E strategy shared one engine and both appended the same bar → duplicated model input | `add_context` idempotent per stamped `bar_index` | `test_add_context_is_idempotent_within_a_stamped_bar`, `test_shared_engine_advisor_plus_strategy_records_bar_once` |
| C2 | Rule-based fallback compared bare `"BUY"`/`"SELL"` (dead + inverted) | substring match with canonical direction | `test_timesfm_engine_fallback_mode_*` |
| C3 | Thesis-flip / EOD / tick-TP closes logged a stale or empty `exit_source` | central stamp in `_execute_full_close` | `test_exit_source.py` |
| C4 | Two stale runtime gate-1 tests assumed one decision per bar | assert the warmup transition instead of a fixed index | `test_runtime.py` |

### 3.3 Single-authority invariants already landed

- BUG-1/2/3/4, STRUCT-1/3/6/7/8 from `docs/decision_pipeline_deep_review.md`
  are fixed on this branch (see `docs/superpowers/plans/2026-09-10-decision-pipeline-fixes.md`).

### 3.4 Known residuals (WARN — do not silently ignore)

| ID | Residual | Impact | Disposition |
|---|---|---|---|
| R1 | Native advisor / AMT panel can show a different view ("Quant FLAT") than the TimesFM model decision ("AI LONG") because the model is the entry authority in E2E mode | Operator may read the AMT/Quant panel as a veto when it is informational only | By design: the model is the central intelligence. The `DecisionProduced` card and `[SIGNAL EXECUTED]` / `[POSITION CLOSED]` logs are the truth. |
| R2 | Two forecast inferences per bar (advisor engine + strategy) in E2E mode | latency/cost, and the two payloads can differ | Accepted for paper; revisit if bar latency budget is exceeded. |

---

## 4. Pre-session operator observations (paper/live)

Run these on the **first session** of the release and tick each.

- [ ] `GET /health` → `status: "ok"`, TimesFM model loaded, contracts monitored.
- [ ] First `amt_dto` after bar 15: `poc`/`valueAreaHigh`/`valueAreaLow` non-zero.
- [ ] `cvdSlope` non-zero once order flow is present.
- [ ] `absorptionSide` ∈ {`BUY_ABSORBED`, `SELL_ABSORBED`, `""`} — never bare.
- [ ] Env confirms the intended path:
      `TIMESFM_END_TO_END`, `TIMESFM_ADVISOR_ENABLED`, `TIMESFM_NATIVE`,
      `LLM_ADVISOR_ENABLED`, `QUANT_EXECUTION_MODE`, `TRADING_MODE`.
- [ ] Every approved entry has a matching `TIMESFM APPROVAL ... Model: TimesFM-<setup>` line.
- [ ] Every close has `exit_source=` populated and matching the close reason.
- [ ] No trade is opened without an approved `DecisionProduced` on the same bar.
- [ ] No trade is opened while the last decision reason is `DATA_QUALITY_BLOCKED`.
- [ ] After session end, run the §5.4 acceptance gate over the day's journals
      (see `docs/PAPER_LIVE_RUNBOOK.md` §2).

---

## 5. Sign-off

| Gate | Command / evidence | Result | Date | By |
|---|---|---|---|---|
| Static + behaviour probes | `scripts/pre_release_decision_check.py --skip-suites` | 12 PASS / 1 WARN / 0 FAIL | 2026-09-10 | agent |
| Decision + strategy + exit + runtime suites | `pytest tests/quant/decision tests/quant/strategies tests/quant/execution/test_exit_source.py tests/quant/execution/test_position_management_flow.py tests/quant/runtime/test_runtime.py` | 306 PASS / 0 FAIL | 2026-09-10 | agent |
| Broader affected suites | `pytest tests/quant/decision tests/quant/execution tests/quant/strategies` | 541 PASS / 0 FAIL | 2026-09-10 | agent |
| Pre-session observations (§4) | paper session log | ☐ | | |
| Acceptance gate (§5.4) | `backend/scripts/acceptance_gate.py` | ☐ | | |
