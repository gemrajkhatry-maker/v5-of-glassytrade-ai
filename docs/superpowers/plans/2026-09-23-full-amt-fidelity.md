# Full AMT Fidelity Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Close remaining AMT doc-vs-code gaps from the 2026-09-23 fidelity review: literal §12.2 house-money (with retracement veto only), correct inverted CVD market thresholds, restore portfolio open-risk after restart, prior-session fields on DecisionContext, §6.2 CVD slope formula, 15m bias layer, optional range-bar micro decisions with OHLCV synth seed (warmup = 15 live range bars AND ≥15 min), and doc drift fixes — without removing AI/model integration.

**Architecture:** Keep live path `main → composition_root → QuantCoordinator → QuantEngine → AMT → 4 gates → OMS → ExitManager/ExitEngine`. Wave 1 tasks are file-disjoint and run in parallel. Wave 2 touches `quant/runtime.py` (bias + range bars) and runs after Wave 1. Range bars ship behind `GLASSYTRADE_USE_RANGE_BARS` (default **false**); 5m macro stays time-based.

**Tech Stack:** Python 3.13, pytest, root `.venv`, YAML config, optional range mode on existing `BarAggregator`.

## Global Constraints

- **Never remove AI/model integration:** keep `wiring_advisor`, `laya_advisor`, `timesfm_*`, `llm/*`, env `LLM_*`/`TIMESFM_*`/`LAYA_*`/`MLX_*`/`OPENROUTER_API_KEY`.
- **Exit authority:** `ExitManager → PositionManager → ExitEngine`.
- **Entry authority:** single `AmtScalpingStrategy.should_enter`.
- **Python tests:** `PYTHONPATH=backend:. .venv/bin/python -m pytest …`
- **Gates:** `make lint` and `make pre-release` green before final commit. Merge gate: `PYTHONPATH=backend:. .venv/bin/python -m pytest tests/architecture tests/quant/decision tests/quant/execution tests/quant/runtime tests/quant/amt -q`
- **Commits:** one commit per task; path-scoped `git add` (never `git add -A`).
- **House-money design (approved):** offensive = `E0×0.0025 + 0.40×Cushion`, ceiling `min(..., 0.50%)`; **keep** 50%-from-peak retracement veto; **delete** 30%-of-profit cushion cap.
- **Range-bar warmup (approved):** entries require `live_range_bars >= 15` AND `live_minutes >= 15` when range mode on; seed/synth bars never count toward entry warmup; seed bars: no drive, no hard absorption, no Triple-A progress from seed-only.
- **Range flag default false:** `GLASSYTRADE_USE_RANGE_BARS` / config `range_bars_enabled: false`.
- **Do not** invent Greek/delta (fail-closed stays).

## Wave map

| Wave | Tasks | Parallel? |
|------|-------|-----------|
| 1 | T1 house-money, T2 CVD thresholds, T3 restore open-risk, T4 prior VAH/VAL/gap, T5 CVD EMA slope, T6 docs | **Yes** — disjoint files |
| 2 | T7 15m bias, T8 range bars + synth seed | T7 then T8 (both `runtime.py`) |
| 3 | T9 merge gates | serial |

---

### Task 1: House-money §12.2 (literal + retracement veto)

**Files:**
- Modify: `quant/execution/risk.py` (`_risk_per_trade_pct`, `_cushion_tier` docstring)
- Test: `tests/quant/execution/test_risk_cushion_tiers.py` (create or extend existing risk tests)

**Interfaces:**
- Consumes: `SessionRisk._starting_equity`, `_daily_pnl`, `_peak_daily_pnl`, `_halted`, `_macro_risk_cap`
- Produces: same public API; `risk_per_trade_pct` in offensive mode = `min(0.0025 + 0.40*pnl/E0, 0.0050)` with retracement veto → `0.0025`; **no** `daily_pnl*0.30/E0` term

- [x] **Step 1: Failing tests**

```python
# tests/quant/execution/test_risk_cushion_tiers.py
def test_offensive_cushion_is_literal_spec_formula():
    from quant.execution.risk import SessionRisk
    r = SessionRisk(starting_equity=100_000.0)
    r._daily_pnl = 5_000.0
    r._consecutive_losses = 0
    r._consecutive_wins = 1
    # tier CUSHION_TIER_1: base 0.25% + 40% of 5000 = 250+2000 → 2250/100000 = 0.0225 → cap 0.0050
    assert abs(r._risk_per_trade_pct() - 0.0050) < 1e-9

def test_offensive_has_no_30pct_profit_cap_below_ceiling():
    from quant.execution.risk import SessionRisk
    r = SessionRisk(starting_equity=100_000.0)
    r._daily_pnl = 500.0  # 0.40*500/100000 = 0.002 → risk 0.0045; old 30% cap → 0.0025+0.00015=0.00265
    r._consecutive_losses = 0
    r._consecutive_wins = 1
    assert abs(r._risk_per_trade_pct() - (0.0025 + 0.002)) < 1e-9

def test_retracement_veto_stays():
    from quant.execution.risk import SessionRisk
    r = SessionRisk(starting_equity=100_000.0)
    r._peak_daily_pnl = 4_000.0
    r._daily_pnl = 1_000.0  # <= 0.5 * peak
    assert r._cushion_tier() == "BASE_RETRACEMENT_VETO"
    assert abs(r._risk_per_trade_pct() - 0.0025) < 1e-9
```

