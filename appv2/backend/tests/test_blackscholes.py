"""Tests for Black-Scholes computation."""

import sys
import math
from pathlib import Path
_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

from appv2.domain.services.blackscholes import black_scholes, implied_volatility


def test_ce_call_basic():
    """Basic CE call should have positive delta."""
    greeks = black_scholes(S=100, K=100, T=30 / 365, r=0.065, sigma=0.20, option_type="CE")
    assert 0.4 < greeks.delta < 0.6  # ATM call ≈ 0.50
    assert greeks.gamma > 0
    assert greeks.theoretical > 0


def test_pe_put_basic():
    """PE put should have negative delta."""
    greeks = black_scholes(S=100, K=100, T=30 / 365, r=0.065, sigma=0.20, option_type="PE")
    assert -0.6 < greeks.delta < -0.4  # ATM put ≈ -0.50
    assert greeks.gamma > 0


def test_itm_call():
    """ITM call (S > K) should have delta > 0.50."""
    greeks = black_scholes(S=105, K=100, T=30 / 365, r=0.065, sigma=0.20, option_type="CE")
    assert greeks.delta > 0.50


def test_otm_call():
    """OTM call (S < K) should have delta < 0.50."""
    greeks = black_scholes(S=95, K=100, T=30 / 365, r=0.065, sigma=0.20, option_type="CE")
    assert greeks.delta < 0.50


def test_theta_decay():
    """Theta should be negative (time decay)."""
    greeks = black_scholes(S=100, K=100, T=30 / 365, r=0.065, sigma=0.20, option_type="CE")
    assert greeks.theta < 0


def test_iv_convergence():
    """Implied volatility should converge to input vol."""
    # Compute theoretical price
    greeks = black_scholes(S=100, K=100, T=30 / 365, r=0.065, sigma=0.25, option_type="CE")
    theoretical = greeks.theoretical

    # Recover IV from theoretical price
    iv = implied_volatility(theoretical, S=100, K=100, T=30 / 365, r=0.065, option_type="CE")
    assert abs(iv - 0.25) < 0.01  # Within 1%
