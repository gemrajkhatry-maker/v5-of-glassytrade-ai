# AMT Live Readiness Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make the deterministic AMT strategy spec-aligned, fail-closed for unsafe live data, and fully tested through mocked OMS, replay, parity, and release gates.

**Architecture:** Preserve the single path `AMTAnalyzer -> DecisionContext -> GatePipeline -> SignalBuilder -> SessionRisk/PortfolioRiskAuthority -> PaperOMS/LiveOMS`. Add explicit broker capabilities, durable stop/close identities, actual-fill accounting, evidence-family provenance, and option-underlying gating. Do not introduce a second strategy path or a legacy compatibility mode.

**Tech Stack:** Python 3.13, pytest, existing `quant` and `backend` packages, root `.venv`, existing PaperOMS/LiveOMS, deterministic fake brokers, replay/golden tapes, YAML configuration, existing EventStore/persistence seams.

## Global Constraints

- Work on `feat/amt-live-readiness` from the approved design commit.
- Every production behavior change starts with a focused failing test.
- Use `PYTHONPATH=backend:. .venv/bin/python -m pytest` for Python tests.
- Do not add dependencies, broker credentials, live orders, or sandbox integrations.
- Preserve `DecisionService`/`GatePipeline` as the sole entry authority; narrative/advisor output remains advisory-only.
- Required live evidence is exact or explicitly blocked; do not synthesize depth or silently relabel proxy data.
- Preserve documented AMT thresholds; do not change value-area, LVN, absorption, or range-bar constants in this plan.
- Use path-scoped `git add`; never stage `automation/reports/` or unrelated worktree files.
- Do not add comments to production code unless the user explicitly requests them.
- Each task ends with its focused test command passing and one reviewable commit.
- Push the branch normally only after the final release commands exit successfully.

## File Map

**Production files to modify:**

- `quant/contracts/ports/broker.py` — explicit native-stop capability contract.
- `quant/execution/order.py` — durable stop/parent identity fields and position serialization.
- `quant/execution/live_oms.py` — stop lifecycle, actual fills, close intents, live pyramids.
- `quant/execution/oms.py` — matching paper pyramid/fill identity behavior.
- `quant/execution/fills.py` — single broker-fill normalization contract.
- `quant/execution/exposure.py` — durable partial/unknown exposure and reconciliation.
- `quant/execution/risk.py` — effective configured HMP authority and quantity tests.
- `quant/execution/portfolio_risk.py` — pyramid/release accounting if the new live path requires it.
- `quant/engine/submission_handler.py` — reconciliation-safe OMS result handling.
- `quant/engine/decision_loop.py` — evidence-family live gate and option execution block.
- `quant/engine/tick_handler.py` — no synthetic depth.
- `quant/state.py` — clear stale cached depth when a live tick has no book.
- `quant/decision/data_quality.py` — per-family failure reporting.
- `quant/decision/context_builder.py` — preserve evidence provenance and option metadata.
- `quant/decision/gates_edge.py` — literal Triple-A Aggression path.
- `quant/amt/triple_a.py` — direction-specific CVD confirmation.
- `quant/amt/analyzer.py` and `quant/amt/profile/vwap.py` — recent-regime VA/VWAP consistency.
- `quant/amt/session/scanner.py` — no invented option delta.
- `quant/multi_engine.py` — option engines cannot execute without an underlying feed.
- `quant/brokers/multiplexed_feed.py` — deterministic test shutdown.
- `backend/app/infrastructure/adapters/dhan_broker_adapter.py` — capability declaration and close/reconciliation identity.
- `backend/app/infrastructure/adapters/paper_broker.py` — capability declaration for parity.

**Test files to modify or extend:**

- `tests/quant/execution/test_live_oms.py`
- `tests/quant/execution/test_live_partial_fill_reconciliation.py`
- `tests/quant/execution/test_close_identity.py`
- `tests/quant/execution/test_oms_conformance.py`
- `tests/quant/execution/test_restart_reconciliation.py`
- `tests/quant/execution/test_pyramid_integration.py`
- `tests/quant/execution/test_pyramid_oms.py`
- `tests/quant/execution/test_risk_config_propagation.py`
- `tests/quant/decision/test_proxy_live_entry_block.py`
- `tests/quant/decision/test_gate_triple_a_edge.py`
- `tests/quant/decision/test_triple_a_lvn_proximity.py`
- `tests/quant/decision/test_option_signal_translation.py`
- `tests/quant/amt/test_analyzer.py`
- `tests/quant/amt/orderflow/test_cvd.py`
- `tests/quant/amt/orderflow/test_detectors.py`
- `tests/quant/test_underlying_feed.py`
- `tests/quant/runtime/test_tick_handler.py`
- `tests/quant/test_production_correctness.py`
- `tests/quant/test_certification.py`
- `tests/quant/test_stress_and_portfolio_risk.py`
- `tests/quant/coordinator/test_multi_symbol_isolation.py`
- `tests/quant/test_multiplexed_feed.py`

**Documentation/report files:**

- `docs/amt/AMT_INSTITUTIONAL_SCALPER_ALGORITHM.md`
- `docs/amt/fabio_decision_pipeline.md`
- `docs/amt/WALKTHROUGH.md`
- `docs/reviews/2026-09-24-amt-live-readiness-report.md` (create after verification)
- `docs/architecture/amt-live-readiness-workflow.md` (create; source-backed Mermaid workflow).
- Add a superseded-status banner to overlapping `2026-09-18-amt-live-safety-remediation.md` and `2026-09-23-full-amt-fidelity.md` plans rather than silently treating them as current execution instructions.

---

### Task 1: Make live stop capability explicit

