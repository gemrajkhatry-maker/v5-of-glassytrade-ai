"""
Replay Infrastructure - Replay Engine.

Loads captured events and replays with timing control.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from brokersv2.replay.event_clock import ReplayClock, ClockState

logger = logging.getLogger(__name__)


@dataclass
class ReplayProgress:
    """Replay progress tracking."""
    total_events: int = 0
    replayed_events: int = 0
    current_sequence: int = 0
    
    @property
    def percentage(self) -> float:
        """Get progress percentage."""
        if self.total_events == 0:
            return 0.0
        return (self.replayed_events / self.total_events) * 100.0


class ReplayEngine:
    """Replay engine for captured events."""
    
    def __init__(
        self,
        event_path: Optional[Path] = None,
        clock: Optional[ReplayClock] = None,
    ):
        self._event_path = event_path
        self._clock = clock or ReplayClock()
        self._events: List[Dict[str, Any]] = []
        self._event_handlers: List[Callable] = []
        self._progress = ReplayProgress()
        self._state = "idle"
        self._stop_event = asyncio.Event()
        self._pause_event = asyncio.Event()
        self._pause_event.set()
    
    async def load(self) -> None:
        """Load events from JSONL file."""
        if not self._event_path or not self._event_path.exists():
            self._events = []
            return
        
        self._events = []
        with open(self._event_path, 'r') as f:
            for line in f:
                line = line.strip()
                if line:
                    event = json.loads(line)
                    self._events.append(event)
        
        self._events.sort(key=lambda e: e.get('sequence_id', 0))
        self._progress.total_events = len(self._events)
        self._progress.replayed_events = 0
    
    def on_event(self, handler: Callable[[Dict[str, Any]], None]) -> None:
        """Register event handler."""
        self._event_handlers.append(handler)
    
    async def replay(self, speed: float = 1.0) -> None:
        """Replay all events."""
        if not self._events:
            return
        
        self._state = "running"
        self._stop_event.clear()
        self._pause_event.set()
        self._clock.start()
        self._clock.set_speed(speed)
        
        try:
            for event in self._events:
                # Check for stop BEFORE processing each event
                if self._stop_event.is_set():
                    break
                
                await self._pause_event.wait()
                
                # Check again after pause wait
                if self._stop_event.is_set():
                    break
                
                for handler in self._event_handlers:
                    result = handler(event)
                    # Support async handlers
                    if asyncio.iscoroutine(result):
                        await result
                
                self._progress.replayed_events += 1
                self._progress.current_sequence = event.get('sequence_id', 0)
                
                await asyncio.sleep(0.001 / speed)
        finally:
            self._clock.stop()
            self._state = "complete" if not self._stop_event.is_set() else "stopped"
    
    async def pause(self) -> None:
        """Pause replay."""
        self._state = "paused"
        self._pause_event.clear()
        self._clock.pause()
    
    async def resume(self) -> None:
        """Resume replay."""
        self._state = "running"
        self._pause_event.set()
        self._clock.resume()
    
    async def stop(self) -> None:
        """Stop replay."""
        self._state = "stopping"
        self._stop_event.set()
        self._clock.stop()
    
    @property
    def events(self) -> List[Dict[str, Any]]:
        """Get loaded events."""
        return self._events
    
    @property
    def state(self) -> str:
        """Get current state."""
        return self._state
    
    @property
    def progress(self) -> ReplayProgress:
        """Get replay progress."""
        return self._progress
