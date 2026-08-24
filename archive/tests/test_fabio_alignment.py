"""Tests for Fabio Valentini methodology alignment.

These tests validate the fixes to align with Fabio's 2-state model and edge detection.
"""
import pytest
from datetime import datetime, time

# Test 1: MarketState Enum Should Be 2-State Only
def test_market_state_is_two_state():
    """MarketState should only have BALANCED and IMBALANCED."""
    from quant.contracts.enums import MarketState
    
    states = list(MarketState)
    assert len(states) == 2, f"Expected 2 states, got {len(states)}: {states}"
    assert MarketState.BALANCED in states
    assert MarketState.IMBALANCED in states
    
    # NO_TRADE and PROBING should not exist
    with pytest.raises((AttributeError, ValueError)):
        MarketState.NO_TRADE
    with pytest.raises((AttributeError, ValueError)):
        MarketState.PROBING


# Test 2: use the canonical phase contract currently consumed by risk sizing.
def test_opening_phase_contract_exists():
    """The live phase classifier exposes the guarded opening-noise phase."""
    from quant.execution.risk_sizing import SessionPhase

    assert SessionPhase.OPENING_NOISE.value == "OPENING_NOISE"
    assert SessionPhase.OPENING_NOISE is not None


if __name__ == "__main__":
    pytest.main([__file__, "-v"])