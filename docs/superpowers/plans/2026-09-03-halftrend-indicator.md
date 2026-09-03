# HalfTrend Indicator Plan (lines + Buy/Sell labels, no trades)

**Date:** 2026-09-03
**Repository:** GlassyTrade AI
**Branch at planning time:** `feat/fractal-half-trend-signals`
**Status:** Execution plan — pending approval before implementation

> **For agentic workers:** apply this document as an ordered execution plan. Keep
> the repository discipline: `quant/` stays pure (no FastAPI/frontend imports),
> every deliberate ceiling carries a `# ponytail:` comment, no broad staging,
> and no new dependency unless an existing capability cannot do the job.

## 1. Objective

Replace the previously added ChartArt **Fractal Breakout** feature on this
branch with a faithful port of the **HalfTrend** indicator (everget, Pine v6,
GPL-3.0) that the user pasted. Deliverables, all **display-only** — no trade,
risk, or decision-logic changes anywhere:

1. The **HalfTrend line** (`ht = trend == 0 ? up : down`) drawn on the chart,
   colored by trend exactly like the Pine `htPlot` (blue when `trend == 0`,
   red when `trend == 1`).
2. The **ATR channel** (`atrHigh`/`atrLow` = `ht ± channelDeviation·atr2`,
   where `atr2 = ta.atr(100) / 2`) drawn around the line.
3. **Buy / Sell labels and arrows** at the exact bars where the Pine signals
   fire: `buySignal = not na(arrowUp) and trend == 0 and trend[1] == 1` and the
   mirrored sell condition.
4. All calculation in the **backend**; the frontend only renders.

The fractal breakout implementation (detector, DTO block, markers, line
overlay, badge, tests) is removed as part of this change since the user asked
for it to be taken out in favor of HalfTrend.

## 2. Current Assessment

The repo already has the exact architecture needed — HalfTrend fits the
established **VARS detector pattern**:

- `quant/amt/market/vars_detector.py` — stateful per-closed-bar detector whose
  result rides `AMTResult` → `quant/amt/dto.py` `amt_result_to_dto` → the WS
  `amt` payload (`AmtUpdated` event) → frontend `inst.amtAnalysis` merge in
  `frontend/hooks/useServerTradingSystem.ts`.
- The chart is fed two ways: **REST warm-up history**
  (`GET /api/market/history/{symbol}?interval=&limit=500`, loaded per symbol +
  interval) and **live per-tick candles/AMT over the WS**; the hook merges
  same-timestamp live bars over history in `setInstruments`.
- Chart overlays live in `frontend/components/ChartScene.tsx` (candle +
  histogram + optional line series via `chart.addLineSeries`, per-point `color`
  supported by lightweight-charts 4.1.1) and markers are produced by pure
  functions in `frontend/components/chart/ExecutionMarkersManager.ts`
  (per-candle markers placed at candle times via `toISTTimestamp`).
- Fractal breakout feature currently on this branch: `quant/amt/market/fractal_half_trend.py`,
  `AMTResult.fractal_result`, DTO `fractal` block, frontend `FractalState`,
  `generateFractalMarkers` + `fractalLineData`, ChartScene fractal line series
  + memo-compare entries, MarketStateCard/AIAnalysisPanel fractal badge, and
  the matching backend/frontend tests.

### HalfTrend semantics to port faithfully (Pine v6)

```text
amplitude = 2, channelDeviation = 2, atr2 = ta.atr(100) / 2
highPrice = high of the highest of the last `amplitude` bars   (ta.highestbars)
lowPrice  = low  of the lowest  of the last `amplitude` bars   (ta.lowestbars)
highma = sma(high, amplitude);  lowma = sma(low, amplitude)

State machine (trend / nextTrend / maxLowPrice / minHighPrice):
  while nextTrend == 1: maxLowPrice := max(lowPrice, maxLowPrice)
    flip to trend=1 when highma < maxLowPrice AND close < low[1]
  while nextTrend == 0: minHighPrice := min(highPrice, minHighPrice)
    flip to trend=0 when lowma > minHighPrice AND close > high[1]

up / down rails (na-guarded, exactly as Pine):
  on flip into trend=0:  up := down[1]; arrowUp := up - atr2   (Buy signal)
  else while trend=0:    up := max(maxLowPrice, up[1])
  on flip into trend=1:  down := up[1]; arrowDown := down + atr2 (Sell signal)
  else while trend=1:    down := min(minHighPrice, down[1])

ht = trend == 0 ? up : down
atrHigh = ht-track + dev ; atrLow = ht-track - dev
```

Order of evaluation matters: Pine v6 computes the current bar's `up`/`down`
**after** the flip block on the same bar, and the `trend[1]` guards keep the
flip branch from re-running on the bar after the signal. The port must keep
this per-bar order: (1) track rails, (2) flip decision, (3) rail update,
(4) `ht`/`atrHigh`/`atrLow`, (5) signal flags. Warm-up/`nz` semantics:
`nz(low[1], low)` on the first bar uses the current bar — replicate by seeding
history with `na`-guards or by requiring a warm-up bar, whichever matches Pine.

