# Target Architecture Dependency Graph

**Updated:** 2026-09-24
**Rule:** Parallelize only when file ownership and durable interfaces are frozen. Serialize any task that can change the same contract, schema, composition root, generated artifact, or migration boundary.

## Completed foundation

```text
Task 0 baseline/hermetic/CI
  -> Task 1 safety/config/auth
  -> Task 2 canonical contracts/ports
  -> Task 3 journal/schema/projections
  -> Task 4 broker normalization
  -> Task 5 OMS/risk transactions
  -> Task 6 recovery/reconciliation
  -> Task 7 target runtime
  -> Task 8 protection/EOD
```

Tasks 0–11 are implemented in the isolated worktree. Runtime readiness remains gated until approved cutover evidence is complete. Task 12 is blocked at the retirement gate.

## Remaining graph

```text
                         +------------------------------+
                         | 9A backend schemas/presenter  |
                         | versioned REST/WS contracts  |
                         +---------------+--------------+
                                         |
             +---------------------------+---------------------------+
             |                                                       |
+------------v-------------+                         +---------------v--------------+
| 9B frontend projection    |                         | 10A migration tooling         |
| reducer/store/selectors   |                         | source DB -> target DB        |
+------------+-------------+                         +---------------+--------------+
             |                                                         |
             +---------------------------+-----------------------------+
                                         |
                         +---------------v--------------+
                         | 9C API/browser contract gate  |
                         | snapshot/delta/resync         |
                         +---------------+--------------+
                                         |
                 +-----------------------+-----------------------+
                 |                                               |
      +----------v-----------+                      +------------v-----------+
      | 10B shadow comparison |                      | 10C paper acceptance    |
      | no broker writes      |                      | session/EOD evidence     |
      +----------+-----------+                      +------------+-----------+
                 |                                               |
                 +-----------------------+-----------------------+
                                         |
                              +----------v-----------+
                              | 11 backup/cutover    |
                              | immutable release     |
                              +----------+-----------+
                                         |
                              +----------v-----------+
                              | 12 legacy retirement |
                              | final release gate   |
                              +----------------------+
```

## Safe parallel lanes

- **9A and 9B:** backend contract/schema work and frontend reducer/store work can proceed in parallel after the envelope shape is frozen. They must not edit generated files or `package.json` concurrently.
- **9B and 10A:** frontend projection and migration tooling are independent, provided migration tests use temporary databases and do not touch the runtime composition root.
- **10B and 10C:** shadow comparison and paper-session evidence can run in parallel after Task 9 schemas exist; neither may dispatch live orders.
- **Independent bottleneck triage:** lifecycle, runtime-duration, exit-manager, and frontend warning investigations can run in parallel as read-only/test-only work.

## Serialized boundaries

- Task 9A → 9C: generated contracts and browser assertions depend on the exact envelope.
- Task 10A → 10B/10C: shadow/paper evidence must use the verified migration manifest.
- Task 10B + 10C → Task 11: no cutover without complete evidence artifacts.
- Task 11 → Task 12: legacy code is retired only after immutable release and rollback evidence.
- Any changes to `RuntimeConfig`, `main.py`, composition roots, SQLite migrations, or generated frontend contracts are serialized even when their tests appear independent.

## Current bottlenecks

1. Built-in actor service: repeated upstream `APIError` before agent execution; this currently prevents real multi-agent implementation dispatch.
2. Full quant suite: no longer hangs after failed-start cleanup; remaining runtime is finite but dominated by deterministic replay tests.
3. Runtime suite: one pre-existing golden drift remains (`test_decide_golden_matches_committed_snapshot`); no automatic golden regeneration is allowed.
4. Exit manager: one pre-existing stop-loss close failure remains; it is a correctness gate, not a speed issue.
5. Chaos/performance: finite but slow (about 68 seconds in the measured group), with documented environment-bound skips.

## Execution protocol

- Keep one implementation writer per shared worktree.
- Use separate worktrees for genuinely independent implementation lanes when the actor service recovers.
- Run focused tests per lane, then one combined gate at each dependency boundary.
- Do not start live/paper cutover, migration against a production database, or broker dispatch from a parallel lane.
