# ADR-0002: Broker ports — collapse gated on port extension (GAP found)

Status: Investigation complete (Plan E Task 3, Half A). Decision: **GATED — do NOT
migrate until the port-extension question below is decided by the owner.**

## Context

Two broker abstractions coexist:

- **Quant `IBroker`** (`quant/contracts/ports/broker.py`, 3 abstract methods):
  `execute_order(signal, portfolio, symbol) -> Position | None`,
  `close_position(symbol, side, quantity, portfolio, reference_price=None)
  -> Position | None`, `cancel_order(order_id) -> bool`. Types are the quant
  broker domain: `quant.contracts.entities.Signal` (BUY/SELL, Decimal),
  `quant.contracts.aggregates.Portfolio`, `quant.contracts.entities.Position`.
- **`IBrokerPort`** (`brokers/broker/ports.py`, primary broker ABC): lifecycle
  (`initialize`, `close`), market data (`get_quote`, `get_quotes_batch`,
  `get_historical`), streaming (`stream_ticker`, `stream_quotes`,
  `stream_depth`, `stream_full`), options (`get_option_chain`,
  `get_expiry_list`, `find_atm_options`, `find_otm_options`,
  `find_itm_options`, `get_lot_size`, `get_step_size`), orders
  (`place_order(order: Order) -> Order`, `cancel_order(order_id) -> bool`,
  `get_order_status(order_id) -> Order`), portfolio (`get_positions()`,
  `get_orderbook()`). Types are `brokers/broker/entities.py`
  (`Instrument`, `Order`, `Position`, ...) — a different type universe from
  the quant contracts.

The architect decision (Plan E Task 3) proposes retiring quant `IBroker` so the
chain becomes engine → `IOMS` → (`LiveOMS`) → `IBrokerPort` → broker, keeping
`IOMS` as the engine seam. This ADR records the method-by-method mapping that
gates that decision.

## Mapping table (quant `IBroker` → `IBrokerPort`)

| Quant `IBroker` method | `IBrokerPort` equivalent | Verdict + evidence |
|---|---|---|
| `execute_order(signal: Signal, portfolio: Portfolio, symbol: str) -> Position \| None` | **NONE** | **GAP.** `IBrokerPort.place_order` takes a broker `Order` (instrument/side/qty/order_type), not a quant `Signal`+`Portfolio`. `DhanBrokerAdapter.execute_order` (~170 lines: `_resolve_quantity` risk sizing, duplicate-signal-id guard, C7 entry slippage collar, durable SUBMITTED persistence, poll-to-terminal + cancel-on-timeout, `Position` mapping) is composition logic with no port-level counterpart. Collapsing the port does not eliminate this code — it only moves it. |
| `close_position(symbol, side, quantity, portfolio, reference_price=None) -> Position \| None` | **NONE** | **GAP.** `IBrokerPort` has no close operation at all. `DhanBrokerAdapter.close_position` (~150 lines: symbol classification → `Instrument`, close-side slippage collar, cancel-on-timeout fill race check, C7 MARKET-fallback guarantee for zero-fill collared closes) likewise has no counterpart. A collapse would have to *invent* where this composition lives (`LiveOMS` vs a new close service) — a semantic choice, not a rename. |
| `cancel_order(order_id: str) -> bool` | `IBrokerPort.cancel_order(order_id: str) -> bool` | **CLEAN.** Identical signature; `DhanBrokerAdapter.cancel_order` is already pure delegation to `broker.cancel_order`. |

Extra surface (not on the port, relevant to migration): `DhanBrokerAdapter`
additionally exposes `get_positions() -> list[quant Position]` (mapped from
`broker.get_positions()`), which no caller resolves through `IBroker`.

## Importers / implementers / DI wiring (evidence)

- **Port definition:** `quant/contracts/ports/broker.py` (+ re-export in
  `quant/contracts/ports/__init__.py`).
- **Implementers:** `backend/app/infrastructure/adapters/dhan_broker_adapter.py::DhanBrokerAdapter(IBroker)`
  (wraps `brokers/.../dhan/application/broker.DhanBroker`, which implements
  `IBrokerPort` — see `brokers/tests/test_dhan_broker.py::issubclass` check);
  `backend/app/infrastructure/adapters/paper_broker.py::PaperBrokerAdapter(IBroker)`
  (standalone; cost model + `Portfolio.open_position` delegation).
- **DI:** `backend/app/application/di/composition_root.py::_broker_port()`
  returns quant `IBroker`; `_create_broker_adapter` returns `DhanBrokerAdapter`
  (live) / `PaperBrokerAdapter` (paper); `_create_quant_coordinator` resolves
  `IBroker` and passes it as `broker=` to `QuantCoordinator`. Also
  `backend/app/application/di/container.py` (`register_singleton(IBroker, ...)`).
- **Consumers:** `backend/app/main.py:404` (`container.resolve(IBroker)`);
  `backend/app/api/dependencies.py::get_broker` / `BrokerDep` (typed `IBroker`);
  `quant/execution/live_oms.py::LiveOMS(broker: IBroker)` (entries via
  `execute_order`, exits via `close_position`); tests
  (`tests/quant/execution/test_live_oms.py::MockBroker(IBroker)`).
- **No `isinstance`/`issubclass` checks** against quant `IBroker` in production
  code (only the `IBrokerPort` check in `brokers/tests/test_dhan_broker.py`).

## Decision

**GAP — STOP after this ADR. No migration in this task.** Two of three
`IBroker` methods have no `IBrokerPort` equivalent, and the adapter bodies
behind them are substantial composition logic (sizing, dedup, collars,
polling, fallback guarantees), not thin delegation. Retiring `IBroker` now
would strand that logic without a designed home.

## Migration order (only after the owner resolves the gap)

1. Decide where `execute_order`/`close_position` composition lives (options:
   extend `IBrokerPort` with signal-level methods; move composition into
   `LiveOMS`; introduce a dedicated execution service). This is a separate
   owner decision — not made here.
2. Then, in order: adapters → `LiveOMS` → DI (`composition_root.py`,
   `container.py`, `main.py`, `dependencies.py`) → delete
   `quant/contracts/ports/broker.py`. One commit per sub-step with
   characterization tests first (Plan E Task 3 Step 3).
3. `IOMS` stays regardless (engine seam; both `PaperOMS` and `LiveOMS`
   satisfy it — see the OMS conformance suite from Task 3 Half B).
