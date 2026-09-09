# TimesFM Compatibility Façade Implementation Plan

**Spec:** `docs/superpowers/specs/2026-09-09-timesfm-compatibility-facade-design.md`
**Status:** Ready for implementation

## Delivery rules

- Use TDD for every behavior change: failing test, minimal implementation, regression run.
- Keep the existing working tree changes isolated. Do not reformat or rewrite unrelated files.
- Preserve deterministic mode as the default.
- Do not enable TimesFM primary mode in live configuration during this migration.
- No native broker calls in tests. Use paper and adapter contract boundaries.

## Phase 1: Typed model status and runtime modes

### Files

- Add `quant/modeling/contracts.py`.
- Add `quant/modeling/mode.py`.
- Add focused tests under `tests/quant/modeling/`.

### Contracts

Define immutable value objects:

```python
class ForecastStatus(str, Enum):
    AVAILABLE = "AVAILABLE"
    UNAVAILABLE = "UNAVAILABLE"
    INFERENCE_FAILED = "INFERENCE_FAILED"

class StrategyMode(str, Enum):
    DETERMINISTIC = "DETERMINISTIC"
    TIMESFM_ASSISTED = "TIMESFM_ASSISTED"
    TIMESFM_PRIMARY = "TIMESFM_PRIMARY"
    SAFE_HALT = "SAFE_HALT"
```

`ForecastSnapshot` must include symbol, decision sequence, generated timestamp, status, model version, optional quantile paths, expected return, dispersion, velocity, and failure reason. It must reject an `AVAILABLE` snapshot without model metadata and must not label fallback data as native TimesFM.

`ModeController` maps model status and configured mode to the next mode. Existing positions remain protectable in every mode. `TIMESFM_PRIMARY + unavailable` becomes `SAFE_HALT`; assisted mode may delegate to deterministic mode only when explicitly configured.

### Acceptance

- Unit tests cover every status/mode transition.
- Serialization is stable and JSON-safe.
- Existing runtime defaults remain deterministic.

## Phase 2: ForecastProvider façade

### Files

- Add `quant/modeling/forecast_provider.py`.
- Adapt `quant/decision/timesfm_engine.py` behind the provider.
- Adapt `quant/strategies/timesfm_strategy.py` and advisor consumption.
- Add provider contract tests.

### Behavior

- Exactly one inference per `(symbol, decision_sequence)`.
- Strategy and advisor receive the same snapshot.
- Model-load and inference errors become typed statuses.
- Fallback data contains explicit fallback metadata.
- Existing-position management remains available when inference fails.

### Acceptance

- Provider tests prove caching and identity reuse.
- Existing focused TimesFM tests remain green.
- The unavailable-model position payload includes `activePosition`.
- No runtime TimesFM call remains outside the provider after this phase.

## Phase 3: TradeIntent façade

### Files

- Add `quant/decision/intent.py`.
- Add adapter in `quant/decision/intent_provider.py`.
- Add tests under `tests/quant/decision/`.
- Adapt both AMT and TimesFM strategies without changing entry behavior.

### Contract

`TradeIntent` contains symbol, direction, setup, entry reference, stop reference, target reference, confidence, forecast identity, rationale, creation timestamp, and expiry. It does not contain final quantity and cannot submit orders.

### Acceptance

- Existing `QuantDecision` behavior is preserved through the adapter.
- Intent rejects missing symbol, invalid direction, invalid stop/target relationships, and expired timestamps.
- Golden decision output remains stable unless the change is explicitly recorded.

## Phase 4: Single RiskSizer authority

### Files

- Add `quant/execution/risk_sizer.py` or extract the smallest stable boundary around `SessionRisk.position_size`.
- Add contract tests for sizing and lot snapping.
- Remove only proven duplicate runtime sizing calls.

### Behavior

- Final quantity is calculated once.
- TimesFM forecast is input evidence, not an independent final quantity.
- Expiry, session, portfolio, and lot constraints are applied exactly once.
- Zero quantity blocks before reservation.

### Acceptance

- One input intent produces one executable quantity.
- PaperOMS and LiveOMS receive identical quantity.
- Broker adapter never re-sizes from portfolio state.
- Reservation risk equals executable signal risk.

## Phase 5: Portfolio and OMS contract hardening

### Files

- `quant/execution/ports.py`
- `quant/execution/live_oms.py`
- broker mapper and Dhan adapter boundary files
- contract tests under `tests/quant/execution/` and `backend/tests/unit/infrastructure/`

### Behavior

- `ExecutableSignal` quantity is mandatory and immutable.
- Submit rejection releases exactly one reservation.
- Duplicate submissions are idempotent by deterministic order identity.
- Partial fills remain durable and reconciliation-required.

### Acceptance

- Existing LiveOMS and broker infrastructure suites stay green.
- Add an explicit engine-to-broker quantity assertion.
- Add rejection, timeout, partial-fill, and duplicate-submit cases.

## Phase 6: Unified exits

### Files

- `quant/execution/exits.py`
- `quant/decision/timesfm_risk.py`
- `quant/position_manager.py`
- exit tests.

### Behavior

- `ExitEngine` remains the only orchestration boundary.
- TimesFM creates exit candidates.
- Hard stop, emergency, reconciliation, and monotonic stop protections win over model candidates.
- Close calls are idempotent and bounded-retry.

### Acceptance

- Existing exit, tick-exit, pyramid, and close tests pass.
- Model failure still protects open positions.
- Stop never loosens.
- Duplicate close cannot flip a position.

## Phase 7: Event and projection contracts

### Files

- `quant/execution/events.py`
- event store/state projection modules
- backend serialization schemas
- frontend types and ingestion tests.

### Events

Add or normalize `ModelFailure`, `StrategyModeChanged`, `TradeIntentCreated`, `RiskReservationRejected`, and `OrderRejected` without breaking existing event consumers.

### Acceptance

- Event replay remains deterministic.
- Backend REST/WebSocket contracts remain stable or are versioned.
- Frontend consumes mode/model status as facts and does not recalculate strategy decisions.

## Phase 8: Cleanup and deletion

Only after all previous gates pass:

- Delete duplicate forecast factories.
- Remove strategy-owned sizing authority.
- Remove dead exit implementation paths.
- Remove frontend decision/risk re-derivations.
- Update architecture documentation and deprecation notes.

## Validation matrix

| Boundary | Required check |
|---|---|
| Forecast | Provider cache, status, fallback identity |
| Decision | Intent contract and golden decisions |
| Risk | Quantity, expiry, lot, zero-budget behavior |
| Portfolio | Atomic reservation/release |
| OMS | Quantity preservation and rejection behavior |
| Broker | Payload mapping without re-sizing |
| Exit | Hard protections, monotonic stops, idempotency |
| Events | Replay determinism and mode transitions |
| Backend | REST and WebSocket acceptance |
| Frontend | 282-test baseline and production build |
| Live | Explicitly blocked until credentials/sandbox connectivity exist |

## First implementation increment

Implement only Phase 1 and the TimesFM fallback regression test. Do not begin Phase 2 until:

1. Phase 1 tests fail before implementation.
2. Phase 1 tests pass after implementation.
3. Focused TimesFM tests pass.
4. The full quant suite is rerun with the declared dependency environment.
5. The change is committed separately from unrelated working-tree changes.
