# v7 Prune Execution Plan — parallel multi-agent schedule

Source of truth: [`2026-09-21-v7-prune-execution-graph.json`](./2026-09-21-v7-prune-execution-graph.json).
Resolve waves with `make plan-json`-style resolution (see `scripts/plan_waves.py`).

## Baseline

- Commit `9c078c20` — data-quality propagation fix, 473 passing focused tests.
- Live outage root cause fixed; **two** data-quality authorities still exist (N3).

## Waves

**Wave 1 (parallel — disjoint file footprints):**
- **N3** — collapse dual data-quality gates (money-path; RED-first)
- **N1** — delete `quant/sidecars/`, `quant/modeling/` (+ their tests)
- **N2** — delete dead modules; fold forecast access into one provider
- **N9** — repo hygiene: gitignore, untrack artifacts, fix `AGENTS.md`

**Wave 2 (after N3):**
- **N4** — flatten the decision gates home (kill re-export wrappers)
- **N5** — verify Dhan adapter split is port-oriented; dedupe only true helpers

**Wave 3 (after N1+N2+N4):**
- **N6** — one constants module; delete `quant/config/` + dead aliases

**Any wave:**
- **N8** — persistence-layer audit doc (verify-only; no deletion without its own plan)

## Collision rules

Per the graph conventions: one node per worktree (`agent/n1` … `agent/n9`);
`quant/runtime.py` is owned by N2 (wave 1) then N6 (wave 3) — never concurrently;
`quant/decision/gates_edge.py` import swaps belong to N6 only; N4 moves files, N6
rewrites imports inside them.

## Merge gate (every node)

1. Focused tests for the node
2. `tests/architecture/`
3. `tests/quant/decision/`
4. `tests/quant/execution/`

## Preserved by design

AI/LLM integration stays: `quant/llm/` (advisor, narrative, bridge),
`quant/decision/timesfm_{advisor,engine,agents,client,risk,option_selector,forecast_factory}.py`,
`quant/wiring_advisor.py`. Only provably-dead AI paths are removed
(`quant/sidecars/` — zero importers; `quant/modeling/` — test-only;
`timesfm_sizing.py` — orphaned after dynamic-sizing removal).

## Provenance of findings

All deletion targets were verified by import scan against production + tests
(`grep -rlw` over `quant backend/app tests scripts`, vendored trees excluded).
Zero-importer files: `exit_signal.py`, `coordinator_view.py` (Protocol), all of
`quant/sidecars/`. Test-only importers: `ws_contract.py`, `timesfm_sizing.py`,
`paper_trading_contracts.py`, all of `quant/modeling/`, `dataset_generator.py`.
