"""Opt-in AMT strategy extension.

Importing this package never registers or enables a trading strategy.
"""

from tradex_trading.strategy.extensions.amt.absorption import Absorption, AbsorptionDetector
from tradex_trading.strategy.extensions.amt.gates import AMTDecisionContext, evaluate
from tradex_trading.strategy.extensions.amt.kernel import AMTKernel
from tradex_trading.strategy.extensions.amt.model import (
    AMTDecision,
    AMTPhase,
    AMTSnapshot,
    AMTStrategyConfig,
    BookSnapshot,
)
from tradex_trading.strategy.extensions.amt.scanner import AMTScanner, AMTScanResult
from tradex_trading.strategy.extensions.amt.strategy import AMTStrategy

__all__ = [
    "Absorption",
    "AbsorptionDetector",
    "AMTDecision",
    "AMTDecisionContext",
    "AMTKernel",
    "AMTPhase",
    "AMTScanResult",
    "AMTScanner",
    "AMTSnapshot",
    "AMTStrategy",
    "AMTStrategyConfig",
    "BookSnapshot",
    "evaluate",
]
