# AMT Live Safety Remediation Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Prevent proxy AMT evidence from creating live entries, preserve directional flow correctness, and keep broker exposure and durable lifecycle state consistent through partial fills, failures, and restart.

**Architecture:** Harden the existing `DataQuality`, `ExposureState`, `DecisionContext`, `DecisionLoop`, OMS, and EventStore seams. First make AMT evidence directional and provenance-aware; then enforce the live-entry boundary; then complete broker reconciliation and durable lifecycle behavior; finally update the architecture artifact to match tested runtime boundaries.

**Tech Stack:** Python 3, pytest, FastAPI/WebSocket runtime, PaperOMS/LiveOMS, Dhan broker adapter, append-only EventStore, inline SVG/HTML architecture artifact.

## Global Constraints

- Proxy AMT evidence may be used for paper/replay analysis but must block live AMT entries.
- Numerical AMT parity is deferred; do not change 68.2% value area, LVN, absorption, or range-bar thresholds in this plan.
- `DecisionService`/`GatePipeline` remains the sole deterministic entry authority.
- Narrative/advisor output remains advisory-only.
- Preserve unrelated dirty worktree changes; modify only files required by each task.
- Every production behavior change requires a failing test first.
- Do not claim live readiness until broker partial/unknown/restart tests and event persistence tests pass.

---

### Task 1: Make AMT Flow Directional and Provenance-Aware

**Files:**
- Modify: `quant/amt/orderflow/compute.py:21-144`
- Modify: `quant/amt/analyzer.py:627-658`
- Modify: `quant/amt/orderflow/aggression.py:118-224`
- Modify: `quant/amt/dto.py:45-60`
- Modify: `quant/decision/data_quality.py:1-25`
- Modify: `quant/decision/context.py:1-50`
- Modify: `quant/decision/context_builder.py:489-566`
- Test: `tests/quant/amt/orderflow/test_directional_compute.py`
- Test: `tests/quant/amt/orderflow/test_aggression_direction.py`
- Test: `backend/tests/unit/domain/test_amt_analyzer.py`
- Test: `tests/architecture/test_amt_dto_contract.py`

**Interfaces:**
- Consumes: `market_state`, `cvd_state`, `current`, AMT flow detectors, and candidate direction from the analyzer/context path.
- Produces: `cvd_confirmed` and aggression results that cannot credit opposing signed flow; DTO/context fields that retain normalized flow quality.

- [ ] **Step 1: Write the failing CVD direction tests.**

Add tests that call the real `compute_order_flow_metrics()` with `MarketState.IMBALANCED` and a positive or negative CVD slope. Assert that a LONG candidate only confirms positive slope and a SHORT candidate only confirms negative slope. Add a test that an opposing slope leaves `cvd_confirmed` false.

```python
def test_imbalanced_cvd_only_confirms_candidate_direction():
    long_flow = compute_order_flow_metrics(
        recent_data=[bar], order_book=None, current=bar,
        agg_prints=[], market_state=MarketState.IMBALANCED,
        lvns=[], vah=0, val=0, poc=0, tick_size=1,
        cvd_state=CVDState(slope=-1.0), candidate_direction="LONG",
    )
    assert long_flow["cvd_confirmed"] is False
```

- [ ] **Step 2: Run the focused tests and verify the expected failure.**

Run:

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/amt/orderflow/test_directional_compute.py -q
```

Expected: FAIL because `compute_order_flow_metrics()` currently has no candidate-direction contract and confirms both CVD signs in `IMBALANCED` state.

- [ ] **Step 3: Add the minimal direction argument and directional CVD rule.**

Extend `compute_order_flow_metrics()` with `candidate_direction: str | None = None`. When a direction is supplied, confirm only the matching CVD sign. Preserve directionless behavior only for display-only callers; the analyzer must always pass its candidate direction before scoring.

```python
def _cvd_confirms(cvd_state, market_state, candidate_direction):
    if cvd_state is None:
        return False
    if cvd_state.has_divergence:
        return True
    if market_state is not MarketState.IMBALANCED:
        return False
    if candidate_direction == "LONG":
        return cvd_state.slope > 0
    if candidate_direction == "SHORT":
        return cvd_state.slope < 0
    return cvd_state.slope != 0
