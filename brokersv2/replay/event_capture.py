"""Event Capture Engine - Capture and store events for replay."""

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


@dataclass(frozen=True)
class CapturedEvent:
    """Captured event with metadata."""
    sequence: int
    timestamp: datetime
    event_type: str
    event_data: dict
    metadata: Optional[dict] = None


class EventCaptureEngine:
    """
    Captures events for later replay.
    
    Features:
    - Sequence numbering
    - Start/stop capture lifecycle
    - Event data extraction from various types
    - Metadata attachment
    - State reset
    """
    
    def __init__(self):
        """Initialize event capture engine."""
        self._capturing = False
        self._sequence = 0
        self._events: List[CapturedEvent] = []
    
    def start_capture(self) -> None:
        """Start capturing events."""
        self._capturing = True
        logger.info("Event capture started")
    
    def stop_capture(self) -> None:
        """Stop capturing events."""
        self._capturing = False
        logger.info("Event capture stopped")
    
    def capture_event(
        self,
        event: Any,
        event_type: str,
        metadata: Optional[dict] = None,
    ) -> CapturedEvent:
        """
        Capture an event.
        
        Args:
            event: Event object (dict, object, or primitive)
            event_type: Type identifier for the event
            metadata: Optional metadata dict
            
        Returns:
            CapturedEvent with sequence number and timestamp
            
        Raises:
            RuntimeError: If capture not started
        """
        if not self._capturing:
            raise RuntimeError("Capture not started")
        
        # Extract event data
        event_data = self._extract_event_data(event)
        
        # Increment sequence
        self._sequence += 1
        
        # Create captured event
        captured = CapturedEvent(
            sequence=self._sequence,
            timestamp=datetime.now(timezone.utc),
            event_type=event_type,
            event_data=event_data,
            metadata=metadata,
        )
        
        # Store event
        self._events.append(captured)
        
        return captured
    
    def get_captured_events(self) -> List[CapturedEvent]:
        """
        Get all captured events.
        
        Returns:
            Copy of captured events list
        """
        return self._events.copy()
    
    def clear(self) -> None:
        """Clear all events and reset sequence."""
        self._events.clear()
        self._sequence = 0
        logger.info("Event capture cleared")
    
    def _extract_event_data(self, event: Any) -> dict:
        """
        Extract event data from various types.
        
        Args:
            event: Event object
            
        Returns:
            Dictionary of event data
        """
        # If dict, use directly
        if isinstance(event, dict):
            return event
        
        # If object with attributes, convert to dict
        if hasattr(event, '__dict__'):
            return event.__dict__.copy()
        
        # If primitive, wrap as value
        return {"value": str(event)}


# Aliases for backward compatibility
EventCapture = EventCaptureEngine


@dataclass
class CaptureFilter:
    """Filter for event capture."""
    event_types: Optional[List[str]] = None
    symbols: Optional[List[str]] = None
    start_time: Optional[datetime] = None
    end_time: Optional[datetime] = None
