"""Orderflow pattern detectors and signal aggregator (Fabio methodology).

Detectors are pure functions over ``OrderflowCandle`` history (and optional
``OrderbookTracker`` state), so they are deterministic and replayable. They
emit the domain ``Signal``; ``OrderflowAggregator`` runs the trade-lifecycle
state machine on top of that stream.
"""

from tradex_trading.strategy.extensions.orderflow.aggregator import OrderflowAggregator
from tradex_trading.strategy.extensions.orderflow.detectors import (
    detect_absorption,
    detect_divergence,
    detect_exhaustion,
    detect_initiative,
    detect_sweep,
)

__all__ = [
    "OrderflowAggregator",
    "detect_absorption",
    "detect_divergence",
    "detect_exhaustion",
    "detect_initiative",
    "detect_sweep",
]
