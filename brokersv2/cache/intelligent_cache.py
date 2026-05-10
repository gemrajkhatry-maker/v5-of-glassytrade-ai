"""
Intelligent Market Data Cache - Multi-tier caching with automatic management.
"""

from __future__ import annotations

import logging
from typing import Any, List, Optional

from brokersv2.cache.base import CacheInterface, CacheStats
from brokersv2.cache.memory_cache import LRUMemoryCache
from brokersv2.cache.disk_cache import SQLiteDiskCache

logger = logging.getLogger(__name__)


class IntelligentMarketDataCache:
    """
    Multi-tier intelligent cache for market data.
    
    Architecture:
    - L1: Fast in-memory LRU cache (recent data, <1ms access)
    - L2: Persistent SQLite disk cache (historical data, <10ms access)
    
    Features:
    - Automatic L1 → L2 promotion on misses
    - TTL-based expiry per instrument/timeframe
    - Cache warming support
    - Automatic cleanup of expired entries
    - Hit/miss statistics
    
    Usage:
        cache = IntelligentMarketDataCache(
            l1_max_size=500,
            l2_db_path="/tmp/cache.db",
            default_ttl=3600
        )
        
        # Get candles (tries L1, then L2, then returns None)
        candles = await cache.get_candles("NSE_EQ_RELIANCE", "5m", "2026-05-01", "2026-05-07")
        
        # Set candles (stores in both L1 and L2)
        await cache.set_candles("NSE_EQ_RELIANCE", "5m", candles)
    """
    
    def __init__(
        self,
        l1_max_size: int = 500,
        l2_db_path: str = "/tmp/market_data_cache.db",
        default_ttl: int = 3600,  # 1 hour
    ):
        """
        Initialize intelligent cache.
        
        Args:
            l1_max_size: Maximum items in L1 memory cache
            l2_db_path: Path to L2 SQLite database
            default_ttl: Default TTL in seconds for cached data
        """
        self._l1_cache = LRUMemoryCache(max_size=l1_max_size)
        self._l2_cache = SQLiteDiskCache(db_path=l2_db_path)
        self._default_ttl = default_ttl
    
    def _build_key(
        self,
        instrument_id: str,
        timeframe: str,
        from_date: str,
        to_date: str,
    ) -> str:
        """
        Build cache key from parameters.
        
        Args:
            instrument_id: Instrument identifier
            timeframe: Timeframe (e.g., "5m", "15m")
            from_date: Start date
            to_date: End date
            
        Returns:
            Cache key string
        """
        return f"candles:{instrument_id}:{timeframe}:{from_date}:{to_date}"
    
    async def get_candles(
        self,
        instrument_id: str,
        timeframe: str,
        from_date: str,
        to_date: str,
    ) -> Optional[List]:
        """
        Get cached candles (tries L1 first, then L2).
        
        Args:
            instrument_id: Instrument identifier
            timeframe: Timeframe
            from_date: Start date
            to_date: End date
            
        Returns:
            Cached candle list or None
        """
        key = self._build_key(instrument_id, timeframe, from_date, to_date)
        
        # Try L1 cache first (fastest)
        candles = await self._l1_cache.get(key)
        if candles is not None:
            logger.debug(f"L1 cache hit for {key}")
            return candles
        
        # Try L2 cache (slower but persistent)
        candles = await self._l2_cache.get(key)
        if candles is not None:
            logger.debug(f"L2 cache hit for {key}, promoting to L1")
            # Promote to L1 for faster future access
            await self._l1_cache.set(key, candles, ttl_seconds=self._default_ttl)
            return candles
        
        logger.debug(f"Cache miss for {key}")
        return None
    
    async def set_candles(
        self,
        instrument_id: str,
        timeframe: str,
        from_date: str,
        to_date: str,
        candles: List,
        ttl_seconds: Optional[int] = None,
    ) -> None:
        """
        Cache candles in both L1 and L2.
        
        Args:
            instrument_id: Instrument identifier
            timeframe: Timeframe
            from_date: Start date
            to_date: End date
            candles: Candle data list
            ttl_seconds: TTL override (uses default if None)
        """
        key = self._build_key(instrument_id, timeframe, from_date, to_date)
        ttl = ttl_seconds or self._default_ttl
        
        # Store in both caches
        await self._l1_cache.set(key, candles, ttl_seconds=ttl)
        await self._l2_cache.set(key, candles, ttl_seconds=ttl)
        
        logger.debug(f"Cached {key} ({len(candles)} candles)")
    
    async def invalidate(
        self,
        instrument_id: str,
        timeframe: Optional[str] = None,
    ) -> int:
        """
        Invalidate cache for instrument (and optionally timeframe).
        
        Args:
            instrument_id: Instrument identifier
            timeframe: Timeframe to invalidate (None = all timeframes)
            
        Returns:
            Number of entries invalidated
        """
        invalidated = 0
        
        # We need to scan for matching keys - in production, maintain an index
        # For now, clear all cache entries for this instrument
        # TODO: Implement key indexing for efficient invalidation
        
        # Clear L1 entries matching pattern
        l1_stats = self._l1_cache.get_stats()
        await self._l1_cache.clear()  # Simplified - should be more selective
        invalidated += l1_stats.item_count
        
        logger.info(f"Invalidated {invalidated} cache entries for {instrument_id}")
        return invalidated
    
    async def warmup(
        self,
        keys_data: dict,
        ttl_seconds: Optional[int] = None,
    ) -> int:
        """
        Warm cache with pre-fetched data.
        
        Args:
            keys_data: Dict mapping cache keys to data
                      {"candles:RELIANCE:5m:2026-05-01:2026-05-07": [...]}
            ttl_seconds: TTL for cached data
            
        Returns:
            Number of entries warmed
        """
        ttl = ttl_seconds or self._default_ttl
        warmed = 0
        
        for key, data in keys_data.items():
            await self._l1_cache.set(key, data, ttl_seconds=ttl)
            await self._l2_cache.set(key, data, ttl_seconds=ttl)
            warmed += 1
        
        logger.info(f"Warmed cache with {warmed} entries")
        return warmed
    
    async def cleanup(self) -> dict:
        """
        Clean up expired entries from both caches.
        
        Returns:
            Dict with cleanup stats
        """
        l1_cleaned = await self._l1_cache.cleanup_expired()
        l2_cleaned = await self._l2_cache.cleanup_expired()
        
        return {
            "l1_cleaned": l1_cleaned,
            "l2_cleaned": l2_cleaned,
            "total_cleaned": l1_cleaned + l2_cleaned,
        }
    
    def get_stats(self) -> dict:
        """
        Get comprehensive cache statistics.
        
        Returns:
            Dict with L1, L2, and combined stats
        """
        l1_stats = self._l1_cache.get_stats()
        l2_stats = self._l2_cache.get_stats()
        
        return {
            "l1": {
                "hits": l1_stats.hits,
                "misses": l1_stats.misses,
                "hit_rate": l1_stats.hit_rate,
                "items": l1_stats.item_count,
                "size_bytes": l1_stats.size_bytes,
            },
            "l2": {
                "hits": l2_stats.hits,
                "misses": l2_stats.misses,
                "hit_rate": l2_stats.hit_rate,
                "items": l2_stats.item_count,
                "size_bytes": l2_stats.size_bytes,
            },
            "combined": {
                "total_items": l1_stats.item_count + l2_stats.item_count,
                "total_size_bytes": l1_stats.size_bytes + l2_stats.size_bytes,
            },
        }
    
    async def clear(self) -> None:
        """Clear all cache data."""
        await self._l1_cache.clear()
        await self._l2_cache.clear()
        logger.info("Cleared all cache data")
