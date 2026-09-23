# tests/quant/amt/session/test_india_option_selection.py
"""Tests for Indian Option Contract Selection and Validation (Task 6)."""

from datetime import timedelta


from quant.amt.session.selector import OptionSelector, OptionSelection
from quant.contracts.timezones import today_ist

# Rolling future expiry so the DTE check stays valid whenever the suite runs.
# A hardcoded date rolls into the past and the "liquid" contract below gets
# rejected as expired (DTE < min_days_to_expiry) instead of accepted.
_VALID_EXPIRY = (today_ist() + timedelta(days=7)).isoformat()


def test_rejects_option_when_spread_exceeds_premium_limit():
    selector = OptionSelector()
    opt = OptionSelection(
        underlying="NIFTY",
        strike=24800,
        option_type="CE",
        expiry=_VALID_EXPIRY,
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
        expiry=_VALID_EXPIRY,
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
