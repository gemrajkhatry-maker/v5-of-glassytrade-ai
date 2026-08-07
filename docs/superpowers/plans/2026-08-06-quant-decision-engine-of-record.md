# Make `quant/` the Decision Engine of Record (Execution Wiring)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Wire the greenfield `quant/` engine (AuctionState → 5 gates → SignalBuilder + VA-fade) into the LIVE backend so its `Signal` drives the existing execution path (`EntryCoordinator.execute_signal`), replacing the legacy AMT gate path — behind a feature flag so the old path stays as fallback.

**Architecture:** `QuantBridge` already feeds `AuctionCoordinator` per symbol on bar close and stores the serialized `auction` DTO. This plan adds: (1) a **quant decision** step that runs `GatePipeline` + `SignalBuilder` (+ `VAFade`) on the live `AuctionState` with a `DecisionContext` built from session/risk facts; (2) a **mapper** from `quant.decision.signal_builder.Signal` → the existing `app.domain.trading.models.entities.Signal` (SignalType.LONG/SHORT, price, stop_loss, take_profit, setup, source); (3) a **feature flag** `QUANT_DECISION_ENABLED` (`.env`, default `false`) so `session_event_router.execute_entry_path` routes to the quant signal when on, legacy otherwise; (4) broadcast the quant decision as `quantSignal` + `quantDecision` WS fields; (5) a system E2E test proving a synthetic session's quant LONG signal reaches `EntryCoordinator.execute_signal` (mocked) when the flag is on.

**Tech Stack:** Python 3.11, dataclasses, pytest, existing FastAPI + EntryCoordinator.

## Global Constraints