- [x] **Step 2:** Run → FAIL
- [x] **Step 3: Minimal impl** in `_risk_per_trade_pct` CUSHION_TIER_1 branch — remove the `min(cushion_add, daily_pnl*0.30/E0)` block; keep `risk = min(base + cushion_add, 0.0050)` and retracement/consecutive/halt/macro caps. Update `_cushion_tier`/`_risk_per_trade_pct` docstrings to match §12.2 + “retracement veto is intentional safety rail, not in spec.”
- [x] **Step 4:** Run tests → PASS; run existing risk tests
- [x] **Step 5:** `git add quant/execution/risk.py tests/quant/execution/test_risk_cushion_tiers.py && git commit -m "fix(risk): literal §12.2 house-money, drop 30% profit cap"`

---

### Task 2: Inverted CVD market thresholds

**Files:**
- Modify: `quant/contracts/constants.py` (`FABIO_CVD_THRESHOLD_NSE/MCX`)
- Modify: `quant/decision/context_builder.py` (uses constants — no logic change if constants fixed)
- Test: `tests/quant/contracts/test_fabio_constants.py` + direction-resolution unit if present

**Interfaces:**
- Produces: `FABIO_CVD_THRESHOLD_NSE = 0.3`, `FABIO_CVD_THRESHOLD_MCX = 0.5` (matches `gates_edge.py:192-194` and `fabio_decision_pipeline.md:106-107`)

- [x] **Step 1: Failing test**

```python
def test_fabio_cvd_thresholds_match_pipeline_doc():
    from quant.contracts.constants import FABIO_CVD_THRESHOLD_MCX, FABIO_CVD_THRESHOLD_NSE
    assert FABIO_CVD_THRESHOLD_NSE == 0.3  # tighter NSE
    assert FABIO_CVD_THRESHOLD_MCX == 0.5  # looser MCX
```

- [x] **Step 2:** FAIL
- [x] **Step 3:** Swap constants to 0.3 / 0.5; comment “matches Gate-3 veto and pipeline doc; was inverted”
- [x] **Step 4:** PASS; grep no other hard-coded 0.5/0.3 pairs for CVD direction left inconsistent
- [x] **Step 5:** commit `fix(cvd): NSE 0.3 / MCX 0.5 direction thresholds (was inverted)`

---

### Task 3: Restore open-risk after restart

**Files:**
- Modify: `quant/runtime.py` (`restore_position` ~:801-802)
- Test: `tests/quant/runtime/test_restore_open_risk.py`

**Interfaces:**
- Consumes: `position` (qty/entry/sl or risk estimate), `PortfolioRiskAuthority.register_open(rupees, symbol=)`
- Produces: restored book contributes real open risk, not `0.0`

- [x] **Step 1: Failing test** — construct engine, restore a position with known `|entry-sl|*qty`, assert `portfolio_risk` open-risk sum includes that risk (or mock `register_open` and assert first arg != 0.0 / equals computed).

```python
def test_restore_registers_nonzero_open_risk(mocker):
    ...
    # after restore_position
    spy.assert_called_once()
    assert spy.call_args[0][0] > 0.0
```

- [x] **Step 2:** FAIL
- [x] **Step 3:** Compute `risk = abs(entry - sl) * qty` (same basis as SessionRisk if available; else `abs(entry-sl)*qty`); `register_open(risk, symbol=self.symbol)`. If position lacks sl, fall back to `abs(entry)*qty*0.0025` only if documented — prefer sl-based.
- [x] **Step 4:** PASS
- [x] **Step 5:** commit `fix(risk): restore_position registers real open risk`

---

### Task 4: Prior VAH/VAL/gapType on DecisionContext

**Files:**
- Modify: `quant/decision/context.py` (add fields after `prior_poc`)
- Modify: `quant/decision/context_builder.py` (map DTO keys)
- Test: `tests/quant/decision/test_prior_session_context.py`

