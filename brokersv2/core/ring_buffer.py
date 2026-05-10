"""
Ring Buffer - High-performance circular buffer for tick streaming.

Replaces asyncio.Queue for:
- Zero allocation after initialization
- O(1) enqueue/dequeue
- Bounded memory usage
- Lock-free operations (single producer/consumer)
"""

from __future__ import annotations

from typing import Any, List, Optional

from brokersv2.core.constants import RingBuffer as RingBufferConstants


class RingBuffer:
    """
    High-performance circular buffer.
    
    Features:
    - Fixed capacity with automatic drop on overflow
    - O(1) put and get operations
    - Thread-safe for single producer/single consumer
    - Drop rate tracking
    
    Usage:
        buffer = RingBuffer(capacity=10000)
        buffer.put(tick)
        tick = buffer.get()
    """
    
    def __init__(self, capacity: int = None):
        """
        Initialize ring buffer.
        
        Args:
            capacity: Maximum number of items
        """
        self._capacity = capacity or RingBufferConstants.DEFAULT_CAPACITY
        if self._capacity <= 0:
            raise ValueError("Capacity must be positive")
        
        self._buffer: List[Optional[Any]] = [None] * self._capacity
        self._read_idx = 0
        self._write_idx = 0
        self._count = 0
        self._dropped = 0
    
    def put(self, item: Any) -> bool:
        """
        Add item to buffer.
        
        Args:
            item: Item to add
            
        Returns:
            True if successful, False if buffer full (item dropped)
        """
        if self._count >= self._capacity:
            self._dropped += 1
            return False
        
        self._buffer[self._write_idx] = item
        self._write_idx = (self._write_idx + 1) % self._capacity
        self._count += 1
        
        return True
    
    def get(self) -> Optional[Any]:
        """
        Get next item from buffer.
        
        Returns:
            Item or None if buffer empty
        """
        if self._count == 0:
            return None
        
        item = self._buffer[self._read_idx]
        self._buffer[self._read_idx] = None  # Clear reference for GC
        self._read_idx = (self._read_idx + 1) % self._capacity
        self._count -= 1
        
        return item
    
    def peek(self) -> Optional[Any]:
        """
        Peek at next item without removing it.
        
        Returns:
            Next item or None if buffer empty
        """
        if self._count == 0:
            return None
        
        return self._buffer[self._read_idx]
    
    def clear(self):
        """Clear all items from buffer."""
        self._buffer = [None] * self._capacity
        self._read_idx = 0
        self._write_idx = 0
        self._count = 0
    
    @property
    def capacity(self) -> int:
        """Get buffer capacity."""
        return self._capacity
    
    @property
    def size(self) -> int:
        """Get current number of items."""
        return self._count
    
    @property
    def is_empty(self) -> bool:
        """Check if buffer is empty."""
        return self._count == 0
    
    @property
    def is_full(self) -> bool:
        """Check if buffer is full."""
        return self._count >= self._capacity
    
    @property
    def dropped_count(self) -> int:
        """Get total number of dropped items."""
        return self._dropped
    
    @property
    def drop_rate(self) -> float:
        """
        Get drop rate (dropped / total attempted).
        
        Returns:
            Drop rate between 0.0 and 1.0
        """
        total = self._count + self._dropped
        return self._dropped / total if total > 0 else 0.0
    
    def __len__(self) -> int:
        """Return number of items in buffer."""
        return self._count
    
    def __repr__(self) -> str:
        return (
            f"RingBuffer(capacity={self._capacity}, size={self._count}, "
            f"dropped={self._dropped}, drop_rate={self.drop_rate:.2%})"
        )
