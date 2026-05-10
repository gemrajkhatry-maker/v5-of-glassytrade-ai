"""
LRU Memory Cache - Fast in-memory cache with LRU eviction.
"""

from __future__ import annotations

import time
from collections import OrderedDict
from dataclasses import dataclass, field
from typing import Any, Optional

from brokersv2.cache.base import CacheInterface, CacheStats


@dataclass
class CacheEntry:
    """Single cache entry with metadata."""
    value: Any
    created_at: float
    expires_at: Optional[float] = None
    last_accessed: float = field(default_factory=time.time)
    access_count: int = 0
    
    @property
    def is_expired(self) -> bool:
        """Check if entry has expired."""
        if self.expires_at is None:
            return False
        return time.time() > self.expires_at
    
    def touch(self):
        """Update access timestamp and count."""
        self.last_accessed = time.time()
        self.access_count += 1


class LRUMemoryCache(CacheInterface):
    """
    LRU (Least Recently Used) in-memory cache.
    
    Features:
    - O(1) get/set operations using OrderedDict
    - Automatic eviction of least recently used items
    - TTL-based expiry
    - Configurable max size
    - Thread-safe (single-threaded async context)
    
    Usage:
        cache = LRUMemoryCache(max_size=1000)
        await cache.set("key", value, ttl_seconds=300)
        value = await cache.get("key")
    """
    
    def __init__(self, max_size: int = 1000):
        """
        Initialize LRU cache.
        
        Args:
            max_size: Maximum number of items to cache
        """
        self._cache: OrderedDict[str, CacheEntry] = OrderedDict()
        self._max_size = max_size
        self._stats = CacheStats()
    
    async def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache (moves to end for LRU tracking).
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found/expired
        """
        if key not in self._cache:
            self._stats.record_miss()
            return None
        
        entry = self._cache[key]
        
        # Check expiry
        if entry.is_expired:
            del self._cache[key]
            self._stats.record_miss()
            return None
        
        # Move to end (most recently used)
        self._cache.move_to_end(key)
        entry.touch()
        
        self._stats.record_hit()
        return entry.value
    
    async def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        """
        Set value in cache (updates LRU order).
        
        Args:
            key: Cache key
            value: Value to cache
            ttl_seconds: Time-to-live in seconds (optional)
        """
        # If key exists, update it
        if key in self._cache:
            self._cache.move_to_end(key)
            expires_at = time.time() + ttl_seconds if ttl_seconds else None
            self._cache[key] = CacheEntry(
                value=value,
                created_at=time.time(),
                expires_at=expires_at,
            )
            return
        
        # Evict if at capacity
        if len(self._cache) >= self._max_size:
            self._evict_lru()
        
        # Add new entry
        expires_at = time.time() + ttl_seconds if ttl_seconds else None
        self._cache[key] = CacheEntry(
            value=value,
            created_at=time.time(),
            expires_at=expires_at,
        )
    
    async def delete(self, key: str) -> bool:
        """
        Delete value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            True if key was deleted, False if not found
        """
        if key in self._cache:
            del self._cache[key]
            return True
        return False
    
    async def clear(self) -> None:
        """Clear all cached data."""
        self._cache.clear()
        self._stats.reset()
    
    def get_stats(self) -> CacheStats:
        """
        Get cache statistics.
        
        Returns:
            CacheStats with current metrics
        """
        self._stats.item_count = len(self._cache)
        self._stats.size_bytes = self._calculate_size()
        return self._stats
    
    def __len__(self) -> int:
        """Return number of items in cache."""
        return len(self._cache)
    
    def _evict_lru(self) -> None:
        """Evict least recently used item."""
        if self._cache:
            # popitem(last=False) removes first item (least recently used)
            self._cache.popitem(last=False)
            self._stats.record_eviction()
    
    def _calculate_size(self) -> int:
        """Estimate cache size in bytes (rough approximation)."""
        size = 0
        for entry in self._cache.values():
            # Rough estimate: 100 bytes per entry + value size
            size += 100
            if hasattr(entry.value, '__sizeof__'):
                size += entry.value.__sizeof__()
            elif isinstance(entry.value, (list, tuple)):
                size += len(entry.value) * 100  # Estimate per item
        return size
    
    async def cleanup_expired(self) -> int:
        """
        Remove all expired entries.
        
        Returns:
            Number of entries removed
        """
        expired_keys = [
            key for key, entry in self._cache.items()
            if entry.is_expired
        ]
        
        for key in expired_keys:
            del self._cache[key]
        
        return len(expired_keys)
