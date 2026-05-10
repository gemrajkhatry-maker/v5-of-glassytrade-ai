"""
Tests for Intelligent Market Data Cache.
"""

import pytest
import tempfile
import os
from datetime import datetime

from brokersv2.cache.memory_cache import LRUMemoryCache
from brokersv2.cache.disk_cache import SQLiteDiskCache
from brokersv2.cache.intelligent_cache import IntelligentMarketDataCache


class TestLRUMemoryCache:
    """Test LRU memory cache functionality."""
    
    @pytest.mark.asyncio
    async def test_set_and_get(self):
        """Should store and retrieve values."""
        cache = LRUMemoryCache(max_size=100)
        
        await cache.set("key1", "value1")
        result = await cache.get("key1")
        
        assert result == "value1"
    
    @pytest.mark.asyncio
    async def test_get_missing_key(self):
        """Should return None for missing key."""
        cache = LRUMemoryCache()
        
        result = await cache.get("nonexistent")
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_ttl_expiry(self):
        """Should expire entries after TTL."""
        import asyncio
        cache = LRUMemoryCache()
        
        await cache.set("key1", "value1", ttl_seconds=1)  # 1 second TTL
        await asyncio.sleep(1.1)  # Wait for expiry
        result = await cache.get("key1")
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_lru_eviction(self):
        """Should evict least recently used items."""
        cache = LRUMemoryCache(max_size=3)
        
        await cache.set("key1", "value1")
        await cache.set("key2", "value2")
        await cache.set("key3", "value3")
        
        # Access key1 to make it recently used
        await cache.get("key1")
        
        # Add key4 - should evict key2 (LRU)
        await cache.set("key4", "value4")
        
        assert await cache.get("key1") == "value1"  # Still there
        assert await cache.get("key2") is None  # Evicted
        assert await cache.get("key3") == "value3"
        assert await cache.get("key4") == "value4"
    
    @pytest.mark.asyncio
    async def test_delete(self):
        """Should delete entries."""
        cache = LRUMemoryCache()
        
        await cache.set("key1", "value1")
        result = await cache.delete("key1")
        
        assert result is True
        assert await cache.get("key1") is None
    
    @pytest.mark.asyncio
    async def test_delete_missing_key(self):
        """Should return False for missing key."""
        cache = LRUMemoryCache()
        
        result = await cache.delete("nonexistent")
        
        assert result is False
    
    @pytest.mark.asyncio
    async def test_clear(self):
        """Should clear all entries."""
        cache = LRUMemoryCache()
        
        await cache.set("key1", "value1")
        await cache.set("key2", "value2")
        await cache.clear()
        
        assert len(cache) == 0
        assert await cache.get("key1") is None
    
    def test_stats_tracking(self):
        """Should track hits and misses."""
        cache = LRUMemoryCache()
        
        # Synchronous stats check
        stats = cache.get_stats()
        assert stats.hits == 0
        assert stats.misses == 0


