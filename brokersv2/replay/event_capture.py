"""Event Capture Engine - Capture and store events for replay."""

import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
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
    
    def __init__(
        self,
        output_path: Optional[Path] = None,
        buffer_size: int = 1000,
        **kwargs
    ):
        """Initialize event capture engine.
        
        Args:
            output_path: File path for event storage (JSONL format).
            buffer_size: Internal buffer size before auto-flush.
        """
        self._capturing = False
        self._sequence = 0
        self._events: List[CapturedEvent] = []
        self._output_path = output_path
        self._buffer_size = buffer_size
        
        # Set up file writer if output_path provided
        self._file_writer = None
        if output_path is not None:
            self._setup_file_writer(output_path)
        
        # Resource management
        self._closed = False
        self._file_handle = self._file_writer  # Alias for test compatibility
    
    def _setup_file_writer(self, path: Path) -> None:
        """Set up file-based event writer."""
        try:
            self._file_writer = open(path, 'a', encoding='utf-8')
        except OSError as exc:
            logger.error("EventCapture: cannot open %s: %s", path, exc)
    
    async def capture(self, event: Any, event_type: str, metadata: Optional[dict] = None) -> None:
        """Capture event to storage."""
        # Auto-start capture if not started
        if not self._capturing:
            self.start_capture()
        
        captured = self.capture_event(event, event_type, metadata)
        if self._file_writer is not None:
            # Convert CapturedEvent to dict
            event_dict = {
                'sequence': captured.sequence,
                'sequence_id': captured.sequence,
                'timestamp': captured.timestamp.isoformat(),
                'event_type': captured.event_type,
                'event_data': captured.event_data,
                'metadata': captured.metadata,
            }
            self._file_writer.write(json.dumps(event_dict) + '\n')
    
    async def flush(self) -> None:
        """Flush buffered events to file."""
        if self._closed:
            return  # Safe to call after close (idempotent)
        if self._file_writer is not None:
            self._file_writer.flush()
    
    async def close(self) -> None:
        """Close the capture and release resources."""
        if self._closed:
            return  # Idempotent
        
        self._closed = True
        self.stop_capture()
        
        try:
            await self.flush()
        except RuntimeError:
            pass  # Already closed
        
        if self._file_writer is not None:
            try:
                self._file_writer.close()
            except Exception:
                pass
            self._file_writer = None
            self._file_handle = None
    
    def __del__(self) -> None:
        """Close file writer on deletion."""
        if self._file_writer is not None:
            try:
                self._file_writer.close()
            except Exception:
                pass
    
    # Context manager protocol
    def __enter__(self):
        """Enter context manager - start capture."""
        self.start_capture()
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        """Exit context manager - stop capture and flush."""
        try:
            self.flush()
        except Exception:
            pass  # Suppress flush errors on exit
        finally:
            self.stop_capture()
            self._closed = True
            # Close file handle
            if self._file_writer is not None:
                try:
                    self._file_writer.close()
                except Exception:
                    pass
                self._file_writer = None
                self._file_handle = None
        return False  # Don't suppress exceptions
    
    # Async context manager protocol
    async def __aenter__(self):
        """Async enter context manager."""
        self.start_capture()
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Async exit context manager."""
        try:
            await self.flush()
        except Exception:
            pass
        finally:
            self.stop_capture()
            self._closed = True
            # Close file handle
            if self._file_writer is not None:
                try:
                    self._file_writer.close()
                except Exception:
                    pass
                self._file_writer = None
                self._file_handle = None
        return False
    
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


class CaptureFilter:
    """Filter for event capture."""
    
    def __init__(
        self,
        allowed_types: Optional[List[str]] = None,  # Backward compat
        event_types: Optional[List[str]] = None,
        symbols: Optional[List[str]] = None,
        start_time: Optional[datetime] = None,
        end_time: Optional[datetime] = None,
        **kwargs  # Forward compat
    ):
        """Initialize capture filter.
        
        Args:
            allowed_types: Deprecated. Use event_types instead.
        """
        if allowed_types is not None:
            warnings.warn(
                "allowed_types parameter is deprecated. "
                "Use event_types instead.",
                DeprecationWarning,
                stacklevel=2,
            )
            # Use allowed_types if event_types not provided
            self.event_types = event_types if event_types is not None else allowed_types
        else:
            self.event_types = event_types
        
        self.symbols = symbols
        self.start_time = start_time
        self.end_time = end_time
