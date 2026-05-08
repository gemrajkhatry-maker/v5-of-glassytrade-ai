"""
Sequence Validator for market data streams.

Validates message sequencing:
- Detect missing/duplicate/out-of-order messages
- Track sequence numbers per stream
- Handle sequence resets
- Generate sequence statistics
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)


class SequenceError:
    """Represents a sequence validation error."""
    
    def __init__(
        self,
        error_type: str,
        expected: int,
        received: int,
        timestamp: datetime,
        message: str = "",
    ):
        self.error_type = error_type  # "gap", "duplicate", "out_of_order", "reset"
        self.expected = expected
        self.received = received
        self.timestamp = timestamp
        self.message = message
    
    def __repr__(self) -> str:
        return (
            f"SequenceError(type={self.error_type}, "
            f"expected={self.expected}, received={self.received})"
        )


@dataclass
class StreamState:
    """State of a message stream."""
    
    stream_id: str
    last_sequence: int = 0
    messages_received: int = 0
    errors_detected: int = 0
    last_valid_time: Optional[datetime] = None
    is_active: bool = True
    
    # Tracking
    recent_sequences: List[int] = field(default_factory=list)
    max_recent_size: int = 1000
    
    def add_sequence(self, seq: int) -> Optional[SequenceError]:
        """
        Validate and record sequence number.
        
        Returns:
            SequenceError if validation fails, None if valid
        """
        self.messages_received += 1
        self.last_valid_time = datetime.now(timezone.utc)
        
        error = None
        
        if self.last_sequence == 0:
            # First message
            if seq != 1:
                error = SequenceError(
                    error_type="initial_gap",
                    expected=1,
                    received=seq,
                    timestamp=self.last_valid_time,
                    message=f"First message should be sequence 1, got {seq}",
                )
        elif seq == self.last_sequence:
            # Duplicate
            error = SequenceError(
                error_type="duplicate",
                expected=self.last_sequence + 1,
                received=seq,
                timestamp=self.last_valid_time,
                message=f"Duplicate sequence {seq}",
            )
        elif seq < self.last_sequence:
            # Out of order
            error = SequenceError(
                error_type="out_of_order",
                expected=self.last_sequence + 1,
                received=seq,
                timestamp=self.last_valid_time,
                message=f"Out of order: expected >= {self.last_sequence + 1}, got {seq}",
            )
        elif seq > self.last_sequence + 1:
            # Gap
            gap_size = seq - self.last_sequence - 1
            error = SequenceError(
                error_type="gap",
                expected=self.last_sequence + 1,
                received=seq,
                timestamp=self.last_valid_time,
                message=f"Gap of {gap_size} messages: expected {self.last_sequence + 1}, got {seq}",
            )
        
        if error:
            self.errors_detected += 1
            # For initial_gap, still update last_sequence since we got our first message
            if error.error_type == "initial_gap":
                self.last_sequence = seq
        else:
            self.last_sequence = seq
        
        # Track recent sequences
        self.recent_sequences.append(seq)
        if len(self.recent_sequences) > self.max_recent_size:
            self.recent_sequences = self.recent_sequences[-self.max_recent_size:]
        
        return error
    
    def reset(self, new_sequence: int = 0) -> None:
        """Reset stream state."""
        self.last_sequence = new_sequence
        self.recent_sequences.clear()
        logger.info(f"Stream {self.stream_id} reset to sequence {new_sequence}")
    
    def get_stats(self) -> Dict:
        """Get stream statistics."""
        return {
            "stream_id": self.stream_id,
            "last_sequence": self.last_sequence,
            "messages_received": self.messages_received,
            "errors_detected": self.errors_detected,
            "error_rate": (
                round(self.errors_detected / self.messages_received * 100, 2)
                if self.messages_received > 0
                else 0.0
            ),
            "is_active": self.is_active,
        }


class SequenceValidator:
    """
    Validates sequence numbers for multiple message streams.
    
    Features:
    - Per-stream sequence tracking
    - Gap, duplicate, and out-of-order detection
    - Sequence reset handling
    - Statistics and monitoring
    
    Usage:
        validator = SequenceValidator()
        
        # Validate message
        error = validator.validate("stream_1", sequence_number=5)
        if error:
            logger.error(f"Sequence error: {error}")
        
        # Reset stream (e.g., after reconnect)
        validator.reset_stream("stream_1")
    """
    
    def __init__(self, auto_cleanup: bool = True, inactive_threshold: int = 300):
        """
        Initialize validator.
        
        Args:
            auto_cleanup: Automatically cleanup inactive streams
            inactive_threshold: Seconds before stream considered inactive
        """
        self._streams: Dict[str, StreamState] = {}
        self._auto_cleanup = auto_cleanup
        self._inactive_threshold = inactive_threshold
        self._total_validated = 0
        self._total_errors = 0
    
    def validate(self, stream_id: str, sequence: int) -> Optional[SequenceError]:
        """
        Validate sequence number for a stream.
        
        Args:
            stream_id: Stream identifier
            sequence: Sequence number to validate
            
        Returns:
            SequenceError if validation fails, None if valid
        """
        self._total_validated += 1
        
        # Get or create stream state
        if stream_id not in self._streams:
            self._streams[stream_id] = StreamState(stream_id=stream_id)
        
        stream = self._streams[stream_id]
        stream.is_active = True
        
        # Validate sequence
        error = stream.add_sequence(sequence)
        
        if error:
            self._total_errors += 1
            logger.warning(
                f"Sequence error on {stream_id}: {error.message}"
            )
        
        return error
    
    def validate_batch(
        self,
        stream_id: str,
        sequences: List[int],
    ) -> List[SequenceError]:
        """
        Validate batch of sequence numbers.
        
        Args:
            stream_id: Stream identifier
            sequences: List of sequence numbers in order
            
        Returns:
            List of sequence errors (empty if all valid)
        """
        errors = []
        for seq in sequences:
            error = self.validate(stream_id, seq)
            if error:
                errors.append(error)
        
        return errors
    
    def reset_stream(self, stream_id: str, new_sequence: int = 0) -> None:
        """
        Reset stream state (e.g., after reconnect).
        
        Args:
            stream_id: Stream identifier
            new_sequence: New starting sequence (default 0)
        """
        if stream_id in self._streams:
            self._streams[stream_id].reset(new_sequence)
        else:
            # Create new stream with reset state
            self._streams[stream_id] = StreamState(
                stream_id=stream_id,
                last_sequence=new_sequence,
            )
            logger.info(f"Created reset stream {stream_id} at sequence {new_sequence}")
    
    def deactivate_stream(self, stream_id: str) -> None:
        """Mark stream as inactive."""
        if stream_id in self._streams:
            self._streams[stream_id].is_active = False
    
    def get_stream_state(self, stream_id: str) -> Optional[StreamState]:
        """Get state for a stream."""
        return self._streams.get(stream_id)
    
    def get_active_streams(self) -> List[str]:
        """Get list of active streams."""
        return [
            stream_id
            for stream_id, state in self._streams.items()
            if state.is_active
        ]
    
    def cleanup_inactive(self) -> int:
        """
        Remove inactive streams.
        
        Returns:
            Number of streams removed
        """
        if not self._auto_cleanup:
            return 0
        
        now = datetime.now(timezone.utc)
        inactive_streams = []
        
        for stream_id, state in self._streams.items():
            if not state.is_active:
                inactive_streams.append(stream_id)
            elif state.last_valid_time:
                age = (now - state.last_valid_time).total_seconds()
                if age > self._inactive_threshold:
                    inactive_streams.append(stream_id)
        
        for stream_id in inactive_streams:
            del self._streams[stream_id]
        
        if inactive_streams:
            logger.info(f"Cleaned up {len(inactive_streams)} inactive streams")
        
        return len(inactive_streams)
    
    def get_validation_stats(self) -> Dict:
        """Get overall validation statistics."""
        active_count = len(self.get_active_streams())
        total_messages = sum(s.messages_received for s in self._streams.values())
        total_errors = sum(s.errors_detected for s in self._streams.values())
        
        return {
            "total_streams": len(self._streams),
            "active_streams": active_count,
            "total_validated": self._total_validated,
            "total_errors": self._total_errors,
            "overall_error_rate": (
                round(total_errors / total_messages * 100, 2)
                if total_messages > 0
                else 0.0
            ),
            "streams": {
                stream_id: state.get_stats()
                for stream_id, state in self._streams.items()
            },
        }
    
    def reset_all(self) -> None:
        """Reset all streams and statistics."""
        self._streams.clear()
        self._total_validated = 0
        self._total_errors = 0
        logger.info("Sequence validator reset")
