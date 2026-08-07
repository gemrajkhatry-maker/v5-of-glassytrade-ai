# WS-CRUFT — Report

**Branch:** `migration/ws-cruft` (worktree `/Users/apple/Documents/wt-ws-cruft`)
**Date:** 2026-08-07
**Status:** ✅ complete — working tree clean of cruft, tests green

## What was deleted

| Path | Reason |
|------|--------|
| `.env.bak` | Stale backup containing **secrets** (Dhan + OpenRouter API keys). `*.bak` now ignored. |
| `backend/.env.bak` | Stale NSE-mode env backup. `*.bak` now ignored. |
| `backend/tests/integration/test_e2e_trading_lifecycle.py.bak` | Stale backup — live source file exists. |
| `backend/tests/unit/domain/test_exchange_isolation.py.bak` | Stale backup — live source file exists. |
| `backend/shared.egg-info/` (4 files) | Stale build metadata. `*.egg-info/` now ignored. |

No tracked `.DS_Store` files existed (grep of `git ls-files` found none); the repo-root
`.gitignore` already had `.DS_Store` and `__pycache__/` rules. No tracked `__pycache__`.

## `.gitignore` additions

Added two lines to the Python section of the repo-root `.gitignore`:
- `*.egg-info/`
- `*.bak`

`.DS_Store` (root + nested) and `__pycache__/` were already covered and verified via
`git check-ignore`.

## RL checkpoints — `backend/rl_models/` finding

- **All 11 zips are TRACKED** (`git ls-files backend/rl_models`), added in the initial
  commit `b1d2ddc` (2026-02-15).
- They form a legitimate training history: `checkpoint_10000.zip` … `checkpoint_100000.zip`
  (10 steps) + `valentini_final.zip`. Each is ~150 KB (~3.2 MB total) — small, not bloat.
- Nothing in the codebase references `rl_models/` (no trainer code writes there), so nothing
  regenerates them — they are not the untracked/regenerable case.
- **Decision: KEPT all 11.** Not obviously stale; intentionally versioned; deleting tracked
  model artifacts is out of scope for a hygiene sweep.
- Documented via `backend/rl_models/README.md` (checkpoint status, sizes, and guidance to
  gitignore if the RL pipeline is reintroduced).

## Commits

1. `365ccd9` — `chore: remove repo cruft (.DS_Store, .bak, stale egg-info) + gitignore` (9 files)
2. `35f359c` — `chore: document rl_models checkpoint status` (1 file)

## Tests

`/Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/unit -q --tb=short --continue-on-collection-errors`
→ **1330 passed, 0 failed, 0 errors** (61 skipped). No source files touched.

## Concerns

- `.env.bak` had committed secrets; deleting it removes them from `HEAD`, but they remain in
  git history (`git log -p .env.bak`) on this branch and the shared remote history. If this
  repo is ever public/shared, rotate the Dhan + OpenRouter keys.
- The RL checkpoints remain versioned; if the intent was to keep them out of the repo, that's
  a separate decision (untracking ~3.2 MB). Flagged, not acted on, per brief.
- Not committed (per instructions): report/plan files under `.superpowers/`, `docs/superpowers/plans/`, `docs/*.md`.
