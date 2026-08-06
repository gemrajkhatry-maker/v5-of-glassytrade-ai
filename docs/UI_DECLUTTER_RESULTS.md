# UI Declutter — Results

**Date:** 2026-08-06 · **Branch:** stable_4 · **Plan:** docs/superpowers/plans/2026-08-06-ui-declutter.md

## What shipped (5 commits, all TDD/verified)

| Task | Commit | Result |
|---|---|---|
| T1 remove fabricated values | `ccbbc17` | Removed the simulated CVD sparkline (`Math.sin`/`noise`), fake Est. TP (`ltp×1.002`), false "vol below prior session" claim (aggression is an orderflow score), "INSTITUTIONAL" trader-label from print size, static `[ENGINE ARMED]` badge, Delta-confidence % heuristic, VA-acceptance duration estimate. EquityPanel's real P&L is now the only P&L display. |
| T2 collapse panel | `4a0c454` | AIAnalysisPanel split into **Decision tier** (always visible) + **Diagnostics tier** (`<details>`, closed by default). Deleted 3 duplicate blocks (structure ×2, gap/bias ×2, LVN ×2). Fixed rule-checklist double-count (4/4 passable with 3 rules). |
| T3 dedup across panels | `8446da6` | probability 5×→2 (banner + panel), direction 4×→2, LTP 4×→2, marketState 4×→2. Deleted LiveOpportunityCard + its App.tsx mount. Sidebar slimmed (no prob/LTP/mode-badge/recent-trades). |
| T4 dead files/code | `c8b02be` | Deleted `SessionPhaseMarkers.ts` + `ChartOverlayEngine.ts` (unused, only tests imported them) + dead exports in AMTLevelsOverlay/ExecutionMarkersManager, unused `vwapStd` const, unused DecisionCard `timing` prop. |
| T5 DTO telemetry drop | `776b720` | Dropped 13 telemetry-only AMT DTO fields (dayType, liquiditySweep, cushionTier, sessionPnl, bubbleRetests, cvdSource, bimodalActivePole, underlyingPrice, optionType, openingType, hourlyVah, hourlyVal, mtfAlignment) — all grep-verified as frontend-unread. 9 were already gone from a prior commit; removed the 6 lingering in the Pydantic model. |

## Verified results

- **Backend tests:** 1819 passed / 77 skipped (only pre-existing env-broken suites ignored).
- **Frontend:** `npm run build` clean; **179 tests passed**.
- **Live smoke:** backend + frontend restart clean; model loads, 3 contracts scanned, **0 tick errors**; live LLM prompt contract intact (SESSION renders, 1484 chars).

## Impact

- **Fabricated data eliminated** — no simulated/fake values rendered anywhere.
- **Dedup achieved** — probability/direction/timing/LTP/marketState each render once (banner + panel canonical homes).
- **Diagnostics collapsed** — the 1784-line panel now opens to Decision-tier essentials; full analysis behind one toggle.
- **Payload slimmer** — 13 telemetry fields off the WS DTO.

## Remaining known items (non-blocking)

- `AMTAnalysisDTO` Pydantic model is a dead contract-doc (no code imports it) — candidate for deletion.
- `ofi`/`swingDelta`/`absorptionRangeRatio`/`absorptionVolRatio`/`breakType`/`breakLevel`/`pocSignal`/`pocVsPrice`/`daily*`/`hourlyPoc`/`structureConfidence` still render in the Diagnostics tier — kept (decision context, some spatial on chart).
- The paper-mode "quiet window" (no decisions during smoke) is market activity, not a bug — entry fires on candle-close/event triggers per the earlier throttle work.
