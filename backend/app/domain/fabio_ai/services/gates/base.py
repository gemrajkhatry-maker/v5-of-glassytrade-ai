"""Base gate classes — extensible entry gate evaluation per OCP.

Each gate is an independent, testable unit that evaluates a specific condition.
The GateChain runs gates sequentially and returns the first failure.

Adding a new gate: create a class that inherits from EntryGate and implements
evaluate(). No modification to existing code required (Open/Closed Principle).
"""

from __future__ import annotations

import logging
from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from app.domain.trading.models.value_objects import OHLC, AMTResult, OrderBook

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class GateContext:
    """Context passed to gate evaluations.

    Contains all data needed for gate decisions.
    Frozen dataclass prevents accidental mutation.
    """

    # Current tick data
    tick: OHLC

    # AMT analysis result
    amt_result: AMTResult

    # Session data
    session_data: list  # Recent candles for momentum analysis

    # Order book (optional)
    order_book: OrderBook | None = None

    # CVD data
    cvd_slope: float = 0.0
    cvd_divergence: str = ""

    # Footprint data (optional)
    footprint_candle: object | None = None  # FootprintCandle

    # Direction being evaluated
    direction: str = ""  # "LONG" or "SHORT"

    # Market-specific thresholds
    cvd_threshold: float = 5000  # NSE default

    @property
    def price(self) -> float:
        return float(self.tick.close)

    @property
    def profile_shape(self) -> str:
        return str(self.amt_result.profile_shape or "")


@dataclass(frozen=True)
class GateResult:
    """Result of gate evaluation."""

    passed: bool
    gate_name: str  # Name of the gate that produced this result
    reason: str  # Short reason (e.g., "CVD_OPPOSING")
    detail: str  # Human-readable detail
    confidence_adjustment: float = 0.0  # -1.0 to +1.0 for confidence adjustment


class EntryGate(ABC):
    """Abstract base class for entry gates.

    Each gate evaluates a specific condition and returns a GateResult.
    Gates are independent, testable, and composable.

    To add a new gate:
    1. Create a class that inherits from EntryGate
    2. Implement evaluate(context) -> GateResult
    3. Add to GateChain in llm_entry_handler.py
    """

    @property
    @abstractmethod
    def name(self) -> str:
        """Human-readable name for logging."""
        ...

    @abstractmethod
    def evaluate(self, context: GateContext) -> GateResult:
        """Evaluate the gate condition.

        Args:
            context: Trading context with all necessary data.

        Returns:
            GateResult with passed/failed status and details.
        """
        ...


class GateChain:
    """Runs gates sequentially, returns first failure.

    Usage:
        chain = GateChain([CVDGate(), ProfileShapeGate()])
        result = chain.evaluate(context)
        if not result.passed:
            # Entry blocked
    """

    def __init__(self, gates: list[EntryGate] | None = None) -> None:
        self._gates: list[EntryGate] = gates or []

    def add(self, gate: EntryGate) -> GateChain:
        """Add a gate to the chain (builder pattern)."""
        self._gates.append(gate)
        return self

    def evaluate(self, context: GateContext) -> GateResult:
        """Evaluate all gates sequentially. Returns first failure or success.

        Args:
            context: Trading context with all necessary data.

        Returns:
            GateResult: First failure if any gate blocks, otherwise success.
        """
        for gate in self._gates:
            result = gate.evaluate(context)
            if not result.passed:
                logger.info(
                    "Gate %s blocked %s: %s — %s",
                    gate.name,
                    context.direction,
                    result.reason,
                    result.detail,
                )
                return result

        # All gates passed
        return GateResult(
            passed=True,
            gate_name="ALL",
            reason="ALL_PASSED",
            detail=f"All {len(self._gates)} gates passed",
        )

    @property
    def gate_count(self) -> int:
        """Number of gates in the chain."""
        return len(self._gates)

    @property
    def gate_names(self) -> list[str]:
        """Names of all gates in the chain."""
        return [g.name for g in self._gates]