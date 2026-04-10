"""Tests for Market State Engine."""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from appv2.domain.services.market_state_engine import detect_market_state
from appv2.domain.enums.market_state import MarketState


def test_no_trade_at_poc():
    """Price at POC → NO_TRADE state."""
    result = detect_market_state(
        price=100.0, poc=100.0, vah=110, val=90,
        tick_size=0.05, has_displacement=False, has_acceptance=False,
    )
    assert result.state == MarketState.NO_TRADE


def test_balanced_inside_va():
    """Price inside VA with good balance → BALANCED."""
    # Price must not be near POC (POC_NO_TRADE_TICKS=5 × 0.05 = 0.25)
    result = detect_market_state(
        price=105.0, poc=100.0, vah=110, val=90,
        tick_size=0.05, has_displacement=False, has_acceptance=False,
        balance_ratio=0.60,
    )
    assert result.state == MarketState.BALANCED


def test_imbalanced_with_displacement():
    """Price outside VA + displacement + acceptance → IMBALANCED."""
    result = detect_market_state(
        price=115.0, poc=100.0, vah=110, val=90,
        tick_size=0.05, has_displacement=True, has_acceptance=True,
    )
    assert result.state == MarketState.IMBALANCED


def test_probing_without_displacement():
    """Price outside VA, no displacement → PROBING."""
    result = detect_market_state(
        price=115.0, poc=100.0, vah=110, val=90,
        tick_size=0.05, has_displacement=False, has_acceptance=False,
    )
    assert result.state == MarketState.PROBING


def test_probing_at_va_edge():
    """Price at VA edge with displacement → PROBING (pre-emptive)."""
    result = detect_market_state(
        price=109.8, poc=100.0, vah=110, val=90,
        tick_size=0.05, has_displacement=True, has_acceptance=False,
        balance_ratio=0.50,
    )
    assert result.state == MarketState.PROBING
