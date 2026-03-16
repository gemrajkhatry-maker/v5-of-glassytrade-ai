"""Strategy Engine Protocols - Contracts for Modular Strategy Design.

This module defines the interfaces (protocols) that each strategy component
must implement. This ensures:
1. Clear separation of concerns
2. Easy testing (mock each protocol)
3. Independent evolution of components
4. Type safety across modules
"""

from __future__ import annotations

from typing import Protocol, Optional
from dataclasses import dataclass


@dataclass
class Setup:
    """A trading setup identified from market analysis."""

    setup_type: str  # "AAA", "MOMENTUM", "MEAN_REVERSION", "FAILED_AUCTION"
    confidence: float  # 0.0 - 1.0
    thesis: str  # Human-readable rationale
    key_levels: dict[str, float]  # Named price levels
    trigger_conditions: list[str]  # What triggers entry


@dataclass
class MarketContext:
    """Complete market state at a point in time."""

    symbol: str
    current_price: float
    market_state: str  # "BALANCED" or "IMBALANCED"
    regime: str  # Current regime
    vwap: float
    vah: float
    val: float
    poc: float
    cvd_slope: float
    delta: float
    profile_shape: str
    volume_bubbles: str
    lvns: list[float]
    hvns: list[float]
    # ... more fields as needed


@dataclass
class EntrySignal:
    """A generated entry signal ready for risk validation."""

    symbol: str
    direction: str  # "LONG" or "SHORT"
    entry_price: float
    stop_loss: float
    take_profit: float
    position_size: float
    setup: Setup
    confidence: str  # "HIGH", "MEDIUM", "LOW"
    thesis: str  # Why this trade makes sense


@dataclass
class RiskResult:
    """Result of risk validation."""

    approved: bool
    rejection_reason: str = ""
    risk_metrics: dict = None

    def __post_init__(self):
        if self.risk_metrics is None:
            self.risk_metrics = {}


@dataclass
class Order:
    """A planned order ready for execution."""

    order_id: str
    trade_id: str
    symbol: str
    side: str  # "BUY" or "SELL"
    order_type: str  # "MARKET", "LIMIT"
    price: float | None  # None for market orders
    quantity: float
    time_in_force: str = "DAY"


# =============================================================================
# PROTOCOLS
# =============================================================================


class SetupDetector(Protocol):
    """Identifies trading setups from market data.

    Implementations:
    - AMTSetupDetector: Uses Auction Market Theory
    - MLSetupDetector: Uses machine learning
    - HybridSetupDetector: Combines multiple approaches
    """

    def identify(self, context: MarketContext) -> Setup | None:
        """Identify a setup from current market context.

        Returns:
            Setup if one is identified, None otherwise.
        """
        ...


class MarketAnalyzer(Protocol):
    """Computes market context from raw data.

    Implementations:
    - AMTMarketAnalyzer: Computes AMT indicators
    - SimpleMarketAnalyzer: Basic price/volume analysis
    """

    def analyze(self, symbol: str, data: list, tick) -> MarketContext:
        """Analyze market and return context.

        Args:
            symbol: Trading symbol
            data: Historical candles
            tick: Current tick

        Returns:
            MarketContext with computed indicators
        """
        ...


class SignalGenerator(Protocol):
    """Generates entry signals from market context and setup.

    Implementations:
    - LLMSignalGenerator: Uses LLM for signal generation
    - RulesBasedSignalGenerator: Uses deterministic rules
    - HybridSignalGenerator: Combines approaches
    """

    def generate(
        self, context: MarketContext, setup: Setup | None = None
    ) -> EntrySignal | None:
        """Generate an entry signal.

        Args:
            context: Current market context
            setup: Identified setup (optional)

        Returns:
            EntrySignal if conditions are met, None otherwise.
        """
        ...


