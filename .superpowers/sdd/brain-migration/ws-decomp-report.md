# WS-DECOMP Report — Decompose AIAnalysisPanel (audit F-20)

**Status:** COMPLETE — decomposition landed, all tests green, build clean.

## What changed

`frontend/components/AIAnalysisPanel.tsx` was decomposed from **1,589 → 258 lines** into
**15 presentational sub-components** under `frontend/components/ai/` (12 new + 3 pre-existing:
`EquityPanel`, `RiskStateDisplay`, `DecisionHistoryPanel`).

New components (one responsibility each):

| Component | Responsibility |
|---|---|
| `QuantDecisionCard` | PRIMARY quant decision card (SL/TP/RR/confidence, Approved/Standing By) |
| `MarketStateCard` | 01 Session & Leg regime badges (DEAD/IMBALANCED/PROBING, displacement) |
| `LocationCard` | 02 Volume-profile bar (VAH/VAL/POC/HPOC/DPOC/LegPOC/LTP markers, overflow) |
| `AggressionCard` | 03 Volume Aggression — delta score, bar, bull/bear control |
| `OrderFlowCard` | 03b Market Metrics — OFI/CVD slope bars, divergence, balance, shape, spread |
| `InitialBalanceCard` | 03d IB + Breaks — range, size class, 1.5x/2x targets, proximity, breakouts |
| `LvnPlayCard` | 03e LVN velocity play |
| `AbsorptionCard` | 03d Absorption & Large Prints, swing delta |
| `VwapContextCard` | 03f VWAP + sigma meter + gap/bias/velocity |
| `AgentProbabilityCard` | 04 Probability engine (P(target), timing/size, drive cycle, formulas) |
| `OverseerCard` | 04b Overseer action/reason |
| `TradePlanCard` | 04c Open positions (SL/TP/R-mult, partial TP, time held) |
| `RecentExitsCard` | Recent closed trades (last 5, close reason, duration) |
| `DiagnosticsPanel` | Diagnostics tier (structure donut, POC signal, VWAP events, rule checklist) |
| `ModelIoFooter` | MODEL I/O footer (direction dot, decision text, rationale dump) |

Barrel `frontend/components/ai/index.ts` updated with all 18 exports.

## Behavior guarantees

- **ZERO behavior change.** All JSX was relocated verbatim; the parent retains all derived
  data logic (`currentLtp` fallback, `effectiveAnalysis`/`displayAnalysis`, `aggScore`,
  `deltaScore`, `statusColor/statusBg`, `liveMarketState`, `openPnl`). Only dead code
  removed: unused memoized `vah`/`val` strings (never referenced in render) and 6 unused
  lucide imports.
- **WS-FRONTEND `quantDecision` primary is not regressed.** `QuantDecisionCard` renders
  as the primary card before `LegacyAmtWrapper`, which still collapses the legacy AMT body
  behind a grayed `<details>` when a quant decision is present (verified by the existing
  F-07 tests).
- **WS wire contract untouched.** No change to `types.ts` or any data shape.

## Tests

- Baseline before refactor: **190 passed / 13 files**.
- After refactor: **198 passed / 15 files** — all 190 existing tests still green, including
  the 4 AIAnalysisPanel F-07 quant-precedence tests and the full WS integration tests
  (`auction-render`, `trading-flow`).
- New tests added (≥2 required, got 8 assertions across 2 files):
  - `tests/components/ai/QuantDecisionCard.test.tsx` (3 tests)
  - `tests/components/ai/AgentProbabilityCard.test.tsx` (5 tests)

## Build

- `npm run build`: **clean** (`vite build` succeeded, 1735 modules). Pre-existing
  >500 kB chunk warning only.

## Typecheck

- `tsc --noEmit` shows only pre-existing errors in untouched files
  (`ErrorBoundary.tsx`, `constants.ts`, legacy tests). **Zero errors in the refactored
  files** (`components/AIAnalysisPanel.tsx`, `components/ai/*`, new tests).

## Commits (5, on `migration/ws-decomp`)

1. `198e542 refactor(ui): extract QuantDecision/MarketState/Location/Aggression cards`
2. `ff8d85d refactor(ui): extract OrderFlow/InitialBalance/LVN/Absorption/VWAP cards`
3. `0138a64 refactor(ui): extract Probability/Overseer/TradePlan/Exits/Diagnostics/ModelIO cards`
4. `32a7fcc refactor(ui): wire AIAnalysisPanel to extracted ai sub-components`
5. `d525773 test(ui): add QuantDecisionCard and AgentProbabilityCard tests`

Each commit is self-consistent (barrel extended incrementally; parent rewired only in #4).
Working tree clean. The incidental `npm install` `package-lock.json` churn was reverted.

## Concerns / notes

- **Path divergence:** the brief referenced `frontend/src/components/ai/`, but this worktree
  uses `frontend/components/ai/` (no `src/`). Decomposition followed the worktree's actual
  existing structure.
- **Sub-component count:** 15 extracted (requirement was ≥8).
- **`DiagnosticsPanel` is large (347 lines)** because it bundles the collapsed tier plus the
  rule-checklist. It is internally one collapsed `<details>` section; splitting it further
  would have risked subtle whitespace/structure drift for no readability gain. Can be split
  (e.g. `RuleChecklistCard`) in a follow-up if desired.
- **Typecheck noise is pre-existing** — the repo's `tsconfig` (extends `expo/tsconfig.base`)
  doesn't cover all test globals; that predates this change.
