"""Unit tests for EIACalendar — EIA release window detection per FR-01-07."""

import pytest
from datetime import datetime, time, timedelta, timezone
from quant.amt.session.eia import EIACalendar, EIAWindow, EIA_SCHEDULE

_IST = timezone(timedelta(hours=5, minutes=30))
_ET = timezone(timedelta(hours=-5))


class TestEIACalendarSchedule:
    """Verify EIA schedule configuration."""

    def test_naturalgas_schedule(self):
        """NATURALGAS: Thursday 10:30 AM ET."""
        ng = EIA_SCHEDULE["NATURALGAS"]
        assert ng.symbol == "NATURALGAS"
        assert ng.release_day == 3  # Thursday
        assert ng.release_time_et == time(10, 30)
        assert ng.suppression_minutes == 15

    def test_crudeoil_schedule(self):
        """CRUDEOIL: Wednesday 10:30 AM ET."""
        cl = EIA_SCHEDULE["CRUDEOIL"]
        assert cl.symbol == "CRUDEOIL"
        assert cl.release_day == 2  # Wednesday
        assert cl.release_time_et == time(10, 30)
        assert cl.suppression_minutes == 15


class TestEIACalendarIsSuppressed:
    """Test suppression window detection."""

    def test_naturalgas_thursday_suppressed(self):
        """NATURALGAS suppressed on Thursday 10:20 ET (within 15 min window)."""
        cal = EIACalendar(suppression_minutes=15)
        # Thursday 10:20 ET = within suppression window
        thursday_1020_et = datetime(2026, 3, 19, 10, 20, tzinfo=_ET)  # Thursday
        thursday_1020_ist = thursday_1020_et.astimezone(_IST)
        assert cal.is_suppressed("NATURALGAS", thursday_1020_ist) is True

    def test_naturalgas_thursday_not_suppressed_before_window(self):
        """NATURALGAS not suppressed on Thursday 10:10 ET (before 15 min window)."""
        cal = EIACalendar(suppression_minutes=15)
        thursday_1010_et = datetime(2026, 3, 19, 10, 10, tzinfo=_ET)
        thursday_1010_ist = thursday_1010_et.astimezone(_IST)
        assert cal.is_suppressed("NATURALGAS", thursday_1010_ist) is False

    def test_naturalgas_thursday_not_suppressed_after_window(self):
        """NATURALGAS not suppressed on Thursday 10:50 ET (after 15 min window)."""
        cal = EIACalendar(suppression_minutes=15)
        thursday_1050_et = datetime(2026, 3, 19, 10, 50, tzinfo=_ET)
        thursday_1050_ist = thursday_1050_et.astimezone(_IST)
        assert cal.is_suppressed("NATURALGAS", thursday_1050_ist) is False

    def test_naturalgas_wednesday_not_suppressed(self):
        """NATURALGAS not suppressed on Wednesday (wrong day)."""
        cal = EIACalendar(suppression_minutes=15)
        wednesday_1020_et = datetime(2026, 3, 18, 10, 20, tzinfo=_ET)  # Wednesday
        wednesday_1020_ist = wednesday_1020_et.astimezone(_IST)
        assert cal.is_suppressed("NATURALGAS", wednesday_1020_ist) is False

    def test_crudeoil_wednesday_suppressed(self):
        """CRUDEOIL suppressed on Wednesday 10:25 ET (within 15 min window)."""
        cal = EIACalendar(suppression_minutes=15)
        wednesday_1025_et = datetime(2026, 3, 18, 10, 25, tzinfo=_ET)  # Wednesday
        wednesday_1025_ist = wednesday_1025_et.astimezone(_IST)
        assert cal.is_suppressed("CRUDEOIL", wednesday_1025_ist) is True

    def test_crudeoil_thursday_not_suppressed(self):
        """CRUDEOIL not suppressed on Thursday (wrong day)."""
        cal = EIACalendar(suppression_minutes=15)
        thursday_1025_et = datetime(2026, 3, 19, 10, 25, tzinfo=_ET)  # Thursday
        thursday_1025_ist = thursday_1025_et.astimezone(_IST)
        assert cal.is_suppressed("CRUDEOIL", thursday_1025_ist) is False

    def test_unknown_symbol_not_suppressed(self):
        """Unknown symbol never suppressed."""
        cal = EIACalendar(suppression_minutes=15)
        assert cal.is_suppressed("GOLD") is False
        assert cal.is_suppressed("NIFTY") is False

    def test_boundary_start(self):
        """Exactly at suppression start → suppressed."""
        cal = EIACalendar(suppression_minutes=15)
        # 10:15 ET = exactly 15 min before release
        thursday_1015_et = datetime(2026, 3, 19, 10, 15, tzinfo=_ET)
        thursday_1015_ist = thursday_1015_et.astimezone(_IST)
        assert cal.is_suppressed("NATURALGAS", thursday_1015_ist) is True

    def test_boundary_end(self):
        """Exactly at suppression end → suppressed."""
        cal = EIACalendar(suppression_minutes=15)
        # 10:45 ET = exactly 15 min after release
        thursday_1045_et = datetime(2026, 3, 19, 10, 45, tzinfo=_ET)
        thursday_1045_ist = thursday_1045_et.astimezone(_IST)
        assert cal.is_suppressed("NATURALGAS", thursday_1045_ist) is True


class TestEIACalendarNextRelease:
    """Test next release time calculation."""

    def test_next_release_naturalgas(self):
        """Next NATURALGAS release is next Thursday 10:30 ET."""
        cal = EIACalendar(suppression_minutes=15)
        # Monday 3/16/2026
        monday = datetime(2026, 3, 16, 12, 0, tzinfo=_IST)
        next_release = cal.get_next_release("NATURALGAS", monday)
        assert next_release is not None
        # Should be Thursday 3/19/2026 10:30 ET = 21:00 IST
        assert next_release.weekday() == 3  # Thursday

    def test_next_release_crudeoil(self):
        """Next CRUDEOIL release is next Wednesday 10:30 ET."""
        cal = EIACalendar(suppression_minutes=15)
        monday = datetime(2026, 3, 16, 12, 0, tzinfo=_IST)
        next_release = cal.get_next_release("CRUDEOIL", monday)
        assert next_release is not None
        assert next_release.weekday() == 2  # Wednesday

    def test_next_release_unknown_symbol(self):
        """Unknown symbol returns None."""
        cal = EIACalendar(suppression_minutes=15)
        assert cal.get_next_release("GOLD") is None


class TestEIACalendarSuppressionWindow:
    """Test suppression window retrieval."""

    def test_get_suppression_window_when_active(self):
        """Get suppression window when currently in window."""
        cal = EIACalendar(suppression_minutes=15)
        thursday_1020_et = datetime(2026, 3, 19, 10, 20, tzinfo=_ET)
        thursday_1020_ist = thursday_1020_et.astimezone(_IST)
        window = cal.get_suppression_window("NATURALGAS", thursday_1020_ist)
        assert window is not None
        start, end = window
        assert start < thursday_1020_ist < end

    def test_get_suppression_window_when_not_active(self):
        """Returns None when not in suppression window."""
        cal = EIACalendar(suppression_minutes=15)
        thursday_1050_et = datetime(2026, 3, 19, 10, 50, tzinfo=_ET)
        thursday_1050_ist = thursday_1050_et.astimezone(_IST)
        window = cal.get_suppression_window("NATURALGAS", thursday_1050_ist)
        assert window is None