**Files:**
- Modify: `quant/contracts/ports/broker.py:9-34`
- Modify: `backend/app/infrastructure/adapters/dhan_broker_adapter.py:44-120`
- Modify: `backend/app/infrastructure/adapters/paper_broker.py:40-150`
- Modify: `quant/execution/live_oms.py:87-226`
- Test: `tests/quant/execution/test_live_oms.py`
- Test: `tests/quant/execution/test_oms_conformance.py`

**Interfaces:**
- Produces `IBroker.supports_native_stop_loss() -> bool`, defaulting to `False`.
- Produces a live `submit()` that refuses an unprotected entry before sending the entry order when the broker reports no native stop capability.
- Dhan and deterministic test brokers explicitly return `True` only when their `place_stop_loss()` implementation is usable.

- [ ] **Step 1: Write the failing capability test**

```python
def test_live_submit_refuses_entry_when_native_stop_is_unavailable():
    broker = MockBroker()
    broker.supports_native_stop_loss.return_value = False
    oms = LiveOMS(broker, Portfolio.create_default())
    signal = approved_signal()

    with pytest.raises(EmergencyFlattenError, match="native stop"):
        oms.submit(signal, 10)

    broker.execute_order.assert_not_called()
```

```python
def test_capable_broker_records_stop_id():
    broker = MockBroker()
    broker.supports_native_stop_loss.return_value = True
    broker.place_stop_loss.return_value = "stop-1"
    oms = LiveOMS(broker, Portfolio.create_default())

    position = oms.submit(approved_signal(), 10)

    assert position.stop_order_id == "stop-1"
    broker.place_stop_loss.assert_called_once()
```

- [ ] **Step 2: Run the focused test and verify it fails**

Run:

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/test_live_oms.py -k "native_stop or stop" -q
```

Expected: FAIL because the current port has no capability method and a broker inheriting `place_stop_loss()` is treated as successful via `"mock_pass"`.

- [ ] **Step 3: Add the capability contract**

Add this method to `IBroker`:

```python
def supports_native_stop_loss(self) -> bool:
    return False
```

Return `True` from `DhanBrokerAdapter` and deterministic test brokers whose fake `place_stop_loss()` records a real order ID. Keep `PaperBrokerAdapter` at `False` because it has no native stop implementation. Remove the `"mock_pass"` fallback from `LiveOMS`. If the capability is false, raise `EmergencyFlattenError` before `execute_order()`.

- [ ] **Step 4: Preserve the emergency path for post-fill stop failure**

```python
def test_post_fill_stop_failure_attempts_emergency_flatten():
    broker = MockBroker()
    broker.supports_native_stop_loss.return_value = True
    broker.place_stop_loss.return_value = None
    oms = LiveOMS(broker, Portfolio.create_default())

    with pytest.raises(EmergencyFlattenError):
        oms.submit(approved_signal(), 10)

    assert broker.close_position.called
```

- [ ] **Step 5: Run the OMS tests and commit**

Run:

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/test_live_oms.py tests/quant/execution/test_oms_conformance.py -q
```

Expected: PASS.

Commit:

```bash
git add quant/contracts/ports/broker.py backend/app/infrastructure/adapters/dhan_broker_adapter.py backend/app/infrastructure/adapters/paper_broker.py quant/execution/live_oms.py tests/quant/execution/test_live_oms.py tests/quant/execution/test_oms_conformance.py
git commit -m "fix(oms): require explicit live stop capability"
```

### Task 2: Persist and reconcile the protective stop lifecycle

**Files:**
- Modify: `quant/execution/order.py:8-119`
- Modify: `quant/execution/live_oms.py:160-460`
- Modify: `quant/persistence_bridge.py:95-203`
- Test: `tests/quant/execution/test_live_oms.py`
- Test: `tests/quant/execution/test_restart_reconciliation.py`
- Test: `tests/quant/test_event_store_roundtrip_real.py`

**Interfaces:**
- Adds `Position.stop_order_id: str = ""` and `Position.parent_position_id: str = ""` with default values so existing constructors remain valid.
- Serializes and restores both fields through `position_to_row()` and `row_to_position()`.
- `LiveOMS.close()` and `close_partial()` cancel the stored stop before submitting a reduction, then replace or retain the correct stop quantity for the remaining position.

- [ ] **Step 1: Write failing stop lifecycle tests**

```python
def test_close_cancels_persisted_stop_before_exit():
    position = position_with_stop("stop-1")
    oms = LiveOMS(MockBroker(), Portfolio.create_default())
    oms._broker.cancel_order = Mock(return_value=True)
    oms._broker.close_position = Mock(return_value=close_fill(size=10))
    oms.close(position, 105, "t", "TP")
    assert oms._broker.cancel_order.call_args.args == ("stop-1",)


def test_restart_restores_stop_id():
    row = position_row(stop_order_id="stop-1", parent_position_id="base-1")
    restored = row_to_position(row)
    assert restored.stop_order_id == "stop-1"
    assert restored.parent_position_id == "base-1"
```

```python
def test_failed_stop_cancellation_creates_reconciliation():
    broker = MockBroker()
    broker.cancel_order.return_value = False
    oms = LiveOMS(broker, Portfolio.create_default())
    with pytest.raises(ReconciliationRequiredError):
        oms.close(position_with_stop("stop-1"), 105, "t", "TP")


def test_partial_close_replaces_stop_for_remaining_size():
    broker = MockBroker()
    broker.cancel_order.return_value = True
    broker.close_position.return_value = close_fill(size=5)
    broker.place_stop_loss.return_value = "stop-2"
    oms = LiveOMS(broker, Portfolio.create_default())
    fill, remaining = oms.close_partial(position_with_stop("stop-1"), 0.5, 105, "t", "TP1")
    assert abs(remaining.size) == 5
    assert remaining.stop_order_id == "stop-2"
```

