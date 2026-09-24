"""Cert E7: balance-threshold drift between named constant and literal."""
from __future__ import annotations


from quant.amt.market.state_engine import detect_market_state
from quant.contracts.constants import BALANCE_RATIO_THRESHOLD


def test_balance_ratio_threshold_matches_named_constant():
    """Named threshold affects confidence/trigger text, not inside-VA state."""
    # Inside the session value area remains BALANCED; a low balance ratio is
    # reported as a confidence/trigger concern rather than flipping the state.
    res = detect_market_state(
        price=100.0, poc=100.0, vah=101.0, val=99.0, tick_size=0.05,
        has_displacement=False, has_acceptance=True,
        balance_ratio=BALANCE_RATIO_THRESHOLD - 0.001,
    )
    assert res.state.value == "BALANCED"
    assert f"({BALANCE_RATIO_THRESHOLD - 0.001:.2f})" in res.trigger
