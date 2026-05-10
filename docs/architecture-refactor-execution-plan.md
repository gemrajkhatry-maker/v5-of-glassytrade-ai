# Architecture Refactor Execution Plan

This plan converts `brokersv2` into a single canonical trading execution architecture
without changing trading semantics during migration.

## 0) Current Design Decision

- `brokersv2` currently has parallel implementations for:
  - Broker runtime wiring
  - Order lifecycle/state handling
  - Market data streaming
  - Retry/rate-limit behaviors
- This is the highest risk source of hidden drift for live-trading correctness.
- Migration strategy: preserve interfaces, reduce parallelism, then remove legacy paths.

## 1) Phase 1 — Stabilize Production Paths (Week 1)

### 1.1 Define and freeze canonical boundaries
- Create (if not already present) a single “application composition root” for:
  - Broker client creation
  - Event bus wiring
  - Rate-limit and resilience policy injection
  - Market-data service creation
- Ensure CLI and Gateway consume from the same composition path.

### 1.2 Make behavior explicit where placeholders exist
- Any mocked / incomplete live path must fail loudly with explicit errors until implemented.
- Replace TODO fallback behavior with explicit `NotImplemented` or feature-flag gating in all public entry points.

### 1.3 Start de-duplication of cross-cutting policy
- Introduce one policy module for retry and rate-limit configuration vocabulary.
- Legacy call-sites continue to work via adapter wrappers.

### 1.4 Acceptance criteria (Phase 1)
- One broker composition path is used by both CLI and Gateway.
- No runtime path silently returns mocked results while claiming live behavior.
- Duplicate policy names are no longer ambiguous at import sites.
- Existing external interfaces remain stable behind compatibility adapters.

## 2) Phase 2 — Canonical Order and Market Data Flow (Week 2)

### 2.1 Order state unification
- Keep one authoritative domain state transition model.
- Keep `oms/order_machine.py` compatibility exports initially, then switch internal consumers to domain canonical model.

### 2.2 Market-data single ingress path
- Select one websocket manager as canonical (`DhanWebSocketManager` unless rejected by parity tests).
- Route all live market data flows through this path.
- Ensure replay/live pipelines consume common transforms and sequence validation.

### 2.3 Invariants enforced
- One symbol and event contract across:
  - market events
  - event bus
  - storage/replay
- No implicit enum duplication in core domain flows.

### 2.4 Acceptance criteria (Phase 2)
- End-to-end market stream parity test between replay and live mode passes for shared event contract.
- Order lifecycle transitions are validated against one canonical table.
- No ambiguous state transitions between `OrderStatus` and local/alternate enums.

## 3) Phase 3 — Remove Legacy Coupling (Week 3)

### 3.1 Legacy external broker path retirement
- Migrate CLI and server entry points off legacy `brokers/` facade.
- Keep a compatibility shell for legacy scripts until deprecation window complete.

### 3.2 Consolidate websocket utilities
- Remove duplicated websocket orchestration layers; retain only abstract interfaces + concrete Dhan adapter.

### 3.3 Acceptance criteria (Phase 3)
- No direct `sys.path` mutation for broker imports.
- All production modules import broker adapters through one infra/application boundary.
- No duplicate websocket manager trees remain active in the production flow.

## 4) Phase 4 — Hardening and Operationalization (Week 4)

### 4.1 Reliability and observability
- Add/confirm parity for:
  - retry policy metrics
  - rate-limit counters
  - stream gap alerts
  - order reconciliation drift alerts

### 4.2 Configuration and startup contracts
- Enforce schema-validated, typed configuration at boot.
- Fail fast when required credentials/limits are missing.

### 4.3 Finalization
- Remove dead modules and deprecated compatibility shims after one stable release cycle.
- Publish migration notes and update architecture docs.

### 4.4 Acceptance criteria (Phase 4)
- End-to-end smoke:
  - place/cancel/update order
  - stream tick/depth subscriptions
  - replay/live parity assertion with sequence checks
- No unresolved references to deprecated paths remain in active services.

## 5) Ownership map (initial)

| Domain | Primary Owner | Co-owner |
| --- | --- | --- |
| Trading order domain/state | OMS | Risk |
| Market data + stream | Market Data | Infrastructure |
| Broker integration | Infrastructure | Application |
| Web/API surface | Gateway | Platform |
| Reliability policies | Platform | SRE |

## 6) Rollback and risk controls

For each phase:
- Keep deprecated shims enabled behind explicit feature flags.
- Add runtime logs for branch usage (`legacy-path`, `canonical-path`).
- Run dual-path shadow execution before cutover.
- Roll back by re-enabling previous path until parity tests recover.
