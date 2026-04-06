"""
Session manager — detect session boundaries, classify time periods.

Handles warmup, dead zone, active session, and outside session states.
"""

from datetime import datetime, time
from enum import Enum
from typing import Optional

from src.config.engine_config import CFG
from src.config.instruments import InstrumentConfig


class SessionState(str, Enum):
    """Session time classification."""

    OUTSIDE = "OUTSIDE"  # Outside trading hours
    WARMUP = "WARMUP"  # Initial warmup period
    ACTIVE = "ACTIVE"  # Active trading
    DEAD_ZONE = "DEAD_ZONE"  # Low activity period
    CLOSING = "CLOSING"  # Near session close


class SessionManager:
    """
    Manage session boundaries and time-based filters.

    Classifies each moment into a SessionState for gate filtering.
    """

    def __init__(self, instrument: InstrumentConfig):
        self._instrument = instrument
        self._session_open = time(instrument.open_hour, instrument.open_minute)
        self._session_close = time(instrument.close_hour, instrument.close_minute)
        self._warmup_minutes = (
            CFG.warm_up_minutes_mcx
            if instrument.exchange == "MCX"
            else CFG.warm_up_minutes_nse
        )
        self._session_start: Optional[datetime] = None

    def classify_time(self, timestamp: datetime) -> SessionState:
        """
        Classify a timestamp into a session state.

        Returns the appropriate SessionState for the given time.
        """
        current_time = timestamp.time()

        # Outside session hours
        if not self._is_within_session(current_time):
            return SessionState.OUTSIDE

        # Calculate minutes since session open
        if self._session_start is None:
            self._session_start = timestamp.replace(
                hour=self._session_open.hour,
                minute=self._session_open.minute,
                second=0,
                microsecond=0,
            )

        minutes_since_open = (timestamp - self._session_start).total_seconds() / 60

        # Warmup period
        if minutes_since_open < self._warmup_minutes:
            return SessionState.WARMUP

        # Dead zone (12:00 - 13:30 IST)
        if self._is_dead_zone(current_time):
            return SessionState.DEAD_ZONE

        # Closing period (last 15 minutes)
        minutes_until_close = self._minutes_until_close(current_time)
        if minutes_until_close <= 15:
            return SessionState.CLOSING

        # Active trading
        return SessionState.ACTIVE

    def _is_within_session(self, current_time: time) -> bool:
        """Check if current time is within session hours."""
        if self._session_open <= self._session_close:
            # Same day session (e.g., NSE: 09:15 - 15:30)
            return self._session_open <= current_time <= self._session_close
        else:
            # Overnight session (e.g., MCX: 09:00 - 23:30)
            return current_time >= self._session_open or current_time <= self._session_close

    def _is_dead_zone(self, current_time: time) -> bool:
        """Check if current time is in the dead zone."""
        dead_start = time(CFG.dead_zone_start_hour, CFG.dead_zone_start_minute)
        dead_end = time(CFG.dead_zone_end_hour, CFG.dead_zone_end_minute)
        return dead_start <= current_time <= dead_end

    def _minutes_until_close(self, current_time: time) -> float:
        """Calculate minutes until session close."""
        close_dt = datetime.combine(datetime.today(), self._session_close)
        current_dt = datetime.combine(datetime.today(), current_time)
        delta = close_dt - current_dt
        return delta.total_seconds() / 60

    def is_preferred_window(self, timestamp: datetime) -> bool:
        """
        Check if current time is in a preferred trading window.

        Preferred windows:
        - 09:30 - 11:30 IST
        - 14:00 - 15:30 IST
        """
        current_time = timestamp.time()

        # Window 1: 09:30 - 11:30
        w1_start = time(9, 30)
        w1_end = time(11, 30)
        if w1_start <= current_time <= w1_end:
            return True

        # Window 2: 14:00 - 15:30
        w2_start = time(14, 0)
        w2_end = time(15, 30)
        if w2_start <= current_time <= w2_end:
            return True

        return False

    def get_candle_count(self, timestamp: datetime) -> int:
        """
        Get the number of 5-minute candles since session open.

        Used for warmup gate and IB detection.
        """
        if self._session_start is None:
            return 0

        minutes_since_open = (timestamp - self._session_start).total_seconds() / 60
        return int(minutes_since_open // 5)

    def reset_session(self, timestamp: datetime) -> None:
        """Reset session state for a new session."""
        self._session_start = timestamp.replace(
            hour=self._session_open.hour,
            minute=self._session_open.minute,
            second=0,
            microsecond=0,
        )