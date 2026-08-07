# WS-TS — Frontend `tsc --noEmit` cleanup report

**Date:** 2026-08-07
**Branch:** `migration/ws-ts`
**Worktree:** `/Users/apple/Documents/wt-ws-ts` (main repo untouched)

## Status

DONE. `npx tsc --noEmit` → **0 errors**; `npm test` → **198/198 green**; `npm run build` → clean (pre-existing 500 kB chunk-size warning only). No behavior change. No `any` escapes. Working tree clean.

## Commits

| Commit | Message |
| --- | --- |
| `9f7c42b` | `fix(ui): align types with WS snapshot shape (showPredictions/modelWeights/analysis fields)` |
| `48b9e22` | `fix(ui): wire vitest globals in tsconfig` |
| `5dea0ef` | `chore(ui): pin @types/react + @types/react-dom for tsc reproducibility` |

## tsc before/after

- **Before:** 13 errors (verified against main repo baseline with `@types/react` present): 5× `showPredictions` on `ChartConfig`, 1× fixture missing `auctionAnalysis`/`quantDecisionAnalysis`/`depth20Active`, 2× `modelWeights` on `InstrumentState`, 5× vitest globals (`describe`/`it`/`expect`) in `tests/types.test.ts`.
- **After:** 0 errors.

## Changes

- `frontend/types.ts` — added `showPredictions: boolean` to `ChartConfig`; added optional `modelWeights?: ModelWeights`, `generation?: number`, `predictions?: OHLCData[]`, `stats?: InstrumentStats | null` to `InstrumentState` (new `InstrumentStats` interface matching the backend `stats_to_dto` shape); changed `depth20Active` from required to **optional** (see Concerns).
- `frontend/hooks/useServerTradingSystem.ts` — `createInstrumentState` fixture now sets `auctionAnalysis: null` and `quantDecisionAnalysis: null`.
- `frontend/tests/components/MarketSidebar.test.tsx`, `frontend/tests/integration/trading-flow.test.tsx` — mock fixtures gained `auctionAnalysis: null`, `quantDecisionAnalysis: null` (required fields the literals were missing).
- `frontend/tsconfig.json` — `"types": ["node", "vitest/globals"]` (kept `node`; it is used by `tests/types.test.ts` and `vite.config.ts`).
- `frontend/tests/setup.ts` — `global.vi = vi` → `Object.assign(globalThis, { vi })`. Same runtime effect; the original form no longer type-checks once vitest globals types are loaded (ambient `let` declarations don't attach to `typeof globalThis`).
- `frontend/package.json` / `package-lock.json` — pinned `@types/react@^19.2.14`, `@types/react-dom@^19.2.3` as devDependencies.

## Test / build results

- `npm test`: **198 passed / 15 files** (baseline 198).
- `npm run build`: clean build, 1735 modules, only the pre-existing chunk-size warning.

## Concerns / deviations from brief

1. **`depth20Active` made optional instead of added to the fixture.** The brief asked to add all three fields to `createInstrumentState`. That conflicts with an existing test — `tests/hooks/useServerTradingSystem.test.tsx` "does not store phantom depth20Active state" asserts the initial state's `depth20Active` is `undefined`. The WS handler never maps `depth20Active` (full-state branch spreads `...inst` and omits it), no production code reads it, and the backend never sends it. Adding `depth20Active: false` to the fixture would have failed the test and changed runtime behavior. Making the field optional aligns the type with the actual runtime shape (per brief task #1) while keeping all 198 tests green. The fixture fix therefore added only the two genuinely-required fields.
2. **`generation`/`predictions`/`stats` also added to `InstrumentState`.** They were not in the brief's error list because TS reports only the *first* excess-property error per object literal; fixing `modelWeights` would have surfaced them next (verified empirically). They are real WS-snapshot fields (backend `stats_to_dto`, `analysis_service.predictions`, learning-engine `generation`), so they were added as optional to keep tsc at 0 without touching test semantics.
3. **Third commit for `@types/react` / `@types/react-dom`.** A clean `npm ci` does not install these optional peer deps (npm 11), so a fresh checkout reported 7 additional tsc errors in `components/ErrorBoundary.tsx` (class fields `state`/`props` unresolvable). Pinning them as devDependencies makes `npm ci` → `tsc --noEmit` → 0 errors reproducible. Type-only packages; no runtime/build impact.
4. **`tests/setup.ts` edited** (in the vitest-globals commit) — same runtime semantics, required to keep tsc clean once `vitest/globals` is loaded.
