"""Expiry schedule tests for brokers.broker.market_info.

Pins the current NSE schedule: NIFTY weekly on Tuesday (the only remaining
weekly), BANKNIFTY/FINNIFTY/MIDCPNIFTY monthly on the last Tuesday, and BSE
SENSEX weekly on Friday.
"""

from datetime import datetime

from brokers.broker.market_info import (
    EXPIRY_WEEKDAY,
    get_expiry_weekday,
    is_expiry_day,
)


class _FixedNow:
    """Stand-in for datetime with a fixed 'now' for expiry-day checks."""

    fixed: datetime

    @classmethod
    def now(cls, tz=None):  # noqa: ARG001
        return cls.fixed


def test_expiry_weekday_table_matches_current_nse_schedule():
    # NIFTY is the only remaining weekly — every Tuesday.
    assert EXPIRY_WEEKDAY["NIFTY"] == 1
    # Monthlies: last Tuesday of the month.
    for sym in ("BANKNIFTY", "FINNIFTY", "MIDCPNIFTY"):
        assert EXPIRY_WEEKDAY[sym] == 1
    # BSE SENSEX weekly remains Friday.
    assert EXPIRY_WEEKDAY["SENSEX"] == 4


def test_get_expiry_weekday_returns_tuesday_for_nse():
    assert get_expiry_weekday("NIFTY") == 1
    assert get_expiry_weekday("BANKNIFTY") == 1
    assert get_expiry_weekday("FINNIFTY") == 1
    assert get_expiry_weekday("MIDCPNIFTY") == 1
    assert get_expiry_weekday("NIFTY 50") == 1  # normalized alias
    assert get_expiry_weekday("UNKNOWN_INDEX") == 1  # NSE default = Tuesday


def test_get_expiry_weekday_sensex_friday():
    assert get_expiry_weekday("SENSEX") == 4


def test_is_expiry_day_nifty_on_tuesday(monkeypatch):
    _FixedNow.fixed = datetime(2026, 2, 24, 12, 0, 0)  # Tuesday
    monkeypatch.setattr("brokers.broker.market_info.datetime", _FixedNow)
    assert is_expiry_day("NIFTY") is True
    assert is_expiry_day("BANKNIFTY") is True


def test_is_expiry_day_not_on_monday(monkeypatch):
    _FixedNow.fixed = datetime(2026, 2, 23, 12, 0, 0)  # Monday
    monkeypatch.setattr("brokers.broker.market_info.datetime", _FixedNow)
    assert is_expiry_day("NIFTY") is False


def test_is_expiry_day_sensex_on_friday(monkeypatch):
    _FixedNow.fixed = datetime(2026, 2, 27, 12, 0, 0)  # Friday
    monkeypatch.setattr("brokers.broker.market_info.datetime", _FixedNow)
    assert is_expiry_day("SENSEX") is True
    assert is_expiry_day("NIFTY") is False
