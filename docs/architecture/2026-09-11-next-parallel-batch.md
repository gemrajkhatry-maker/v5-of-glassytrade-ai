# Next parallel batch from v6 execution graph

**Graph:** `docs/architecture/2026-09-11-v6-execution-graph.json`
**Resolver:** `scripts/triage_parallel_work.py`
**Readout date:** 2026-09-11

## What the graph says once DEC-2 is marked done

If you only mark `DEC-2` merged, the graph still shows a 9-wave dependency tail — but that is
**because only 15 edges were loaded**. The node list has 36 nodes and the earlier plan had 41 edges.
The 15-edge snapshot in the file under-represents the real dependency structure, so this readout is
best treated as “what is unblocked right now because nothing is marked merged”, not “the final shape”.

Two things are unambiguous even from the current file:

1. **Two hard file collisions still block true parallelism:**
   - `B1` vs `D4` both touch `quant/execution/risk.py`
   - `A4` vs `E1` both touch `quant/runtime.py`

2. The **highest-leverage open money-path work** is not the largest file edits — it is the smallest
   ones that posture the system toward fail-safe behavior before any structural rewrite.

## What I would run next, if I were staffing this today

### Tier 1 — no prerequisites, no file collisions, directly posture the money path or correctness

- **`DEC-2`** — decision, no files. Still open in the current graph. This is the gate the live-money
  nodes say they need before they touch `IBrokerPort` or `LiveOMS`.
- **`C1` family completeness** — the current file still lists `C1`’s downstream as `A1` and `A2`,
  but the aggression direction work you already ran was on a subset. Before a full `C1` lands, the
  graph should explicitly record the files your C1 touch set owns, so parallel schedulers do not let
  another node edit the same aggression files at the same time.
- **`B3`** — fail-closed portfolio cap + degraded readiness surface. Footprint:
  `quant/execution/portfolio_risk.py`, `quant/execution/readiness.py`, `quant/ws_contract.py`.
  Disjoins from `B1` and `D4` only if `risk.py` is not touched here.
- **`A6`** — route every stop write through `ProtectiveStopState.tighten()`. Footprint:
  `quant/execution/protective_stop.py`, `quant/position_manager.py`.

These four are a coherent early batch: decision first, then the stop-integrity posture, then the
sizing/degraded-readiness posture.

### Tier 2 — run after the Tier-1 collision set is cleared

- **`B1`** or **`D4`** — not both in the same wave. One of them owns `quant/execution/risk.py`
  today in the graph.
- **`A4`** or **`E1`** — not both in the same wave. One of them owns `quant/runtime.py` today in the
  graph.

### Keep out of this batch

- **`E1`, `E2`, `E3`** — structural/god-class decomposition. These are high-effort and touch the
  files that the money-path and stop-integrity nodes need for the earliest posture changes. Put them
  after the money-path collisions are resolved.
- **`G3`** — frontend render decoupling. Unverified premise (P2-19), and it does not move the live
  readiness flag.
- **`H5`, `H6`** — terminal. Nobody starts them until the earlier phase gates are green.

## Suggested next action

If you want the next move to be the smallest parallel-safe step that actually improves the safety
posture, pick this:

1. Mark `DEC-2` merged in `MERGED_NODES.md`
2. Re-run `scripts/triage_parallel_work.py`
3. Take the Tier-1 set from that output as the next batch, with RED tests first

If you want to keep going on the aggression / Gate 3 correctness path instead, the graph still needs
the full `C1` footprint declared so it does not collide with any later stop-identity or edge-gating
node.

## One explicit warning

This batch suggestion assumes the current graph is the schedule. It is not yet reconciled against the
full 41-edge dependency set from the earlier parallel execution plan. If that 41-edge set is the one
you want to run from, regenerate the JSON from `scripts/plan_waves.py` or the original `make plan`
output and re-run the triage script on that file before assigning any agents.
