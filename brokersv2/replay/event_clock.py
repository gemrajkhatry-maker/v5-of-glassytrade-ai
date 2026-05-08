"""
Replay Infrastructure - Event Clock Abstraction.

Provides deterministic time control for replay:
- LiveClock: Real-time clock for live trading
- ReplayClock: Simulated time with speed control
- Pause, resume, speed manipulation (0.5x, 1x, 2x, 10x)
"""

import time
from abc import ABC, abstractmethod
from datetime import datetime, timedelta, timezone
from enum import Enum
from typing import Optional


class ClockState(Enum):
    """Clock operational states."""
    STOPPED = "stopped"
    RUNNING = "running"
    PAUSED = "paused"


class EventClock(ABC):
    """Abstract base for event time control."""
    
    @abstractmethod
    def now(self) -> datetime:
        """Get current time."""
        ...
    
    @abstractmethod
    def sleep(self, seconds: float) -> None:
        """Sleep for specified duration (respects clock speed)."""
        ...
    
    @abstractmethod
    def state(self) -> ClockState:
        """Get current clock state."""
        ...


class LiveClock(EventClock):
    """
    Real-time clock for live trading.
    
    Uses system clock with nanosecond precision.
    """
    
    def now(self) -> datetime:
        """Get current UTC time."""
        return datetime.now(timezone.utc)
    
    def sleep(self, seconds: float) -> None:
        """Sleep for real duration."""
        time.sleep(seconds)
    
    def state(self) -> ClockState:
        """Live clock is always running."""
        return ClockState.RUNNING
    
    def __repr__(self) -> str:
        return "LiveClock()"


class ReplayClock(EventClock):
    """
    Simulated time clock for replay.
    
    Features:
    - Start from specific timestamp
    - Speed control (0.5x, 1x, 2x, 10x, etc.)
    - Pause/resume capability
    - Deterministic time progression
    
    Usage:
        clock = ReplayClock(start_time=datetime(2024, 1, 1, 9, 15, 0))
        clock.set_speed(2.0)  # 2x speed
        
        # Time progresses at 2x real-time
        clock.sleep(1.0)  # Advances simulated time by 2 seconds
    """
    
    def __init__(
        self,
        start_time: Optional[datetime] = None,
        speed: float = 1.0,
    ):
        """
        Initialize replay clock.
        
        Args:
            start_time: Starting timestamp (default: now)
            speed: Time multiplier (default: 1.0 = real-time)
        """
        self._start_time = start_time or datetime.now(timezone.utc)
        self._current_time = self._start_time
        self._speed = speed
        self._state = ClockState.STOPPED
        self._last_real_time: Optional[float] = None
    
    def now(self) -> datetime:
        """Get current simulated time."""
        if self._state == ClockState.RUNNING:
            # Calculate elapsed real time and apply speed
            real_now = time.time()
            if self._last_real_time is not None:
                elapsed = real_now - self._last_real_time
                self._current_time += timedelta(seconds=elapsed * self._speed)
            self._last_real_time = real_now
        
        return self._current_time
    
    def sleep(self, seconds: float) -> None:
        """
        Sleep in simulated time.
        
        Advances simulated time by `seconds * speed`.
        Real sleep duration is `seconds / speed`.
        
        Args:
            seconds: Simulated seconds to sleep
        """
        if self._state == ClockState.PAUSED:
            # Just advance time without real sleep
            self._current_time += timedelta(seconds=seconds)
            return
        
        if self._state == ClockState.RUNNING:
            # Sleep for adjusted real time
            real_sleep = seconds / self._speed if self._speed > 0 else seconds
            time.sleep(real_sleep)
            # Update current time
            self._current_time += timedelta(seconds=seconds)
    
    def set_speed(self, speed: float) -> None:
        """
        Set replay speed multiplier.
        
        Args:
            speed: Time multiplier (>0). Examples: 0.5, 1.0, 2.0, 10.0
        """
        if speed <= 0:
            raise ValueError(f"Speed must be > 0, got {speed}")
        self._speed = speed
    
    @property
    def speed(self) -> float:
        """Get current speed multiplier."""
        return self._speed
    
    def start(self) -> None:
        """Start the clock."""
        self._state = ClockState.RUNNING
        self._last_real_time = time.time()
    
    def pause(self) -> None:
        """Pause the clock."""
        self._state = ClockState.PAUSED
        self._last_real_time = None
    
    def resume(self) -> None:
        """Resume from paused state."""
        if self._state == ClockState.PAUSED:
            self._state = ClockState.RUNNING
            self._last_real_time = time.time()
    
    def stop(self) -> None:
        """Stop the clock."""
        self._state = ClockState.STOPPED
        self._last_real_time = None
    
    def reset(self, new_start_time: Optional[datetime] = None) -> None:
        """
        Reset clock to start time.
        
        Args:
            new_start_time: New start time (default: original start)
        """
        self._current_time = new_start_time or self._start_time
        self._state = ClockState.STOPPED
        self._last_real_time = None
    
    def state(self) -> ClockState:
        """Get current clock state."""
        return self._state
    
    def elapsed(self) -> timedelta:
        """Get elapsed simulated time from start."""
        return self._current_time - self._start_time
    
    def __repr__(self) -> str:
        return (
            f"ReplayClock(start={self._start_time}, "
            f"current={self._current_time}, "
            f"speed={self._speed}, "
            f"state={self._state.value})"
        )
