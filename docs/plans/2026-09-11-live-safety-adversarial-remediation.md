# Live-Safety and Adversarial Correctness Remediation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans. Steps use checkbox syntax.

**Goal:** Close the P0/P1 findings from the 2026-09-11 adversarial review so live Indian-market execution has timestamped forecast inputs, exact exposure ownership, durable broker reconciliation, and truthful AMT provenance.

**Architecture:** Separate the work into three safety boundaries: observation identity, broker exposure lifecycle, and canonical event persistence. A trade cannot advance to the next state until the preceding boundary has a durable, replayable record. Inferred AMT data remains explicitly constrained; it is never silently treated as exact order flow.

**Tech Stack:** Python 3.13, pytest, numpy, existing Dhan adapters, JSONL/SQLite persistence. No new dependencies.

## Global Constraints

- No live order may be submitted from a forming or unidentifiable observation.
- No partial broker exposure may be represented as local flat state.
- No event side effect may outrun the canonical durable append without a fail-stop/readiness signal.
- `EventStore.fold()` is the canonical projected state; mutable runtime state is operational cache only.
- `PositionManager` is the only position lifecycle owner; OMS is the execution boundary; broker state is reconciled explicitly.
- Exact trade-side/L2 claims require `TICK_EXACT`; candle-distributed/Gaussian data cannot silently approve rules requiring exact flow.
- Every new event/schema field must have backward-compatible replay behavior.
- Preserve the user's unrelated `brokers/broker/dhan/infrastructure/symbol_mapper.py` modification.
- Run tests per-directory to avoid OpenMP contention. Never use one unbounded combined pytest invocation as the only verification.

---

## Wave L1 — Observation and AMT correctness

### Task 1: Canonical `ForecastObservationIdentity`

**Files:**
- Create: `quant/modeling/observation.py`
- Modify: `quant/decision/timesfm_engine.py`, `quant/strategies/timesfm_strategy.py`, `quant/modeling/forecast_provider.py`
- Test: `tests/quant/modeling/test_observation_identity.py`, `tests/quant/decision/test_timesfm_engine.py`

**Interfaces:**

```python
@dataclass(frozen=True)
class ForecastObservationIdentity:
    symbol: str
    source_symbol: str
    timeframe_seconds: int
    observed_at: str
    bar_index: int
    close: float
    is_complete: bool
    synthetic_padding_count: int = 0
```

- [ ] Write tests for equality, ordering, forming/complete rejection, and same-index different-time/close inequality.
- [ ] Run the tests red because the module/API does not exist.
- [ ] Add the identity type and use it as the forecast-cache key/value metadata.
- [ ] Update `TimesFMForecast` to carry identity metadata without breaking existing constructors.
- [ ] Run native engine/strategy tests.
- [ ] Commit `feat: add forecast observation identity contract`.

### Task 2: Reject forming and out-of-order model inputs

**Files:**
- Modify: `quant/decision/timesfm_engine.py`, `quant/runtime.py`, `quant/decision/context_builder.py`
- Test: `tests/quant/decision/test_temporal_observation_contract.py`

- [ ] Write failing tests: forming candle rejected for closed-only path; same bar index with changed time/close is not reused; older identity cannot overwrite newer cache.
- [ ] Add explicit `is_complete`/observation identity checks before cache reuse and before `_fresh_forecast` accepts a forecast.
- [ ] Preserve a separate explicit micro-observation mode if current production intentionally allows micro entries; mark it in the decision record as `timeframe=60` and `is_complete=True` only after the micro bar closes.
- [ ] Ensure `bar_open/high/low` from a still-forming parent bar never enter a closed-candle forecast.
- [ ] Run temporal tests and golden replay tests.
- [ ] Commit `fix: enforce forecast observation temporal identity`.

### Task 3: Bound ad-hoc scanner/coordinator forecast inputs

**Files:**
- Modify: `quant/amt/session/scanner.py`, `quant/multi_engine.py`, `quant/decision/timesfm_client.py`, `quant/modeling/forecast_provider.py`
- Test: `tests/quant/decision/test_forecast_source_contract.py`

- [ ] Write tests requiring source symbol, timeframe, observation timestamp and completion status for scanner/coordinator forecasts.
- [ ] Stop using `datetime.now()` as the only forecast observation identity.
- [ ] Reject or mark repeated quote/spot padding as `synthetic_padding_count > 0` and prevent it from satisfying exact-flow/high-conviction gates.
- [ ] Add TTL/observation identity to `ForecastProvider` cache; reject sequence reuse for a different observation.
- [ ] Add monotonic timestamp validation to remote snapshot buffers and discard late snapshots.
- [ ] Commit `fix: enforce forecast source and completion identity`.