- [ ] **Step 2: Run the tests and verify they fail**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/test_live_oms.py tests/quant/execution/test_restart_reconciliation.py -k "stop or restart" -q
```

Expected: FAIL because `LiveOMS` stores the stop ID only in a local variable and does not serialize or cancel it.

- [ ] **Step 3: Add the durable position fields**

Add default-valued fields to `Position`, then map them in both serialization directions. Keep `_id` as the existing position identity; do not derive parentage from a reason string.

- [ ] **Step 4: Store the accepted stop ID on the returned position**

After stop placement succeeds, return a position carrying `stop_order_id`. On stop cancellation failure, raise `ReconciliationRequiredError` with the position and stop IDs and do not report a clean close.

- [ ] **Step 5: Add a stop helper used by all exits**

Use one private helper for full close, partial close, emergency flatten, and restart repair. It must cancel the existing stop by its durable ID before submitting a reduction and must expose a distinct failure state when cancellation cannot be confirmed.

- [ ] **Step 6: Run the tests and commit**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/test_live_oms.py tests/quant/execution/test_restart_reconciliation.py tests/quant/test_event_store_roundtrip_real.py -q
```

Expected: PASS.

Commit:

```bash
git add quant/execution/order.py quant/execution/live_oms.py quant/persistence_bridge.py tests/quant/execution/test_live_oms.py tests/quant/execution/test_restart_reconciliation.py tests/quant/test_event_store_roundtrip_real.py
git commit -m "fix(execution): persist and reconcile protective stops"
```

### Task 3: Make close accounting use actual fills and distinct intents

**Files:**
- Modify: `quant/execution/fills.py:15-37`
- Modify: `quant/execution/live_oms.py:228-460`
- Modify: `quant/execution/exposure.py:15-89`
- Modify: `quant/engine/submission_handler.py:199-272`
- Modify: `backend/app/infrastructure/adapters/dhan_broker_adapter.py:422-740`
- Modify: `quant/event_store.py:247-439`
- Modify: `quant/runtime.py:450-470,875-900,1300-1410`
- Modify: `quant/state.py:234-291`
- Test: `tests/quant/execution/test_live_oms.py`
- Test: `tests/quant/execution/test_live_partial_fill_reconciliation.py`
- Test: `tests/quant/execution/test_close_identity.py`
- Test: `tests/quant/runtime/test_eventstore_failure_consistency.py`
- Test: `tests/quant/runtime/test_snapshot_projection.py`

**Interfaces:**
- `broker_position_to_fill()` returns the broker-reported fill quantity and marks fallback quantity explicitly.
- `LiveOMS.close()` returns a fill whose position size is the actual filled quantity; a partial close returns the actual reduction and the actual remaining position.
- `Fill.logical_id` is stable for a retry of one economic close and distinct for TP1, TP2, and a later independent close.
- `ExposureState` remains `RECONCILIATION_REQUIRED` for partial/unknown/contradictory outcomes.
- A lifecycle event that cannot be durably appended is not projected as canonical success; the runtime exposes degraded/reconciliation state.

- [ ] **Step 1: Write failing fill and identity tests**

```python
def test_partial_close_uses_broker_filled_quantity():
    broker = MockBroker()
    broker.close_position.return_value = close_fill(size=2)
    oms = LiveOMS(broker, Portfolio.create_default())
    position = open_position(size=10)

    fill, remaining = oms.close_partial(position, 0.5, 105, "t", "TP1")

    assert abs(fill.position.size) == 2
    assert abs(remaining.size) == 8


def test_tp_stages_have_distinct_close_ids():
    broker = MockBroker()
    broker.close_position.return_value = close_fill(size=5)
    oms = LiveOMS(broker, Portfolio.create_default())
    position = open_position(size=10)

    first, _ = oms.close_partial(position, 0.5, 105, "t", "TP1")
    second, _ = oms.close_partial(position, 0.5, 110, "t", "TP2")

    assert first.logical_id != second.logical_id


def test_same_close_retry_keeps_one_id():
    broker = MockBroker()
    broker.close_position.return_value = close_fill(size=10)
    oms = LiveOMS(broker, Portfolio.create_default())
    position = open_position(size=10)

    first = oms.close(position, 105, "t", "TP")
    second = oms.close(position, 105, "t", "TP")

    assert first.logical_id == second.logical_id
```

- [ ] **Step 2: Run the tests and verify the current failure**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/test_live_oms.py tests/quant/execution/test_live_partial_fill_reconciliation.py tests/quant/execution/test_close_identity.py -k "partial or close_identity or retry" -q
```

Expected: FAIL because `close_partial()` ignores `_filled_qty` and all closes currently use `close:{position.id}`.

- [ ] **Step 3: Centralize fill normalization**

Keep `broker_position_to_fill()` as the only broker-position mapping. Treat a missing or invalid quantity as a reconciliation outcome for live closes rather than silently using the requested quantity.

- [ ] **Step 4: Generate durable close IDs by economic stage**

Use a private helper that returns `close:{position.id}:{normalized_reason}`. Preserve the same normalized reason for retries and use distinct reasons for TP1 and TP2. Pass the ID through the broker adapter and into `Fill.logical_id`.

- [ ] **Step 5: Update P&L and remaining position calculations**

Compute partial P&L from `actual_filled_qty` and remaining size from `position.size - signed_filled_qty`. If the actual fill exceeds the request, raise `ReconciliationRequiredError`; never clamp a contradictory fill into a normal close.

- [ ] **Step 6: Preserve durable event projection on failure**

```python
def test_event_append_failure_keeps_exposure_unresolved(engine):
    engine.event_store.append = fail_storage
    engine.emit_reconciliation_required("order-1", requested_qty=10, filled_qty=4)
    assert engine.exposure_state.status is ExposureStatus.RECONCILIATION_REQUIRED
    assert engine.snapshot.degraded is True
    assert engine.entry_guards_block_new_orders() is True
