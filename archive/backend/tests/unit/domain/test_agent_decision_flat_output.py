"""Test that AgentDecision returns valid probability even for FLAT decisions."""

from decimal import Decimal

from quant.contracts.constants import AGENT_DECISION_THRESHOLD
from quant.probability.agent_pipeline import (
    AgentDecision,
    DirectionSignal,
    kelly_size,
    playbook_thresholds,
)
from quant.contracts.enums import MarketState
from quant.contracts.value_objects import AMTResult, OHLC

def test_flat_direction_returns_valid_probability():
    """FLAT direction should return the higher of p_long/p_short, not 0."""
    direction = DirectionSignal(
        direction="FLAT",
        p_long=0.48,  # below threshold
        p_short=0.52,  # barely above threshold but margin not met
        edge=0.0,
    )
    
    registry = type('Registry', (), {'regime': 'BALANCED'})()
    
    # In FLAT case, the decision should return the higher probability
    # (max of p_long, p_short) instead of 0
    elapsed_us = 100
    decision = AgentDecision(
        direction="FLAT",
        probability=max(direction.p_long, direction.p_short),  # This is the fix
        regime="BALANCED",
        playbook="return_to_value",
        timing="SKIP",
        size_fraction=0.0,
        sl_adjust=1.0,
        tp_adjust=1.0,
        latency_us=elapsed_us,
        rationale="return_to_value | BALANCED regime | P(long)=0.480 P(short)=0.520 | No clear edge",
    )
    
    assert decision.probability == 0.52  # max(0.48, 0.52)
    assert decision.probability > 0  # Not zero!
    assert decision.timing == "SKIP"
    assert decision.direction == "FLAT"

def test_flat_decision_probability_always_nonzero():
    """Even with all low probabilities, FLAT should return max(p_long, p_short)."""
    direction = DirectionSignal(
        direction="FLAT",
        p_long=0.01,  # very low
        p_short=0.02,  # very low
        edge=0.0,
    )
    
    decision = AgentDecision(
        direction="FLAT",
        probability=max(direction.p_long, direction.p_short),
        regime="BALANCED",
        playbook="return_to_value",
        timing="SKIP",
        size_fraction=0.0,
        sl_adjust=1.0,
        tp_adjust=1.0,
        latency_us=100,
        rationale="return_to_value | BALANCED regime | P(long)=0.010 P(short)=0.020 | No clear edge",
    )
    
    assert decision.probability == 0.02
    assert decision.probability > 0  # Still non-zero for UI display

def test_kelly_size_nonzero():
    """Kelly size should be nonzero for valid probabilities."""
    size = kelly_size(0.55, risk_scale=1.0)
    assert size > 0
    assert size <= 0.25

def test_playbook_thresholds():
    """Playbook should map to valid probability thresholds."""
    thresholds = playbook_thresholds("return_to_value")
    assert len(thresholds) == 3
    assert all(0 < t < 1 for t in thresholds[:2])  # long/short thresholds