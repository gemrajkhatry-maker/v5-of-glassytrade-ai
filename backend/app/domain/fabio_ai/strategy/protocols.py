"""Strategy protocols — interfaces for AMT strategy components.

Planned feature: Protocol-based interfaces for setup detection,
market context, entry signals, risk management, and strategy execution.
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
    setup_type: str = "UNKNOWN"
    thesis: str = ""
    key_levels: dict = field(default_factory=dict)
    trigger_conditions: list = field(default_factory=list)


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
    volume_bubbles: str = ""
    lvns: list = field(default_factory=list)
    hvns: list = field(default_factory=list)
    probe_bars: int = 0
    # Failed auction detection fields
    prior_vah: float = 0.0
    prior_val: float = 0.0
    prior_poc: float = 0.0
    delta_flipping: bool = False
    cvd_diverging: bool = False
    rejection_at_high: bool = False
    rejection_at_low: bool = False
    acceptance_above: bool = False
    acceptance_below: bool = False


@dataclass
class EntrySignal:
    """A trade entry signal produced by a strategy."""
    symbol: str = ""
    direction: str = "FLAT"
    entry_price: float = 0.0
    stop_loss: float = 0.0
    take_profit: float = 0.0
    position_size: float = 0.0
    setup: Setup | None = None
    confidence: str = ""
    thesis: str = ""

    @property
    def price(self) -> float:
        return self.entry_price

    @property
    def size(self) -> float:
        return self.position_size

    @property
    def setup_type(self) -> str:
        return self.setup.setup_type if self.setup else ""


@dataclass
class RiskResult:
    """Result of risk validation for a potential trade."""
    approved: bool = False
    max_position_size: float = 0.0
    rejection_reason: str = ""

    @property
    def reason(self) -> str:
        return self.rejection_reason


@dataclass
class Order:
    """Order to be sent to the broker."""
    order_id: str = ""
    trade_id: str = ""
    symbol: str = ""
    side: str = ""  # BUY or SELL
    order_type: str = "MARKET"
    price: float = 0.0
    quantity: float = 0.0


class Strategy(ABC):
    """Abstract strategy interface.

    A strategy receives market context and produces entry signals.
    """

    def __init__(
        self,
        market_analyzer=None,
        setup_detector=None,
        signal_generator=None,
        risk_calculator=None,
        execution_planner=None,
        exit_engine=None,
    ):
        self.market_analyzer = market_analyzer
        self.setup_detector = setup_detector
        self.signal_generator = signal_generator
        self.risk_calculator = risk_calculator
        self.execution_planner = execution_planner
        self.exit_engine = exit_engine

    def evaluate(self, context: MarketContext) -> Optional[EntrySignal]:
        """Evaluate market context and produce an entry signal, or None."""
        raise NotImplementedError

    def validate(self, signal: EntrySignal, context: MarketContext) -> RiskResult:
        """Validate a signal against risk constraints."""
        raise NotImplementedError