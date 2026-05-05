"""Redis cache layer for high-frequency market data."""
from dataclasses import dataclass
from typing import Optional, Any, Dict
import json
import asyncio

try:
    import aioredis
    HAS_AIOREDIS = True
except ImportError:
    HAS_AIOREDIS = False


@dataclass
class RedisConfig:
    """Redis cache configuration."""
    host: str = "localhost"
    port: int = 6379
    db: int = 0
    password: Optional[str] = None
    prefix: str = "trading:"
    default_ttl: int = 300  # 5 minutes


class RedisCache:
    """Redis cache for market data and position caching."""
    
    def __init__(self, config: RedisConfig):
        self._config = config
        self._redis = None
    
    async def connect(self):
        """Connect to Redis."""
        if not HAS_AIOREDIS:
            raise ImportError("aioredis not installed. Run: pip install aioredis")
        
        self._redis = await aioredis.from_url(
            f"redis://{self._config.host}:{self._config.port}/{self._config.db}",
            password=self._config.password,
            decode_responses=True
        )
    
    def _key(self, key: str) -> str:
        """Add prefix to key."""
        return f"{self._config.prefix}{key}"
    
    async def get(self, key: str) -> Optional[Any]:
        """Get value from cache."""
        if not self._redis:
            return None
        
        value = await self._redis.get(self._key(key))
        if value:
            try:
                return json.loads(value)
            except json.JSONDecodeError:
                return value
        return None
    
    async def set(self, key: str, value: Any, ttl: Optional[int] = None) -> bool:
        """Set value in cache."""
        if not self._redis:
            return False
        
        try:
            serialized = json.dumps(value) if not isinstance(value, str) else value
            ttl = ttl or self._config.default_ttl
            await self._redis.setex(self._key(key), ttl, serialized)
            return True
        except Exception:
            return False
    
    async def delete(self, key: str) -> bool:
        """Delete key from cache."""
        if not self._redis:
            return False
        
        result = await self._redis.delete(self._key(key))
        return result > 0
    
    async def get_market_data(self, symbol: str) -> Optional[Dict]:
        """Get cached market data for symbol."""
        return await self.get(f"market:{symbol}")
    
    async def set_market_data(self, symbol: str, data: Dict, ttl: int = 30) -> bool:
        """Cache market data with short TTL."""
        return await self.set(f"market:{symbol}", data, ttl)
    
    async def get_positions(self, symbol: Optional[str] = None) -> Optional[Any]:
        """Get cached positions."""
        if symbol:
            return await self.get(f"positions:{symbol}")
        return await self.get("positions:all")
    
    async def set_positions(self, positions: list, symbol: Optional[str] = None) -> bool:
        """Cache positions."""
        if symbol:
            return await self.set(f"positions:{symbol}", positions)
        return await self.set("positions:all", positions)
    
    async def close(self):
        """Close Redis connection."""
        if self._redis:
            await self._redis.close()