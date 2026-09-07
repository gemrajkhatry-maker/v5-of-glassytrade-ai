# Paper Trading Readiness Implementation Plan

> **Prerequisite:** The approved design is
> `docs/superpowers/specs/2026-09-07-paper-trading-readiness-design.md`.
>
> **Implementation mode:** TDD. For every production change, write a failing
> behavior test, run it, implement the smallest change, run focused tests,
> then run the relevant integration gates. No live broker calls.
>
> **Do not touch:** user dirty files unless a task explicitly requires them.
> Keep Dhan security IDs inside broker adapters. Do not add them to quant
> contracts or signal DTOs.

## Global gates

Run from repository root:

```bash
.venv/bin/python -m pytest <focused-tests> -q
```

Required before paper-readiness completion:

```bash
.venv/bin/python -m pytest tests/quant -q
.venv/bin/python -m pytest backend/tests/unit -q
.venv/bin/python -m pytest tests/system/test_paper_protocol.py -q
```

Also run:

```bash
git diff --check
python3 -m compileall -q quant backend/app brokers
```

No task is complete if a paper order can be opened without a valid contract,
lot, fill, cost, journal event and restart representation.

---

## Phase 0 — Freeze semantics and add paper configuration contracts

### Task 0.1 — Separate capital deployment from stop-loss risk

**Files:**

- Modify: `backend/config/environments/paper.yaml`
- Modify: `backend/config/strategies/nse_options.yaml`
- Modify: `backend/config/strategies/mcx_options.yaml`
- Modify: `backend/config_models` loader/models/validator as needed
- Add tests under `backend/tests/unit` and `tests/quant/execution`

**Behavior:**

- Add `paper.capital_deployment_pct: 0.95`.
- Keep `risk_per_trade_pct` as stop-loss risk, default `0.005`.
- Keep `max_daily_loss_pct` independent.
- Reject a paper `risk_per_trade_pct >= 0.05` unless explicit
  `allow_extreme_risk=true`.
- Always reject that value in live mode.
- Ensure the coordinator receives the validated values exactly once.

**TDD:**

1. Test paper config exposes deployment 0.95 and stop risk 0.005.
2. Test 95% deployment does not imply 95% stop risk.
3. Test extreme-risk mode is explicit and paper-only.
4. Test live config rejects extreme risk.
5. Run focused config tests and inspect the failing output.
6. Implement minimal config model/loader/validator changes.

**Acceptance:** No code path interprets `capital_deployment_pct` as
`risk_per_trade_pct`.

### Task 0.2 — Add paper readiness feature gate

**Files:**

- Modify: configuration/DI composition root
- Add: paper readiness tests

**Behavior:**

- `paper_trading_enabled` means simulator mode only.
- `live_oms_enabled` remains false in paper mode.
- Paper mode must never instantiate `DhanBrokerAdapter` for execution.
- A missing paper simulator or invalid paper config fails startup.

**Acceptance:** A paper boot test proves no live OMS is reachable through the
composition root.

---

## Phase 1 — Broker-neutral contract identity

### Task 1.1 — Define `ContractRef` and normalized paper contract

**Files:**

- Add canonical value object under `quant/contracts/`.
- Modify broker-neutral ports only where needed.
- Add tests under `tests/quant/contracts`.

**Behavior:**

`ContractRef` contains only broker-neutral data:

```text
symbol, exchange, expiry, strike, option_type,
lot_size, tick_size, multiplier, product_type
```

It must not have `security_id`, `dhan_*`, auth fields or raw broker payloads.

**TDD:**

- Construct valid futures, index-option and MCX-option refs.
- Reject missing expiry/lot/tick for derivatives.
- Reject zero/negative lot or tick.
- Verify serialization contains no security ID.
- Verify import boundaries prevent `quant.*` importing Dhan infrastructure.

### Task 1.2 — Add adapter-private contract resolution

**Files:**

- Modify: `brokers/broker/ports.py` or canonical broker port
- Modify: `backend/app/infrastructure/adapters/dhan_broker_adapter.py`
- Modify: Dhan symbol mapper/security master integration
- Add: paper resolver in `backend/app/infrastructure/adapters/paper_broker.py`
- Add tests for Dhan and paper resolution

**Behavior:**

