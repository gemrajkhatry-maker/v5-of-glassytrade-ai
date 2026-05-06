"""Direction and timing signals for agent pipeline.

Extracted from agent_pipeline.py for separation of concerns.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from app.domain.trading.model.value_objects import OHLC
from app.domain.trading.model.value_objects import AMTResult
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
    signal = str(getattr(amt_result, "signal", "") or "").upper()
    if signal == "SKIP":
        return DirectionSignal("FLAT", 0.0, "No setup detected")

    direction = str(getattr(amt_result, "direction", "") or "").upper()
    if not direction:
        setup = str(getattr(amt_result, "setup", "") or "").upper()
        if setup:
            direction = setup
        elif signal in {"GREEN", "LONG", "BUY"}:
            direction = "LONG"
        elif signal in {"RED", "SHORT", "SELL"}:
            direction = "SHORT"
        else:
            direction = "FLAT"

    confidence = getattr(amt_result, "confidence", None)
    if confidence is None:
        confidence = getattr(amt_result, "structure_confidence", 0.0)
    prob = float(confidence or 0.5)

    # Apply regime filters
    if direction == "LONG" and not regime.allowed_long:
        return DirectionSignal("FLAT", 0.0, "Long not allowed in regime")
    if direction == "SHORT" and not regime.allowed_short:
        return DirectionSignal("FLAT", 0.0, "Short not allowed in regime")

    return DirectionSignal(direction, prob, f"AMT signal {signal or getattr(amt_result, 'setup', '')}")


def assess_timing(amt_result: AMTResult, data: dict[str, Any]) -> tuple[str, float]:
    """Assess timing for trade entry.

    Args:
        amt_result: AMT pipeline result
        data: Market data context

    Returns:
        Tuple of (timing, probability) where timing is ENTER_NOW, WAIT, or SKIP
    """
    signal = str(getattr(amt_result, "signal", "") or "").upper()
    if signal == "SKIP":
        return "SKIP", 0.0

    # Check for immediate entry conditions
    if signal in ("GREEN", "RED"):
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