```

- [ ] **Step 4: Write the failing analyzer-to-scorer propagation test.**

Use a real analyzer fixture with a LONG direction, negative `norm_delta`, negative CVD slope, opposing absorption, and opposing OFI. Assert the resulting aggression score is zero or below the configured minimum and `direction_opposed` is true. The test must observe the active analyzer path, not call `AggressionScorer` directly.

- [ ] **Step 5: Run the propagation test and verify it fails for the current legacy additive path.**

Run:

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest backend/tests/unit/domain/test_amt_analyzer.py -k directional -q
```

Expected: FAIL because `analyzer.py` currently calls the scorer without direction or signed inputs.

- [ ] **Step 6: Pass signed flow and direction through the active path.**

Pass `candidate_direction`, `cvd_slope`, `ofi_result.ofi`, `norm_delta`, and `absorption_side` from `analyzer.py` to `compute_order_flow_metrics()`, then pass those values from `compute.py` into `persistent_agg_scorer.score()`. Keep the existing directionless scorer API for explicitly display-only callers.

- [ ] **Step 7: Add provenance fields without changing numerical thresholds.**

Use the existing `DataQuality` vocabulary and DTO normalization. Add a normalized flow-quality mapping for each required evidence family, defaulting unknown values to fail-closed. `CANDLE_DISTRIBUTED` remains valid for paper/replay but is not upgraded to `TICK_EXACT` merely because a footprint object exists.

- [ ] **Step 8: Run the focused AMT suites.**

Run:

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest \
  tests/quant/amt/orderflow \
  tests/quant/amt/market \
  backend/tests/unit/domain/test_amt_analyzer.py \
  tests/architecture/test_amt_dto_contract.py -q
```

Expected: all existing tests pass, with new tests proving directional behavior and normalized provenance.

- [ ] **Step 9: Commit the directional AMT change.**

```bash
git add quant/amt/orderflow/compute.py quant/amt/analyzer.py quant/amt/orderflow/aggression.py quant/amt/dto.py quant/decision/data_quality.py quant/decision/context.py quant/decision/context_builder.py tests/quant/amt/orderflow/test_directional_compute.py tests/quant/amt/orderflow/test_aggression_direction.py backend/tests/unit/domain/test_amt_analyzer.py tests/architecture/test_amt_dto_contract.py
git commit -m "fix(amt): preserve directional flow and provenance"
```

### Task 2: Block Proxy AMT Entries in Live Mode

**Files:**
- Modify: `quant/decision/decision_service.py:60-100`
- Modify: `quant/decision/context.py:1-50`
- Modify: `quant/engine/decision_loop.py:219-291`
- Modify: `quant/engine/submission_handler.py:100-145`
- Modify: `quant/execution/flow_provenance.py:1-25`
- Modify: `quant/execution/risk.py:280-300`
- Test: `tests/quant/decision/test_proxy_live_entry_block.py`
- Test: `tests/quant/test_decision_loop.py`
- Test: `tests/quant/test_submission_handler.py`

**Interfaces:**
- Consumes: `DecisionContext.data_quality`, runtime mode, and an approved `QuantDecision`.
- Produces: distinct `PROXY_FLOW_BLOCKED` decision/submission reason in live mode; paper/replay continues with `PROXY_MODE` metadata.

- [ ] **Step 1: Write the failing live-block test.**

Construct a valid otherwise-approved decision context with `DataQuality.CANDLE_DISTRIBUTED`, configure live mode, and assert the decision is rejected with `PROXY_FLOW_BLOCKED` before OMS submission.

```python
def test_live_entry_blocks_candle_distributed_amt_evidence(live_decision_loop, approved_context):
    approved_context.data_quality = DataQuality.CANDLE_DISTRIBUTED
    decision = live_decision_loop.evaluate(approved_context.dto, approved_context.bar)
    assert decision.approved is False
    assert decision.reason == "PROXY_FLOW_BLOCKED"
    assert live_decision_loop.oms.submissions == []
