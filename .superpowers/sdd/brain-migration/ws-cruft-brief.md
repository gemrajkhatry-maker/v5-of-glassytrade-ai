# WS-CRUFT — Repo hygiene sweep

**Worktree:** `/Users/apple/Documents/wt-ws-cruft` (branch `migration/ws-cruft`). Work ONLY there.

**Context:** The repo accumulated non-source cruft during the migration. Clean it up. GOAL: no tracked cruft, .gitignore catches it going forward, and no source artifacts accidentally deleted.

**Tasks:**
1. **`.DS_Store` files**: find and `git rm` any TRACKED `.DS_Store` (e.g. `quant/.DS_Store`, `brokers/.DS_Store`, root `.DS_Store`). Add `.DS_Store` to the repo-root `.gitignore` (check if `.gitignore` already has it).
2. **`.bak` files**: find tracked `*.bak` (3 reported) — inspect each; if it's a stale backup of a source file that exists, delete; if it's referenced, keep + report.
3. **`*.egg-info` dirs**: `shared.egg-info/`, `backend.egg-info/` (if any) are stale build metadata — `git rm -r` if tracked; add `*.egg-info/` to `.gitignore`.
4. **`backend/rl_models/checkpoint_*.zip`** (11 zips): CHECK FIRST — `git ls-files backend/rl_models | head`. If tracked, they are RL model artifacts (possibly intentionally versioned); do NOT delete tracked model checkpoints unless they're clearly stale duplicates — report sizes + git status and only delete if obviously superseded (e.g. checkpoint_100000.zip is the newest — keep; older ones may be a legit history). If they are NOT tracked (untracked artifacts), leave them but add `backend/rl_models/*.zip` to `.gitignore` only if they're regenerable — verify by checking the trainer code writes checkpoints there.
5. **`__pycache__`**: verify `.gitignore` covers `__pycache__/` (it should); do not commit pycache.
6. Verify `git status --short` after: only intended deletions/ignores.

**Verify:** `git status` clean of cruft; `cd backend && /Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/unit -q --tb=short --continue-on-collection-errors` still 0 failed / 0 errors (nothing source-related changed).

**Commits:** `chore: remove repo cruft (.DS_Store, .bak, stale egg-info) + gitignore`, `chore: document rl_models checkpoint status`.

**Report:** `/Users/apple/Documents/v5-of-glassytrade-ai/.superpowers/sdd/brain-migration/ws-cruft-report.md` (what was deleted, what was kept + why, the rl_models finding). Reply: status, commits, test counts, concerns.