### Task 4: Enforce AMT provenance at decision gates

**Files:**
- Modify: `quant/decision/decision_service.py`, `quant/decision/gates_edge.py`, `quant/decision/timesfm_agents.py`, `quant/decision/data_quality.py`
- Test: `tests/quant/decision/test_provenance_gate_adversarial.py`

- [ ] Write tests with identical OHLCV and opposing hidden trade-side distributions; inferred provenance must not produce the same exact-flow approval.
- [ ] Define which AMT rules require `TICK_EXACT`, which permit `CANDLE_DISTRIBUTED`, and which are informational only.
- [ ] Make the gate result explicitly report `PROVENANCE_BLOCKED`/`PROXY_MODE` rather than only exposing a DTO field.
- [ ] Ensure E2E TimesFM authority cannot bypass a safety provenance block for rules explicitly classified as exact-flow-required.
- [ ] Commit `fix: prevent inferred flow from masquerading as exact AMT evidence`.

### Task 5: Fabio parity matrix and source claims

**Files:**
- Create: `tests/quant/amt/test_fabio_rule_vectors.py`
- Modify: `docs/amt/AMT_INSTITUTIONAL_SCALPER_ALGORITHM.md`, `docs/reviews/2026-09-11-full-system-adversarial-review.md`
- Possibly modify: `quant/amt/profile/volume_profile.py`, `quant/amt/orderflow/detectors.py` only when a vector demonstrates a required correction.

- [ ] Add frozen vectors for value area, LVN, absorption, Triple-A phases, VWAP, CVD and range-bar expectations.
- [ ] Classify every vector EXACT/APPROXIMATION/MISSING/INCORRECT.
- [ ] Do not claim exact Fabio compliance while 70% value area, missing range bars, alternate LVN and alternate absorption thresholds remain.
- [ ] Commit `docs: publish Fabio parity matrix and approximation boundaries` if no runtime rule is changed; otherwise use `fix:` with failing vectors first.

---

## Wave L2 — Durable broker exposure and lifecycle

### Task 6: Explicit `RECONCILIATION_REQUIRED` exposure state for partial entries

**Files:**
- Modify: `quant/execution/order.py`, `quant/execution/ports.py`, `quant/execution/live_oms.py`, `quant/runtime.py`, `quant/events.py`, `quant/transitions.py`
- Create/modify: `quant/execution/reconciliation.py`
- Test: `tests/quant/execution/test_partial_entry_reconciliation.py`

**Interfaces:**

```python
class ExposureStatus(StrEnum):
    NONE = "NONE"
    OPEN = "OPEN"
    RECONCILIATION_REQUIRED = "RECONCILIATION_REQUIRED"
    CLOSE_PENDING = "CLOSE_PENDING"
    UNKNOWN = "UNKNOWN"
```

- [ ] Write a failing test: broker fills 40%, cancel/status race returns no complete Position; local state must retain partial quantity and status `RECONCILIATION_REQUIRED`.
- [ ] Persist the exposure obligation before releasing any risk reservation.
- [ ] Block new entries for the symbol while reconciliation is required.
- [ ] On restart, query broker state and reconcile the partial before allowing a new order.
- [ ] Emit one durable event containing signal ID, broker order ID, filled quantity, remaining quantity, and status.
- [ ] Commit `fix: preserve partial broker exposure as reconciliation-required state`.

### Task 7: Durable close intent and exactly-once close reconciliation

**Files:**
- Modify: `quant/execution/live_oms.py`, `backend/app/infrastructure/adapters/dhan_broker_adapter.py`, `quant/runtime.py`, `quant/persistence_bridge.py`
- Test: `tests/quant/execution/test_close_retry_reconciliation.py`

- [ ] Write failing tests: crash after broker acceptance before local fill; collared close late-fill versus market fallback; duplicate close request.
- [ ] Persist close intent before broker I/O with a stable economic close ID.
- [ ] Link collar and fallback broker orders to one economic close attempt.
- [ ] Reconcile late fills exactly once, preserving PositionManager and EventStore consistency.
- [ ] Commit `fix: make live close intent durable and restart-reconcilable`.

### Task 8: Atomic EventStore side effects and readiness degradation

**Files:**
- Modify: `quant/runtime.py`, `quant/event_store.py`, `quant/events.py`, `quant/multi_engine.py`, `backend/app/api/routers/health.py`
- Test: `tests/quant/test_eventstore_failure_policy.py`, `backend/tests/unit/test_health_eventstore_degraded.py`