```

- [ ] **Step 2: Run the test and verify it fails.**

Run:

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest tests/quant/decision/test_proxy_live_entry_block.py -q
```

Expected: FAIL because current conviction/data-quality handling treats candle-distributed data as allowed for the active entry path.

- [ ] **Step 3: Implement the narrow live-entry gate.**

Add a single decision-layer predicate that returns true only for exact required evidence in live mode. Invoke it after the deterministic strategy decision is built but before quantity translation or OMS submission. Return `PROXY_FLOW_BLOCKED` and emit the same `DecisionProduced`/certification telemetry path used by other blocks.

- [ ] **Step 4: Preserve paper/replay behavior explicitly.**

For paper/replay, allow proxy decisions but attach `PROXY_MODE` to the decision record and DTO/telemetry. Do not silently convert proxy evidence into exact evidence. Add tests for paper approval and for unknown provenance failing closed in live mode.

- [ ] **Step 5: Run entry and certification suites.**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest \
  tests/quant/decision/test_proxy_live_entry_block.py \
  tests/quant/test_decision_loop.py \
  tests/quant/test_submission_handler.py \
  tests/quant/test_certification.py -q
```

- [ ] **Step 6: Commit the live provenance boundary.**

```bash
git add quant/decision/decision_service.py quant/decision/context.py quant/engine/decision_loop.py quant/engine/submission_handler.py quant/execution/flow_provenance.py quant/execution/risk.py tests/quant/decision/test_proxy_live_entry_block.py tests/quant/test_decision_loop.py tests/quant/test_submission_handler.py
git commit -m "fix(trading): block proxy AMT entries in live mode"
```

### Task 3: Complete Partial/Unknown Fill Reconciliation

**Files:**
- Modify: `quant/execution/exposure.py:1-55`
- Modify: `quant/execution/execution_state_machine.py:1-55`
- Modify: `quant/engine/submission_handler.py:200-250`
- Modify: `quant/execution/live_oms.py:1-430`
- Modify: `backend/app/infrastructure/adapters/dhan_broker_adapter.py:220-330`
- Modify: `quant/runtime.py:450-470,875-900,1300-1410`
- Modify: `quant/multi_engine.py` startup/reconciliation wiring
- Test: `tests/quant/execution/test_exposure_state.py`
- Test: `tests/quant/execution/test_live_partial_fill_reconciliation.py`
- Test: `tests/quant/execution/test_restart_reconciliation.py`
- Test: `tests/quant/execution/test_close_identity.py`

**Interfaces:**
- Consumes: normalized broker order result, requested quantity, filled quantity/average price, durable exposure state.
- Produces: explicit `RECONCILIATION_REQUIRED` state; entry blocking until resolution; one economic close identity across retries/fallbacks.

- [ ] **Step 1: Write failing partial, unknown, and restart tests.**

Cover these exact cases:

```python
def test_partial_entry_keeps_risk_and_blocks_new_entry():
    result = broker.submit_partial(requested_qty=10, filled_qty=4)
    assert result.status == ExecutionStatus.RECONCILIATION_REQUIRED
    assert risk.reservation_exists(result.order_id)
    assert entry_guard.blocked_reason() == "RECONCILIATION_REQUIRED"

def test_unknown_entry_is_not_clean_rejection():
    result = broker.submit_unknown()
    assert result.status == ExecutionStatus.RECONCILIATION_REQUIRED

def test_restart_restores_unresolved_exposure():
    persist_partial(symbol="MCX", order_id="o1", filled_qty=4)
    restarted = build_engine_from_storage()
    assert restarted.exposure_state.status is ExposureStatus.RECONCILIATION_REQUIRED
```

- [ ] **Step 2: Run the tests and confirm the lifecycle failure.**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest \
  tests/quant/execution/test_live_partial_fill_reconciliation.py \
  tests/quant/execution/test_restart_reconciliation.py -q
```

Expected: FAIL where adapter/OMS behavior currently returns a failed/flat result or loses unresolved state across construction.

- [ ] **Step 3: Normalize broker outcomes before local bookkeeping.**

