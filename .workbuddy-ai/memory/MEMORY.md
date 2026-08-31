# Project conventions — v5-of-glassytrade-ai

## SDD workflow (spec-driven development)

This repo runs fix work in **waves** with a fixed layout. Follow it rather than improvising.

| Artifact | Location | Committed? |
|---|---|---|
| Plan doc | `docs/superpowers/plans/<date>-<name>.md` | **Yes** |
| Task briefs | `.superpowers/sdd/<wave>/task-N-brief.md` | No — gitignored |
| Lane reports | `.superpowers/sdd/<wave>/lane{A,B,C,D}-report.md` | No |
| Progress ledger | `.superpowers/sdd/progress.md` (append) | No |

`.superpowers/` is gitignored (`.gitignore:118`). Only plan docs are tracked. Don't try to
`git add .superpowers` — it fails, and prior waves don't have them committed either.

Conventions inside a wave:
- **Lanes** A–D run in parallel worktrees (`../v5-<wave>-lane{A..D}`) on branches
  `<wave>-{A..D}`. Lane file ownership must be disjoint; note any overlap in the plan.
- **Stage only explicit paths. NEVER `git add -A`** — the working tree carries unrelated user WIP.
- Every task **starts with a failing test** that reproduces the defect, then fixes it. "Did it
  work" is decided by the suite, not by inspection.
- Wave 5 is `fix/w5-money-safety`, base `2602fe0`. Current work branch is `feature/wire-money-path`.

## `ponytail:` comment tag

`# ponytail:` (or `// ponytail:` in TS) marks a **deliberate, deferred design decision** —
a known shortcut or ceiling someone chose and wants visible. ~30 occurrences across
`quant/`, `frontend/`, `tests/`. Use it when you intentionally pick a limit, skip a
generalization, or leave a boundary float. It is not a TODO; it means "decided, for now, on purpose."

## Test environments

- Root `.venv/bin/python` (3.13) runs both `tests/quant` and `backend/tests`.
- `backend/venv/` also exists; prefer root `.venv` for consistency.
- Frontend: `cd frontend && npm test` (vitest).

## Known baseline failures (don't "fix" as drive-by)

- `frontend/tests/types.test.ts` — phantom-field guard fails (`direction`, `underlyingPrice`
  still in `AMTAnalysis`). Pre-existing.
- `tests/quant/test_production_correctness.py` — some routing ImportErrors at certain bases.

## Architecture one-liner

`quant/` is the real system (pure, zero backend imports). `backend/` is a FastAPI transport
shell over it — `backend/app/domain/` is intentionally near-empty. `brokers/` is a separate
hexagonal Dhan library. `frontend/` is a renderer with no business logic.
