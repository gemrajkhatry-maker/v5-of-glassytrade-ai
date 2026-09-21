# Domain docs

Index of the domain-level documentation an agent needs before touching the
trading core. Read the relevant doc before editing in that area.

## The trading pipeline (money-path)

- [`../architecture/fabio_amt_deterministic_flow.md`](../architecture/fabio_amt_deterministic_flow.md)
  — the deterministic Fabio AMT flow: Tick → AMTEngine → DecisionService →
  GatePipeline (1–4) → SignalBuilder/VA-fade → OMS.
- [`../architecture/ARCHITECTURE_AND_FLOWS.md`](../architecture/ARCHITECTURE_AND_FLOWS.md)
  — full component map across `quant/` and `backend/app/`.

## Data quality / provenance (single authority)

One rule: **`DecisionLoop._build_decision` is the only data-quality gate.**
Live OMS capability requires `TICK_EXACT` evidence; paper/replay marks
`PROXY_MODE`. `DecisionService` is quality-agnostic. See
`tests/quant/decision/test_single_data_quality_authority.py` before proposing
changes.

## Execution graphs (parallel agent work)

- [`../architecture/2026-09-21-v7-prune-execution-plan.md`](../architecture/2026-09-21-v7-prune-execution-plan.md)
  — current prune plan (waves, footprints, merge gates).
- [`../architecture/2026-09-11-v6-execution-graph.json`](../architecture/2026-09-11-v6-execution-graph.json)
  — the v6 graph format that v7 follows.

## Verification

Run the merge gate for any quant change:

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/architecture \
  tests/quant/decision tests/quant/execution tests/quant/runtime -q
```
