# TimesFM Compatibility Façade Architecture

**Date:** 2026-09-09
**Status:** Draft for review

## Goal

Consolidate model interpretation, decision intent, sizing, portfolio reservation, execution, and exits behind explicit boundaries without removing the existing TimesFM integration or forcing a risky rewrite.

## Constraints

- Preserve current deterministic/Fabio and TimesFM behavior during migration.
- Keep broker adapters free of portfolio sizing.
- Preserve exact executable quantity from risk sizing through OMS and broker payload.
- Make model unavailability explicit and deterministic.
- Protect existing positions even when model inference is unavailable.
- Keep frontend as a consumer of backend facts.

## Target flow

```text
Canonical tick/bar
  -> ForecastProvider
  -> ForecastSnapshot
  -> DecisionProvider
  -> TradeIntent
  -> RiskSizer
  -> ExecutableSignal
  -> PortfolioRiskAuthority
  -> OMS/broker adapter
  -> Order/fill/position events
  -> Unified ExitPolicy
  -> projections and REST/WebSocket
```

## Components

### ForecastProvider

The only runtime boundary allowed to invoke TimesFM. It returns an immutable `ForecastSnapshot` containing symbol, decision sequence, generated timestamp, model status/version, quantile paths when available, expected return, dispersion, velocity, and fallback reason. Calls are cached per symbol and decision sequence so strategy and advisor consumers use the same snapshot.

Statuses are `AVAILABLE`, `UNAVAILABLE`, and `INFERENCE_FAILED`. A fallback must never be labelled as native TimesFM output.

### DecisionProvider

Consumes canonical context and a forecast snapshot and returns a `TradeIntent`. It owns entry direction, setup, confidence, stop/target references, rationale, forecast identity, and expiry. It never calculates final quantity and never submits orders.

Existing `AmtScalpingStrategy` and `TimesFMTradingStrategy` are adapted behind this boundary first. Their behavior is preserved while their outputs are normalized.

### RiskSizer

The only final quantity authority. It consumes `TradeIntent`, account/session state, portfolio state, contract metadata, and optional forecast-derived risk inputs. It returns an `ExecutableSignal` with quantity, lot size, entry, stop, target, max loss, and portfolio risk. Lot snapping occurs exactly once at this boundary or its immediate execution contract.

`SessionRisk.position_size` remains the initial implementation authority. `TimesFMPositionSizer` becomes a pure helper or is retired only after equivalent behavior is covered.

### PortfolioRiskAuthority

Atomically reserves, releases, and realizes risk. Reservation occurs after final sizing and before OMS submission. Failed submissions release the exact reservation. Successful fills and closes reconcile the reservation with durable order/fill state.

### OMS and broker adapter

OMS accepts only an `ExecutableSignal`. Broker adapters map the signal without re-sizing portfolio exposure. Order state is durable and supports created, submitted, acknowledged, partial, filled, cancelled, rejected, and reconciliation-required states.

### Unified ExitPolicy

`ExitEngine` remains the orchestration boundary. Hard stop, session halt, emergency, reconciliation, and monotonic trailing protections are deterministic. TimesFM contributes an exit candidate, never an authority that can weaken hard protections. Close operations are idempotent and retry-bounded.

### Mode controller

Explicit modes:

- `DETERMINISTIC`: rules/Fabio entry and deterministic exits.
- `TIMESFM_ASSISTED`: TimesFM is evidence/filter; deterministic fallback is allowed by policy.
- `TIMESFM_PRIMARY`: TimesFM generates intent; model failure blocks new entries by default.
- `SAFE_HALT`: no new entries; protect and reconcile existing positions.

A model failure emits a mode-change event. It cannot silently become a synthetic native forecast.

## Failure behavior

- Forecast failure: emit model failure, transition mode, protect existing positions, block or delegate new entries according to policy.
- Invalid/zero sizing: emit decision blocked; do not reserve or submit.
- Reservation rejection: do not call OMS.
- OMS rejection/exception: release reservation, emit order rejected, keep engine alive, do not emit approval.
- Partial fill/timeout: retain durable non-terminal order and let reconciliation establish position truth.
- Exit failure: retain position open, retry within a bounded policy, and prevent duplicate closes.

## Migration phases

1. Add typed mode and forecast-status contracts.
2. Add `ForecastProvider` façade and route TimesFM strategy/advisor calls through it.
3. Add `TradeIntent` façade while preserving current runtime behavior.
4. Move final sizing behind `RiskSizer` and remove duplicate runtime sizing paths.
5. Prove quantity preservation through PaperOMS, LiveOMS, broker mapper, and adapter.
6. Unify TimesFM and deterministic exit candidates under `ExitEngine`.
7. Add durable order lifecycle and explicit reconciliation boundaries.
8. Delete duplicate model, sizing, exit, and frontend decision logic only after migration gates pass.

## Acceptance criteria

- Focused TimesFM fallback and position-management tests pass with the model unavailable.
- One forecast snapshot is shared by strategy and advisor for a decision sequence.
- Exactly one final quantity is produced and preserved to broker payload.
- Every portfolio reservation has an explicit release or realization path.
- Model failure produces an observable mode transition.
- Existing positions remain protected during model failure.
- Replay remains deterministic.
- Backend REST/WebSocket and frontend build/test contracts remain green.
- Paper execution passes the same executable-signal contract as live execution.

## Testing strategy

Pure unit tests cover snapshots, mode transitions, intents, sizing, lot rules, exits, and signed positions. Contract tests cover provider implementations, OMS quantity preservation, and broker mapping. Runtime integration tests cover tick-to-order, reservation release, partial fills, reconciliation, and exit idempotency. Replay tests cover deterministic event sequences and model-unavailable runs. REST/WebSocket, frontend, and paper end-to-end acceptance remain mandatory migration gates.

## Explicit non-goals

- No big-bang rewrite of `QuantEngine`.
- No immediate removal of TimesFM.
- No live-broker test requiring credentials as part of ordinary CI.
- No frontend implementation of strategy or risk logic.
- No silent fallback from model mode to synthetic model output.