```

The runtime must retain the reconciliation/exposure obligation, emit a degraded projection marker, and block new live entries until the event log is repaired.

- [ ] **Step 7: Run the tests and commit**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/test_live_oms.py tests/quant/execution/test_live_partial_fill_reconciliation.py tests/quant/execution/test_close_identity.py tests/quant/runtime/test_eventstore_failure_consistency.py tests/quant/runtime/test_snapshot_projection.py -q
```

Expected: PASS.

Commit:

```bash
git add quant/execution/fills.py quant/execution/live_oms.py quant/execution/exposure.py quant/engine/submission_handler.py quant/event_store.py quant/runtime.py quant/state.py backend/app/infrastructure/adapters/dhan_broker_adapter.py tests/quant/execution/test_live_oms.py tests/quant/execution/test_live_partial_fill_reconciliation.py tests/quant/execution/test_close_identity.py tests/quant/runtime/test_eventstore_failure_consistency.py tests/quant/runtime/test_snapshot_projection.py
git commit -m "fix(execution): reconcile actual fills and close identities"
```

### Task 4: Implement live 50%/25% pyramiding

**Files:**
- Modify: `quant/contracts/ports/broker.py:9-34`
- Modify: `quant/execution/live_oms.py:462-494`
- Modify: `quant/execution/oms.py:330-430`
- Modify: `quant/position_manager.py:436-579`
- Modify: `quant/execution/risk.py:460-520`
- Modify: `quant/execution/portfolio_risk.py:108-206`
- Modify: `backend/app/infrastructure/adapters/dhan_broker_adapter.py:180-420`
- Test: `tests/quant/execution/test_pyramid_integration.py`
- Test: `tests/quant/execution/test_pyramid_oms.py`
- Test: `tests/quant/test_pyramid_certification.py`
- Test: `tests/quant/runtime/test_pyramid_accounting_parity.py`

**Interfaces:**
- Adds `IBroker.supports_pyramid() -> bool`, defaulting to `False`.
- `IOMS.add_pyramid()` returns a broker-backed `Position` with `is_pyramid=True`, `pyramid_level=1|2`, and `parent_position_id` set to the base position.
- P1 uses 50% of base size and P2 uses 25% of base size after lot snapping.
- Every add has a unique order signal, stop, risk reservation, and durable identity.

- [ ] **Step 1: Write failing live pyramid tests**

```python
def test_live_pyramid_creates_broker_backed_linked_position():
    broker = MockBroker()
    oms = LiveOMS(broker, Portfolio.create_default(), lot_size=1)
    base = open_position(size=10)
    add = oms.add_pyramid(base, 101, 99, 5, "t", pyramid_level=1)

    assert add.is_pyramid is True
    assert add.pyramid_level == 1
    assert add.parent_position_id == base.id
    assert broker.execute_order.called


def test_live_pyramid_rejects_unsupported_broker_capability():
    broker = MockBroker()
    broker.supports_pyramid = False
    oms = LiveOMS(broker, Portfolio.create_default())
    with pytest.raises(ValueError, match="pyramid"):
        oms.add_pyramid(open_position(size=10), 101, 99, 5, "t", 1)
```

- [ ] **Step 2: Run the tests and verify the current failure**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/test_pyramid_integration.py tests/quant/execution/test_pyramid_oms.py -q
```

Expected: FAIL because `LiveOMS.add_pyramid()` always raises.

- [ ] **Step 3: Construct a unique pyramid signal**

Use `dataclasses.replace()` on the base signal with the new entry, stop, a `pyramid:{level}` reason, and a deterministic signal ID based on the base position ID and level. Check `supports_pyramid()` before creating the signal; route it through the existing broker mapper and `execute_order()`.

- [ ] **Step 4: Map the broker fill into a linked position**

Use the broker-reported fill quantity and create a `Position` with `parent_position_id=base.id`, the new stop, the base TP, and the correct pyramid level. Add `supports_pyramid()` to Dhan and deterministic test brokers; leave unsupported brokers blocked. Do not create an in-memory position when the broker reports zero or an unknown fill.

- [ ] **Step 5: Reserve and release portfolio risk around the add**

Call `PortfolioRiskAuthority.can_accept(risk, symbol=base.order.signal.symbol, is_pyramid=True)` before submission and register only the actual filled risk. Release the reservation on rejection or broker failure; retain it for reconciliation.

- [ ] **Step 6: Add quantity-level tests for P1/P2**

```python
def test_pyramid_quantities_are_lot_rounded():
    broker = MockBroker()
    broker.execute_order.side_effect = [broker_fill(size=5), broker_fill(size=2)]
    oms = LiveOMS(broker, Portfolio.create_default(), lot_size=1)
    base = open_position(size=10)
    p1 = oms.add_pyramid(base, 101, 99, 5, "t", 1)
    p2 = oms.add_pyramid(base, 102, 99, 2, "t", 2)
    assert abs(p1.size) == 5
    assert abs(p2.size) == 2
    assert broker.execute_order.call_count == 2
```

- [ ] **Step 7: Run pyramid and risk tests and commit**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/execution/test_pyramid_integration.py tests/quant/execution/test_pyramid_oms.py tests/quant/test_pyramid_certification.py tests/quant/runtime/test_pyramid_accounting_parity.py -q
```

Expected: PASS.

Commit:

```bash
git add quant/contracts/ports/broker.py quant/execution/live_oms.py quant/execution/oms.py quant/position_manager.py quant/execution/risk.py quant/execution/portfolio_risk.py backend/app/infrastructure/adapters/dhan_broker_adapter.py tests/quant/execution/test_pyramid_integration.py tests/quant/execution/test_pyramid_oms.py tests/quant/test_pyramid_certification.py tests/quant/runtime/test_pyramid_accounting_parity.py
git commit -m "feat(execution): implement broker-backed AMT pyramiding"
```