Ensure every live submit result distinguishes `FILLED`, `PARTIAL`, `REJECTED`, `UNKNOWN`, and `RECONCILIATION_REQUIRED`. A partial or unknown result must call `ExposureState.partial_entry()` or an equivalent explicit unknown constructor before releasing any risk reservation.

- [ ] **Step 4: Persist and restore exposure state.**

Use the existing exposure persistence/restart hooks in `quant/runtime.py`. Persist symbol, order identity, requested quantity, filled quantity, average price, and status. On startup, restore unresolved exposure before accepting decisions and invoke broker reconciliation. Do not reset unresolved state to `NONE` when the broker query fails.

- [ ] **Step 5: Gate entries on unresolved exposure.**

Make `_entry_guards()` and submission handling reject new entries while any unresolved exposure exists. Keep the risk reservation until reconciliation returns `RECONCILED_OPEN` or `RECONCILED_FLAT`.

- [ ] **Step 6: Add close idempotency tests before implementation.**

Test that a collared close followed by market fallback uses one durable close identity, and a late fill from the original order is linked to that identity without double-counting position size or P&L.

- [ ] **Step 7: Implement one economic close identity.**

Add or reuse a stable close intent ID passed through `LiveOMS`, `DhanBrokerAdapter`, fill normalization, and event emission. Retries may have broker order IDs, but all belong to one close intent.

- [ ] **Step 8: Run execution and recovery suites.**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest \
  tests/quant/execution \
  tests/quant/chaos/test_crash_recovery.py \
  tests/quant/test_decision_loop.py \
  tests/quant/test_submission_handler_integration.py -q
```

- [ ] **Step 9: Commit reconciliation safety.**

```bash
git add quant/execution/exposure.py quant/execution/execution_state_machine.py quant/engine/submission_handler.py quant/execution/live_oms.py backend/app/infrastructure/adapters/dhan_broker_adapter.py quant/runtime.py quant/multi_engine.py tests/quant/execution/test_exposure_state.py tests/quant/execution/test_live_partial_fill_reconciliation.py tests/quant/execution/test_restart_reconciliation.py tests/quant/execution/test_close_identity.py
git commit -m "fix(execution): preserve unresolved broker exposure"
```

### Task 4: Make Durable Events and Architecture Artifact Match Runtime

**Files:**
- Modify: `quant/runtime.py:1717-1734`
- Modify: `quant/event_store.py:247-439`
- Modify: `quant/transitions.py:230-250`
- Modify: `quant/multi_engine.py:760-780`
- Modify: `quant/ws_adapter.py`
- Modify: `backend/app/api/websocket/gameloop.py`
- Modify: `quant/decision/gap_architecture.workflow.html`
- Modify: `quant/decision/gap_architecture.workflow.json`
- Test: `tests/quant/runtime/test_eventstore_failure_consistency.py`
- Test: `tests/quant/runtime/test_snapshot_projection.py`
- Test: `tests/quant/test_event_store_roundtrip_real.py`
- Test: `tests/architecture/test_gap_architecture_contract.py`

**Interfaces:**
- Consumes: lifecycle event, EventStore append result, folded state, coordinator snapshot.
- Produces: canonical event-backed state or explicit degraded state; diagram edges matching the tested path.

- [ ] **Step 1: Write failing EventStore consistency tests.**

Assert that an append failure does not produce a canonical `PositionOpened` projection, and that snapshot consumers receive a degraded/reconciliation marker rather than silently receiving mutable fallback state.

```python
def test_event_append_failure_does_not_advance_canonical_position_state(engine):
    engine.event_store.append = fail_storage
    engine.emit(PositionOpened(...))
    assert engine.canonical_state.position is None
    assert engine.snapshot.degraded is True
```

- [ ] **Step 2: Run the focused tests and verify failure.**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest \
  tests/quant/runtime/test_eventstore_failure_consistency.py \
  tests/quant/runtime/test_snapshot_projection.py -q
```

Expected: FAIL because EventBus/operational side effects currently precede tolerated EventStore failure and snapshot fallback masks fold errors.

- [ ] **Step 3: Implement explicit append failure behavior.**

Define whether the event is retried or the engine enters degraded mode, but never mark the durable projection successful when append failed. Preserve the event identity and failure diagnostic. Block new live entries while canonical lifecycle state is degraded.