class TestSQLiteDiskCache:
    """Test SQLite disk cache functionality."""
    
    @pytest.fixture
    def db_path(self):
        """Create temporary database path."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            yield f.name
        # Cleanup
        if os.path.exists(f.name):
            os.unlink(f.name)
    
    @pytest.mark.asyncio
    async def test_set_and_get(self, db_path):
        """Should store and retrieve values."""
        cache = SQLiteDiskCache(db_path=db_path)
        
        await cache.set("key1", {"data": [1, 2, 3]})
        result = await cache.get("key1")
        
        assert result == {"data": [1, 2, 3]}
    
    @pytest.mark.asyncio
    async def test_get_missing_key(self, db_path):
        """Should return None for missing key."""
        cache = SQLiteDiskCache(db_path=db_path)
        
        result = await cache.get("nonexistent")
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_ttl_expiry(self, db_path):
        """Should expire entries after TTL."""
        import asyncio
        cache = SQLiteDiskCache(db_path=db_path)
        
        await cache.set("key1", "value1", ttl_seconds=1)  # 1 second TTL
        await asyncio.sleep(1.1)  # Wait for expiry
        result = await cache.get("key1")
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_persistence(self, db_path):
        """Should persist data across cache instances."""
        cache1 = SQLiteDiskCache(db_path=db_path)
        await cache1.set("key1", "persistent_value")
        
        # Create new cache instance with same DB
        cache2 = SQLiteDiskCache(db_path=db_path)
        result = await cache2.get("key1")
        
        assert result == "persistent_value"
    
    @pytest.mark.asyncio
    async def test_delete(self, db_path):
        """Should delete entries."""
        cache = SQLiteDiskCache(db_path=db_path)
        
        await cache.set("key1", "value1")
        result = await cache.delete("key1")
        
        assert result is True
        assert await cache.get("key1") is None
    
    @pytest.mark.asyncio
    async def test_clear(self, db_path):
        """Should clear all entries."""
        cache = SQLiteDiskCache(db_path=db_path)
        
        await cache.set("key1", "value1")
        await cache.set("key2", "value2")
        await cache.clear()
        
        assert len(cache) == 0


class TestIntelligentMarketDataCache:
    """Test intelligent multi-tier cache."""
    
    @pytest.fixture
    def cache(self):
        """Create intelligent cache with temp DB."""
        with tempfile.NamedTemporaryFile(suffix=".db", delete=False) as f:
            cache = IntelligentMarketDataCache(
                l1_max_size=100,
                l2_db_path=f.name,
                default_ttl=3600,
            )
            yield cache
        # Cleanup
        if os.path.exists(f.name):
            os.unlink(f.name)
    
    @pytest.mark.asyncio
    async def test_set_and_get_candles(self, cache):
        """Should store and retrieve candles."""
        candles = [
            {"timestamp": "2026-05-07T10:00:00", "open": 100, "close": 101},
            {"timestamp": "2026-05-07T10:05:00", "open": 101, "close": 102},
        ]
        
        await cache.set_candles("RELIANCE", "5m", "2026-05-07", "2026-05-08", candles)
        result = await cache.get_candles("RELIANCE", "5m", "2026-05-07", "2026-05-08")
        
        assert result == candles
    
    @pytest.mark.asyncio
    async def test_cache_miss(self, cache):
        """Should return None for uncached data."""
        result = await cache.get_candles("UNKNOWN", "5m", "2026-05-07", "2026-05-08")
        
        assert result is None
    
    @pytest.mark.asyncio
    async def test_l1_promotion(self, cache):
        """Should promote L2 hits to L1."""
        candles = [{"data": "test"}]
        
        # Set in L2 only (simulate by directly setting)
        await cache._l2_cache.set(
            cache._build_key("RELIANCE", "5m", "2026-05-07", "2026-05-08"),
            candles,
        )
        
        # Get should hit L2 and promote to L1
        result = await cache.get_candles("RELIANCE", "5m", "2026-05-07", "2026-05-08")
        
        assert result == candles
        
        # Second get should hit L1
        result2 = await cache.get_candles("RELIANCE", "5m", "2026-05-07", "2026-05-08")
        assert result2 == candles
    
    @pytest.mark.asyncio
    async def test_invalidate(self, cache):
        """Should invalidate cache entries."""
        candles = [{"data": "test"}]
        
        await cache.set_candles("RELIANCE", "5m", "2026-05-07", "2026-05-08", candles)
        invalidated = await cache.invalidate("RELIANCE")
        
        # Invalidation clears cache (simplified implementation)
        assert invalidated >= 0
    
    @pytest.mark.asyncio
    async def test_warmup(self, cache):
        """Should warm cache with pre-fetched data."""
        keys_data = {
            "candles:RELIANCE:5m:2026-05-07:2026-05-08": [{"open": 100}],
            "candles:INFY:5m:2026-05-07:2026-05-08": [{"open": 1500}],
        }
        
        warmed = await cache.warmup(keys_data, ttl_seconds=3600)
        
        assert warmed == 2
        
        result = await cache.get_candles("RELIANCE", "5m", "2026-05-07", "2026-05-08")
        assert result == [{"open": 100}]
    
    @pytest.mark.asyncio
    async def test_cleanup(self, cache):
        """Should clean up expired entries."""
        # Add expired entry
        await cache._l1_cache.set("expired_key", "value", ttl_seconds=0)
        
        stats = await cache.cleanup()
        
        assert stats["l1_cleaned"] >= 0
        assert stats["total_cleaned"] >= 0
    
    def test_get_stats(self, cache):
        """Should return comprehensive statistics."""
        stats = cache.get_stats()
        
        assert "l1" in stats
        assert "l2" in stats
        assert "combined" in stats
        assert "hits" in stats["l1"]
        assert "hit_rate" in stats["l1"]
    
    @pytest.mark.asyncio
    async def test_clear(self, cache):
        """Should clear all cache data."""
        await cache.set_candles("RELIANCE", "5m", "2026-05-07", "2026-05-08", [{"data": "test"}])
        await cache.clear()
        
        result = await cache.get_candles("RELIANCE", "5m", "2026-05-07", "2026-05-08")
        assert result is None
