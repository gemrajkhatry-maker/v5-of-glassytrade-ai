"""BackendV2 Runtime — deterministic pipeline architecture.

No historic-mode reconstruction. Event-driven pipeline stages with explicit ownership,
bounded mutation, and live-only execution.

Module layout:
  runtime/
    __init__.py          Package root
    pipeline/
      __init__.py        PipelineStage trait, SPSC queue
      events.py          Pipeline event types
      sequencer.py       TickSequencer stage
      candle_builder.py  CandlePipeline stage
      orderflow.py       OrderFlowPipeline stage
      microstructure.py  MicrostructureAnalysis stage
      market_structure.py MarketStructureAnalysis stage
      features.py        FeatureComputation stage
      signal.py          SignalGeneration stage
      gates.py           GateEvaluation stage
      risk.py            RiskEvaluation stage
      position.py        PositionLifecycle stage
      execution.py       ExecutionPipeline stage
      broker_sync.py     BrokerSynchronization stage
      persistence.py     EventPersistence stage
      telemetry.py       TelemetryPipeline stage
      strategy.py        StrategyRuntime stage
    feeds/
      __init__.py        Feed source abstraction
      live.py            Live feed adapter
    orchestrator/
      __init__.py        RuntimeOrchestrator
      session.py         SessionRuntime
      registry.py        RuntimeOrchestrator registry
"""

from .pipeline import PipelineStage, SPSCQueue
from .pipeline.events import (
    Tick,
    SequencedTick,
    NormalizedTick,
    Candle,
    CandleTimeframe,
    OrderFlowMetrics,
    MicrostructureMetrics,
    MarketStructureResult,
    FeatureVector,
    Signal,
    GateResult,
    RiskResult,
    PositionEvent,
    OrderRequest,
    OrderStatusEvent,
    FillEvent,
    ExitDecision,
)
from .orchestrator import RuntimeOrchestrator, SessionRuntime

__all__ = [
    "PipelineStage",
    "SPSCQueue",
    "Tick",
    "SequencedTick",
    "NormalizedTick",
    "Candle",
    "CandleTimeframe",
    "OrderFlowMetrics",
    "MicrostructureMetrics",
    "MarketStructureResult",
    "FeatureVector",
    "Signal",
    "GateResult",
    "RiskResult",
    "PositionEvent",
    "OrderRequest",
    "OrderStatusEvent",
    "FillEvent",
    "ExitDecision",
    "RuntimeOrchestrator",
    "SessionRuntime",
]