- [ ] Write a failing test where EventStore append fails after an event was published; assert the engine enters explicit degraded/readiness state.
- [ ] Prevent production snapshots from silently falling back to mutable state without `degraded=true` and a readiness failure.
- [ ] Separate non-critical UI/journal subscribers from canonical fold persistence.
- [ ] Emit a metric for append failures and block new orders while canonical state is degraded.
- [ ] Commit `fix: fail safe when canonical event persistence is degraded`.

### Task 9: Partial close and fill-ledger parity

**Files:**
- Modify: `quant/execution/live_oms.py`, `quant/execution/oms.py`, `quant/position_manager.py`, `quant/transitions.py`
- Test: `tests/quant/execution/test_live_partial_close.py`, `tests/quant/test_partial_fold_reconcile.py`

- [ ] Write tests for partial broker close, remaining quantity, stop quantity, risk release and replay.
- [ ] Ensure PaperOMS and LiveOMS expose the same economic fill contract even if timing differs.
- [ ] Ensure `PositionReduced` contains enough data to preserve effective stop and realized P&L exactly once.
- [ ] Commit `fix: make partial close accounting parity explicit`.

---

## Wave L3 — Indian market, parity and observability

### Task 10: Indian calendar and contract acceptance suite

**Files:**
- Create: `tests/acceptance/test_indian_market_contracts.py`
- Modify only if needed: `quant/session_gates.py`, `quant/contracts/instrument_registry.py`, scanner contract resolution.

- [ ] Test NSE/MCX sessions, holidays, shifted weekly/monthly expiry, IST midnight boundaries, expired chain fallback, lot/tick/freeze limits and option type.
- [ ] Test broker metadata override versus static registry.
- [ ] Test quantity chunking or explicit rejection above freeze limits.
- [ ] Commit `test: add Indian-market contract acceptance vectors` if implementation passes; use `fix:` only for proven runtime defects.

### Task 11: Paper/live parity certification

**Files:**
- Create: `tests/quant/certification/test_live_paper_parity.py`
- Modify: `quant/execution/paper_simulator.py`, cost models only with failing parity evidence.

- [ ] Compare instant-mid, bid/ask, delayed fill, partial fill, costs, slippage, and same-bar entry/exit semantics.
- [ ] Require a declared execution mode in every decision trace.
- [ ] Add a negative test proving instant-mid results are not labeled live-equivalent.
- [ ] Commit `test: certify paper/live semantic differences explicitly`.

### Task 12: Canonical `DecisionRecord` and forensic trace

**Files:**
- Create: `quant/contracts/decision_record.py`
- Modify: runtime decision emission, EventStore, journal, WS diagnostics.
- Test: `tests/quant/test_decision_record_forensics.py`

**Record fields:**

```python
DecisionRecord(
    decision_id,
    symbol,
    source_symbol,
    observation_identity,
    input_candle_times,
    input_hash,
    data_quality,
    amt_evidence_hash,
    timesfm_source,
    forecast_hash,
    forecast_summary,
    setup,
    gate_results,
    risk_snapshot,
    position_snapshot,
    action,
    order_id,
    timestamp,
)
```

- [ ] Write a failing forensic test requiring reconstruction of why an entry/skip/exit occurred.
- [ ] Emit exactly one record at the decision seam; advisory narrative cannot overwrite it.
- [ ] Ensure replay regenerates the same record hash for the same input journal.
- [ ] Commit `feat: add canonical forensic DecisionRecord`.

### Task 13: Fresh-clone and remote fixture closure

**Files:**
- Create: `tests/architecture/test_tracked_import_closure.py`
- Modify only tests/fixture paths and `.gitignore`.

- [ ] Verify every tracked test import path exists in a materialized fresh clone.
- [ ] Keep `runtime_audit/e2e` tracked because `tests/e2e/test_cross_process_injection.py` imports it.
- [ ] Keep `frontend/tests/fixtures/ws_payloads.json` tracked and ensure no test references the old untracked path.
- [ ] Commit `test: enforce fresh-clone tracked test dependencies`.

---

## Final acceptance

- [ ] Run P0/P1 adversarial tests with no network/broker mocking at the boundary where possible.
- [ ] Run per-directory suites separately to avoid OpenMP contention.
- [ ] Run golden tape/replay/file determinism.
- [ ] Run release gate and require 0 failures.
- [ ] Generate LVN availability, pyramid approval, partial exposure, close retry, event persistence and timestamp-provenance metrics.
- [ ] Update `docs/PRE_RELEASE_READINESS_CHECKLIST.md` and `docs/reviews/2026-09-11-full-system-adversarial-review.md`.
- [ ] Live readiness remains NO-GO until Tasks 6-9 and the exact-flow provenance gate pass.
