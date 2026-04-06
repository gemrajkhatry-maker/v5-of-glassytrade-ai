"""Tests for session_context helpers — is_expiry_day and seconds_to_close."""

from datetime import date, datetime, timezone, timedelta

import pytest

from app.domain.fabio_ai.services.session_context import is_expiry_day, seconds_to_close


_IST = timezone(timedelta(hours=5, minutes=30))


# ---- is_expiry_day ----

def test_thursday_is_expiry_day():
    """Thursday (weekday=3) is always an expiry day."""
    # 2026-02-26 is a Thursday
    assert is_expiry_day(date(2026, 2, 26)) is True


def test_friday_is_not_expiry_day():
    assert is_expiry_day(date(2026, 2, 27)) is False


def test_monday_is_not_expiry_day():
    assert is_expiry_day(date(2026, 2, 23)) is False


def test_last_thursday_of_month_is_expiry():
    """Last Thursday of month (monthly expiry) is also a Thursday."""
    # 2026-02-26 is last Thursday of Feb 2026
    assert is_expiry_day(date(2026, 2, 26)) is True


# ---- seconds_to_close ----

def test_nse_seconds_to_close_morning():
    """At 10:00 IST, 5h15m = 18900s to NSE close (15:15)."""
    dt = datetime(2026, 2, 25, 10, 0, 0, tzinfo=_IST)
    result = seconds_to_close(dt, "NSE")
    assert result == 18900.0


def test_nse_seconds_to_close_near_end():
    """At 15:00 IST, 15 min = 900s to close."""
    dt = datetime(2026, 2, 25, 15, 0, 0, tzinfo=_IST)
    result = seconds_to_close(dt, "NSE")
    assert result == 900.0


def test_nse_seconds_to_close_after_close():
    """After 15:15 IST, returns 0."""
    dt = datetime(2026, 2, 25, 15, 30, 0, tzinfo=_IST)
    result = seconds_to_close(dt, "NSE")
    assert result == 0.0


def test_mcx_seconds_to_close():
    """MCX close is 23:15 IST."""
    dt = datetime(2026, 2, 25, 22, 0, 0, tzinfo=_IST)
    result = seconds_to_close(dt, "MCX")
    assert result == 4500.0  # 1h15m


def test_unknown_exchange_returns_zero():
    dt = datetime(2026, 2, 25, 10, 0, 0, tzinfo=_IST)
    assert seconds_to_close(dt, "UNKNOWN") == 0.0
