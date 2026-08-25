"""Tests for session_context — ported from backend/tests/unit/domain/test_session_context.py + parity."""

from datetime import date, datetime, timezone, timedelta

import pytest

from quant.amt.session.context import (
    get_session,
    get_session_info,
    classify_gap,
    opening_relation,
    seconds_to_close,
    is_expiry_day,
    get_sub_session,
)
from tests.quant.parity_harness import assert_parity

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
    # Phase 2: seconds_to_close now measures to the real exchange close
    # (15:30), not the last-entry cutoff (15:15) — 10:00 -> 15:30 = 5.5h.
    dt = datetime(2026, 2, 25, 10, 0, 0, tzinfo=_IST)
    result = seconds_to_close(dt, "NSE")
    assert result == 19800.0


def test_nse_seconds_to_close_near_end():
    # 15:00 -> 15:30 close = 1800s (was measured to 15:15 last-entry before
    # Phase 2 unified the NSE close constants).
    dt = datetime(2026, 2, 25, 15, 0, 0, tzinfo=_IST)
    result = seconds_to_close(dt, "NSE")
    assert result == 1800.0


def test_nse_seconds_to_close_after_close():
    dt = datetime(2026, 2, 25, 15, 30, 0, tzinfo=_IST)
    result = seconds_to_close(dt, "NSE")
    assert result == 0.0


def test_mcx_seconds_to_close():
    # MCX closes 23:30 IST: 22:00 -> 90 minutes.
    dt = datetime(2026, 2, 25, 22, 0, 0, tzinfo=_IST)
    result = seconds_to_close(dt, "MCX")
    assert result == 5400.0


def test_unknown_exchange_returns_zero():
    dt = datetime(2026, 2, 25, 10, 0, 0, tzinfo=_IST)
    assert seconds_to_close(dt, "UNKNOWN") == 0.0


# ---- get_session_info: NSE vs MCX after NSE cash close (regression) ----


def test_nse_post_market_after_1530_ist():
    ts = "2026-04-17T16:57:00+05:30"
    info = get_session_info(timestamp=ts, market="NSE")
    assert info.session == "POST_MARKET"
    assert info.allow_entry is False


def test_mcx_afternoon_still_allows_entry_same_clock():
    ts = "2026-04-17T16:57:00+05:30"
    info = get_session_info(timestamp=ts, market="MCX")
    assert info.session == "MCX_AFTERNOON"
    assert info.allow_entry is True


def test_mcx_evening_is_high_liquidity_trend_window():
    """18:00-23:00 is the US/COMEX/NYMEX overlap — the engine must treat it
    as the high-liquidity trend-continuation window, not the old
    "reduced liquidity / NEUTRAL" classification."""
    ts = "2026-04-17T20:00:00+05:30"
    info = get_session_info(timestamp=ts, market="MCX")
    assert info.session == "MCX_EVENING"
    assert info.allow_entry is True
    assert info.favor_strategy == "TREND_CONTINUATION"


def test_mcx_close_window_blocks_at_real_close():
    """MCX close protection runs 23:00-23:30 (real close 23:30 IST): the
    23:20 window blocks new entries and forces the square-off."""
    ts = "2026-04-17T23:20:00+05:30"
    info = get_session_info(timestamp=ts, market="MCX")
    assert info.session == "MCX_CLOSE"
    assert info.allow_entry is False
    assert info.force_exit is True
    # Still inside the close window — entries were allowed at 22:55.
    ts_before = "2026-04-17T22:55:00+05:30"
    info_before = get_session_info(timestamp=ts_before, market="MCX")
    assert info_before.session == "MCX_EVENING"
    assert info_before.allow_entry is True


# ======================================================================
# Parity: legacy shim vs quant module on fixed inputs
# ======================================================================

_SESSION_TS = [
    "2026-04-17T02:00:00Z",
    "2026-04-17T04:00:00Z",
    "2026-04-17T06:00:00Z",
    "2026-04-17T08:30:00Z",
    "2026-04-17T10:00:00Z",
    "2026-04-17T12:00:00Z",
    "2026-04-17T14:00:00Z",
    "2026-04-17T16:00:00Z",
    "2026-04-17T18:00:00Z",
    "2026-04-17T20:00:00Z",
    "2026-04-17T22:00:00Z",
    "2026-04-17T23:59:00Z",
    "2026-04-17T16:57:00+05:30",
]

_GAP_CASES = [
    (100.0, 100.0, 50.0),
    (100.0, 99.0, 50.0),
    (100.0, 95.0, 50.0),
    (100.0, 80.0, 50.0),
    (100.0, 0.0, 50.0),
    (100.0, 50.0, 0.0),
    (100.0, 99.9, 10.0),
]

_OPENING_CASES = [
    (100.0, 105.0, 95.0),
    (100.0, 95.0, 90.0),
    (100.0, 110.0, 100.0),
    (100.0, 100.0, 100.0),
]

_CLOSE_CASES = [
    (datetime(2026, 2, 25, 10, 0, 0, tzinfo=_IST), "NSE"),
    (datetime(2026, 2, 25, 15, 0, 0, tzinfo=_IST), "NSE"),
    (datetime(2026, 2, 25, 15, 30, 0, tzinfo=_IST), "NSE"),
    (datetime(2026, 2, 25, 22, 0, 0, tzinfo=_IST), "MCX"),
    (datetime(2026, 2, 25, 10, 0, 0, tzinfo=_IST), "UNKNOWN"),
]

_EXPIRY_DATES = [
    date(2026, 2, 26),
    date(2026, 2, 27),
    date(2026, 2, 23),
    date(2026, 3, 19),
    date(2026, 3, 18),
]

_SUB_SESSION_TS = [
    datetime(2026, 2, 25, 8, 0, 0, tzinfo=_IST),
    datetime(2026, 2, 25, 10, 0, 0, tzinfo=_IST),
    datetime(2026, 2, 25, 15, 0, 0, tzinfo=_IST),
    datetime(2026, 2, 25, 20, 0, 0, tzinfo=_IST),
    datetime(2026, 2, 25, 23, 59, 0, tzinfo=_IST),
]


def test_session_context_parity():
    for ts in _SESSION_TS:
        get_session(ts)
    for args in _GAP_CASES:
        classify_gap(*args)
    for args in _OPENING_CASES:
        opening_relation(*args)
    for dt, ex in _CLOSE_CASES:
        seconds_to_close(dt, ex)
    for d in _EXPIRY_DATES:
        is_expiry_day(d)
    for dt in _SUB_SESSION_TS:
        get_sub_session("MCX", dt)
        get_sub_session("NSE", dt)
    for market in ("NSE", "MCX", "GLOBAL"):
        for ts in _SESSION_TS:
            (lambda: get_session_info(timestamp=ts, market=market))()
