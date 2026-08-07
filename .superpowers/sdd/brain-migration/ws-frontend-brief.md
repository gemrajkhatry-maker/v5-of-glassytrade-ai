# WS-FRONTEND — Honesty + decision authority (audit F-03/F-05/F-07/F-13/F-58)

**Worktree:** `/Users/apple/Documents/wt-ws-frontend` (branch `migration/ws-frontend`). Work ONLY there. Node modules: `/Users/apple/Documents/v5-of-glassytrade-ai/node_modules` is at repo root; run `cd /Users/apple/Documents/wt-ws-frontend/frontend && npm install` if needed (it may already resolve via the root), then `npm test` (vitest) and `npm run build`.

**From:** brain-migration plan AUDIT ADOPTION → WS-FRONTEND. Scope: correctness items, NOT the full AIAnalysisPanel decomposition (that stays queued). Honor the architecture proposal non-negotiable #6: **No fabricated data in any UI**.

**Task 1 — Remove gap-filling fabrication (F-03/F-05).** `frontend/src/hooks/useServerTradingSystem.ts`:
- `mergeCandleData` (~lines 82-126) forward-fills missing candles with zero-volume flat bars at prior close → DELETE the forward-fill; missing candles stay gaps (charts render the gap).
- The `gap_fill` WS message branch: remove/ignore it (no fabricated candles).
- `recentMessageIdsRef` (line ~153): it's dead code (declared, never used) — delete it.
- Update the hook's tests in `frontend/src/tests/hooks/useServerTradingSystem.test.tsx` accordingly (remove/add tests asserting no gap-fill; any test asserting fabricated candles must be changed).

**Task 2 — One decision authority (F-07).** `frontend/src/components/AIAnalysisPanel.tsx` (or the panel it delegates to) renders `amtAnalysis` (legacy) + `auctionAnalysis` + `quantDecisionAnalysis` side by side. Make `quantDecision` (when present) the PRIMARY decision, and when a quantDecision exists, show `amtAnalysis` only as collapsed/grayed legacy. Do not remove the fields from the WS contract — this is a UI presentation change only. Update the affected tests in `frontend/src/tests/`.

**Task 3 — Centralize IST offset (F-13).** The magic `19800` (IST offset seconds) is duplicated in 5+ frontend files. Add `export const IST_OFFSET_SECONDS = 19800` to `frontend/src/constants.ts` and replace the literal usages with the constant (search `19800` across `frontend/src`).

**Task 4 — Delete unused store (F-58).** `frontend/src/stores/instruments.ts` (179 lines) is unused — verify `grep -rn "useInstrumentsStore\|stores/instruments" frontend/src` shows no imports (except its own), then delete the file and any test for it.

**Verify:** `cd /Users/apple/Documents/wt-ws-frontend/frontend && npm test` (all pass) and `npm run build` (clean). Report counts.

**Commits:** `fix(ui): remove gap-filling fabrication (F-03/F-05)`, `feat(ui): quantDecision is the primary decision card (F-07)`, `refactor(ui): centralize IST offset constant (F-13)`, `chore(ui): delete unused instruments store (F-58)`.

**Report:** `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/ws-frontend-report.md`. Reply: status, commits, test/build results, concerns.