## 3. Non-Negotiable Rules

1. **No trades.** HalfTrend only emits display data; nothing in
   `quant/decision/`, gates, OMS, or execution reads it.
2. **No business-logic changes** to existing AMT/VARS/decision behavior.
3. **Calculation lives in the backend** (`quant/amt/market/half_trend.py` and
   the analysis endpoint); the frontend renders arrays/state it is given and
   performs no trend math.
4. **`quant/` stays independent** of `backend/`, FastAPI, broker SDKs, and the
   frontend — mirror `vars_detector.py` imports.
5. No new dependency; lightweight-charts 4.1.1 per-point `color` is sufficient.
6. History and live tail must agree: REST series and the WS per-bar record
   come from the same detector semantics.
7. Session/rollover reset mirrors existing detector lifecycle
   (`reset()` called in analyzer day-rollover path).
8. Every deliberate ceiling (e.g., cap on line-history bars, channel dots vs
   circles) gets a `# ponytail:` comment.
9. Tests: backend unit tests for Pine-faithful state transitions and signals
   (trace-verified like `test_fractal_half_trend.py`), plus endpoint test and
   frontend pure-function tests. No broad staging; stage only files we own.

## 4. Architecture / Data Flow

```text
backend                                       frontend
--------                                      --------
history candles -> HalfTrendSeries.compute()   -> REST GET /api/market/halftrend/{symbol}?interval&limit
                                                 → {data:[{time,ht,atrHigh,atrLow,trend,buy,sell}]}
live closed bar -> HalfTrendDetector.update()  -> WS amt.halfTrend {time,ht,atrHigh,atrLow,trend,
   (in AMTAnalyzer per bar, like vars)                 buySignal,sellSignal}
                                                 → instrument store merge (same-timestamp overwrite,
                                                   exactly like candle history merge)
ChartScene:
  ht line series      = history + live points (per-point color: trend? red : blue)
  atrHigh/atrLow      = thin dotted series around ht (channel)
  Buy/Sell labels     = ExecutionMarkersManager markers at signal times
                        (text 'Buy'/'Sell' + triangle arrows), derived from
                        the same series arrays — no frontend calculation
```

- Detector output per bar is a small frozen dataclass `HalfTrendResult`.
- A stateless `compute_half_trend_series(candles) -> list[HalfTrendResult]`
  reuses the detector by replaying candles — single source of truth for the
  REST history endpoint and the live detector.
- REST endpoint added to `backend/app/api/routers/market.py`
  (`/halftrend/{symbol}`) using the same `market_data.fetch_history` used by
  `/history/{symbol}` so both datasets align bar-for-bar.
- WS DTO: `quant/amt/dto.py` gains `"halfTrend": {...}` (empty-safe, defaults
  in `empty_amt_dto()` like `vars`/`fractal`).
- The live `amt` payload rides the same `AmtUpdated` channel already merged by
  the frontend, so per-tick `ht`/`atrHigh`/`atrLow` stay current between bar
  closes with **no new socket plumbing**.

## 5. Task Breakdown

### Lane A — Remove the ChartArt fractal feature
1. Delete `quant/amt/market/fractal_half_trend.py` and
   `tests/quant/amt/market/test_fractal_half_trend.py`.
2. Unwire analyzer (`_fractal_detector`, reset call, `fractal_result=` kwargs
   in `_build_result` call + signature + `AMTResult(...)`) and drop
   `AMTResult.fractal_result` from `quant/contracts/value_objects.py`.
3. Drop the `fractal` block in `quant/amt/dto.py`.
4. Frontend: remove `FractalState`/`FractalLinePoint` from `types.ts`,
   `generateFractalMarkers`/`fractalLineData` + call in
   `ExecutionMarkersManager.ts`, the fractal line-series setup/update in
   `ChartScene.tsx`, the `fractalSame` memo-compare entries, and the fractal
   prop/badge in `MarketStateCard.tsx`/`AIAnalysisPanel.tsx`; remove the
   related frontend tests. Also remove now-unused `ChartMarker` export if only
   fractal code used it (check first).
5. `git grep` for `fractal|Fractal` must come back clean (repo scope), then
   commit.