### Task 5: Enforce evidence-family provenance at the live seam

**Files:**
- Modify: `quant/decision/data_quality.py:4-41`
- Modify: `quant/decision/context_builder.py:610-621,679-712`
- Modify: `quant/engine/decision_loop.py:409-487`
- Modify: `quant/engine/tick_handler.py:197-216`
- Modify: `quant/state.py:251-281`
- Test: `tests/quant/decision/test_proxy_live_entry_block.py`
- Test: `tests/quant/runtime/test_tick_handler.py`
- Test: `tests/quant/amt/test_analyzer.py`

**Interfaces:**
- Produces `failed_evidence_families(value) -> tuple[str, str, str, str, str]` and keeps `live_evidence_exact(value) -> bool` as a wrapper.
- `DecisionContext.evidence_provenance` is the sole per-family input used by the live gate.
- Missing live depth clears the cached book and yields `ofi_depth=UNAVAILABLE`; it never produces a synthetic one-tick book.

- [ ] **Step 1: Write failing provenance and depth tests**

```python
def test_live_block_names_each_non_exact_family():
    provenance = {
        "footprint_imbalance": DataQuality.TICK_EXACT,
        "cvd_delta": DataQuality.PRICE_DIRECTION_PROXY,
        "ofi_depth": DataQuality.UNAVAILABLE,
        "absorption": DataQuality.TICK_EXACT,
        "stacked_imbalance": DataQuality.TICK_EXACT,
    }
    assert failed_evidence_families(provenance) == ("cvd_delta", "ofi_depth")


def test_depthless_tick_does_not_synthesize_a_book():
    handler, depth_callback = make_handler_with_depth_callback()
    handler.process_tick(tick_without_depth())
    assert depth_callback.call_count == 0
```

```python
def test_paper_replay_keeps_proxy_metadata():
    loop = make_decision_loop(live=False, provenance=proxy_provenance())
    decision = loop.evaluate(proxy_amt_dto(), approved_bar())
    assert decision.approved is True
    assert decision.metadata["mode"] == "PROXY_MODE"


def test_live_replay_blocks_the_same_proxy_dto():
    loop = make_decision_loop(live=True, provenance=proxy_provenance())
    decision = loop.evaluate(proxy_amt_dto(), approved_bar())
    assert decision.approved is False
    assert decision.reason == "PROXY_FLOW_BLOCKED"
```

- [ ] **Step 2: Run the tests and verify the current failure**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_proxy_live_entry_block.py tests/quant/runtime/test_tick_handler.py -q
```

Expected: FAIL because `DecisionLoop` checks one aggregate quality value and `TickHandler` creates a synthetic depth object.

- [ ] **Step 3: Add per-family failure reporting**

Implement `failed_evidence_families()` using `REQUIRED_EVIDENCE_FAMILIES` and `normalize_evidence_provenance()`. Preserve deterministic family order.

- [ ] **Step 4: Replace the aggregate live check**

In `_build_decision()`, compute the failing family tuple from `ctx.evidence_provenance` when the OMS is live. Demote an otherwise-approved decision to `reason="PROXY_FLOW_BLOCKED"` and include the family names in `block_reasons`. In paper/replay, retain the decision and add explicit `PROXY_MODE` metadata.

- [ ] **Step 5: Remove synthetic depth**

Delete the `step = 0.05` fallback in `TickHandler.process_tick()`. In `LiveQuoteCache.on_quote()`, set the cached depth to `None` when `tick.depth` is absent so stale book data cannot authorize a later bar.

- [ ] **Step 6: Run evidence and decision tests and commit**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_proxy_live_entry_block.py tests/quant/runtime/test_tick_handler.py tests/quant/amt/test_analyzer.py -q
```

Expected: PASS for provenance and depth behavior; the three known analyzer assertions remain separately tracked for Task 7.

Commit:

```bash
git add quant/decision/data_quality.py quant/decision/context_builder.py quant/engine/decision_loop.py quant/engine/tick_handler.py quant/state.py tests/quant/decision/test_proxy_live_entry_block.py tests/quant/runtime/test_tick_handler.py tests/quant/amt/test_analyzer.py
git commit -m "fix(amt): enforce per-family live evidence provenance"
```

### Task 6: Align Triple-A Aggression with the canonical rules

**Files:**
- Modify: `quant/amt/triple_a.py:232-247`
- Modify: `quant/decision/gates_edge.py:227-295`
- Test: `tests/quant/decision/test_gate_triple_a_edge.py`
- Test: `tests/quant/decision/test_triple_a_lvn_proximity.py`
- Test: `tests/quant/test_production_correctness.py`
- Test: `tests/quant/amt/orderflow/test_cvd.py`

**Interfaces:**
- LONG Aggression requires `close > absorption_cluster_high`, `close > vwap`, and `cvd_slope > 0`.
- SHORT Aggression requires `close < absorption_cluster_low`, `close < vwap`, and `cvd_slope < 0`.
- Aggression does not require a nearby leg LVN; LVN Sniper/retest logic remains in its own path.

- [ ] **Step 1: Write failing boundary tests**

```python
@pytest.mark.parametrize("slope", [-0.1, -0.3, 0.0])
def test_long_aggression_rejects_nonpositive_cvd(slope):
    machine = absorbing_machine()
    result = machine.update(
        close=101,
        high=101.2,
        low=100,
        vwap=100,
        cvd_slope=slope,
        absorption_side="SELL_ABSORBED",
        absorption_active=True,
        absorption_cluster_high=100.5,
        absorption_cluster_low=99.5,
        poc=100,
        tick_size=0.05,
    )
    assert result.phase != "AGGRESSION"


def test_playbook_a_does_not_require_leg_lvn_proximity():
    context = approved_triple_a_context(leg_lvn=0.0, close=101, vwap=100)
    result = gate_triple_a_edge(context)
    assert result.passed is True
    assert result.setup_key == "TRIPLE_A"
```

