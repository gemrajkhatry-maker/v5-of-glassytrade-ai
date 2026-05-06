# CONTEXT: Execution Runtime Architecture

## Target Runtime Intent

- Build a live-first, low-latency trading runtime with deterministic behavior.
- Execute all trading decisions through explicit module boundaries.
- Keep state ownership local, bounded, and auditable.
- Reuse the same business logic for paper and live execution paths.

## Module Map (Runtime Topology)

1. `MarketDataIngestion`  
   Entry for broker feeds (L1 and optional L2) and synthetic feeds.
2. `TickSequencer`  
   Enforces per-symbol ordering and produces deterministic sequence numbers.
3. `TickNormalization`  
   Normalizes exchange payloads into canonical tick/event payloads.
4. `CandlePipeline`  
   Builds and emits time-bucket candles from tick flow.
5. `OrderFlowPipeline`  
   Builds micro-depth and order-flow signals from full/partial book data.
6. `MicrostructureAnalysis`  
   Derives aggression, imbalance, and footprint primitives.
7. `MarketStructureAnalysis`  
   Derives market state, value area, acceptance/rejection, and balance zones.
8. `FeatureComputation`  
   Computes derived features used by gating and risk logic.
9. `SignalGeneration`  
   Produces candidate signals from analysis + feature model stack.
10. `GateEvaluation`  
    Applies policy gates (risk, confidence, session, playbook).
11. `RiskEvaluation`  
    Applies hard limits and position constraints.
12. `PositionLifecycle`  
    Owns lifecycle state transitions and invariants for open/close/modification.
13. `ExecutionPipeline`  
    Submits, tracks, and reconciles broker-facing orders.
14. `BrokerSynchronization`  
    Reconciles local state with broker state at startup and periodic checkpoints.
15. `SessionRuntime`  
    Orchestrates one symbol-session end-to-end and owns session policy.
16. `EventPersistence`  
    Appends immutable domain events and stores snapshots for recovery.
17. `TelemetryPipeline`  
    Captures and exports per-stage latency, drop, and health signals.
18. `StrategyRuntime`  
    Binds strategy-specific rules and module wiring per symbol set.

## Pipeline Execution Model

- `Tick Source → TickSequencer → TickNormalization → CandlePipeline → OrderFlowPipeline → MarketStructureAnalysis → SignalGeneration → GateEvaluation → RiskEvaluation → ExecutionPipeline → EventPersistence`
- L1 feed and optional L2 feed both enter through `MarketDataIngestion` and share the same downstream pipeline.
- Broker events and synthetic inputs are sequenced and normalized before entering the same downstream module set.
- Module output contracts are immutable data payloads that preserve symbol, sequence, and source clock.

## State Boundaries

- Symbol-local state belongs to `SessionRuntime` and `PositionLifecycle`.
- Auditable event state belongs to `EventPersistence`.
- In-memory hot-path caches belong only to modules that require microsecond-level decisions.
- Cross-module ownership is expressed through explicit dependency injection and immutable commands/events.

## Determinism Invariants

- Sequence and timestamp fields are mandatory on every event in the hot path.
- Order of application is total per symbol and stable across recovery.
- Reconstructed state for a symbol is deterministic by re-applying the same event set.
- State reconstruction for debugging is implemented by deterministic re-application of events to snapshots, not side effect reproduction.

## Failure and Recovery

- Failures remain inside module scope with explicit state rollback boundaries.
- Recovery uses snapshot + event re-application to rebuild deterministic session state.
- Telemetry emits stall/drop counters at each pipeline boundary.