- [ ] **Step 4: Make unmatched transition events observable.**

Keep replay tolerance, but emit a structured diagnostic containing event type, symbol, position/order identity, and sequence when a partial/reduction cannot be applied.

- [ ] **Step 5: Add architecture contract assertions.**

Represent the workflow as source metadata in `gap_architecture.workflow.json` and test that it contains these edges:

```text
SignalBuilder -> Risk
Risk -> OMS
OMS -> Broker
Broker -> Reconciliation
Reconciliation -> PositionManager
PositionManager -> EventStore
EventStore -> Canonical Projection
Canonical Projection -> WebSocket/UI
DecisionContext -.-> Narrative
```

- [ ] **Step 6: Update the HTML diagram.**

Add nodes and edges for durable order intent, OMS/Broker, normalized fill, reconciliation, EventStore, canonical projection, and WebSocket/UI. Change the narrative/grade link to a dashed advisory-only path. Do not label the diagram as exact Fabio parity.

- [ ] **Step 7: Run full relevant verification.**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest \
  tests/quant/amt \
  tests/quant/decision \
  tests/quant/execution \
  tests/quant/runtime \
  tests/quant/test_certification.py \
  tests/architecture -q
```

Expected: all relevant tests pass, with only explicitly documented pre-existing skips.

- [ ] **Step 8: Commit durable projection and architecture documentation.**

```bash
git add quant/runtime.py quant/event_store.py quant/transitions.py quant/multi_engine.py quant/ws_adapter.py backend/app/api/websocket/gameloop.py quant/decision/gap_architecture.workflow.html quant/decision/gap_architecture.workflow.json tests/quant/runtime/test_eventstore_failure_consistency.py tests/quant/runtime/test_snapshot_projection.py tests/quant/test_event_store_roundtrip_real.py tests/architecture/test_gap_architecture_contract.py
git commit -m "docs(runtime): align lifecycle architecture with durable state"
```

### Task 5: Final Release Gate and Live-Readiness Report

**Files:**
- Modify: `docs/amt/fabio_decision_pipeline.md`
- Modify: `docs/reviews/2026-09-11-full-system-adversarial-review.md` only for verified status updates
- Create: `docs/reviews/2026-09-18-amt-live-safety-verification.md`
- Test: existing release/certification suites

- [ ] **Step 1: Run focused regression suites.**

```bash
PYTHONPATH=backend:. .venv/bin/python -m pytest \
  tests/quant/amt \
  tests/quant/decision \
  tests/quant/execution \
  tests/quant/runtime \
  tests/quant/test_certification.py -q
```

- [ ] **Step 2: Run the project release gate.**

```bash
make test-quant
```

If the repository's current release command differs, use the command documented by the existing Makefile; do not substitute a green partial suite for the release gate.

- [ ] **Step 3: Verify live safety conditions.**

The verification report must state separately:

- directional AMT tests passed;
- proxy live-entry blocks passed;
- paper/replay proxy mode passed;
- partial/unknown/restart reconciliation passed;
- EventStore failure behavior passed;
- architecture contract passed;
- numerical AMT parity remains deferred;
- live status is `NO-GO` if any broker/exposure or persistence gate remains incomplete.

- [ ] **Step 4: Commit the verification report and verified documentation changes.**

```bash
git add docs/amt/fabio_decision_pipeline.md docs/reviews/2026-09-11-full-system-adversarial-review.md docs/reviews/2026-09-18-amt-live-safety-verification.md
git commit -m "docs: record AMT live safety verification"
```

## Self-Review Checklist

- [x] Every confirmed finding has a task: proxy flow, directional CVD/aggression, partial exposure, EventStore consistency, and architecture mismatch.
- [x] Numerical AMT parity is explicitly deferred and not accidentally mixed into safety work.
- [x] Existing partial `ExposureState` and data-quality primitives are reused.
- [x] Every production change begins with a focused failing test.
- [x] The diagram update is after runtime changes and contract tests.
- [x] No task requires reverting unrelated worktree changes.
- [x] Completion criteria distinguish paper/replay readiness from live readiness.
