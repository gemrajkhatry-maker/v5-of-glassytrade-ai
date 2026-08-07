# WS-TS — Fix the 13 pre-existing frontend `tsc --noEmit` errors

**Worktree:** `/Users/apple/Documents/wt-ws-ts` (branch `migration/ws-ts`). Work ONLY there.

**Context:** `npx tsc --noEmit` in `frontend/` currently reports 13 pre-existing errors (baseline — untouched by earlier waves). Goal: `tsc --noEmit` clean, while `npm test` and `npm run build` stay green.

**The errors (baseline):**
- `constants.ts:28`, `tests/components/ChartScene.test.tsx:70`, `tests/hooks/useServerTradingSystem.test.tsx:39`, `tests/integration/auction-render.test.tsx:41`, `tests/integration/trading-flow.test.tsx:110` — `'showPredictions' does not exist in type 'ChartConfig'`.
- `hooks/useServerTradingSystem.ts:15` — a `createInstrumentState`-style fixture object missing `auctionAnalysis`, `quantDecisionAnalysis`, `depth20Active`.
- `tests/components/MarketSidebar.test.tsx:22`, `tests/integration/trading-flow.test.tsx:71` — `'modelWeights' does not exist in type 'InstrumentState'`.
- `tests/types.test.ts:4,17` — `describe`/`it` not found (vitest globals types not wired).

**Task:**
1. In `frontend/src/types.ts` (and `ChartConfig` wherever it's defined — likely `components/chart/*` or `types.ts`): add the missing optional fields the code/tests already use — `showPredictions` on `ChartConfig`, `modelWeights` on `InstrumentState`, and confirm `auctionAnalysis`, `quantDecisionAnalysis`, `depth20Active` exist on `InstrumentState` (add if missing). Match the actual runtime shapes (they come from the WS snapshot).
2. In `hooks/useServerTradingSystem.ts:15` fixture: add the three missing fields to the `createInstrumentState` fallback so the type matches.
3. `tests/types.test.ts`: add vitest types — in `tsconfig.json` set `"types": ["vite/client", "vitest/globals"]` (or add a `vitest` types entry / a `src/vite-env.d.ts` reference) so `describe`/`it`/`expect` resolve. Prefer the tsconfig `types` approach; ensure it doesn't break the build.
4. Do NOT change behavior. Do NOT weaken types (no `any` escapes).

**Verify:** `cd frontend && npx tsc --noEmit` → **0 errors**; `npm test` → all green (198 baseline); `npm run build` → clean.

**Commits:** `fix(ui): align types with WS snapshot shape (showPredictions/modelWeights/analysis fields)`, `fix(ui): wire vitest globals in tsconfig`.

**Report:** `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/ws-ts-report.md`. Reply: status, commits, `tsc` error count before/after, test/build results, concerns.
