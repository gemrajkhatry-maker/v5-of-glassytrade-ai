# Fabio AMT Simplification — Multi-Agent Program Handoff

**Date:** 2026-09-16 · **Base commit:** `25ea293f` (S3 dead-code prune, already landed on `architecture/design-level-refactoring`)
**Governance:** tradexv2-org structure. Council decisions already taken by product owner:

| Decision | Value |
|---|---|
| S3 dead code | ✅ committed (`25ea293f`) |
| Gate 1 canonical semantics | **Production wins**: 2.0×tick spread cap + NSE/MCX blackout |
| Gate 3 → 2 models | ✅ in scope (TREND / MEAN_REVERSION, certification regoldens) |
| Execution mode | Parallel sessions on git worktrees |

## Teams (tradexv2-org mapping)

| Workstream | Branch / worktree | Team | Brief |
|---|---|---|---|
| **WS-A** Gate 1–2 convergence | `ws-a/gate-convergence` → `.worktrees/ws-a` | Architecture (Chief Architect + Domain Eng) | `docs/plans/2026-09-16-ws-a-gate-convergence-brief.md` |
| **WS-B** Gate 3 → 2 models | `ws-b/gate3-two-models` → `.worktrees/ws-b` | Research + Domain | `docs/plans/2026-09-16-ws-b-gate3-two-models-brief.md` |
| **WS-C** Test integrity ledger | `ws-c/test-integrity` → `.worktrees/ws-c` | Quality (Test Eng + Integration Validator) | `docs/plans/2026-09-16-ws-c-test-integrity-ledger-brief.md` |

## Launching a session

Open a new Freebuff session per workstream and paste as the first message:

```
Work in /Users/apple/Documents/v5-of-glassytrade-ai/.worktrees/ws-a
Read /Users/apple/Documents/v5-of-glassytrade-ai/docs/plans/2026-09-16-ws-a-gate-convergence-brief.md (absolute path — worktrees were cut before the briefs were committed) and execute it fully.
```
(swap `ws-a` → `ws-b` / `ws-c` and the brief filename accordingly)

**Environment note:** worktrees have no `.venv`. Always invoke the main repo's interpreter by absolute path from the worktree cwd:
`PYTHONPATH=backend:. /Users/apple/Documents/v5-of-glassytrade-ai/.venv/bin/python -m pytest ...`

## Merge order & review gates

1. **WS-C** merges first or second (it's docs-only) — its ledger defines the failure baseline all PRs are judged against.
2. **WS-A** next: Gate 1–2 tests repointed, flat `gates_session_position.py` deleted, 2 docs fixed.
3. **WS-B** last: depends on WS-A's stable gate tests; shares `docs/amt/fabio_decision_pipeline.md` (Gate-3 section only).
4. Every PR gate: failure-set diff vs `25ea293f` must be explained row-by-row against the WS-C ledger — identical-or-better, never silently worse. Ruff clean on touched files.

## Known hazards (from this program's discovery phase)

- `docs/reviews/2026-09-10-audit-appendices/audit-sizing-context.md:315` claims the whole gate pipeline is bypassed on the E2E path — WS-B must verify which decision path is live before regoldening.
- 3 prior audit claims were already proven stale (LiveOMS alive, no displacement duplicate, TickFootprintAccumulator wired) — verify before trusting any audit row.
- `LiveOMS.add_pyramid` has ~70 unreachable lines behind an unconditional raise (deferred E9 work) — deliberately out of scope.
