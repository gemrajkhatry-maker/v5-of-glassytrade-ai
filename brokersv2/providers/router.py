"""
Historical data router with priority-based provider selection.

Routes requests to primary (Dhan) with automatic fallback to
secondary (OpenChart) on timeout or failure.

Architecture:
- Single-user desktop optimization (no distributed features)
- Deterministic routing: Dhan → OpenChart fallback
- Timeout-based fallback (not random)
- Full metrics tracking for observability
"""

from __future__ import annotations

from typing import List, Optional
import asyncio
import logging

from brokersv2.providers.base import BaseHistoricalProvider
from brokersv2.providers.metrics import ProviderMetrics
from brokersv2.providers.exceptions import (
    ProviderUnavailableError,
    RateLimitExceededError,
    ProviderTimeoutError,
)
from brokersv2.domain.market.models import Candle
from brokersv2.domain.instrument.models import CanonicalInstrument

logger = logging.getLogger(__name__)


class HistoricalDataRouter:
    """
    Router for historical data providers with fallback support.
    
    Routes requests in priority order:
    1. Dhan (primary) - 10s timeout
    2. OpenChart (fallback) - 15s timeout
    
    Fallback triggers:
    - TimeoutError (>10s)
    - ProviderUnavailableError (401/403/network error)
    - RateLimitExceededError (429)
    """
    
    PRIMARY_TIMEOUT = 10.0  # seconds
    FALLBACK_TIMEOUT = 15.0  # seconds
    
    def __init__(
        self,
        primary: BaseHistoricalProvider,
        fallback: Optional[BaseHistoricalProvider] = None,
    ):
        """
        Initialize router.
        
        Args:
            primary: Primary provider (usually Dhan)
            fallback: Fallback provider (usually OpenChart)
        """
        self._primary = primary
        self._fallback = fallback
        self._metrics = ProviderMetrics()
        
        logger.info(
            f"HistoricalDataRouter initialized: "
            f"primary={primary.provider_name}, "
            f"fallback={fallback.provider_name if fallback else 'none'}"
        )
    
    async def get_candles(
        self,
        instrument: CanonicalInstrument,
        timeframe: str,
        from_date: str,
        to_date: str,
    ) -> List[Candle]:
        """
        Fetch candles with automatic fallback.
        
        Args:
            instrument: Instrument
            timeframe: Timeframe
            from_date: Start date
            to_date: End date
        
        Returns:
            List of Candle objects from first successful provider
        """
        logger.debug(
            f"Router: fetching {instrument.symbol} {timeframe} "
            f"({from_date} to {to_date})"
        )
        
        # Try primary provider
        try:
            candles = await self._fetch_with_timeout(
                self._primary,
                instrument, timeframe, from_date, to_date,
                timeout=self.PRIMARY_TIMEOUT,
            )
            
            # Success
            self._metrics.record_primary_success(
                candles_count=len(candles),
            )
            
            logger.info(
                f"Router: primary success ({self._primary.provider_name}), "
                f"{len(candles)} candles"
            )
            
            return candles
            
        except (TimeoutError, ProviderUnavailableError, RateLimitExceededError) as e:
            # Primary failed - record and fallback
            failure_type = type(e).__name__
            self._metrics.record_primary_failure(failure_type=failure_type)
            
            logger.warning(
                f"Router: primary ({self._primary.provider_name}) failed: "
                f"{e}, trying fallback"
            )
            
            # Try fallback
            if self._fallback and self._fallback.is_available:
                return await self._try_fallback(
                    instrument, timeframe, from_date, to_date
                )
            
            # No fallback available
            logger.error("Router: no fallback available")
            raise
    
    async def search_symbol(self, query: str) -> List[CanonicalInstrument]:
        """
        Search for symbols using primary provider.
        
        Args:
            query: Search query
        
        Returns:
            List of matching instruments
        """
        try:
            return await self._primary.search_symbol(query)
        except Exception as e:
            logger.warning(f"Primary symbol search failed: {e}")
            
            if self._fallback and self._fallback.is_available:
                try:
                    return await self._fallback.search_symbol(query)
                except Exception as fallback_error:
                    logger.error(f"Fallback symbol search also failed: {fallback_error}")
            
            return []
    
    async def _try_fallback(
        self,
        instrument: CanonicalInstrument,
        timeframe: str,
        from_date: str,
        to_date: str,
    ) -> List[Candle]:
        """
        Attempt to fetch from fallback provider.
        
        Args:
            instrument: Instrument
            timeframe: Timeframe
            from_date: Start date
            to_date: End date
        
        Returns:
            List of Candle objects from fallback
        """
        try:
            logger.info(f"Router: trying fallback ({self._fallback.provider_name})")
            
            candles = await self._fetch_with_timeout(
                self._fallback,
                instrument, timeframe, from_date, to_date,
                timeout=self.FALLBACK_TIMEOUT,
            )
            
            # Fallback success
            self._metrics.record_fallback_success(candles_count=len(candles))
            
            logger.info(
                f"Router: fallback success ({self._fallback.provider_name}), "
                f"{len(candles)} candles"
            )
            
            return candles
            
        except Exception as e:
            # Fallback also failed
            self._metrics.record_fallback_failure()
            
            logger.error(
                f"Router: fallback ({self._fallback.provider_name}) also failed: {e}"
            )
            
            raise ProviderUnavailableError(
                f"All providers failed. Primary: {self._primary.provider_name}, "
                f"Fallback: {self._fallback.provider_name}. "
                f"Error: {e}"
            )
    
    async def _fetch_with_timeout(
        self,
        provider: BaseHistoricalProvider,
        instrument: CanonicalInstrument,
        timeframe: str,
        from_date: str,
        to_date: str,
        timeout: float,
    ) -> List[Candle]:
        """
        Fetch candles with timeout wrapper.
        
        Args:
            provider: Provider to fetch from
            instrument: Instrument
            timeframe: Timeframe
            from_date: Start date
            to_date: End date
            timeout: Timeout in seconds
        
        Returns:
            List of Candle objects
        
        Raises:
            TimeoutError: If request exceeds timeout
        """
        try:
            return await asyncio.wait_for(
                provider.get_candles(
                    instrument, timeframe, from_date, to_date
                ),
                timeout=timeout,
            )
        except asyncio.TimeoutError:
            logger.error(f"Provider {provider.provider_name} timed out after {timeout}s")
            raise TimeoutError(
                f"Provider {provider.provider_name} timed out after {timeout}s"
            )
    
    @property
    def metrics(self) -> ProviderMetrics:
        """Get current provider metrics."""
        return self._metrics
    
    def get_provider_status(self) -> dict:
        """
        Get current status of all providers.
        
        Returns:
            Dict with provider status information
        """
        status = {
            "primary": {
                "name": self._primary.provider_name,
                "available": self._primary.is_available,
                "supported_timeframes": self._primary.supported_timeframes,
            }
        }
        
        if self._fallback:
            status["fallback"] = {
                "name": self._fallback.provider_name,
                "available": self._fallback.is_available,
                "supported_timeframes": self._fallback.supported_timeframes,
            }
        
        status["metrics"] = {
            "total_requests": self._metrics.total_requests,
            "total_fallbacks": self._metrics.total_fallbacks,
            "fallback_rate": self._metrics.fallback_rate,
            "primary_health": self._metrics.primary_health,
        }
        
        return status
    
    def __repr__(self) -> str:
        fallback_name = self._fallback.provider_name if self._fallback else "none"
        return (
            f"<HistoricalDataRouter "
            f"primary={self._primary.provider_name} "
            f"fallback={fallback_name} "
            f"requests={self._metrics.total_requests}>"
        )
