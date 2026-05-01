"""Tests for Fabio Valentini methodology alignment.

These tests validate the fixes to align with Fabio's 2-state model and edge detection.
"""
import pytest
from datetime import datetime, time

# Test 1: MarketState Enum Should Be 2-State Only
def test_market_state_is_two_state():
    """MarketState should only have BALANCED and IMBALANCED."""
    from backend.app.domain.trading.models.enums import MarketState
    
    states = list(MarketState)
    assert len(states) == 2, f"Expected 2 states, got {len(states)}: {states}"
    assert MarketState.BALANCED in states
    assert MarketState.IMBALANCED in states
    
    # NO_TRADE and PROBING should not exist
    with pytest.raises((AttributeError, ValueError)):
        MarketState.NO_TRADE
    with pytest.raises((AttributeError, ValueError)):
        MarketState.PROBING


# Test 2: TradingPhase Should Have OPENING_AUCTION
def test_opening_auction_exists():
    """TradingPhase should have OPENING_AUCTION, not OPENING_NOISE."""
    from backend.app.domain.services.session_phase_gate import TradingPhase
    
    assert hasattr(TradingPhase, 'OPENING_AUCTION')
    assert hasattr(TradingPhase, 'AAA_WINDOW')
    assert not hasattr(TradingPhase, 'OPENING_NOISE')


if __name__ == "__main__":
    pytest.main([__file__, "-v"])