- [ ] **Step 2: Run the tests and verify the current failure**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_gate_triple_a_edge.py tests/quant/decision/test_triple_a_lvn_proximity.py tests/quant/test_production_correctness.py -k "triple_a or aggression" -q
```

Expected: FAIL because `_confirm_direction()` permits mildly adverse CVD and the Aggression path rejects `leg_lvn=0`.

- [ ] **Step 3: Make `_confirm_direction()` literal**

Use strict sign checks after validating cluster and VWAP values. Do not accept zero or missing values as confirmation. Preserve the current state transition and expiry reset behavior.

- [ ] **Step 4: Separate Aggression from LVN retest**

Remove the LVN-proximity rejection from the Aggression branch. Keep proximity checks in the `LVN_SNIPER` branch and in pyramid authorization. Preserve compression-box and VWAP checks that are independent of LVN proximity.

- [ ] **Step 5: Run CVD and gate tests and commit**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt/orderflow/test_cvd.py tests/quant/decision/test_gate_triple_a_edge.py tests/quant/decision/test_triple_a_lvn_proximity.py tests/quant/test_production_correctness.py -q
```

Expected: PASS.

Commit:

```bash
git add quant/amt/triple_a.py quant/decision/gates_edge.py tests/quant/decision/test_gate_triple_a_edge.py tests/quant/decision/test_triple_a_lvn_proximity.py tests/quant/test_production_correctness.py tests/quant/amt/orderflow/test_cvd.py
git commit -m "fix(amt): align Triple-A Aggression with canonical rules"
```

### Task 7: Complete option and risk eligibility

**Files:**
- Modify: `quant/multi_engine.py:1980-2029`
- Modify: `quant/decision/gate_session_phase.py:75-99`
- Modify: `quant/amt/session/scanner.py:27-45,102-145,415-494`
- Modify: `quant/execution/risk.py:64,579-607`
- Modify: `backend/app/config/environments/live.yaml:15-25`
- Test: `tests/quant/test_underlying_feed.py`
- Test: `tests/quant/decision/test_option_signal_translation.py`
- Test: `tests/quant/decision/test_option_delta_semantics.py`
- Test: `tests/quant/execution/test_risk_config_propagation.py`
- Test: `tests/quant/execution/test_risk.py`

**Interfaces:**
- Option engines with no underlying gateway are observation-only (`execution_enabled=False`) and never create a paper/live AMT order.
- Missing option delta is `None`, never the invented value `0.50`; contracts without a valid delta are excluded from scoring.
- `SessionRisk` exposes the effective per-trade risk and HMP tier used by the shipped live configuration.

- [ ] **Step 1: Write failing option and risk tests**

```python
def test_option_without_underlying_is_observation_only():
    coordinator = make_coordinator(option_without_underlying=True)
    engine = coordinator._spawn_engine(option_symbol())
    assert engine is not None
    assert engine._decision_loop._execution_enabled is False


def test_scanner_rejects_missing_delta_without_inventing_half():
    result = OptionScannerService._score_contract(
        strike=100,
        atm=100,
        interval=50,
        oi=10000,
        vol=1000,
        opt=option(delta=None),
        ltp=50,
        bid=49,
        ask=51,
        underlying_upper="NIFTY",
    )
    assert result[2] is None


def test_live_config_uses_the_house_money_floor(monkeypatch):
    monkeypatch.setenv("GLASSYTRADE_ENV", "live")
    config = load_config()
    assert config.risk.risk_per_trade_pct == pytest.approx(0.0025)


def test_effective_risk_state_reports_the_floor():
    risk = SessionRisk(starting_equity=1_000_000, base_risk_pct=0.0025, day_of_week=1)
    assert risk.state().risk_per_trade_pct == pytest.approx(0.0025)
    assert risk.state().cushion_tier == "CONSERVATIVE"
```

- [ ] **Step 2: Run the tests and verify the current failure**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/test_underlying_feed.py tests/quant/decision/test_option_signal_translation.py tests/quant/decision/test_option_delta_semantics.py tests/quant/execution/test_risk_config_propagation.py -q
```

Expected: FAIL because premium-only fallback is currently permitted, scanner scoring substitutes `0.50`, and the live per-trade value is silently transformed to `0.25%`.

- [ ] **Step 3: Disable execution without an underlying**

In `_spawn_engine()`, set option `execution_enabled` to `False` when `underlying_gateway is None`. Keep chart/AMT observation available, but ensure the decision loop cannot submit an order and records the reason.

- [ ] **Step 4: Remove invented option delta**

Use `delta = None if opt.delta is None else abs(float(opt.delta))`. Return `None` from scoring for a missing delta, omit the delta bonus, and skip the contract before ranking. Keep valid positive and negative delta semantics unchanged.

- [ ] **Step 5: Align spread/expiry policy with the AMT document**

Move the option/futures spread and stop-distance values to the existing contract constants or a single policy function. Remove duplicate values from the gate and exit path. Preserve the documented expiry adjustment with one named test.

- [ ] **Step 6: Make effective risk configuration explicit**

Set the shipped live base risk to the House Money floor (`0.0025`) and keep the configured value visible as `base_risk_pct`. Add `effective_base_risk_pct` to the runtime risk-state summary so the 0.25% HMP floor and any named tier transformation are observable. The startup summary must print the effective value, not only the raw YAML value.

- [ ] **Step 7: Run the option/risk tests and commit**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/test_underlying_feed.py tests/quant/decision/test_option_signal_translation.py tests/quant/decision/test_option_delta_semantics.py tests/quant/execution/test_risk_config_propagation.py tests/quant/execution/test_risk.py -q
```

