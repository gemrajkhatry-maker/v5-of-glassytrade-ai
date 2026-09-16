# WS-C: Test Integrity Ledger Brief (parallel session)

**Worktree:** `.worktrees/ws-c` (create: `git worktree add -b ws-c/test-integrity .worktrees/ws-c 25ea293f`) · **Base:** `25ea293f`
**Contract:** Read-only on `quant/`. The deliverable is a ledger document that WS-A/WS-B merge gates consume. No production code changes.

## Problem

The branch `architecture/design-level-refactoring` carries **36 pre-existing test failures** (vs 781 passed / 2 skipped at `25ea293f`). Nobody knows which are stale goldens vs real regressions. Both active workstreams need this classified before their merge gates.

## Steps

1. Reproduce the full failure set from the worktree:
   ```bash
   cd /Users/apple/Documents/v5-of-glassytrade-ai/.worktrees/ws-c
   PYTHONPATH=backend:. /Users/apple/Documents/v5-of-glassytrade-ai/.venv/bin/python -m pytest tests/quant -q 2>&1 | tail -60
   ```
   (Worktrees have no `.venv` — always use the main repo's interpreter by absolute path. Skip `test_signal_drop_reasons.py` if you want comparability with the recorded baseline run.)
2. For each of the 36 failures, classify exactly one of:
   - **STALE-GOLDEN** — assertion encodes superseded behaviour (e.g. the 3.0×tick spread cap before WS-A changes it; old certification traces before WS-B regoldens)
   - **REAL-REGRESSION** — failure indicates a genuine defect in current `quant/` code
   - **ENV/ORDER-DEPENDENT** — passes in isolation, fails in suite (known example: `test_half_trend_scale_parity.py` was order-dependent at baseline)
   - **FLAKY** — outcome varies across identical runs (run twice to prove)
3. Write the ledger to `docs/reviews/2026-09-16-test-integrity-ledger.md`:
   one row per failure — test id, class, one-line root cause, owner workstream (WS-A/WS-B/nobody), recommended action (fix / regolden / delete / quarantine).
4. Cross-link: note which failures WS-A's Gate-1 repoint and WS-B's regolden are expected to resolve, so their PRs can be checked against your ledger.

## Done when

Every one of the 36 failures has a class and a recommended action; the ledger exists at the path above; `quant/` shows zero diff.
