"""Tests for AMT advanced services."""

import sys
from pathlib import Path
_root = Path(__file__).resolve().parents[2]
if str(_root) not in sys.path:
    sys.path.insert(0, str(_root))

import asyncio
from datetime import datetime
from appv2.domain.services.npoc_tracker import NPOCTracker
from appv2.domain.services.flash_crash_protector import FlashCrashProtector, FlashCrashLevel
from appv2.domain.services.eia_calendar import EIACalendar, EconomicEvent, EventImpact
from appv2.domain.services.pyramid_manager import PyramidManager
from appv2.domain.services.composite_profile import CompositeProfileBuilder


def test_npoc_tracker_basic():
    """NPOC registration and retrieval should work."""
    tracker = NPOCTracker(max_sessions=5)

    tracker.register_session_poc("2024-01-15", poc=100.0, vah=110, val=90)
    tracker.register_session_poc("2024-01-16", poc=102.0, vah=112, val=92)
    tracker.register_session_poc("2024-01-17", poc=98.0, vah=108, val=88)

    assert tracker.active_count == 3

    # Get NPOCs above (for LONG targets)
    above = tracker.get_active("LONG")
    assert len(above) == 3
    assert above[0].price == 98.0  # Sorted ascending

    # Get nearest
    nearest = tracker.get_nearest(101.0)
    assert nearest is not None
    assert nearest.price == 100.0  # Closest to 101


def test_npoc_filling():
    """NPOC should be marked as filled when price trades through it."""
    tracker = NPOCTracker()
    tracker.register_session_poc("2024-01-15", poc=100.0)

    # Set current session context with POC ABOVE the NPOC
    # This means price has moved through the NPOC level
    tracker.set_current_session(poc=102.0, vah=112.0, val=92.0)

    # Price at 101 (between NPOC at 100 and current POC at 102)
    tracker.update(current_price=101.0)

    # The NPOC at 100 should be filled (price moved above it)
    active = tracker.get_active()
    assert len(active) == 0  # All filled
    assert tracker.filled_count == 1


def test_npoc_max_sessions():
    """Should only keep max_sessions NPOCs."""
    tracker = NPOCTracker(max_sessions=3)

    for i in range(10):
        tracker.register_session_poc(f"2024-01-{15+i:02d}", poc=100.0 + i)

    assert tracker.active_count <= 3


def test_flash_crash_normal():
    """Normal price movement should not trigger alerts."""
    import time
    protector = FlashCrashProtector(
        elevated_velocity_threshold=10.0,
        flash_crash_velocity_threshold=50.0,
        single_tick_jump_threshold=5.0,
    )

    for i in range(20):
        price = 100.0 + i * 0.1  # 0.1 per tick = slow movement
        state = protector.update_tick(price, volume=10)
        time.sleep(0.05)  # 50ms between ticks = realistic

    assert state.level == FlashCrashLevel.NORMAL
    assert not protector.should_halt_trading


def test_flash_crash_elevated():
    """Fast price movement should trigger ELEVATED."""
    protector = FlashCrashProtector(
        elevated_velocity_threshold=10.0,
        flash_crash_velocity_threshold=50.0,
        single_tick_jump_threshold=5.0,
    )

    # Simulate rapid price drop
    for i in range(20):
        price = 100.0 - i * 1.0  # 1.0 per tick = fast
        state = protector.update_tick(price, volume=100)

    # Should be at least ELEVATED
    assert state.level in (FlashCrashLevel.ELEVATED, FlashCrashLevel.FLASH_CRASH)


def test_flash_crash_extreme():
    """Extreme single-tick jump should trigger FLASH_CRASH."""
    protector = FlashCrashProtector(
        elevated_velocity_threshold=10.0,
        flash_crash_velocity_threshold=50.0,
        single_tick_jump_threshold=5.0,
    )

    protector.update_tick(100.0, volume=10)
    state = protector.update_tick(80.0, volume=10)  # 20 point drop in one tick

    assert state.level == FlashCrashLevel.FLASH_CRASH
    assert protector.should_close_positions


