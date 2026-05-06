# ADR-0005: Adopt Modular Live Runtime Topology

Date: 2026-05-05
Status: PROPOSED

## Context

The existing live trading runtime must be reorganized to guarantee deterministic execution, low-latency behavior, and explicit module ownership without explicit history-control loops.

Current complexity is concentrated in runtime orchestration and broad service composition. Execution quality depends on reducing coupling between data ingestion, feature creation, risk checks, and execution.

## Decision

Adopt a fixed module topology where market data progresses through explicit pipelines and each module owns a bounded set of mutable state.

## Module Topology

1. `MarketDataIngestion`
2. `TickSequencer`
3. `TickNormalization`
4. `CandlePipeline`
5. `OrderFlowPipeline`
6. `MicrostructureAnalysis`
7. `MarketStructureAnalysis`
8. `FeatureComputation`
9. `SignalGeneration`
10. `GateEvaluation`
11. `RiskEvaluation`
12. `PositionLifecycle`
13. `ExecutionPipeline`
14. `BrokerSynchronization`
15. `SessionRuntime`
16. `EventPersistence`
17. `TelemetryPipeline`
18. `StrategyRuntime`

## Non-Negotiable Invariants

1. **Deterministic sequencing**  
   All decision inputs are processed in a single per-symbol total order.
2. **Boundary ownership**  
   State mutation is owned by a single module.
3. **Immutable handoff**  
   Downstream modules receive immutable payloads and event commands.
4. **Snapshot recovery**  
   Recovery is deterministic from checkpoints plus persisted domain events.
5. **Broker separation**  
   Execution and synchronization abstractions are isolated from analysis modules.

## Runtime Flow

```text
TickSource
  → TickSequencer
  → TickNormalization
  → CandlePipeline
  → OrderFlowPipeline
  → MarketStructureAnalysis
  → SignalGeneration
  → GateEvaluation
  → RiskEvaluation
  → ExecutionPipeline
  → EventPersistence
```

## Consequences

- **Positive**
  - Reduced coupling and clearer fault domains.
  - Deterministic execution semantics across live and paper mode.
  - Easier validation of each stage via isolated regression coverage.

- **Negative**
  - Initial refactor footprint is high and affects startup wiring.
  - Telemetry and recovery logic must be intentionally preserved during migration.

## Migration Strategy

1. Keep all external interfaces stable while re-mapping module boundaries.
2. Introduce module boundaries and state ownership checks without changing broker/strategy behavior first.
3. Add regression checkpoints after each module extraction.
4. Retain existing paper-live parity by routing both paths through shared `StrategyRuntime` and `SessionRuntime`.

## References

- `ARCHITECTURE.md`
- `docs/adr/0003-eliminate-service-graph.md`
- `docs/adr/0004-keep-session-cache.md`