**Interfaces:**
- Consumes: DTO `priorVah`, `priorVal`, `gapType`, `openingBias` (already exported `quant/amt/dto.py`)
- Produces: `ctx.prior_vah: float`, `ctx.prior_val: float`, `ctx.gap_type: str`, `ctx.opening_bias: str` (zeros/empty if missing)

- [x] **Step 1: Failing test** — builder with dto `{priorPoc: 100, priorVah: 105, priorVal: 95, gapType: "GAP_UP", openingBias: "ABOVE"}` → fields set.
- [x] **Step 2:** FAIL
- [x] **Step 3:** Add dataclass fields + builder `ds`/`_df` maps next to existing `prior_poc` mapping (~context_builder.py:712).
- [x] **Step 4:** PASS; architecture DTO contract still green
- [x] **Step 5:** commit `feat(decision): prior VAH/VAL/gapType/openingBias on DecisionContext`

---

### Task 5: CVD slope = EMA3 − EMA9 (spec §6.2)

**Files:**
- Modify: `quant/amt/orderflow/cvd.py` (`_compute_slope`)
- Test: `tests/quant/amt/orderflow/test_cvd_slope_ema.py`

**Interfaces:**
- Produces: `slope = EMA(CVD, 3) - EMA(CVD, 9)` on update; keep sign-persistence filter (`CVD_SLOPE_PERSISTENCE_BARS`) if already present (applies to sign of the EMA-diff, not linreg)

- [x] **Step 1: Failing test** — feed synthetic CVD series; assert slope matches independent EMA3−EMA9 implementation; assert not equal to old linreg for a known series.
- [x] **Step 2:** FAIL
- [x] **Step 3:** Replace `mc.linreg_slope(window)` with EMA differences (alpha = 2/(n+1) for n=3 and n=9); seed EMAs from history; persistence sign logic unchanged.
- [x] **Step 4:** PASS; existing cvd tests green
- [x] **Step 5:** commit `fix(cvd): §6.2 slope is EMA3−EMA9 with sign persistence`

---

### Task 6: Doc drift fixes (non-code)

**Files:**
- Modify: `docs/architecture/fabio_amt_deterministic_flow.md` (G4 wording + bar interval default)
- Modify: `docs/amt/fabio_decision_pipeline.md` (Gate 1 file path if wrong)
- Modify: `docs/architecture/ARCHITECTURE_AND_FLOWS.md` (Tier-1 0.50% if it says 0.75%)
- Modify: `docs/amt/AMT_INSTITUTIONAL_SCALPER_ALGORITHM.md` §16 — only after T8: note range flag; until T8 leave §16 alone

**Interfaces:** docs only — no runtime.

- [x] **Step 1:** Grep stale claims; fix G4 → “stop cap (R:R enforced in SignalBuilder)”; fix Gate path to `quant/decision/gate_session_phase.py`; fix 0.75% → 0.50% ceiling.
- [x] **Step 2:** No code tests; `git diff` review
- [x] **Step 3:** commit `docs: fix AMT pipeline/architecture drift (G4, paths, risk ceiling)`

---

### Task 7: Enable 15m bias layer at production 5m macro

**Files:**
- Modify: `quant/runtime.py` (~:386-396)
- Test: `tests/quant/runtime/test_bias_aggregator.py`

**Interfaces:**
- Produces: when `interval_seconds >= 300` (macro exists), also build `BarAggregator(interval_seconds=BIAS_INTERVAL_SEC)` for bias (and underlying bias if gateway present). Change condition from `interval_seconds > BIAS_INTERVAL_SEC` to `interval_seconds > MICRO_SEC` (or always if macro exists).

- [x] **Step 1: Failing test** — `QuantEngine(..., interval_seconds=300)` → `engine._bias_aggregator is not None` and `.interval_seconds == 900`.
- [x] **Step 2:** FAIL
- [x] **Step 3:** Change bias construction to run whenever macro micro-split exists (`interval_seconds > MICRO_SEC`), same for underlying bias.
- [x] **Step 4:** PASS; ensure no crash if bias never fed (None bar OK downstream — grep consumers of `_bias_aggregator`)
- [x] **Step 5:** commit `feat(amt): instantiate 15m bias layer on 5m macro engines`

---

### Task 8: Range bars primary (flag) + OHLCV synth seed + live warmup

**Files:**
- Modify: `quant/runtime.py` (micro aggregator construction when flag on; seed path)
- Modify: `quant/aggregator.py` if needed for range `_bar_time` (range bars: time = tick time, already OK)
- Modify: `backend/config/base.yaml` (implement `GLASSYTRADE_USE_RANGE_BARS` / `range_bars_enabled: false`)
- Modify: `quant/engine/decision_loop.py` or `context_builder` warmup: live range bar counter
- Modify: `quant/amt_engine.py` seed: mark seed bars as non-drive / warmup for range mode
- Create: `quant/amt/range_seed.py` — synthesize range bars from 1m OHLCV given `H_range`
- Test: `tests/quant/amt/test_range_seed.py`, `tests/quant/runtime/test_range_bars_flag.py`

