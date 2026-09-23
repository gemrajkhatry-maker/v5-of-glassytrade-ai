# tests/quant/test_india_session_contract.py
"""Tests for Indian Session Boundaries and Expiry Rules (Task 9)."""

from quant.amt.session.context import get_session_info
from quant.session_gates import session_force_exit


def test_opening_noise_blocks_new_entries():
    # 09:20 IST is NSE_OPENING (09:15-09:30)
    info = get_session_info("2026-08-19T09:20:00+05:30", market="NSE")
    assert info.session == "NSE_OPENING"
    assert info.allow_entry is False


def test_primary_session_allows_trend_and_reversion():
    # 10:00 IST is NSE_PRIMARY (09:30-11:30)
    info = get_session_info("2026-08-19T10:00:00+05:30", market="NSE")
    assert info.session == "NSE_PRIMARY"
    assert info.allow_entry is True
    assert info.allow_trend is True
    assert info.allow_reversion is True


def test_midday_session_blocks_blind_trend():
    # 12:30 IST is NSE_MIDDAY (11:30-14:00)
    info = get_session_info("2026-08-19T12:30:00+05:30", market="NSE")
    assert info.session == "NSE_MIDDAY"
    assert info.allow_entry is True
    assert info.allow_trend is False  # Breakouts blocked
    assert info.allow_reversion is True


def test_close_protection_blocks_entries_and_forces_exit():
    # 15:20 IST is NSE_CLOSE (15:15-15:30)
    info = get_session_info("2026-08-19T15:20:00+05:30", market="NSE")
    assert info.session == "NSE_CLOSE"
    assert info.allow_entry is False
    assert session_force_exit("2026-08-19T15:20:00+05:30", market="NSE") is True
