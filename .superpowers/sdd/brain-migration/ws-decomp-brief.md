# WS-DECOMP — Decompose AIAnalysisPanel (audit F-20)

**Worktree:** `/Users/apple/Documents/wt-ws-decomp` (branch `migration/ws-decomp`). Work ONLY there.

**Context:** `frontend/src/components/AIAnalysisPanel.tsx` is a 1,525-line god component with 40+ conditional render blocks and inline IIFE components (audit F-20). The audit recommends 8–10 sub-components. The panel renders: decision card, market structure, volume profile levels, order flow, CVD, LLM analysis, overseer action, probability agents, risk state, diagnostics. The WS-FRONTEND workstream already made `quantDecision` the primary decision card — do not regress that.

**Task:** Decompose `AIAnalysisPanel.tsx` into focused sub-components under `frontend/src/components/ai/` (that dir already exists with `index.ts`, `EquityPanel.tsx`, `RiskStateDisplay.tsx`, `DecisionHistoryPanel.tsx`):
- Extract at least 8 presentational sub-components with one responsibility each (e.g. `MarketStateCard`, `ValueAreaCard`, `OrderFlowCard`, `CVDCard`, `LLMAnalysisCard`, `OverseerCard`, `AgentProbabilityCard`, `DiagnosticsPanel`). Keep all data-shape handling and logic in the parent (or a small typed `AIAnalysisPanel.types.ts`); sub-components are presentational.
- NO behavior change. NO change to the WS wire contract. Keep the exact same rendered output (same fields, same conditional logic — just relocated).
- Keep the existing tests passing (`frontend/src/tests/components/AIAnalysisPanel.test.tsx`) and add tests for ≥2 of the extracted sub-components.
- Update the barrel `frontend/src/components/ai/index.ts`.

**Verify:** `cd /Users/apple/Documents/wt-ws-decomp/frontend && npm install` (if needed) then `npm test` (all green, incl. the 190 from the previous wave) and `npm run build` (clean).

**Commits:** split into logical chunks (e.g. `refactor(ui): extract MarketState/ValueArea/OrderFlow cards`, `refactor(ui): extract CVD/LLM/Overseer/Agent cards`, `refactor(ui): extract diagnostics + types`, `test(ui): sub-component tests`).

**Report:** `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/ws-decomp-report.md`. Reply: status, commits, test/build results, concerns.
