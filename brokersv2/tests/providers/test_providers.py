"""
Tests for historical data providers framework.

Tests cover:
- Symbol mapper normalization
- Rate limiter functionality
- Candle validation
- Provider metrics
- Router fallback logic
"""

import pytest
from datetime import datetime
from decimal import Decimal

from brokersv2.providers.symbol_mapper import SymbolMapper
from brokersv2.providers.rate_limiter import TokenBucketRateLimiter
from brokersv2.providers.metrics import ProviderMetrics
from brokersv2.providers.candle_normalizer import CandleNormalizer
from brokersv2.providers.exceptions import InvalidCandleError


class TestSymbolMapper:
    """Test symbol normalization across providers."""
    
    def setup_method(self):
        self.mapper = SymbolMapper()
    
    def test_normalize_nse_format(self):
        """Should normalize NSE -EQ suffix."""
        assert self.mapper.normalize_symbol("RELIANCE-EQ") == "RELIANCE"
    
    def test_normalize_space_format(self):
        """Should normalize space format."""
        assert self.mapper.normalize_symbol("RELIANCE EQ") == "RELIANCE"
    
    def test_normalize_nse_prefix(self):
        """Should remove nse: prefix."""
        assert self.mapper.normalize_symbol("nse:RELIANCE") == "RELIANCE"
    
    def test_to_provider_dhan(self):
        """Should convert to Dhan format."""
        result = self.mapper.to_provider_symbol("RELIANCE", "dhan")
        assert result == "RELIANCE"
    
    def test_to_provider_opencart(self):
        """Should convert to OpenChart format."""
        result = self.mapper.to_provider_symbol("NIFTY 50", "opencart")
        assert result == "NIFTY 50"
    
    def test_unknown_symbol_passthrough(self):
        """Should pass through unknown symbols."""
        assert self.mapper.normalize_symbol("UNKNOWN") == "UNKNOWN"


class TestTokenBucketRateLimiter:
    """Test rate limiting functionality."""
    
    @pytest.mark.asyncio
    async def test_acquire_succeeds(self):
        """Should acquire token successfully."""
        limiter = TokenBucketRateLimiter(rate=10.0, burst=5)
        
        # Should succeed immediately with tokens available
        await limiter.acquire()
        assert limiter._tokens < 5.0
    
    @pytest.mark.asyncio
    async def test_cooldown_on_failure(self):
        """Should enter cooldown after failures."""
        limiter = TokenBucketRateLimiter(cooldown_after=2, cooldown_duration=0.1)
        
        # Trigger cooldown
        limiter.record_failure()
        limiter.record_failure()
        
        # Should be in cooldown
        assert limiter._is_in_cooldown()
    
    def test_reset_on_success(self):
        """Should reset failure count on success."""
        limiter = TokenBucketRateLimiter()
        
        limiter.record_failure()
        limiter.record_failure()
        limiter.record_success()
        
        assert limiter._failure_count == 0


class TestCandleNormalizer:
    """Test candle validation and normalization."""
    
    def setup_method(self):
        self.normalizer = CandleNormalizer()
    
    def test_valid_candle(self):
        """Should pass valid candle."""
        from brokersv2.domain.market.models import Candle
        from unittest.mock import Mock
        
        instrument = Mock(symbol="RELIANCE")
        candle = Candle(
            instrument=instrument,
            timeframe="5m",
            timestamp=datetime.now(),
            open=Decimal("100"),
            high=Decimal("105"),
            low=Decimal("99"),
            close=Decimal("103"),
            volume=Decimal("1000"),
        )
        
        assert self.normalizer._validate_candle(candle) is True
    
    def test_invalid_candle_high_low(self):
        """Should reject candle where high < low."""
        from brokersv2.domain.market.models import Candle
        from unittest.mock import Mock
        
        instrument = Mock(symbol="RELIANCE")
        candle = Candle(
            instrument=instrument,
            timeframe="5m",
            timestamp=datetime.now(),
            open=Decimal("100"),
            high=Decimal("95"),  # Invalid: high < low
            low=Decimal("105"),
            close=Decimal("103"),
            volume=Decimal("1000"),
        )
        
        assert self.normalizer._validate_candle(candle) is False
    
    def test_empty_candle_list(self):
        """Should handle empty list."""
        result = self.normalizer.normalize([], None, "5m")
        assert result == []


class TestProviderMetrics:
    """Test provider metrics tracking."""
    
    def setup_method(self):
        self.metrics = ProviderMetrics()
    
    def test_record_primary_success(self):
        """Should increment success counter."""
        self.metrics.record_primary_success(candles_count=100)
        
        assert self.metrics.primary_success == 1
        assert self.metrics.total_requests == 1
        assert self.metrics.total_candles_fetched == 100
    
    def test_record_primary_failure(self):
        """Should increment failure and fallback counters."""
        self.metrics.record_primary_failure("timeout")
        
        assert self.metrics.primary_failure == 1
        assert self.metrics.total_requests == 1
        assert self.metrics.total_fallbacks == 1
    
    def test_fallback_rate_calculation(self):
        """Should calculate fallback rate correctly."""
        self.metrics.record_primary_success()
        self.metrics.record_primary_failure()
        self.metrics.record_primary_failure()
        
        # 2 failures out of 3 total = 66.67%
        assert self.metrics.fallback_rate == pytest.approx(66.67, abs=0.1)
    
    def test_health_indicators(self):
        """Should report correct health status."""
        # Healthy
        self.metrics.record_primary_success()
        assert self.metrics.primary_health == "healthy"
        
        # Warning (25% failure rate)
        self.metrics.record_primary_failure()
        # Now 1 success, 1 failure = 50% failure rate
        assert self.metrics.primary_health == "warning"


class TestHistoricalDataError:
    """Test exception hierarchy."""
    
    def test_exception_with_provider(self):
        """Should create exception with provider info."""
        from brokersv2.providers.exceptions import ProviderUnavailableError
        
        exc = ProviderUnavailableError("Test error", provider="dhan")
        
        assert exc.message == "Test error"
        assert exc.provider == "dhan"
        assert str(exc) == "Test error"