**Interfaces:**
- Consumes: env `GLASSYTRADE_USE_RANGE_BARS=1` or config; ATR(14) from 1m seed for `H_raw`; quantize ladder `{5,10,25,50,100,200}` if values fit NSE/MCX tick scale — if ladder yields 0 after tick snap, use `max(tick, ATR14)` without forcing ladder (document).
- Produces:
  - `range_bars_enabled: bool` on engine
  - micro decision bar = `BarAggregator(range_size=H_range)` when enabled (macro 5m stays time)
  - `synth_range_bars(ohlcs_1m, h_range) -> list[Bar]` volume-conserving
  - `live_range_bars: int` on engine; `warmup_complete` for entries = `live_range_bars >= 15` and elapsed live minutes `>= 15` when range mode; time-bar path unchanged (`warm_bars >= 15`)
  - seed bars: `is_seed=True` on bar meta or separate counter not incrementing drive/Triple-A (drive already session-resets; explicitly skip `track_drives` for seed if needed)

- [x] **Step 1: Failing tests**

```python
def test_synth_range_bars_conserve_volume():
    from quant.amt.range_seed import synth_range_bars
    ohlcs = [...]  # crafted 1m bars spanning H_range
    bars = synth_range_bars(ohlcs, h_range=2.0)
    assert abs(sum(b.volume for b in bars) - sum(c.volume for c in ohlcs)) < 1e-6

def test_flag_off_keeps_time_micro():
    # default engine interval 300 → micro is 60s interval, not range
    ...

def test_range_flag_builds_range_micro():
    # monkeypatch env or pass config range_bars_enabled=True
    # micro_aggregator.range_size is not None
    ...

def test_range_warmup_needs_15_live_and_15_min():
    # simulate 14 live bars → warmup_complete False; 15 bars + 15 min → True
    ...
```

- [x] **Step 2:** FAIL
- [x] **Step 3:** Implement:
  1. Read flag → `self._range_bars_enabled`
  2. If enabled: `self._micro_aggregator = BarAggregator(interval_seconds=MICRO_SEC, range_size=h_range)` **or** replace micro with range-only aggregator (`range_size=h, interval_seconds=0` — check `_window` when range path used: `range_size is not None` bypasses interval — use `BarAggregator(interval_seconds=0, range_size=h)` carefully: `_bar_time` with interval 0 returns tick time — OK)
  3. `range_seed.synth_range_bars` for history seed when flag on
  4. Live counter increments on each closed range micro bar from ticks only
  5. `warmup_complete` branch in `context_builder` when range mode
  6. Skip drive tracking on seed bars if seed feeds analyzer
- [x] **Step 4:** PASS new tests + merge-gate suites
- [x] **Step 5:** commit `feat(amt): optional range-bar micro decisions with OHLCV synth seed`

---

### Task 9: Merge gates + §16 note + ledger

**Files:**
- Modify: `docs/amt/AMT_INSTITUTIONAL_SCALPER_ALGORITHM.md` §16 range paragraph (flag + default off)
- Modify: plan checkboxes

**Steps:**
- [x] `make lint`
- [x] `make pre-release`
- [x] Merge-gate pytest command (Global Constraints)
- [x] Update §16: “Range bars available when `range_bars_enabled`; default time micro; synth seed does not count as live warmup.”
- [x] Commit `docs: §16 range-bar flag status`

---

## Parallel dispatch map (subagent-driven)

| Parallel group | Tasks |
|----------------|-------|
| A | T1 house-money |
| B | T2 CVD thresholds |
| C | T3 restore open-risk |
| D | T4 prior context fields |
| E | T5 CVD EMA slope |
| F | T6 doc drift (code-free) |
| After A–F green | T7 bias |
| After T7 | T8 range bars |
| Last | T9 gates |

Each implementer: TDD, path-scoped commit, no `git add -A`, report SHA + test output.

## Self-review

- **Coverage:** T1–T8 map to review gaps (house-money, CVD invert, restore, prior VA, CVD formula, range, 15m, docs). Options-premium policy already largely in algorithm doc §15 — no separate code task (delta fail-closed already FIXED).
- **Placeholders:** synth OHLCV algorithm defined in T8 (split 1m bar when span ≥ H_range, assign volume pro-rata by high/low path assumption: all volume at close for simplicity — **explicit: volume on close of each synth segment**).
- **Types:** `prior_vah/prior_val: float`, `gap_type/opening_bias: str`; `synth_range_bars(list[OHLC], float) -> list[Bar]`.