### Lane B — Backend HalfTrend detector
1. New `quant/amt/market/half_trend.py`:
   - `@dataclass(frozen=True) HalfTrendResult` with
     `time, trend, ht, atr_high, atr_low, buy_signal, sell_signal`.
   - `HalfTrendDetector(n_time-free)`: constants `amplitude=2`,
     `channel_deviation=2`, `atr_period=100` (constructor-overridable for
     tests). Keep state: last bars for sma/highestbars/lowestbars/atr
     (rolling buffers), `trend`, `next_trend`, `max_low_price`,
     `min_high_price`, `up`, `down`, previous-bar `close/high/low`, previous
     `trend` for `trend[1]` guards.
   - Faithful per-bar order described in §2; `ta.atr(100)` = Wilder/RMA-based
     ATR over 100 — implement with the repo's existing ATR utility if present
     (`quant/amt/...`), else a small RMA/ATR helper in the module
     (`# ponytail:` note if approximated).
   - `reset()` for session rollover.
   - Module-level `compute_half_trend_series(candles, **kw) -> list[HalfTrendResult]`
     replaying candles through a fresh detector (dropping the warm-up prefix,
     matching Pine history availability).
2. Wire into `quant/amt/analyzer.py`: instantiate + `reset()` alongside the
   other detectors, call `self._half_trend_detector.update(current)` in the
   same block as `vars_result`, carry through `_build_result` →
   `AMTResult.half_trend_result`.
3. `quant/contracts/value_objects.py`: `half_trend_result: object | None = None`
   on `AMTResult`.
4. `quant/amt/dto.py`: `"halfTrend": {time, trend, ht, atrHigh, atrLow,
   buySignal, sellSignal}` with `getattr` defaults; empty DTO inherits via
   `empty_amt_dto()`.
5. Endpoint `GET /api/market/halftrend/{symbol}?interval=&limit=`
   in `market.py` returning `{"data":[{time,ht,atrHigh,atrLow,trend,buy,sell}]}`
   from `compute_half_trend_series(await market_data.fetch_history(...))`
   (capped at `limit`, default 500).

### Lane C — Frontend rendering
1. `types.ts`: `HalfTrendState {time?, trend, ht, atrHigh, atrLow, buySignal,
   sellSignal}` + `AMTAnalysis.halfTrend?`; `HalfTrendPoint` for history rows.
2. `frontend/hooks/useServerTradingSystem.ts`: alongside the existing history
   warm-up, fetch `/api/market/halftrend/{symbol}` per symbol+interval and
   store `halfTrendHistory` in instrument state (same merge/dedupe helper
   pattern as candles); per WS `amt` tick merge `state.amt.halfTrend` into the
   same series with the same-timestamp overwrite used for candles.
3. `ChartScene.tsx`: three overlay series created once near the candle series:
   - `ht` line (width 2, per-point color `trend ? '#f23645' : '#2962ff'` to
     match Pine blue/red);
   - `atrHigh`/`atrLow` thin dotted channel lines (per-point colors red/green);
   - update them whenever `stableAmtAnalysis` or the instrument series change
     (extend the memo comparator so new `halfTrend` points are not swallowed).
4. `ExecutionMarkersManager.ts`: pure `halfTrendSignalMarkers(points)` →
   `ChartMarker[]` producing `Buy` label/arrow below bar and `Sell`
   label/arrow above bar at each signal time (green/red palette already used
   by VARS markers); feed it from the merged series in ChartScene so labels
   persist across the whole history, not only the live bar.
5. Remove fractal UI remnants per Lane A step 4.

### Lane D — Tests & verification
1. Backend: `tests/quant/amt/market/test_half_trend.py` — deterministic
   synthetic sequences that force an up-flip (`lowma > minHighPrice and
   close > high[1]`) and a down-flip, asserting: trend transitions,
   `ht` equals the Pine rail values, arrow offsets (`up - atr2` /
   `down + atr2`), signal flags fire on exactly the flip bar (`trend[1]`
   guards), warm-up behavior, `reset()`, and stateless series == detector
   replay parity.
2. Endpoint test asserting `/api/market/halftrend/{symbol}` shape and bar
   alignment with `/history/{symbol}`.
3. Analyzer/WS contract suite stays green (`tests/quant/amt/test_analyzer.py`,
   `tests/quant/test_ws_contract*.py`).
4. Frontend: `tsc --noEmit`; unit tests for `halfTrendSignalMarkers` +
   existing marker suite; component tests still pass.
5. Final gates: full `tests/quant/amt` suite, frontend vitest run.

## 6. Out of Scope (deliberate ceilings)

- No `alertcondition`/notifications; no trade entries (user: "no trades").
- Channel **ribbons** (Pine `fill` under/over `ht`) are not rendered — the
  dotted `atrHigh`/`atrLow` lines convey the channel (`# ponytail:` comment in
  ChartScene). Circles style omitted; dotted lines chosen for
  lightweight-charts.
- Per-symbol toggle UI for HalfTrend visibility is deferred; render always-on
  when data exists, like the other overlays.
- Fractal breakout code from the previous two commits is removed from the tree
  forward (history is preserved; no force-push/rewrite).

## 7. Sequencing

1. Lane A (removal) — commit.
2. Lane B backend detector + wiring + endpoint — commit (tests green).
3. Lane C frontend — commit (tsc + vitest green).
4. Lane D full gates; address failures; final commit.
5. Report; push only on explicit request.
