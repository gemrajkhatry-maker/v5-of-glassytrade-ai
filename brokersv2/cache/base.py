"""
Cache Interface - Abstract base for all cache implementations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Optional


@dataclass
class CacheStats:
    """Cache performance statistics."""
    hits: int = 0
    misses: int = 0
    evictions: int = 0
    size_bytes: int = 0
    item_count: int = 0
    last_cleared: Optional[datetime] = None
    
    @property
    def hit_rate(self) -> float:
        """Calculate cache hit rate (0.0 to 1.0)."""
        total = self.hits + self.misses
        return self.hits / total if total > 0 else 0.0
    
    def record_hit(self):
        """Record a cache hit."""
        self.hits += 1
    
    def record_miss(self):
        """Record a cache miss."""
        self.misses += 1
    
    def record_eviction(self):
        """Record a cache eviction."""
        self.evictions += 1
    
    def reset(self):
        """Reset all statistics."""
        self.hits = 0
        self.misses = 0
        self.evictions = 0
        self.last_cleared = datetime.now()
    
    def __repr__(self) -> str:
        return (
            f"CacheStats(hits={self.hits}, misses={self.misses}, "
            f"hit_rate={self.hit_rate:.2%}, items={self.item_count})"
        )


class CacheInterface(ABC):
    """
    Abstract cache interface.
    
    All cache implementations must provide:
    - Get/set/delete operations
    - TTL support
    - Statistics tracking
    """
    
    @abstractmethod
    async def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found/expired
        """
        pass
    
    @abstractmethod
    async def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        """
        Set value in cache.
        
        Args:
            key: Cache key
            value: Value to cache
            ttl_seconds: Time-to-live in seconds (optional)
        """
        pass
    
    @abstractmethod
    async def delete(self, key: str) -> bool:
        """
        Delete value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            True if key was deleted, False if not found
        """
        pass
    
    @abstractmethod
    async def clear(self) -> None:
        """Clear all cached data."""
        pass
    
    @abstractmethod
    def get_stats(self) -> CacheStats:
        """
        Get cache statistics.
        
        Returns:
            CacheStats object with hit/miss/eviction counts
        """
        pass
    
    @abstractmethod
    def __len__(self) -> int:
        """Return number of items in cache."""
        pass
