# Phase 0 — Multi-Agent Ownership Matrix and Baseline

> Date: 2026-09-07
> Branch: `refactor/phase0-runtime-truth`
> Base commit: `1589060b37594bd66ab88e276de1860461624a6f`
> Status: Phase 0 prepared; implementation work has not started.

## Protected working-tree changes

These changes existed before Phase 0 preparation and are intentionally left in the primary worktree. Agents must not overwrite, stage, reset, stash, or commit them:

| Path | State | Owner during implementation |
|---|---|---|
| `quant/execution/ledger_reconstruction.py` | modified | Ledger domain owner; reconcile against existing edits before changing |
| `quant/multi_engine.py` | modified | Coordinator integration owner; reconcile against existing edits before changing |
| `tests/quant/execution/test_ledger_reconstruction.py` | untracked | Ledger domain owner; preserve existing tests and extend carefully |

The isolated agent worktrees are based on the clean base commit, not these uncommitted changes. Integration must explicitly port or merge the protected changes after reviewing their diffs.

## Baseline environment

- Python: `3.13.11`
- Python executable: `.venv/bin/python`
- Test configuration: root `pytest.ini`, `PYTHONPATH=backend:.`
- Package manager/dependency changes: none

## Baseline command and result

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest \
  tests/quant/execution/test_ledger_reconstruction.py \
  tests/quant/test_multi_engine_startup.py \
  tests/quant/test_partial_fold_reconcile.py \
  tests/quant/test_periodic_reconciliation.py \
  -q --no-header
```

Result:

```text
26 passed in 3.61s
```

Exit status: `0`.

## Agent ownership matrix

| Agent | Branch/worktree | Primary ownership | Deliverable | Dependencies |
|---|---|---|---|---|
| A — Ledger domain | `agent/ledger-contract` | `quant/execution/ledger_reconstruction.py`; focused ledger tests | Canonical reconstruction contract, edge-case matrix, deterministic/idempotent behavior | None; must review protected primary-worktree edits during integration |
| B — Persistence/storage | `agent/persistence-ledger` | `quant/persistence_bridge.py`; `backend/app/infrastructure/storage/database.py`; storage tests | Canonical fill emission, stable ordering, duplicate/conflict handling | Align side vocabulary and IDs with Agent A before implementation |
| C — Coordinator integration | `agent/coordinator-recovery` | `quant/multi_engine.py`; coordinator/startup tests | Ledger-authoritative restoration and readiness/quarantine integration | Requires Agent A/B contract decisions; protected primary edit must be reconciled |
| D — Safety/concurrency | `agent/safety-concurrency` | Lifecycle, failure-injection, readiness, and runtime audit tests | Race/resource/leak/double-close coverage; production fixes only when proven | Can work in parallel on non-overlapping tests; coordinate with C for production changes |
| E — Replay/certification | `agent/replay-certification` | Replay/golden/certification tests and operational notes | Restart/replay convergence and deterministic recovery evidence | Runs after A–C integration; no production ownership by default |

## Parallel execution protocol

1. A and B work in parallel on isolated branches.
2. C starts architectural review and test scaffolding, but production integration waits for A/B contract alignment.
3. D runs independent safety tests in parallel and reports defects without changing shared production files unless assigned.
4. E begins fixture design in parallel, then executes certification after integration.
5. Integration order: A → B → C → D → E.
6. After each integration: inspect diff, run focused tests, and verify only owned files changed.
7. No commits, pushes, or PRs are authorized by Phase 0.

## Phase 0 exit criteria

- [x] Current branch and base commit recorded.
- [x] Existing modified/untracked files identified and protected.
- [x] Focused baseline test command recorded.
- [x] Focused baseline passes: 26/26.
- [x] Agent ownership and file boundaries recorded.
- [x] Isolated worktrees prepared.
- [ ] Agent implementation branches complete — next phase.
