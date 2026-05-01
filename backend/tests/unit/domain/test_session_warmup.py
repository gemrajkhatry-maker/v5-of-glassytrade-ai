"""Tests for SessionWarmupFilter."""

from __future__ import annotations

from datetime import datetime, timedelta

import pytest

from app.domain.fabio_ai.services.session_warmup import SessionWarmupFilter
from app.shared.timezones import IST


def test_warmup_returns_false_when_not_set():
    """is_in_warmup returns False when session_open not set."""
    warmup = SessionWarmupFilter()
    assert warmup.is_in_warmup() is False


def test_warmup_returns_true_during_warmup():
    """is_in_warmup returns True during warmup period."""
    warmup = SessionWarmupFilter(warmup_minutes=15)
    session_open = datetime(2024, 1, 1, 9, 15, tzinfo=IST)  # 09:15 IST
    warmup.set_session_open(session_open)
    
    # 5 minutes after open - still in warmup
    current = datetime(2024, 1, 1, 9, 20, tzinfo=IST)
    assert warmup.is_in_warmup(current) is True


def test_warmup_returns_false_after_warmup():
    """is_in_warmup returns False after warmup period."""
    warmup = SessionWarmupFilter(warmup_minutes=15)
    session_open = datetime(2024, 1, 1, 9, 15, tzinfo=IST)
    warmup.set_session_open(session_open)
    
    # 20 minutes after open - warmup over
    current = datetime(2024, 1, 1, 9, 35, tzinfo=IST)
    assert warmup.is_in_warmup(current) is False


def test_warmup_remaining_seconds():
    """warmup_remaining_seconds returns correct seconds."""
    warmup = SessionWarmupFilter(warmup_minutes=15)
    session_open = datetime(2024, 1, 1, 9, 15, tzinfo=IST)
    warmup.set_session_open(session_open)
    
    # 5 minutes after open - 600 seconds remaining
    current = datetime(2024, 1, 1, 9, 20, tzinfo=IST)
    assert warmup.warmup_remaining_seconds(current) == 600.0


def test_warmup_remaining_seconds_zero_after():
    """warmup_remaining_seconds returns 0 after warmup."""
    warmup = SessionWarmupFilter(warmup_minutes=15)
    session_open = datetime(2024, 1, 1, 9, 15, tzinfo=IST)
    warmup.set_session_open(session_open)
    
    # After warmup
    current = datetime(2024, 1, 1, 9, 35, tzinfo=IST)
    assert warmup.warmup_remaining_seconds(current) == 0.0


def test_reset_clears_state():
    """reset() clears session open time."""
    warmup = SessionWarmupFilter()
    session_open = datetime(2024, 1, 1, 9, 15, tzinfo=IST)
    warmup.set_session_open(session_open)
    
    warmup.reset()
    assert warmup.is_in_warmup() is False
    assert warmup.warmup_remaining_seconds() == 0.0


def test_custom_warmup_minutes():
    """Custom warmup minutes work correctly."""
    warmup = SessionWarmupFilter(warmup_minutes=5)
    session_open = datetime(2024, 1, 1, 9, 15, tzinfo=IST)
    warmup.set_session_open(session_open)
    
    # 4 minutes after open - still in warmup
    current = datetime(2024, 1, 1, 9, 19, tzinfo=IST)
    assert warmup.is_in_warmup(current) is True
    
    # 6 minutes after open - warmup over
    current = datetime(2024, 1, 1, 9, 21, tzinfo=IST)
    assert warmup.is_in_warmup(current) is False