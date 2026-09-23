"""Tests for session_context helpers — is_expiry_day and seconds_to_close."""

from datetime import date, datetime, timezone, timedelta


from quant.amt.session.context import (
    get_session_info,
    is_expiry_day,
    seconds_to_close,
)


_IST = timezone(timedelta(hours=5, minutes=30))


# ---- is_expiry_day ----

def test_tuesday_is_expiry_day():
    """Any Tuesday is an expiry day: NIFTY weekly (every Tuesday)."""
    # 2026-02-24 is a Tuesday (last Tuesday of Feb 2026)
    assert is_expiry_day(date(2026, 2, 24)) is True
    # 2026-02-10 is a plain mid-month Tuesday — still NIFTY weekly expiry
    assert is_expiry_day(date(2026, 2, 10)) is True


def test_friday_is_not_expiry_day():
    assert is_expiry_day(date(2026, 2, 27)) is False


def test_monday_is_not_expiry_day():
    assert is_expiry_day(date(2026, 2, 23)) is False


def test_wednesday_is_not_expiry_day():
    assert is_expiry_day(date(2026, 2, 25)) is False


def test_last_tuesday_of_month_is_expiry():
    """Last Tuesday of month (monthly expiry) is also a Tuesday."""
    # 2026-02-24 is last Tuesday of Feb 2026
    assert is_expiry_day(date(2026, 2, 24)) is True


# ---- seconds_to_close ----

def test_nse_seconds_to_close_morning():
    """At 10:00 IST, 5h30m = 19800s to the real NSE close (15:30) — Phase 2
    unified seconds_to_close on the true exchange close, not the 15:15
    last-entry cutoff it previously (incorrectly) measured against."""
    dt = datetime(2026, 2, 25, 10, 0, 0, tzinfo=_IST)
    result = seconds_to_close(dt, "NSE")
    assert result == 19800.0


def test_nse_seconds_to_close_near_end():
    """At 15:00 IST, 30 min = 1800s to the real 15:30 close."""
    dt = datetime(2026, 2, 25, 15, 0, 0, tzinfo=_IST)
    result = seconds_to_close(dt, "NSE")
    assert result == 1800.0


def test_nse_seconds_to_close_after_close():
    """After 15:15 IST, returns 0."""
    dt = datetime(2026, 2, 25, 15, 30, 0, tzinfo=_IST)
    result = seconds_to_close(dt, "NSE")
    assert result == 0.0


def test_mcx_seconds_to_close():
    """MCX close is 23:30 IST."""
    dt = datetime(2026, 2, 25, 22, 0, 0, tzinfo=_IST)
    result = seconds_to_close(dt, "MCX")
    assert result == 5400.0  # 1h30m


def test_unknown_exchange_returns_zero():
    dt = datetime(2026, 2, 25, 10, 0, 0, tzinfo=_IST)
    assert seconds_to_close(dt, "UNKNOWN") == 0.0


# ---- get_session_info: NSE vs MCX after NSE cash close (regression) ----


def test_nse_post_market_after_1530_ist():
    """After 15:30 IST, NSE calendar is POST_MARKET — no new entries."""
    ts = "2026-04-17T16:57:00+05:30"
    info = get_session_info(timestamp=ts, market="NSE")
    assert info.session == "POST_MARKET"
    assert info.allow_entry is False


def test_mcx_afternoon_still_allows_entry_same_clock():
    """Same wall clock: MCX afternoon session — entries allowed (not NSE POST_MARKET)."""
    ts = "2026-04-17T16:57:00+05:30"
    info = get_session_info(timestamp=ts, market="MCX")
    assert info.session == "MCX_AFTERNOON"
    assert info.allow_entry is True
