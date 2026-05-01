"""Direction and timing signals for agent pipeline.

Extracted from agent_pipeline.py for separation of concerns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.trading.models.value_objects import OHLC
from app.domain.fabio_ai.services.amt_pipeline import AMTResult
from app.domain.probability.regime_classifier import RegimeState


@dataclass(frozen=True)
class DirectionSignal:
    """Direction decision with probability."""
    direction: str  # LONG, SHORT, or FLAT
    probability: float
    rationale: str = ""


def pick_direction(
    amt_result: AMTResult,
    regime: RegimeState,
) -> DirectionSignal:
    """Pick trade direction based on AMT and regime.

    Args:
        amt_result: AMT pipeline result
        regime: Current regime state

    Returns:
        DirectionSignal with direction and probability
    """
    # No signal case
    if amt_result.signal == "SKIP":
        return DirectionSignal("FLAT", 0.0, "No setup detected")

    # Get direction from AMT
    direction = amt_result.direction or "FLAT"
    prob = amt_result.confidence or 0.5

    # Apply regime filters
    if direction == "LONG" and not regime.allowed_long:
        return DirectionSignal("FLAT", 0.0, "Long not allowed in regime")
    if direction == "SHORT" and not regime.allowed_short:
        return DirectionSignal("FLAT", 0.0, "Short not allowed in regime")

    return DirectionSignal(direction, prob, f"AMT signal {amt_result.signal}")


def assess_timing(amt_result: AMTResult, data: dict[str, Any]) -> tuple[str, float]:
    """Assess timing for trade entry.

    Args:
        amt_result: AMT pipeline result
        data: Market data context

    Returns:
        Tuple of (timing, probability) where timing is ENTER_NOW, WAIT, or SKIP
    """
    if amt_result.signal == "SKIP":
        return "SKIP", 0.0

    # Check for immediate entry conditions
    if amt_result.signal in ("GREEN", "RED"):
        return "ENTER_NOW", 0.8

    # Wait for better setup
    return "WAIT", 0.3


def calculate_timing_probability(
    regime: RegimeState,
    market_state: str,
    session_name: str,
) -> float:
    """Calculate probability that timing is favorable.

    Args:
        regime: Current regime state
        market_state: Market state string
        session_name: Trading session name

    Returns:
        Timing probability [0, 1]
    """
    prob = 0.5  # Base probability

    # Higher probability in trending regime
    if regime.regime == "TRENDING":
        prob += 0.2

    # Session-adjusted probability
    if session_name == "OPEN":
        prob += 0.1  # Open session often has good moves
    elif session_name == "CLOSE":
        prob += 0.2  # Close often has volatility

    return min(prob, 1.0)