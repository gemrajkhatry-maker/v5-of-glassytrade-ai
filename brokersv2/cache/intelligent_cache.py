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
        self._key_index: dict[str, set[str]] = {}  # instrument_id -> set of cache keys
    
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
        self._add_to_index(key)

        logger.debug(f"Cached {key} ({len(candles)} candles)")
    
    def _extract_instrument_id(self, key: str) -> str:
        """Extract instrument_id from a cache key.

        Key format: candles:{instrument_id}:{timeframe}:{from_date}:{to_date}
        """
        parts = key.split(":")
        if len(parts) >= 3 and parts[0] == "candles":
            return parts[1]
        return ""

    def _add_to_index(self, key: str) -> None:
        """Add a cache key to the inverted index."""
        instrument_id = self._extract_instrument_id(key)
        if instrument_id:
            self._key_index.setdefault(instrument_id, set()).add(key)

    def _remove_from_index(self, key: str) -> None:
        """Remove a cache key from the inverted index."""
        instrument_id = self._extract_instrument_id(key)
        if instrument_id and instrument_id in self._key_index:
            self._key_index[instrument_id].discard(key)
            if not self._key_index[instrument_id]:
                del self._key_index[instrument_id]

    def _get_keys_for_instrument(
        self, instrument_id: str, timeframe: Optional[str] = None
    ) -> list[str]:
        """Get all cache keys for an instrument, optionally filtered by timeframe."""
        keys = self._key_index.get(instrument_id, set()).copy()
        if timeframe is not None:
            prefix = f"candles:{instrument_id}:{timeframe}:"
            keys = {k for k in keys if k.startswith(prefix)}
        return list(keys)

    async def invalidate(
        self,
        instrument_id: str,
        timeframe: Optional[str] = None,
    ) -> int:
        """
        Invalidate cache for instrument (and optionally timeframe).

        Uses the inverted key index for efficient selective invalidation.

        Args:
            instrument_id: Instrument identifier
            timeframe: Timeframe to invalidate (None = all timeframes)

        Returns:
            Number of entries invalidated
        """
        invalidated = 0
        keys_to_remove = self._get_keys_for_instrument(instrument_id, timeframe)

        for key in keys_to_remove:
            deleted_l1 = await self._l1_cache.delete(key)
            deleted_l2 = await self._l2_cache.delete(key)
            if deleted_l1 or deleted_l2:
                invalidated += 1
            self._remove_from_index(key)

        logger.info(
            f"Invalidated {invalidated} cache entries for {instrument_id}"
            f"{' (timeframe=' + timeframe + ')' if timeframe else ''}"
        )
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
            self._add_to_index(key)
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
        self._key_index.clear()
        logger.info("Cleared all cache data")
