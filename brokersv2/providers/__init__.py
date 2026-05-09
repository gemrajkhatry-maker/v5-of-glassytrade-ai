"""
brokersv2.providers - Historical Data Provider Framework

Provider Abstraction:
- BaseHistoricalProvider: Abstract interface all providers implement
- Strategies depend on this interface, NEVER on broker APIs directly

Providers:
- DhanHistoricalProvider: Primary provider (Dhan APIs)
- OpenChartHistoricalProvider: Fallback provider (OpenChart/NSE)

Infrastructure:
- HistoricalDataRouter: Priority-based routing with fallback
- HistoricalWarmup: Preload data for fast startup
- SymbolMapper: Normalize symbols across providers
- TokenBucketRateLimiter: Rate limiting for provider protection
- ProviderMetrics: Observability and health monitoring
- CandleNormalizer: Validate and normalize candle data

Exceptions:
- HistoricalDataError: Base exception
- ProviderUnavailableError: Provider is down (401/403/network)
- RateLimitExceededError: Rate limit exceeded (429)
- SymbolNotFoundError: Symbol not found
- InvalidCandleError: Data validation failed
- ProviderTimeoutError: Request timed out

Usage:
    from brokersv2.providers import (
        HistoricalDataRouter,
        DhanHistoricalProvider,
        OpenChartHistoricalProvider,
        HistoricalWarmup,
    )
    
    # Create providers
    dhan = DhanHistoricalProvider(adapter)
    opencart = OpenChartHistoricalProvider()
    
    # Create router with automatic fallback
    router = HistoricalDataRouter(
        primary=dhan,
        fallback=opencart,
    )
    
    # Fetch candles (auto-fallbacks on failure)
    candles = await router.get_candles(
        instrument=NIFTY_50,
        timeframe="5m",
        from_date="2026-05-01",
        to_date="2026-05-07",
    )
    
    # Preload for fast startup
    warmup = HistoricalWarmup(router)
    await warmup.preload(
        instruments=[NIFTY_50, BANKNIFTY],
        timeframes=["5m", "15m"],
        lookback_days=10,
    )
"""

from brokersv2.providers.base import BaseHistoricalProvider
from brokersv2.providers.dhan_provider import DhanHistoricalProvider
from brokersv2.providers.opencart_provider import OpenChartHistoricalProvider
from brokersv2.providers.router import HistoricalDataRouter
from brokersv2.providers.warmup import HistoricalWarmup
from brokersv2.providers.symbol_mapper import SymbolMapper
from brokersv2.providers.rate_limiter import TokenBucketRateLimiter
from brokersv2.providers.metrics import ProviderMetrics
from brokersv2.providers.candle_normalizer import CandleNormalizer
from brokersv2.providers.exceptions import (
    HistoricalDataError,
    ProviderUnavailableError,
    RateLimitExceededError,
    SymbolNotFoundError,
    InvalidCandleError,
    ProviderTimeoutError,
)

__all__ = [
    # Base
    "BaseHistoricalProvider",
    
    # Providers
    "DhanHistoricalProvider",
    "OpenChartHistoricalProvider",
    
    # Router & Warmup
    "HistoricalDataRouter",
    "HistoricalWarmup",
    
    # Infrastructure
    "SymbolMapper",
    "TokenBucketRateLimiter",
    "ProviderMetrics",
    "CandleNormalizer",
    
    # Exceptions
    "HistoricalDataError",
    "ProviderUnavailableError",
    "RateLimitExceededError",
    "SymbolNotFoundError",
    "InvalidCandleError",
    "ProviderTimeoutError",
]
