# tests/quant/test_session_gates.py
"""Unit tests for the extracted session_gates module.

Tests the pure functions: session_allow_entry, session_force_exit,
parse_contract_expiry, bar_epoch_ms, ist_dt.
"""

from datetime import date, datetime, timedelta, timezone

import pytest

from quant.session_gates import (
    bar_epoch_ms,
    ist_dt,
    parse_contract_expiry,
    session_allow_entry,
    session_force_exit,
)

_IST = timezone(timedelta(hours=5, minutes=30))


def _ist_epoch(hour: int, minute: int = 0) -> int:
    """Today's date at the given IST hour:minute as epoch seconds."""
    today = datetime.now(tz=_IST).date()
    dt = datetime(today.year, today.month, today.day, hour, minute, tzinfo=_IST)
    return int(dt.timestamp())


class TestBarEpochMs:
    def test_empty_returns_zero(self):
        assert bar_epoch_ms("") == 0
        assert bar_epoch_ms(None) == 0

    def test_iso_string(self):
        result = bar_epoch_ms("2026-08-07T09:15:00+05:30")
        assert result > 0

    def test_epoch_seconds_string(self):
        epoch = str(_ist_epoch(10, 0))
        result = bar_epoch_ms(epoch)
        assert result > 0

    def test_unparseable_returns_zero(self):
        assert bar_epoch_ms("t300") == 0
        assert bar_epoch_ms("not-a-time") == 0


class TestIstDt:
    def test_empty_returns_none(self):
        assert ist_dt("") is None
        assert ist_dt(None) is None

    def test_synthetic_time_returns_none(self):
        assert ist_dt("t300") is None

    def test_epoch_returns_datetime(self):
        epoch = str(_ist_epoch(10, 30))
        result = ist_dt(epoch)
        assert result is not None
        assert result.hour == 10
        assert result.minute == 30


class TestParseContractExpiry:
    def test_valid_mcx_symbol(self):
        result = parse_contract_expiry("CRUDEOIL 17 AUG 7450 CALL")
        assert result is not None
        assert result.month == 8
        assert result.day == 17

    def test_no_month_token_returns_none(self):
        assert parse_contract_expiry("SYM") is None
        assert parse_contract_expiry("SYM 100 CALL") is None
        assert parse_contract_expiry("CRUDEOIL") is None

    def test_past_date_rolls_to_next_year(self):
        today = datetime.now(tz=_IST).date()
        # January contract when it's past January
        result = parse_contract_expiry("CRUDEOIL 10 JAN 7450 CALL")
        if today.month > 1 or (today.month == 1 and today.day > 10):
            assert result.year == today.year + 1
        else:
            assert result.year == today.year


class TestSessionAllowEntry:
    def test_synthetic_time_defaults_to_open(self):
        assert session_allow_entry("t300") is True

    def test_empty_time_defaults_to_open(self):
        assert session_allow_entry("") is True
        assert session_allow_entry(None) is True


class TestSessionForceExit:
    def test_synthetic_time_defaults_to_hold(self):
        assert session_force_exit("t300") is False

    def test_empty_time_defaults_to_hold(self):
        assert session_force_exit("") is False
        assert session_force_exit(None) is False