def test_eia_calendar_suppression():
    """EIA event should trigger suppression window."""
    from datetime import timezone
    calendar = EIACalendar()

    # Add today's EIA event at current time
    now = datetime.now(timezone.utc)
    calendar.add_event(EconomicEvent(
        name="EIA Crude Oil Inventory",
        date=now.strftime("%Y-%m-%d"),
        time_utc=now.strftime("%H:%M"),
        impact=EventImpact.HIGH,
        currencies=["USD"],
    ))

    suppressed, event = calendar.is_in_suppression_window(now)
    assert suppressed
    assert event is not None
    assert "EIA" in event.name


def test_eia_calendar_no_suppression():
    """Outside event window should not suppress."""
    calendar = EIACalendar()

    calendar.add_event(EconomicEvent(
        name="EIA Crude Oil Inventory",
        date="2024-01-15",
        time_utc="15:00",
        impact=EventImpact.HIGH,
        currencies=["USD"],
    ))

    # Check at 12:00 (3 hours before event)
    check_time = datetime(2024, 1, 15, 12, 0, 0)
    suppressed, event = calendar.is_in_suppression_window(check_time)
    assert not suppressed


def test_pyramid_manager_can_add():
    """Should allow pyramid add after sufficient profit."""
    pm = PyramidManager(max_adds=2, add_size_ratio=0.5, min_profit_atr=1.0)

    result = pm.can_pyramid(
        current_price=105.0,
        entry_price=100.0,
        current_sl=95.0,
        atr=3.0,
        is_long=True,
        lots=50,
    )

    assert result.can_add
    assert result.add_size == 25  # 50 × 0.5
    assert result.new_stop_loss >= 100.0  # Moved to at least breakeven


def test_pyramid_manager_insufficient_profit():
    """Should reject pyramid add with insufficient profit."""
    pm = PyramidManager(min_profit_atr=1.0)

    result = pm.can_pyramid(
        current_price=102.0,  # Only 2 points profit
        entry_price=100.0,
        current_sl=95.0,
        atr=5.0,  # Need 5 points profit
        is_long=True,
        lots=50,
    )

    assert not result.can_add
    assert "Insufficient" in result.reason


def test_pyramid_manager_max_adds():
    """Should reject after max adds reached."""
    pm = PyramidManager(max_adds=2)
    pm._adds = [{"price": 105, "lots": 25, "new_sl": 100}]  # Simulate 1 add already

    result = pm.can_pyramid(
        current_price=110.0,
        entry_price=100.0,
        current_sl=100.0,
        atr=2.0,
        is_long=True,
        lots=50,
    )

    # Can still add (1 of 2 used)
    assert result.can_add

    # After second add
    pm.record_add(110.0, 25, 105.0)

    result = pm.can_pyramid(
        current_price=115.0,
        entry_price=100.0,
        current_sl=105.0,
        atr=2.0,
        is_long=True,
        lots=50,
    )

    assert not result.can_add
    assert "Max" in result.reason


def test_composite_profile_build():
    """Composite profile should merge sessions correctly."""
    builder = CompositeProfileBuilder(min_sessions=3)

    builder.add_session("2024-01-15", poc=100.0, vah=110.0, val=90.0)
    builder.add_session("2024-01-16", poc=102.0, vah=112.0, val=92.0)
    builder.add_session("2024-01-17", poc=98.0, vah=108.0, val=88.0)

    profile = builder.build(current_price=103.0)

    assert profile is not None
    assert profile.sessions_merged == 3
    assert 98.0 < profile.weekly_poc < 102.0  # Average of 100, 102, 98
    assert profile.weekly_vah == 112.0  # Max VAH
    assert profile.weekly_val == 88.0   # Min VAL
    assert profile.bias == "BULLISH"    # Price 103 > weekly POC


def test_composite_profile_insufficient():
    """Should return None with too few sessions."""
    builder = CompositeProfileBuilder(min_sessions=3)

    builder.add_session("2024-01-15", poc=100.0, vah=110.0, val=90.0)

    profile = builder.build(current_price=101.0)
    assert profile is None
