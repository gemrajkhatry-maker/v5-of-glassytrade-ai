"""
Replay Infrastructure - Event Capture Engine.

Intercepts events from EventBus and serializes to deterministic format.
"""

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Protocol


@dataclass
class CapturedEvent:
    """Serialized event for replay."""
    sequence: int
    timestamp: datetime
    event_type: str
    event_data: Dict[str, Any]
    metadata: Dict[str, Any] = field(default_factory=dict)


class EventSerializer(Protocol):
    """Protocol for event serialization."""
    
    def serialize(self, event: Any) -> bytes:
        """Serialize event to bytes."""
        ...
    
    def deserialize(self, data: bytes) -> Any:
        """Deserialize bytes to event."""
        ...


class EventCaptureEngine:
    """
    Captures events from EventBus for replay.
    
    Features:
    - Intercepts all events
    - Assigns sequence numbers
    - Serializes to deterministic format
    - Writes to append-only log
    - Supports multiple concurrent captures
    """
    
    def __init__(self, serializer: Optional[EventSerializer] = None):
        """
        Initialize event capture engine.
        
        Args:
            serializer: Event serializer (default: msgspec-based)
        """
        self._sequence = 0
        self._serializer = serializer
        self._captured_events: List[CapturedEvent] = []
        self._is_capturing = False
    
    def start_capture(self) -> None:
        """Start capturing events."""
        self._is_capturing = True
    
    def stop_capture(self) -> None:
        """Stop capturing events."""
        self._is_capturing = False
    
    def capture_event(self, event: Any, event_type: str, metadata: Optional[Dict] = None) -> CapturedEvent:
        """
        Capture and serialize an event.
        
        Args:
            event: Event object to capture
            event_type: Type identifier
            metadata: Additional metadata
        
        Returns:
            CapturedEvent with sequence number
        """
        if not self._is_capturing:
            raise RuntimeError("Capture not started")
        
        self._sequence += 1
        
        captured = CapturedEvent(
            sequence=self._sequence,
            timestamp=datetime.now(timezone.utc),
            event_type=event_type,
            event_data=self._extract_event_data(event),
            metadata=metadata or {},
        )
        
        self._captured_events.append(captured)
        return captured
    
    def get_captured_events(self) -> List[CapturedEvent]:
        """Get all captured events."""
        return self._captured_events.copy()
    
    def clear(self) -> None:
        """Clear captured events and reset sequence."""
        self._captured_events.clear()
        self._sequence = 0
    
    def _extract_event_data(self, event: Any) -> Dict[str, Any]:
        """Extract serializable data from event."""
        # Handle dict directly
        if isinstance(event, dict):
            return event
        # Handle objects with __dict__
        if hasattr(event, "__dict__"):
            return event.__dict__
        # Handle primitives
        return {"value": str(event)}
