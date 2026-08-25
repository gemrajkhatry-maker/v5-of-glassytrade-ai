"""Tests for quant.contracts.timezones helpers."""
from datetime import datetime

from quant.contracts.timezones import IST, today_ist


def test_today_ist_matches_ist_clock():
    assert today_ist() == datetime.now(tz=IST).date()