class RiskCalculator(Protocol):
    """Validates signals against risk rules.

    Implementations:
    - StandardRiskCalculator: Standard risk rules
    - AggressiveRiskCalculator: Relaxed risk for prop trading
    - ConservativeRiskCalculator: Strict risk for managed accounts
    """

    def validate(self, signal: EntrySignal, portfolio_state: dict) -> RiskResult:
        """Validate signal against risk rules.

        Args:
            signal: Entry signal to validate
            portfolio_state: Current portfolio positions and metrics

        Returns:
            RiskResult with approval status and metrics
        """
        ...


class ExecutionPlanner(Protocol):
    """Plans order execution.

    Implementations:
    - ImmediateExecutionPlanner: Market orders
    - LimitExecutionPlanner: Limit orders with retries
    - TWAPExecutionPlanner: Time-weighted execution
    """

    def plan_entry(self, signal: EntrySignal) -> Order:
        """Plan entry order for signal.

        Args:
            signal: Approved entry signal

        Returns:
            Order ready for execution
        """
        ...

    def plan_exit(
        self, trade_id: str, symbol: str, reason: str, current_price: float
    ) -> Order:
        """Plan exit order.

        Args:
            trade_id: Trade to exit
            symbol: Trading symbol
            reason: Exit reason ("SL", "TP", "MANUAL")
            current_price: Current market price

        Returns:
            Order ready for execution
        """
        ...


class ExitEngine(Protocol):
    """Manages trade exits.

    Implementations:
    - RulesBasedExitEngine: Rule-based exits (SL, TP, trailing)
    - LLMBasedExitEngine: LLM-managed exits
    """

    def check_exit(
        self,
        trade_id: str,
        position_state: dict,
        current_price: float,
        context: MarketContext,
    ) -> tuple[bool, str]:
        """Check if trade should exit.

        Args:
            trade_id: Trade to check
            position_state: Current position state
            current_price: Current market price
            context: Current market context

        Returns:
            Tuple of (should_exit, reason)
        """
        ...


# =============================================================================
# COMPOSITE STRATEGY
# =============================================================================


class Strategy:
    """Composite strategy that orchestrates all components."""

    def __init__(
        self,
        market_analyzer: MarketAnalyzer,
        setup_detector: SetupDetector,
        signal_generator: SignalGenerator,
        risk_calculator: RiskCalculator,
        execution_planner: ExecutionPlanner,
        exit_engine: ExitEngine,
    ):
        self.market_analyzer = market_analyzer
        self.setup_detector = setup_detector
        self.signal_generator = signal_generator
        self.risk_calculator = risk_calculator
        self.execution_planner = execution_planner
        self.exit_engine = exit_engine

    def evaluate_entry(
        self, symbol: str, data: list, tick, portfolio_state: dict
    ) -> Order | None:
        """Evaluate and potentially enter a trade.

        Args:
            symbol: Trading symbol
            data: Historical candles
            tick: Current tick
            portfolio_state: Current portfolio state

        Returns:
            Order if signal generated and approved, None otherwise.
        """
        # 1. Analyze market
        context = self.market_analyzer.analyze(symbol, data, tick)

        # 2. Identify setup
        setup = self.setup_detector.identify(context)

        # 3. Generate signal
        signal = self.signal_generator.generate(context, setup)
        if not signal:
            return None

        # 4. Validate risk
        risk_result = self.risk_calculator.validate(signal, portfolio_state)
        if not risk_result.approved:
            return None

        # 5. Plan execution
        order = self.execution_planner.plan_entry(signal)

        return order

    def evaluate_exit(
        self,
        trade_id: str,
        position_state: dict,
        current_price: float,
        context: MarketContext,
    ) -> Order | None:
        """Evaluate and potentially exit a trade.

        Args:
            trade_id: Trade to evaluate
            position_state: Current position state
            current_price: Current market price
            context: Current market context

        Returns:
            Order if exit triggered, None otherwise.
        """
        should_exit, reason = self.exit_engine.check_exit(
            trade_id, position_state, current_price, context
        )

        if not should_exit:
            return None

        return self.execution_planner.plan_exit(
            trade_id, position_state["symbol"], reason, current_price
        )