Expected: PASS.

Commit:

```bash
git add quant/multi_engine.py quant/decision/gate_session_phase.py quant/amt/session/scanner.py quant/execution/risk.py backend/config/environments/live.yaml tests/quant/test_underlying_feed.py tests/quant/decision/test_option_signal_translation.py tests/quant/decision/test_option_delta_semantics.py tests/quant/execution/test_risk_config_propagation.py tests/quant/execution/test_risk.py
git commit -m "fix(options): require underlying data and explicit risk policy"
```

### Task 8: Restore the AMT analyzer/certification release contract

**Files:**
- Modify: `quant/amt/analyzer.py:543-707`
- Modify: `quant/amt/profile/vwap.py:121-221`
- Modify: `tests/quant/amt/test_analyzer.py:230-260,800-960`
- Modify: `tests/quant/test_production_correctness.py:130-220`
- Modify: `tests/quant/test_certification.py:227-295`
- Test: `tests/quant/amt/test_analyzer.py`
- Test: `tests/quant/test_certification.py`

**Interfaces:**
- Decision VA, balance ratio, VWAP, and sigma use the same recent auction window after a regime collapse.
- Raw statistical sigma is published; no hidden floor changes the reported band width.
- Session extremes remain separate fields for failed-auction/VA-fade decisions.
- Certification assertions verify effective quantities, not only passed fraction arguments.

- [ ] **Step 1: Add the three failing analyzer regression tests**

```python
def test_collapsed_regime_uses_recent_decision_value_area():
    result = analyze_collapse_fixture()
    assert result.poc > 95
    assert result.value_area_high < 125
    assert result.value_area_low <= result.poc <= result.value_area_high


def test_session_va_is_bounded_by_session_extremes():
    result = analyze_displacement_fixture()
    assert result.value_area_low >= result.session_extreme_low - 0.01
    assert result.value_area_high <= result.session_extreme_high + 0.01


def test_published_vwap_sigma_is_raw():
    result = analyze_collapse_fixture()
    assert abs(result.vwap_upper_1 - result.session_vwap) < 1.0
    assert abs(result.vwap_deviation_sigmas) < 3.0
```

Use the existing fixture helpers and keep the input-window bounds local to the test; do not add a new public `AMTResult` field solely for the regression assertion.

- [ ] **Step 2: Run the analyzer suite and verify the three current failures**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt/test_analyzer.py -q
```

Expected: 3 failures at the collapsed-regime VA, lower-bound, and raw-sigma assertions.

- [ ] **Step 3: Use the recent window for decision VA**

Compute the recent-window VA and use it for decision `vah`/`val`, while preserving session extremes in their own fields. Ensure the resulting interval contains the POC; if the clamp would exclude it, widen the interval to include the POC and retain the current high/low bounds.

- [ ] **Step 4: Remove the hidden sigma floor from published bands**

Make `SessionVWAP.bands()` use raw recent-window sigma for the returned ±1σ/±2σ values. Keep deviation calculation on the same raw sigma. Remove the hidden `max(1.0, 0.1%×vwap)` band floor so the published bands match the published sigma.

- [ ] **Step 5: Make certification quantity assertions explicit**

In `test_s10_pyramid_cert_records_flow`, assert the final base, P1, P2, and remaining sizes after lot snapping. Retain the current `snap_to_lot` floor policy for paper sizing and update the P2 expectation to the produced lot-rounded quantity; do not change rounding behavior in this task.

- [ ] **Step 6: Run the focused suites and commit**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt/test_analyzer.py tests/quant/test_production_correctness.py tests/quant/test_certification.py -q
```

Expected: no failures in the three affected contracts; explicitly documented pre-existing skips remain.

Commit:

```bash
git add quant/amt/analyzer.py quant/amt/profile/vwap.py tests/quant/amt/test_analyzer.py tests/quant/test_production_correctness.py tests/quant/test_certification.py
git commit -m "fix(amt): restore analyzer and certification contracts"
```

### Task 9: Make feed shutdown deterministic for the full suite

**Files:**
- Modify: `quant/brokers/multiplexed_feed.py:269-337,339-425`
- Modify: `tests/quant/test_multiplexed_feed.py`
- Test: `tests/quant/runtime/test_ws_adapter.py`
- Test: `tests/quant/test_multiplexed_feed.py`

**Interfaces:**
- `MultiplexedMarketFeed.close()` is idempotent, stops retries immediately, cancels pending async stream tasks, joins the producer, and wakes all readers.
- Test fixtures always close feed objects in teardown.
- No daemon thread remains retrying after a test or coordinator shutdown.

- [ ] **Step 1: Write a failing shutdown test**

```python
def test_close_stops_retry_loop_and_joins_producer():
    feed = make_feed_with_failing_stream()
    feed.subscribe("NIFTY")
    feed.close()
    assert feed._thread is None or not feed._thread.is_alive()
    assert all(reader.empty() or reader.get_nowait() is None for reader in feed._queues.values())
```

- [ ] **Step 2: Run the test and verify the current failure**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/runtime/test_ws_adapter.py -k "close or shutdown or feed" -q
```

Expected: FAIL or hang because the producer’s pending `stream_full.__anext__()` task is not cancelled during close.

- [ ] **Step 3: Track and cancel pending async tasks**

Keep references to the `anext_full` and `anext_depth` tasks, cancel them in the `finally` branch, await cancellation, and close both streams. Check `_stop` before every retry and before sleeping.

- [ ] **Step 4: Make close idempotent and clear thread state**

Set `_thread=None` after a successful join, use a lock around reader notification, and make repeated `close()` calls return without starting a new producer.

- [ ] **Step 5: Add fixture cleanup**

```python
@pytest.fixture
def managed_feed():
    feed = make_feed_with_failing_stream()
    try:
        yield feed
    finally:
        feed.close()
