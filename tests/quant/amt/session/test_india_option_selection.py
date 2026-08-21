# tests/quant/amt/session/test_india_option_selection.py
"""Tests for Indian Option Contract Selection and Validation (Task 6)."""

import pytest
from quant.amt.session.selector import OptionSelector, OptionSelection


def test_rejects_option_when_spread_exceeds_premium_limit():
    selector = OptionSelector()
    opt = OptionSelection(
        underlying="NIFTY",
        strike=24800,
        option_type="CE",
        expiry="2026-08-27",
        premium=100.0,
        delta=0.50,
        theta=-10.0,
        iv=15.0,
        bid_ask_spread=3.5,  # 3.5% > 2.0% limit
        oi=500_000,
        lot_size=50,
        num_lots=1,
    )
    passed, reason = selector.validate_option(opt)
    assert passed is False
    assert "Bid-ask spread" in reason


def test_accepts_liquid_option_contract():
    selector = OptionSelector()
    opt = OptionSelection(
        underlying="NIFTY",
        strike=24800,
        option_type="CE",
        expiry="2026-08-27",
        premium=100.0,
        delta=0.50,
        theta=-10.0,
        iv=15.0,
        bid_ask_spread=1.0,  # 1.0% < 2.0% limit
        oi=500_000,
        lot_size=50,
        num_lots=1,
    )
    passed, reason = selector.validate_option(opt)
    assert passed is True
    assert reason == ""
