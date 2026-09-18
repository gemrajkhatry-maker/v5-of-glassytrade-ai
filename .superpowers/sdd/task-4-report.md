# Task 4 Report

## Files

- `quant/runtime.py`
- `quant/multi_engine.py`
- `quant/transitions.py`
- `quant/decision/gap_architecture.workflow.json`
- `quant/decision/gap_architecture.workflow.html`
- `tests/quant/runtime/test_eventstore_failure_consistency.py`
- `tests/quant/runtime/test_snapshot_projection.py`
- `tests/architecture/test_gap_architecture_contract.py`

No changes were required in `quant/event_store.py`, `quant/ws_adapter.py`, or
`backend/app/api/websocket/gameloop.py`; their existing boundaries use the
coordinator snapshot and adapter path after the canonical-state changes.

## Red / Green

Initial focused red run:

```text
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/runtime/test_eventstore_failure_consistency.py tests/quant/runtime/test_snapshot_projection.py tests/architecture/test_gap_architecture_contract.py -q
4 failed, 1 passed
```

The failures demonstrated lifecycle advancement after append failure, mutable
snapshot fallback, and missing architecture nodes/edges.

Focused green run:

```text
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/runtime/test_eventstore_failure_consistency.py tests/quant/runtime/test_snapshot_projection.py tests/architecture/test_gap_architecture_contract.py tests/quant/test_event_store_roundtrip_real.py tests/quant/test_event_appender_boundary.py tests/quant/test_ws_contract.py tests/quant/runtime/test_ws_adapter.py tests/quant/execution/test_paper_failure_modes.py -q
37 passed in 0.55s
```

Additional checks:

```text
git diff --check
passed
python3 -m json.tool quant/decision/gap_architecture.workflow.json
passed
```

## Design Decisions

- Durable append remains the commit point for lifecycle events. Failed
  `PositionOpened`, `PositionReduced`, and `PositionClosed` appends mark the
  runtime degraded and do not advance the in-memory canonical lifecycle state.
- Non-lifecycle operational events retain their existing cache behavior when
  persistence fails; their absence from the EventStore still makes the fold
  canonical state authoritative.
- Snapshot fold failures return an empty canonical projection with
  `riskState.canonicalState=DEGRADED_CANONICAL_FOLD_UNAVAILABLE`; mutable
  `engine.state` is never substituted.
- Append failures expose
  `riskState.canonicalState=DEGRADED_EVENT_APPEND_FAILED` and the exception
  type. Existing entry reconciliation/degraded flags remain the blocking
  signal for live entry handling.
- Unmatched `PositionReduced` replay remains a no-op, while the logger emits
  structured `event_type`, `symbol`, `position_id`, `order_id`, and `sequence`
  fields.

## Architecture Edges

- `SignalBuilder -> Durable Order Intent`
- `Durable Order Intent -> OMS / Broker`
- `OMS / Broker -> Normalized Fill`
- `Normalized Fill -> Reconciliation`
- `Reconciliation -> Position Manager`
- `Position Manager -> EventStore`
- `EventStore -> Canonical Projection`
- `Canonical Projection -> WebSocket / UI`
- `DecisionContext -.-> Narrative`, dashed and advisory-only

The artifact explicitly describes a durable event-backed lifecycle and does not
claim exact Fabio parity.

## Concerns

- The broader `tests/quant/runtime tests/architecture` run remains affected by
  known unrelated dirty-worktree failures, including DTO contract drift,
  existing layer-bypass/silent-except findings, and MagicMock risk fixtures.
- The full Task 4 implementation is intentionally fail-closed for canonical
  lifecycle snapshots; operational fields may still be present, but consumers
  must honor the explicit degraded marker before permitting live entries.

## Review Follow-up

Focused red run after the review findings:

```text
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/architecture/test_gap_architecture_contract.py tests/quant/runtime/test_eventstore_failure_consistency.py tests/quant/runtime/test_snapshot_projection.py -q
5 failed, 7 passed in 0.52s
```

The failures covered missing rendered durable SVG topology, pre-append lifecycle
publication, live-mode entry blocking, unmatched close handling, and absent
optional snapshot fields.

Focused green run:

```text
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/architecture/test_gap_architecture_contract.py tests/quant/runtime/test_eventstore_failure_consistency.py tests/quant/runtime/test_snapshot_projection.py -q
13 passed in 0.40s
```

Task 4 regression set:

```text
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/runtime/test_eventstore_failure_consistency.py tests/quant/runtime/test_snapshot_projection.py tests/architecture/test_gap_architecture_contract.py tests/quant/test_event_store_roundtrip_real.py tests/quant/test_event_appender_boundary.py tests/quant/test_ws_contract.py tests/quant/runtime/test_ws_adapter.py tests/quant/execution/test_paper_failure_modes.py -q
43 passed in 0.83s
```

The HTML contract now parses rendered `data-node-id`, `data-edge-from`, and
`data-edge-to` attributes against the JSON topology; the narrative edge remains
dashed and advisory-only. Lifecycle events append before bus/journal publication,
and failed lifecycle appends set the shared entry guard in every execution mode.
Unmatched closes are replay-tolerant with structured `order_id` diagnostics.
Degraded snapshots use optional engine fields safely and retain the explicit
degraded marker.

Remaining limitations: this follow-up does not claim live readiness; the existing
broader dirty-worktree failures and known DTO failures remain outside this change.