- Dhan adapter resolves `ContractRef → BrokerContract` internally.
- `security_id` remains private to the Dhan adapter.
- Paper resolver creates a deterministic internal instrument key.
- Missing/stale/ambiguous resolution fails closed.
- Exact exchange, expiry, strike and option type are checked.

**Acceptance:** Engine signals contain `ContractRef` or normalized symbol data,
never Dhan security IDs. Dhan payload tests prove the ID appears only at the
adapter boundary.

### Task 1.3 — Remove engine-side security ID leakage

**Files:**

- Search and modify only actual leaks in `quant/`, `shared/`, and strategy
  context.
- Keep infrastructure storage broker IDs where required for reconciliation.
- Add AST/import or serialization tests.

**Acceptance:** A test recursively serializes engine `Signal`, `Order`,
`Position`, `DecisionContext` and AMT DTOs and finds no broker security ID
field or Dhan-specific key.

---

## Phase 2 — One authoritative paper execution simulator

### Task 2.1 — Define paper order/fill lifecycle

**Files:**

- Add normalized paper execution value objects under `quant/execution/`.
- Modify event definitions only if existing events cannot express the flow.
- Add tests under `tests/quant/execution`.

**Behavior:**

Support:

```text
INTENT → SUBMITTED → ACCEPTED → PARTIAL → FILLED
                     ↘ REJECTED
                     ↘ UNKNOWN → RECONCILE_REQUIRED
```

Every transition is idempotent by logical order ID.

**Tests:**

- duplicate submit does not double the position;
- reject leaves no position or risk reservation;
- unknown blocks resubmission;
- partial fill preserves remaining exposure;
- restart replays transitions exactly.

### Task 2.2 — Implement `PaperExecutionSimulator`

**Files:**

- Add simulator in `quant/execution/`.
- Adapt `quant/execution/oms.py` to delegate to it.
- Adapt paper broker composition only after tests describe behavior.

**Fill modes:**

- `instant_mid` only for unit tests;
- `bid_ask` default for paper;
- configurable slippage mode;
- captured replay hook reserved for later phase.

**Behavior:**

- resolve normalized `ContractRef` through paper resolver;
- enforce tick and lot validity;
- calculate executable fill price;
- generate order/fill events;
- return actual quantity and price;
- never call Dhan or rely on Dhan security IDs.

### Task 2.3 — Make PaperOMS and PaperBrokerAdapter converge

**Files:**

- `quant/execution/oms.py`
- `backend/app/infrastructure/adapters/paper_broker.py`
- shared conformance tests

**Acceptance:** Both entry points produce equivalent normalized fills and
positions for the same order request. Any intentional difference must be
explicitly documented and tested.

---

## Phase 3 — Cost-aware fill ledger and 95% deployment policy

### Task 3.1 — Integrate costs into actual fills

**Files:**

- `quant/execution/trade_costs.py`
- paper fill ledger/simulator
- portfolio/risk integration
- paper journal services
- tests under `tests/quant/execution` and `backend/tests/unit`

**Behavior:**

Costs are calculated once from actual fills, not only logged. Net P&L flows to
risk, portfolio, journal and reports.

Tests assert:

```text
net_pnl = gross_pnl - all_costs
risk.daily_pnl delta = journal.net_pnl
portfolio realized delta = journal.net_pnl
```

### Task 3.2 — Enforce 95% paper capital deployment

**Files:**

- `quant/execution/risk.py`
- `quant/execution/portfolio_risk.py`
- configuration and tests

**Behavior:**

- Calculate maximum paper notional/capital deployment from
  `capital_deployment_pct=0.95`.
- Enforce it independently from stop-loss risk.
- Preserve max daily loss, max consecutive loss and max trade limits.
- Make the aggregate 95% setting explicit as capital deployment, not a
  silent aggregate-loss allowance.
- Keep an optional aggregate open-risk ceiling separately configured.

**Acceptance:** A portfolio can deploy up to the requested 95% paper capital
without permitting one trade to risk 95% of equity at the stop.

---

## Phase 4 — Lot-safe partial fills and position truth

### Task 4.1 — Lot-safe exit quantities

**Files:**

- `quant/execution/live_oms.py` only for shared contract behavior if needed;
- `quant/execution/oms.py`;
- paper simulator;
- lot utility tests.

