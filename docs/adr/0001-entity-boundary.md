# ADR-0001: Entity boundary — contract over merge

Status: Accepted (Plan E Task 2).

## Context

Three type families coexist on purpose:

- **Engine** (float-fast): `quant.decision.signal_builder.Signal`
  (LONG/SHORT, float `entry`/`sl`/`tp`) and `quant.execution.order.Position`
  (float `size`/`open_price`). Hot-loop math stays in float.
- **Broker** (Decimal-precise): `quant.contracts.entities.Signal`/`Position`
  (BUY/SELL, Decimal money). Money precision lives here.
- **Wire-canonical**: `shared.entities` models plus Dhan DTOs, mapped by
  `brokers/broker/dhan/application/converters.py` (`DhanConverter`) and
  `order_converter.py`.

Merging float and Decimal worlds risks both speed and precision. The defect
was never the split — it was *implicit* crossing (qty dropped, getattr
chains). Plan B fixed that with named crossing functions.

## Decision

Keep the split. Engine types may cross into broker calls ONLY via:

- `quant/execution/broker_mapper.py::to_broker_signal` (engine→broker signal),
- `quant/execution/fills.py::broker_position_to_fill` (broker→engine fill),
- `quant/execution/order.py::position_to_row` / `row_to_position`
  (engine persist→restore),
- Dhan converters (`DhanConverter`, `order_converter`) for wire↔broker.

## Consequences

- New crossings outside these functions fail review.
- Grep gate: the rule IS expressible as an allowlist gate on
  `to_broker_signal|broker_position_to_fill|position_to_row|row_to_position`
  call sites (allowed: `live_oms.py`, `broker_mapper.py`, `fills.py`,
  `order.py`, `persistence_bridge.py`, `multi_engine.py`). NOT added here:
  `tests/architecture/test_no_layer_bypass.py` is owned by Plan E Task 5
  (ratchet hardening) — add the gate there to avoid concurrent edits to the
  same file. No production-code changes in this task.
