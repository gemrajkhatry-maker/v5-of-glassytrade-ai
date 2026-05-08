"""
Replay Infrastructure - Replay Scheduler.

Dispatches events from EventStore with deterministic timing control.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Callable, Optional

from brokersv2.replay.event_clock import EventClock, ReplayClock
from brokersv2.replay.event_store import EventRecord, EventStore


class ReplayState(Enum):
    """Replay operational states."""
    IDLE = "idle"
    RUNNING = "running"
    PAUSED = "paused"
    STOPPED = "stopped"
    COMPLETE = "complete"


class ReplayScheduler:
    """
    Schedules and dispatches events from EventStore.
    
    Features:
    - Deterministic event replay
    - Speed control (0.5x, 1x, 2x, 10x)
    - Pause/resume during replay
    - Replay from specific sequence
    - Gap handling (skips missing sequences)
    - Completion detection
    
    Usage:
        scheduler = ReplayScheduler(clock=clock, store=store)
        scheduler.set_handler(lambda event: process_event(event))
        scheduler.start()
        
        while scheduler.replay_next():
            pass  # Replay continues automatically
        
        # Or replay all at once
        scheduler.replay_all()
    """
    
    def __init__(
        self,
        clock: EventClock,
        store: EventStore,
    ):
        """
        Initialize replay scheduler.
        
        Args:
            clock: Event clock for timing control
            store: Event store to replay from
        """
        self._clock = clock
        self._store = store
        self._handler: Optional[Callable[[EventRecord], None]] = None
        self._current_sequence = 0
        self._state = ReplayState.IDLE
        self._events_replayed = 0
    
    def set_handler(self, handler: Callable[[EventRecord], None]) -> None:
        """
        Set event handler for replayed events.
        
        Args:
            handler: Callable that receives EventRecord
        """
        self._handler = handler
    
    def start(self) -> None:
        """Start replay from beginning."""
        self._state = ReplayState.RUNNING
        self._current_sequence = 0
        self._events_replayed = 0
        self._clock.start()
    
    def start_from_sequence(self, sequence: int) -> None:
        """
        Start replay from specific sequence.
        
        Args:
            sequence: Sequence number to start from (1-based)
        """
        if sequence <= 0:
            raise ValueError(f"Sequence must be positive, got {sequence}")
        if sequence > self._store.get_latest_sequence():
            raise ValueError(
                f"Sequence {sequence} is beyond store "
                f"(latest: {self._store.get_latest_sequence()})"
            )
        
        self._state = ReplayState.RUNNING
        self._current_sequence = sequence - 1  # Will increment to sequence
        self._events_replayed = 0
        self._clock.start()
    
    def pause(self) -> None:
        """Pause replay."""
        if self._state == ReplayState.RUNNING:
            self._state = ReplayState.PAUSED
            self._clock.pause()
    
    def resume(self) -> None:
        """Resume replay from paused state."""
        if self._state == ReplayState.PAUSED:
            self._state = ReplayState.RUNNING
            self._clock.resume()
    
    def stop(self) -> None:
        """Stop replay and reset to IDLE."""
        self._state = ReplayState.IDLE
        self._current_sequence = 0
        self._events_replayed = 0
        self._clock.stop()
    
    def reset(self) -> None:
        """Reset replay to initial state."""
        self.stop()
        self._clock.reset()
    
    def replay_next(self) -> bool:
        """
        Replay next event.
        
        Returns:
            True if event was dispatched, False if no more events
        """
        if self._state == ReplayState.IDLE:
            return False
        
        if self._state == ReplayState.PAUSED:
            return False  # Don't dispatch when paused
        
        if self._handler is None:
            raise RuntimeError("No handler set. Call set_handler() first")
        
        # Find next event
        next_seq = self._current_sequence + 1
        event = self._store.get_event(next_seq)
        
        if event is None:
            # Check if we've reached the end
            if next_seq > self._store.get_latest_sequence():
                self._state = ReplayState.COMPLETE
                return False
            # Gap in sequence, skip
            self._current_sequence = next_seq
            return self.replay_next()  # Recursive to find next valid
        
        # Dispatch event
        try:
            self._handler(event)
            self._current_sequence = next_seq
            self._events_replayed += 1
            
            # Advance clock
            if self._state == ReplayState.RUNNING:
                self._clock.sleep(0.001)  # Small delay between events
            
            return True
        except Exception:
            # Handler exception - continue replay
            self._current_sequence = next_seq
            self._events_replayed += 1
            return True
    
    def replay_all(self) -> int:
        """
        Replay all remaining events.
        
        Returns:
            Number of events replayed
        """
        count = 0
        while self.replay_next():
            count += 1
        return count
    
    def set_speed(self, speed: float) -> None:
        """
        Set replay speed.
        
        Args:
            speed: Speed multiplier (>0)
        """
        if isinstance(self._clock, ReplayClock):
            self._clock.set_speed(speed)
    
    @property
    def state(self) -> ReplayState:
        """Get current replay state."""
        return self._state
    
    @property
    def events_replayed(self) -> int:
        """Get number of events replayed."""
        return self._events_replayed
    
    @property
    def current_sequence(self) -> int:
        """Get current sequence position."""
        return self._current_sequence
    
    def progress(self) -> float:
        """
        Get replay progress as percentage.
        
        Returns:
            Progress from 0.0 to 1.0
        """
        total = self._store.get_latest_sequence()
        if total == 0:
            return 0.0
        return min(self._current_sequence / total, 1.0)
    
    def __repr__(self) -> str:
        return (
            f"ReplayScheduler(state={self._state.value}, "
            f"replayed={self._events_replayed}, "
            f"sequence={self._current_sequence}, "
            f"progress={self.progress():.1%})"
        )
