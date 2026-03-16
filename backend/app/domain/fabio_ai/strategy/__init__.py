"""Strategy sub-package - Modular strategy components."""

from app.domain.fabio_ai.strategy.protocols import (
    Setup,
    MarketContext,
    EntrySignal,
    RiskResult,
    Order,
    SetupDetector,
    MarketAnalyzer,
    SignalGenerator,
    RiskCalculator,
    ExecutionPlanner,
    ExitEngine,
    Strategy,
)

from app.domain.fabio_ai.strategy.setup_detector import (
    AMTSetupDetector,
    create_setup_detector,
)

__all__ = [
    # Protocols
    "Setup",
    "MarketContext",
    "EntrySignal",
    "RiskResult",
    "Order",
    "SetupDetector",
    "MarketAnalyzer",
    "SignalGenerator",
    "RiskCalculator",
    "ExecutionPlanner",
    "ExitEngine",
    "Strategy",
    # Implementations
    "AMTSetupDetector",
    "create_setup_detector",
]