- Backend only: `/Users/apple/Documents/v5-of-glassytrade-ai/backend` + `quant/`. Branch `stable_4`.
- Feature flag: `QUANT_DECISION_ENABLED` read from `.env`/config, default `false`. When `false`, behavior is byte-identical to today (legacy path). When `true`, quant Signal drives execution.
- The quant mapper must produce a VALID existing `Signal` (SignalType, price=close, stop_loss=take_profit from quant, setup, source="QUANT" or the enum's closest).
- Do NOT touch: the broker adapters, the WS endpoint, the legacy AMT analyzer (kept as fallback), `models/`, `frontend/` (except an optional `quantDecision` field if trivial).
- Test: `cd /Users/apple/Documents/v5-of-glassytrade-ai && /Users/apple/miniconda3/envs/amt_313/bin/python -m pytest tests/quant tests/system -q --tb=short` + the existing backend unit suite (3 env-broken suites `--ignore`d).
- TDD: failing test first, RED, implement, GREEN, commit. One commit per task.

## Dependency Graph

```mermaid
flowchart TD
    T1[Task 1: quant decision orchestrator + flag]
    T2[Task 2: Signal mapper quant→domain]
    T3[Task 3: wire session_event_router routing]
    T4[Task 4: broadcast quantDecision WS field]
    T5[Task 5: system E2E test (flag on → execute)]
    T1 --> T3
    T2 --> T3
    T3 --> T5
    T4 --> T5
```

**File-ownership (Wave 1 parallel, disjoint):**
- T1: `quant/decision/decision_service.py` (new pure orchestrator), `tests/quant/decision/test_decision_service.py`
- T2: `backend/app/application/services/quant_signal_mapper.py` (new), `backend/tests/unit/application/test_quant_signal_mapper.py`
- T3: `backend/app/application/services/quant_bridge.py` (add decision service + flag), `backend/app/application/services/session_event_router.py` (route), `backend/app/config_models/*` (flag)
- T4: `backend/app/application/services/state_snapshot_builder.py` (add `quantDecision`), `session_state_manager.py`/`session_cache.py` (store)
- T5: `tests/system/test_quant_execution_e2e.py` (new)

T1/T2 are independent and produce the interfaces T3 consumes (pinned below). T4 depends on T1's decision DTO shape. T5 depends on all.

---

### Task 1: Quant Decision Service

**Files:**
- Create: `quant/decision/decision_service.py`
- Create: `tests/quant/decision/test_decision_service.py`

**Interfaces:**
- Consumes: `quant.coordinator.AuctionCoordinator`, `quant.decision.context.DecisionContext`, `quant.decision.pipeline.GatePipeline`, `quant.decision.signal_builder.SignalBuilder`, `quant.decision.va_fade.detect_va_fade`
- Produces (pinned — T3 consumes):
  ```python
  @dataclass(frozen=True)
  class QuantDecision:
      approved: bool
      signal: "Signal | None"        # quant signal (type/entry/sl/tp/rr/confidence/symbol/timestamp)
      reason: str                     # "Triple-A" | "VA_FADE" | "NO_EDGE" | "GATE_REJECTED"
      phase: str                      # AuctionState.triple_a_phase
      gate_results: tuple[GateResult, ...]

  class DecisionService:
      def __init__(self, min_rr: float = 1.5) -> None: ...
      def evaluate(self, ctx: DecisionContext) -> QuantDecision:
          """Runs gates 1-5 then SignalBuilder; falls back to VA-fade when
          gates pass but signal is None; returns NO_EDGE when nothing qualifies."""
  ```

- [ ] **Step 1: Write failing tests**
```python
# tests/quant/decision/test_decision_service.py
from quant.decision.decision_service import DecisionService, QuantDecision
from quant.decision.context import DecisionContext
# reuse the AGGRESSION-LONG AuctionState fixture pattern from test_gates_3_4.py

def test_aggression_long_approved():
    ctx = DecisionContext(state=_state(triple_a_phase="AGGRESSION", triple_a_signal="LONG"),
                          bar=None, agent_direction="LONG", agent_probability=0.7)
    d = DecisionService().evaluate(ctx)
    assert d.approved and d.signal is not None and d.signal.type == "LONG"
    assert d.reason == "Triple-A"

def test_va_fade_fallback():
    # gates may not approve (no AGGRESSION) but a VA-fade edge exists
    ctx = DecisionContext(state=_va_fade_state(), bar=None, agent_direction="LONG", agent_probability=0.7)
    d = DecisionService().evaluate(ctx)
    assert d.approved and d.signal is not None and d.reason == "VA_FADE"

def test_no_edge():
    ctx = DecisionContext(state=_quiet_state(), bar=None, agent_direction=None, agent_probability=0.0)
    d = DecisionService().evaluate(ctx)
    assert not d.approved and d.signal is None and d.reason == "NO_EDGE"
```

- [ ] **Step 2: Run, verify FAIL**

- [ ] **Step 3: Implement** — `decision_service.py`: run `GatePipeline().evaluate(ctx)`; if all 5 pass → `SignalBuilder().build(ctx, results)`; if a signal results → approved, reason "Triple-A". Else try `detect_va_fade(state, ctx)` → approved "VA_FADE" (requires agent_direction match). Else "NO_EDGE". Include gate_results.

- [ ] **Step 4: Run, verify PASS** + `pytest tests/quant -q`.

- [ ] **Step 5: Commit** `feat(quant): DecisionService (gates → signal, VA-fade fallback)`

---

### Task 2: Quant → Domain Signal Mapper

**Files:**
- Create: `backend/app/application/services/quant_signal_mapper.py`
- Create: `backend/tests/unit/application/test_quant_signal_mapper.py`

**Interfaces:**
- Consumes: `quant.decision.signal_builder.Signal` (type/entry/sl/tp/rr/confidence/symbol/timestamp), `quant.decision.decision_service.QuantDecision`
- Produces:
  ```python
  def quant_signal_to_domain(qs: "quant Signal", symbol: str) -> "app Signal":
      """Map quant Signal → existing app.domain.trading.models.entities.Signal.
      type→SignalType.LONG/SHORT, price=entry, stop_loss=sl, take_profit=tp,
      setup=SetupType (pick closest: AGGRESSION→IMBALANCE or TRIPLE_A if exists),
      source=Source (closest to LLM/QUANT), metadata={quant_rr, confidence, phase}."""
  ```

- [ ] **Step 1: Write failing tests**
```python
# tests/unit/application/test_quant_signal_mapper.py
from app.application.services.quant_signal_mapper import quant_signal_to_domain
from quant.decision.signal_builder import Signal

def test_maps_long():
    qs = Signal(type="LONG", reason="Triple-A", entry=100.0, sl=99.0, tp=102.0,
                rr=2.0, confidence=0.8, symbol="SYM", timestamp="t1")
    s = quant_signal_to_domain(qs, "SYM")
    assert s.type == SignalType.LONG
    assert float(s.price) == 100.0
    assert float(s.stop_loss) == 99.0
    assert float(s.take_profit) == 102.0
    assert s.metadata["quant_rr"] == 2.0
```
(Read `entities.py` Signal + enums first; adjust the setup/source to what the enums actually offer — report.)

- [ ] **Step 2: Run, verify FAIL**

- [ ] **Step 3: Implement** — the mapper per the pinned signature.

- [ ] **Step 4: Run, verify PASS** + `pytest tests/unit/application/test_quant_signal_mapper.py`.

- [ ] **Step 5: Commit** `feat(backend): map quant Signal → domain Signal`

---

### Task 3: Wire Routing + Feature Flag

**Files:**
- Modify: `backend/app/application/services/quant_bridge.py` (add `DecisionService` + decision on bar close, store on session)
- Modify: `backend/app/application/services/session_event_router.py` (`execute_entry_path` route)
- Modify: `backend/app/config_models/settings_adapter.py` (or the config loader) — add `QUANT_DECISION_ENABLED`
- Modify: `.env` (add `QUANT_DECISION_ENABLED=false`)
- Modify: `backend/app/application/services/session_cache.py` (store `last_quant_decision`)
- Modify: `backend/app/application/services/session_state_manager.py` (field)
- Test: extend `tests/unit/application/test_quant_bridge.py`

**Interfaces:**
- Consumes: `QuantDecision` (T1), `quant_signal_to_domain` (T2)
- Produces: a live execution path — when `QUANT_DECISION_ENABLED`, `execute_entry_path` uses the quant signal instead of the legacy `build_entry_signal`.

- [ ] **Step 1: Write failing tests**
```python
# extend tests/unit/application/test_quant_bridge.py
def test_bridge_decision_stored_on_session():
    br = QuantBridge()
    session = FakeSession()
    br.on_bar_close_with_decision("SYM", _ohlc(), session, ctx_facts={...})
    assert session.last_quant_decision is not None  # when flag on

def test_router_uses_quant_when_flag_on(monkeypatch):
    # patch the flag True, call execute_entry_path, assert EntryCoordinator
    # received a signal derived from quant (mock _entry_coordinator)
```
(Read `session_event_router.execute_entry_path` first — pin the exact hook point.)

- [ ] **Step 2: Run, verify FAIL**

- [ ] **Step 3: Implement**
- `settings_adapter`/config: add `quant_decision_enabled: bool = False` read from `QUANT_DECISION_ENABLED`.
- `quant_bridge`: add `on_bar_close_with_decision(symbol, ohlc, session, ctx_facts) -> dict` that runs `DecisionService` and stores `session.last_quant_decision` (DTO) when the flag is on.
- `session_event_router.execute_entry_path`: at the point where the legacy `build_entry_signal` result is used, if `quant_decision_enabled` AND a `last_quant_decision.approved` exists for the symbol → map to domain Signal via `quant_signal_to_domain` and pass it to `_entry_coordinator.execute_signal` (bypassing the legacy gates). Keep the legacy path as the `else`.

- [ ] **Step 4: Run, verify PASS** + existing `tests/unit/application/test_session_event_router.py` green (flag off = unchanged).

- [ ] **Step 5: Commit** `feat(backend): quant decision routes execution behind QUANT_DECISION_ENABLED flag`

---

### Task 4: Broadcast quantDecision

**Files:**
- Modify: `backend/app/application/services/state_snapshot_builder.py` (add `quantDecision`)
- Modify: `backend/app/application/services/session_state_manager.py` / `session_cache.py` (store, if not done in T3)
- Test: extend `tests/unit/application/test_state_snapshot_builder.py`

**Interfaces:**
- Consumes: `session.last_quant_decision`
- Produces: `"quantDecision": {approved, reason, phase, signal:{type,entry,sl,tp,rr,confidence}} | null` in the WS snapshot.

- [ ] **Step 1: Write failing test** — snapshot contains `quantDecision` with the decision DTO.
- [ ] **Step 2: Run, verify FAIL**
- [ ] **Step 3: Implement** — serialize into the snapshot dict.
- [ ] **Step 4: Run, verify PASS** + `pytest tests/unit/application/test_state_snapshot_builder.py`.
- [ ] **Step 5: Commit** `feat(backend): broadcast quantDecision in WS snapshot`

---

### Task 5: System E2E — quant drives execution

**Files:**
- Create: `tests/system/test_quant_execution_e2e.py`

**Interfaces:**
- Consumes: `QuantBridge` + `DecisionService` + flag + `EntryCoordinator`
- Produces: proof that with `QUANT_DECISION_ENABLED=true`, a synthetic AGGRESSION-LONG session routes a quant Signal to `EntryCoordinator.execute_signal`.

- [ ] **Step 1: Write failing test**
```python
# tests/system/test_quant_execution_e2e.py
# Feed the 60-bar synthetic session (t55 absorption spike → breakout) via
# QuantBridge with the flag ON and a mock EntryCoordinator; assert execute_signal
# was called with a LONG Signal whose entry/stop/tp match the quant values.
```
- [ ] **Step 2: Run, verify FAIL**
- [ ] **Step 3: Implement** — if the wiring is correct this passes; if a gate blocks, adjust the fixture (do NOT weaken gates).
- [ ] **Step 4: Run, verify PASS** + `pytest tests/system tests/quant -q` + backend unit suite (3 ignores).
- [ ] **Step 5: Commit** `test(e2e): quant decision drives EntryCoordinator when flag enabled`

---

## Self-Review

- **Spec coverage:** decision engine of record = T1 (DecisionService) + T2 (mapper) + T3 (routing/flag) + T4 (broadcast) + T5 (e2e proof). Legacy path preserved behind flag (T3 else-branch).
- **Type consistency:** `QuantDecision{s approved, signal, reason, phase, gate_results}` (T1) consumed by T2 (`quant_signal_to_domain`) and T3; `quant.decision.signal_builder.Signal` is the shared quant type; `app.domain.trading.models.entities.Signal` the domain type. Feature flag name `QUANT_DECISION_ENABLED` consistent across T3/.env/config.
- **Known accepted risks:** `Source`/`SetupType` enums may lack a perfect "QUANT" value — mapper picks closest and documents it. The flag default false means zero behavior change until explicitly enabled.
