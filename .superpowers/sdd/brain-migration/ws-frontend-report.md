# WS-FRONTEND Report — Honesty + decision authority (F-03/F-05/F-07/F-13/F-58)

**Status:** ✅ Complete. All 4 tasks implemented, tested, built, and committed on branch `migration/ws-frontend` in `/Users/apple/Documents/wt-ws-frontend`. No fabricated data remains in any UI path.

## Commits (4)

| Commit | Message | Scope |
|---|---|---|
| `c0140d2` | `fix(ui): remove gap-filling fabrication (F-03/F-05)` | `useServerTradingSystem.ts`, `ChartScene.tsx` (gap_fill listener), hook tests |
| `271ceb8` | `feat(ui): quantDecision is the primary decision card (F-07)` | `AIAnalysisPanel.tsx`, `App.tsx` (prop wiring), panel tests |
| `ed66889` | `refactor(ui): centralize IST offset constant (F-13)` | `ChartScene.tsx`, 3 chart managers, `CandleSeriesManager.test.ts` |
| `689e6ba` | `chore(ui): delete unused instruments store (F-58)` | `stores/instruments.ts` (deleted), `App.tsx` (symbol source refactor) |

## Test / Build Results

- **`npm test` (vitest):** 13 files, **190/190 passed** (0 failed). Added 7 tests:
  - 3 gap-fill tests (no fabricated candles from `gap_fill` history; gaps preserved; no `gap_fill` event emitted).
  - 4 quant-decision-precedence tests (primary card renders approved signal; no fabricated signal when `signal: null`; legacy AMT body collapsed + grayed; unwrapped when no quant decision).
- **`npm run build` (vite):** clean build in ~4.7s. Only pre-existing chunk-size warning (>500 kB bundle), no errors.
- **Note:** `tsc --noEmit` reports pre-existing type errors (ErrorBoundary React 19 class-component typing, `showPredictions` in `DEFAULT_CONFIG`/test fixtures vs `ChartConfig`, `createInstrumentState` missing newer optional `InstrumentState` fields, missing test-runner globals in `types.test.ts`). All are in files/lines untouched by this work; `npm test` + `npm run build` are the brief's verification and both pass.

## Task-by-task summary

1. **Gap-filling fabrication removed (F-03/F-05).** Deleted the forward-fill block in `mergeCandleData`, then deleted `mergeCandleData` itself (its only caller was the removed `gap_fill` branch). `history_loaded` messages with `_type === 'gap_fill'` now flow through the normal replace-with-sorted-history path — no candles are synthesized. Removed dead `recentMessageIdsRef` / `maxMessageCacheSize`. Removed the now-unreachable `gap_fill` event listener in `ChartScene.tsx` (the hook no longer dispatches that event). WS wire contract untouched.

2. **quantDecision is the primary decision (F-07).** `AIAnalysisPanel` accepts a new `quantDecision` prop (wired from `App.tsx`). When present, a prominent "Quant Decision" card renders first (approved/standing-by badge, signal type/entry/RR/SL/TP/confidence, or reason/phase when no signal) using only backend fields. The legacy AMT-driven body is wrapped in a collapsed, grayed `<details>` ("Legacy AMT Analysis"); without a quant decision the panel renders exactly as before via a pass-through wrapper. WS contract unchanged.

3. **IST offset centralized (F-13).** `IST_OFFSET_SECONDS` was already exported in `frontend/constants.ts`; replaced all 8 remaining `19800` literals (4 in `ChartScene.tsx`, 3 chart managers, 1 test) with imports of the constant. `grep 19800` now only hits `constants.ts` (and node_modules).

4. **Unused store deleted (F-58).** `stores/instruments.ts` deleted. Verified no imports remained except `App.tsx`, which imported `selectAllSymbols` for Tab/Shift+Tab navigation but the store was never populated (`allIds` always empty — effectively dead). `App.tsx` now derives `allSymbols` from the live WS hook state (`Object.keys(instruments)`), preserving keyboard navigation and making it actually functional for the first time.

## Concerns

- **Keyboards nav semantics (minor, expected):** `allSymbols` is now derived from live WS instruments rather than the (never-populated) store. This makes Tab/Shift+Tab functional where it was previously a no-op — behavior improvement, but a subtle change if anyone relied on the old (broken) state.
- **`tsc` baseline is dirty:** the repo's type-check is not clean independent of this work; not addressed here per the brief's scope (test + build are the gate). Worth a follow-up cleanup ticket.
- **Pre-existing `showPredictions` drift:** `ChartConfig` in `types.ts` lacks `showPredictions` though `DEFAULT_CONFIG` and test fixtures set it — a latent type mismatch unrelated to these tasks.
- **npm install:** required in the worktree (`frontend/` had no `node_modules`). Lockfile diff from install was reverted to keep commits clean.
