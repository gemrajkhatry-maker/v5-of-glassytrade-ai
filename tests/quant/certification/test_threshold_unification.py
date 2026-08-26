"""Cert E7: balance-threshold drift between named constant and literal."""
from __future__ import annotations

import pytest

from quant.amt.market.state_engine import detect_market_state
from quant.contracts.constants import BALANCE_RATIO_THRESHOLD


def test_balance_ratio_threshold_matches_named_constant():
    """Named constant is 0.55; the function must use it, not a stale literal."""
    # balance_ratio between 0.5 and 0.55 must classify IMBALANCED per the
    # named constant (0.55), not slip through as BALANCED via a stale 0.5 literal.
    res = detect_market_state(
        price=100.0, poc=100.0, vah=101.0, val=99.0, tick_size=0.05,
        has_displacement=False, has_acceptance=True,
        balance_ratio=BALANCE_RATIO_THRESHOLD - 0.001,
    )
    assert res.state.value == "IMBALANCED"
    assert f"({BALANCE_RATIO_THRESHOLD - 0.001:.2f})" in res.trigger