```

- [ ] **Step 6: Run feed tests and commit**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/runtime/test_ws_adapter.py tests/quant/test_multiplexed_feed.py -q
```

Expected: PASS and no non-daemon retry process remains.

Commit:

```bash
git add quant/brokers/multiplexed_feed.py tests/quant/runtime/test_ws_adapter.py tests/quant/test_multiplexed_feed.py
git commit -m "fix(feed): make shutdown deterministic"
```

### Task 10: Run the release convergence loop and document evidence

**Files:**
- Modify: `tests/quant/runtime/` only for confirmed stale fixtures whose assertions contradict the approved contracts.
- Modify: `tests/quant/test_stress_and_portfolio_risk.py` only for confirmed contract drift, not to hide production failures.
- Modify: `docs/amt/AMT_INSTITUTIONAL_SCALPER_ALGORITHM.md`
- Modify: `docs/amt/fabio_decision_pipeline.md`
- Modify: `docs/amt/WALKTHROUGH.md`
- Create: `docs/architecture/amt-live-readiness-workflow.md` (Mermaid source-backed runtime workflow)
- Create: `docs/reviews/2026-09-24-amt-live-readiness-report.md`
- Modify: overlapping old plans only to add a superseded-status banner.

**Interfaces:**
- The final report records exact commands, exit codes, test counts, remaining skips, proxy deviations, and live-blocked conditions.
- The architecture artifact includes OMS, broker capability, actual fill, reconciliation, durable event, and canonical projection edges.
- The AMT docs no longer claim unverified completion or numerical/live parity.

- [ ] **Step 1: Run the full quant suite with failure capture**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/ -q --maxfail=1
```

Expected: the first remaining failure is captured with a complete traceback. Fix production behavior first; update a test only when the approved design makes its old expectation invalid.

- [ ] **Step 2: Run the focused AMT/decision/execution/runtime merge gate**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt tests/quant/decision tests/quant/execution tests/quant/runtime tests/quant/test_certification.py tests/architecture -q
```

Expected: 0 failures, with only explicitly documented skips.

- [ ] **Step 3: Run the repository release targets**

```bash
make lint
make parity
make pre-release
make test-quant
(cd frontend && npm test -- --run)
```

Expected: every command exits 0. If `make test-quant` still reports failures, do not update the completion claim or push the final branch.

- [ ] **Step 4: Update AMT documentation**

Document the exact live evidence policy, Triple-A conditions, stop/fill/reconciliation behavior, option-underlying requirement, effective HMP configuration, and the remaining difference between paper/replay and live execution. Remove stale “100% complete” claims that are not supported by the current command output.

- [ ] **Step 5: Update the architecture contract**

Create `docs/architecture/amt-live-readiness-workflow.md` with a Mermaid diagram containing these source-backed edges:

```text
SignalBuilder -> SessionRisk -> PortfolioRiskAuthority
PortfolioRiskAuthority -> OMS -> Broker
Broker -> FillNormalization -> Reconciliation
Reconciliation -> PositionManager -> EventStore
EventStore -> CanonicalProjection -> WebSocket/UI
DecisionContext -.-> Advisory
```

Keep the narrative edge advisory-only and do not label the diagram as exact broker integration proof.

- [ ] **Step 6: Write the verification report**

Create `docs/reviews/2026-09-24-amt-live-readiness-report.md` with:

- commit/branch identity;
- commands and exit codes;
- test pass/fail/skip counts;
- live-safety invariants covered;
- documented proxy deviations;
- unresolved risks, if any;
- explicit statement that no live order or broker credential was used.

- [ ] **Step 7: Review the diff and stage only intended files**

```bash
git status --short
git diff --check
git diff --stat
```

Do not stage `automation/reports/`.

- [ ] **Step 8: Commit the final release evidence**

```bash
git add docs/amt/AMT_INSTITUTIONAL_SCALPER_ALGORITHM.md docs/amt/fabio_decision_pipeline.md docs/amt/WALKTHROUGH.md docs/architecture/amt-live-readiness-workflow.md docs/reviews/2026-09-24-amt-live-readiness-report.md docs/superpowers/plans/2026-09-18-amt-live-safety-remediation.md docs/superpowers/plans/2026-09-23-full-amt-fidelity.md
git commit -m "docs(amt): record live readiness evidence"
```

If test-only corrections are required, stage their exact paths in a separate commit after reviewing the diff.

- [ ] **Step 9: Push the verified branch**

```bash
git push -u origin feat/amt-live-readiness
```

Expected: the remote branch is created and the local commit is the pushed tip. Do not force-push.

## Dependency Order

```text
Task 1 -> Task 2 -> Task 3 -> Task 4
Task 1 -> Task 5 -> Task 6 -> Task 7
Task 5 -> Task 8
Task 9 -> Task 10
Tasks 1-9 -> final push
```

Tasks 5, 6, and 7 may be reviewed in parallel only when their file sets do not overlap. Task 10 is serial and starts only after all implementation tasks are green.

## Final Self-Review Checklist

- [ ] Every approved design decision maps to a task: evidence, Triple-A, stops, fills, close IDs, reconciliation, pyramids, options, risk, tests, docs, branch, and push.
- [ ] Every production task has a failing-test step, a focused red run, a minimal implementation step, a green run, and a commit.
- [ ] No task uses `TBD`, `TODO`, “fix all failures,” or an unspecified file path.
- [ ] New field names are consistent across `Position`, persistence, broker adapters, OMS, and tests.
- [ ] The plan does not claim live readiness from mocked tests alone.
- [ ] The final push occurs only after all release commands exit successfully.