**Behavior:**

- One lot closes fully.
- Multi-lot positions close whole-lot fractions.
- Actual fill quantity determines remaining size and P&L.
- Requested and actual quantity are both journaled.

### Task 4.2 — Paper position projection

**Files:**

- event projector/state transitions;
- fill ledger;
- reconciliation tests.

**Acceptance:** After entry, partial exit, full exit and restart:

```text
engine position == fill-ledger position == journal position
```

No dust quantity, negative remainder, duplicate close or phantom position is
allowed.

---

## Phase 5 — Restart and reconciliation safety for paper mode

### Task 5.1 — Persist paper orders and fills

**Files:**

- `backend/app/infrastructure/storage/database.py` if existing storage is the
  selected persistence boundary;
- quant persistence/event store;
- paper adapter wiring;
- tests.

**Behavior:**

Persist order intent, state transitions, fills, costs, positions and risk
snapshot with logical IDs and sequence numbers.

### Task 5.2 — Reconcile on restart

**Tests first:**

- crash before fill;
- crash after fill before position event;
- crash after partial fill;
- duplicate signal after restart;
- corrupted snapshot;
- unresolved order.

**Acceptance:** Reconciliation either reconstructs the exact state or
quarantines and blocks new entries. It never starts fresh silently.

---

## Phase 6 — Fabio correctness and option basis

### Task 6.1 — Directional aggression and CVD

**Files:**

- `quant/amt/orderflow/aggression.py`
- `quant/amt/orderflow/compute.py`
- tests first under `tests/quant/amt/orderflow`

**Behavior:**

- aggression accepts directional evidence or returns signed confirmation;
- opposing CVD cannot confirm a setup;
- DTO/journal shows direction and evidence source;
- existing parity/golden tests remain unchanged unless behavior is explicitly
  corrected and snapshots are reviewed.

### Task 6.2 — Separate order-flow delta from option Greek delta

**Files:**

- `quant/contracts/value_objects.py`
- `quant/amt/dto.py`
- `quant/decision/context.py`
- `quant/decision/context_builder.py`
- `quant/amt/session/scanner.py`
- `quant/amt/session/selector.py`
- option engine wiring and tests

**Behavior:**

Use separate fields:

```text
orderflow_delta_ratio
option_greek_delta
```

Carry chain Greek delta from scanner selection to the engine. Reject paper
option execution if the Greek is missing or stale unless an explicit
synthetic-Greek test mode is enabled. Never default silently to 0.50 in the
normal paper path.

### Task 6.3 — Label AMT data quality

**Files:**

- AMT result/DTO;
- footprint/profile construction;
- decision evidence;
- tests.

**Values:**

```text
TICK_EXACT
CANDLE_DISTRIBUTED
CANDLE_GAUSSIAN
UNKNOWN
```

High-conviction footprint setups require an allowed data quality level.

---

## Phase 7 — Paper acceptance certification

Create one end-to-end acceptance suite covering:

1. NIFTY one-lot entry and full exit.
2. NIFTY two-lot TP1 and runner.
3. BANKNIFTY option with spread and slippage.
4. MCX option session and timestamp handling.
5. Invalid/stale contract resolution.
6. Duplicate and out-of-order ticks.
7. Feed starvation.
8. Rejected paper order.
9. Unknown paper order.
10. Partial fill.
11. Restart after entry fill.
12. Restart after partial fill.
13. Prior-session profile rollover.
14. 95% paper deployment ceiling.
15. Daily-loss halt.
16. Consecutive-loss halt.
17. Net cost/P&L reconciliation.
18. No broker security ID leakage.

Required commands:

```bash
.venv/bin/python -m pytest tests/quant -q
.venv/bin/python -m pytest backend/tests/unit -q
.venv/bin/python -m pytest tests/system/test_paper_protocol.py -q
python3 -m compileall -q quant backend/app brokers
 git diff --check
```

## Completion gate

Paper mode may be called paper-ready only when:

- all phases 0-5 pass;
- phase 6 option/AMT basis tests pass;
- phase 7 acceptance suite passes;
- the paper journal can independently reproduce equity and risk;
- 95% deployment is visible in startup configuration and dashboards;
- no engine/domain object contains broker security IDs;
- live Dhan code remains disabled and unmodified by paper tests.
