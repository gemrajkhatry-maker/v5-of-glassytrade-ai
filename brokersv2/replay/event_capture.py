"""
Replay Infrastructure - Event Capture System.

Captures events to JSONL format for deterministic replay.
"""

import asyncio
import json
import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Dict, Optional, Set

logger = logging.getLogger(__name__)


@dataclass
class CaptureFilter:
    """Filter for event capture."""
    allowed_types: Optional[Set[str]] = None
    allowed_topics: Optional[Set[str]] = None
    
    def should_capture(self, event_type: str, topic: Optional[str] = None) -> bool:
        """Check if event should be captured."""
        if self.allowed_types and event_type not in self.allowed_types:
            return False
        if self.allowed_topics and topic and topic not in self.allowed_topics:
            return False
        return True


@dataclass
class CapturedEvent:
    """Captured event for replay."""
    sequence_id: int
    event_type: str
    timestamp: datetime
    payload: Dict[str, Any]
    source: str = "live"


class EventCapture:
    """Async event capture system with JSONL output and proper resource management."""
    
    def __init__(
        self,
        output_path: Optional[Path] = None,
        buffer_size: int = 100,
        max_file_size: int = 10 * 1024 * 1024,
        enable_rotation: bool = False,
        capture_filter: Optional[CaptureFilter] = None,
    ):
        self._output_path = output_path or Path("/tmp/events.jsonl")
        self._buffer_size = buffer_size
        self._max_file_size = max_file_size
        self._enable_rotation = enable_rotation
        self._filter = capture_filter
        
        self._sequence = 0
        self._buffer: list = []
        self._lock = asyncio.Lock()
        self._file_handle = None
        self._closed = False
        
        if not self._output_path.parent.exists():
            raise ValueError(f"Parent directory does not exist: {self._output_path.parent}")
    
    async def __aenter__(self):
        """Support async context manager."""
        return self
    
    async def __aexit__(self, exc_type, exc_val, exc_tb):
        """Ensure cleanup on exit."""
        await self.close()
    
    async def capture(self, event: Any, event_type: str, topic: Optional[str] = None) -> None:
        """Capture an event."""
        if self._filter and not self._filter.should_capture(event_type, topic):
            return
        
        async with self._lock:
            self._sequence += 1
            
            captured = CapturedEvent(
                sequence_id=self._sequence,
                event_type=event_type,
                timestamp=datetime.now(timezone.utc),
                payload=self._serialize_event(event),
                source="live",
            )
            
            self._buffer.append(captured)
            
            if len(self._buffer) >= self._buffer_size:
                await self._flush_locked()
    
    async def flush(self) -> None:
        """Flush buffer to disk."""
        async with self._lock:
            await self._flush_locked()
    
    async def _flush_locked(self) -> None:
        """Flush buffer (must be called with lock held) with proper error handling."""
        if not self._buffer or self._closed:
            return
        
        try:
            if self._file_handle is None:
                self._output_path.parent.mkdir(parents=True, exist_ok=True)
                self._file_handle = open(self._output_path, 'a')
            
            if self._enable_rotation:
                current_size = self._output_path.stat().st_size if self._output_path.exists() else 0
                if current_size >= self._max_file_size:
                    self._rotate_file()
            
            for event in self._buffer:
                line = json.dumps({
                    'sequence_id': event.sequence_id,
                    'event_type': event.event_type,
                    'timestamp': event.timestamp.isoformat(),
                    'payload': event.payload,
                    'source': event.source,
                })
                self._file_handle.write(line + '\n')
            
            self._file_handle.flush()
            self._buffer.clear()
            
        except Exception as e:
            logger.error(f"Failed to flush events: {e}")
            raise
    
    def _rotate_file(self) -> None:
        """Rotate current file with proper cleanup."""
        if self._file_handle:
            try:
                self._file_handle.close()
            except Exception as e:
                logger.warning(f"Error closing file during rotation: {e}")
            finally:
                self._file_handle = None
        
        timestamp = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
        rotated_path = self._output_path.with_name(
            f"{self._output_path.stem}_{timestamp}{self._output_path.suffix}"
        )
        self._output_path.rename(rotated_path)
    
    def _serialize_event(self, event: Any) -> Dict[str, Any]:
        """Serialize event to dict."""
        if isinstance(event, dict):
            return event
        if hasattr(event, '__dict__'):
            return {k: v for k, v in event.__dict__.items() if not k.startswith('_')}
        if hasattr(event, '_asdict'):
            return event._asdict()
        return {"value": str(event)}
    
    async def close(self) -> None:
        """Close capture and flush remaining events with proper resource cleanup."""
        if self._closed:
            return
        
        async with self._lock:
            self._closed = True
            try:
                await self._flush_locked()
            finally:
                if self._file_handle:
                    try:
                        self._file_handle.close()
                    except Exception as e:
                        logger.warning(f"Error closing file handle: {e}")
                    finally:
                        self._file_handle = None
    
    @property
    def sequence(self) -> int:
        """Get current sequence number."""
        return self._sequence
