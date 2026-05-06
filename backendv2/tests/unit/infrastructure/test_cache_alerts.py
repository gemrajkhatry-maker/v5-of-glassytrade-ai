"""Tests for Redis cache layer."""
import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from app.infrastructure.cache.redis_cache import RedisCache, RedisConfig
from app.infrastructure.alerts.alert_manager import AlertManager, AlertType
from app.core.feature_flags import FeatureFlags, Feature


class TestRedisCache:
    """Tests for Redis cache."""
    
    @pytest.fixture
    def config(self):
        return RedisConfig(host="localhost", port=6379)
    
    @pytest.fixture
    def cache(self, config):
        return RedisCache(config)
    
    def test_key_prefix(self, cache):
        """Test key prefix is applied."""
        assert cache._key("test") == "trading:test"
    
    @pytest.mark.asyncio
    async def test_get_without_connection_returns_none(self, cache):
        """Test get returns None when not connected."""
        result = await cache.get("test_key")
        assert result is None
    
    @pytest.mark.asyncio
    async def test_set_without_connection_returns_false(self, cache):
        """Test set returns False when not connected."""
        result = await cache.set("test_key", {"data": "value"})
        assert result is False
    
    @pytest.mark.asyncio
    async def test_no_aioredis_check(self, config):
        """Test that missing aioredis raises proper error."""
        cache = RedisCache(config)
        
        with patch('app.infrastructure.cache.redis_cache.HAS_AIOREDIS', False):
            with pytest.raises(ImportError):
                await cache.connect()
    
    @pytest.mark.asyncio
    async def test_market_data_operations(self, cache):
        """Test market data caching helpers."""
        mock_redis = AsyncMock()
        mock_redis.get = AsyncMock(return_value='{"price": 50000}')
        mock_redis.setex = AsyncMock()
        cache._redis = mock_redis
        
        # Get market data
        data = await cache.get_market_data("BTCUSDT")
        assert data["price"] == 50000
        
        # Set market data
        result = await cache.set_market_data("BTCUSDT", {"price": 51000}, ttl=30)
        assert result is True
        mock_redis.setex.assert_called_once()


class TestAlertManager:
    """Tests for Alert Manager."""
    
    @pytest.fixture
    def features(self):
        flags = FeatureFlags()
        flags.enable(Feature.AI_ANALYSIS)
        return flags
    
    @pytest.fixture
    def alert_manager(self, features):
        return AlertManager(features)
    
    def test_subscribe_and_unsubscribe(self, alert_manager):
        """Test subscription management."""
        callback = MagicMock()
        
        unsubscribe = alert_manager.subscribe(callback)
        assert callback in alert_manager._subscribers
        
        unsubscribe()
        assert callback not in alert_manager._subscribers
    
    def test_broadcast_to_subscribers(self, alert_manager):
        """Test alert broadcasting."""
        alerts_received = []
        
        def callback(alert):
            alerts_received.append(alert)
        
        alert_manager.subscribe(callback)
        alert_manager.signal_alert("BTCUSDT", "LONG", 50000, 49000, 52000)
        
        assert len(alerts_received) == 1
        assert alerts_received[0].type.value == "SIGNAL"
    
    def test_no_broadcast_when_feature_disabled(self, features):
        """Test no broadcast when feature is disabled."""
        features.disable(Feature.AI_ANALYSIS)
        alert_manager = AlertManager(features)
        
        callback = MagicMock()
        alert_manager.subscribe(callback)
        alert_manager.signal_alert("BTCUSDT", "LONG", 50000, 49000, 52000)
        
        callback.assert_not_called()
    
    def test_position_alert(self, alert_manager):
        """Test position alert creation."""
        alerts_received = []
        
        def callback(alert):
            alerts_received.append(alert)
        
        alert_manager.subscribe(callback)
        alert_manager.position_alert("pos-123", "BTCUSDT", "OPEN")
        
        assert alerts_received[0].type.value == "POSITION_OPENED"
    
    def test_risk_alert(self, alert_manager):
        """Test risk alert creation."""
        alerts_received = []
        
        def callback(alert):
            alerts_received.append(alert)
        
        alert_manager.subscribe(callback)
        alert_manager.risk_alert("BTCUSDT", "Stop loss approaching", "CRITICAL")
        
        assert alerts_received[0].type.value == "RISK_WARNING"
        assert alerts_received[0].data["level"] == "CRITICAL"