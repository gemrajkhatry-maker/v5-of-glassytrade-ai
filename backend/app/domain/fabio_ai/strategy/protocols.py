"""Strategy protocols — interfaces for AMT strategy components.

Planned feature: Protocol-based interfaces for setup detection,
market context, entry signals, risk management, and strategy execution.

Status: Stub — types defined but not implemented.
"""

from __future__ import annotations
from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from typing import Optional


@dataclass(frozen=True)
class Setup:
    """Identified AMT setup (e.g., RETURN_TO_VALUE, IMBALANCE_CONTINUATION)."""
    type: str = "UNKNOWN"
    confidence: float = 0.0


@dataclass
class MarketContext:
    """Snapshot of current market conditions for strategy decisions.

    This is a data transfer object — tests can construct it with any
    values they need. In production, this would be assembled by the
    AMT analysis pipeline.
    """
    symbol: str = ""
    current_price: float = 0.0
    market_state: str = "BALANCED"
    regime: str = "NORMAL"
    vwap: float = 0.0
    vah: float = 0.0
    val: float = 0.0
    poc: float = 0.0
    cvd_slope: float = 0.0
    delta: float = 0.0
    profile_shape: str = ""
    lvns: list = field(default_factory=list)
    hvns: list = field(default_factory=list)


@dataclass
class EntrySignal:
    """A trade entry signal produced by a strategy."""
    symbol: str = ""
    direction: str = "FLAT"
    price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    size: float = 0.0
    setup_type: str = ""
    confidence: float = 0.0


@dataclass
class RiskResult:
    """Result of risk validation for a potential trade."""
    approved: bool = False
    max_position_size: float = 0.0
    reason: str = ""


@dataclass
class Order:
    """Order to be sent to the broker."""
    symbol: str = ""
    side: str = ""  # BUY or SELL
    price: float = 0.0
    quantity: float = 0.0
    order_type: str = "MARKET"


class Strategy(ABC):
    """Abstract strategy interface.

    A strategy receives market context and produces entry signals.
    """

    @abstractmethod
    def evaluate(self, context: MarketContext) -> Optional[EntrySignal]:
        """Evaluate market context and produce an entry signal, or None."""
        ...

    @abstractmethod
    def validate(self, signal: EntrySignal, context: MarketContext) -> RiskResult:
        """Validate a signal against risk constraints."""
        ...
