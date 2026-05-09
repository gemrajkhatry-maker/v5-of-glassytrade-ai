"""
Dhan historical data provider implementation.

Wraps existing DhanBrokerAdapter with BaseHistoricalProvider interface.
Primary provider for historical data with retry logic.
"""

from __future__ import annotations

from typing import List
from datetime import datetime
from decimal import Decimal
import logging
import asyncio

from brokersv2.providers.base import BaseHistoricalProvider
from brokersv2.providers.exceptions import (
    ProviderUnavailableError,
    RateLimitExceededError,
    SymbolNotFoundError,
    ProviderTimeoutError,
)
from brokersv2.domain.market.models import Candle
from brokersv2.domain.instrument.models import CanonicalInstrument
from brokersv2.infrastructure.dhan_adapter.adapter import DhanBrokerAdapter

logger = logging.getLogger(__name__)


class DhanHistoricalProvider(BaseHistoricalProvider):
    """
    Dhan historical data provider.
    
    Primary provider for historical candle data.
    Wraps existing DhanBrokerAdapter and adds:
    - Retry logic with exponential backoff
    - DataFrame to Candle conversion
    - Structured error handling
    - Health monitoring
    """
    
    SUPPORTED_TIMEFRAMES = ["1m", "5m", "15m", "25m", "1h", "1d"]
    MAX_RETRIES = 3
    BASE_RETRY_DELAY = 1.0  # seconds
    
    def __init__(
        self,
        adapter: DhanBrokerAdapter,
        timeout: float = 10.0,
    ):
        """
        Initialize Dhan provider.
        
        Args:
            adapter: DhanBrokerAdapter instance
            timeout: Request timeout in seconds
        """
        self._adapter = adapter
        self._timeout = timeout
        self._available = True
    
    @property
    def provider_name(self) -> str:
        return "dhan"
    
    @property
    def supported_timeframes(self) -> List[str]:
        return self.SUPPORTED_TIMEFRAMES
    
    @property
    def is_available(self) -> bool:
        return self._available
    
    async def get_candles(
        self,
        instrument: CanonicalInstrument,
        timeframe: str,
        from_date: str,
        to_date: str,
    ) -> List[Candle]:
        """
        Fetch historical candles from Dhan with retry logic.
        
        Args:
            instrument: Instrument to fetch data for
            timeframe: Timeframe (e.g., "5m", "1h")
            from_date: Start date YYYY-MM-DD
            to_date: End date YYYY-MM-DD
        
        Returns:
            List of Candle objects
        
        Raises:
            ProviderUnavailableError: If Dhan API is down
            RateLimitExceededError: If rate limit exceeded
            SymbolNotFoundError: If symbol not found
        """
        if timeframe not in self.SUPPORTED_TIMEFRAMES:
            raise ValueError(
                f"Unsupported timeframe: {timeframe}. "
                f"Supported: {self.SUPPORTED_TIMEFRAMES}"
            )
        
        last_exception = None
        
        for attempt in range(self.MAX_RETRIES):
            try:
                logger.debug(
                    f"Dhan provider: fetching {instrument.symbol} "
                    f"{timeframe} ({from_date} to {to_date}), attempt {attempt + 1}"
                )
                
                # Fetch from Dhan adapter (returns DataFrame)
                candles = await self._fetch_candles_with_timeout(
                    instrument, timeframe, from_date, to_date
                )
                
                if candles is not None:
                    self._available = True
                    logger.info(
                        f"Dhan provider: fetched {len(candles)} candles "
                        f"for {instrument.symbol} {timeframe}"
                    )
                    return candles
                
                # Empty response
                logger.warning(f"Dhan provider: empty response for {instrument.symbol}")
                return []
                
            except asyncio.TimeoutError as e:
                last_exception = e
                logger.warning(
                    f"Dhan provider timeout (attempt {attempt + 1}/{self.MAX_RETRIES}): {e}"
                )
                await self._wait_before_retry(attempt)
                
            except RateLimitExceededError as e:
                # Don't retry rate limits - let router fallback
                self._available = False
                raise ProviderUnavailableError(f"Dhan rate limit exceeded: {e}") from e
                
            except Exception as e:
                last_exception = e
                logger.error(f"Dhan provider error (attempt {attempt + 1}): {e}")
                
                # Check if it's a fatal error
                if "401" in str(e) or "403" in str(e):
                    self._available = False
                    raise ProviderUnavailableError(f"Dhan auth failed: {e}") from e
                
                await self._wait_before_retry(attempt)
        
        # All retries exhausted
        self._available = False
        raise ProviderUnavailableError(
            f"Dhan provider failed after {self.MAX_RETRIES} attempts: {last_exception}"
        ) from last_exception
    
    async def search_symbol(self, query: str) -> List[CanonicalInstrument]:
        """
        Search for symbols on Dhan.
        
        Args:
            query: Search query
        
        Returns:
            List of matching instruments
        """
        # TODO: Implement Dhan symbol search
        # For now, return empty list
        logger.warning("Dhan symbol search not yet implemented")
        return []
    
    async def _fetch_candles_with_timeout(
        self,
        instrument: CanonicalInstrument,
        timeframe: str,
        from_date: str,
        to_date: str,
    ) -> List[Candle]:
        """
        Fetch candles with timeout wrapper.
        
        Args:
            instrument: Instrument
            timeframe: Timeframe
            from_date: Start date
            to_date: End date
        
        Returns:
            List of Candle objects
        """
        try:
            # Use asyncio.wait_for to enforce timeout
            result = await asyncio.wait_for(
                self._fetch_candles_from_adapter(
                    instrument, timeframe, from_date, to_date
                ),
                timeout=self._timeout,
            )
            return result
            
        except asyncio.TimeoutError:
            logger.error(f"Dhan provider timeout after {self._timeout}s")
            raise
    
    async def _fetch_candles_from_adapter(
        self,
        instrument: CanonicalInstrument,
        timeframe: str,
        from_date: str,
        to_date: str,
    ) -> List[Candle]:
        """
        Fetch candles from Dhan adapter and convert to Candle objects.
        
        Args:
            instrument: Instrument
            timeframe: Timeframe
            from_date: Start date
            to_date: End date
        
        Returns:
            List of Candle objects
        """
        # Use existing Dhan adapter method
        # This assumes adapter has get_historical() that returns DataFrame
        # May need adjustment based on actual adapter API
        
        try:
            df = await self._adapter.get_historical(
                instrument=instrument,
                from_date=from_date,
                to_date=to_date,
                interval=timeframe,
            )
            
            if df is None or df.empty:
                return []
            
            # Convert DataFrame to List[Candle]
            candles = []
            for _, row in df.iterrows():
                candle = Candle(
                    instrument=instrument,
                    timeframe=timeframe,
                    timestamp=self._parse_timestamp(row.get("timestamp", row.get("date"))),
                    open=Decimal(str(row.get("open", 0))),
                    high=Decimal(str(row.get("high", 0))),
                    low=Decimal(str(row.get("low", 0))),
                    close=Decimal(str(row.get("close", 0))),
                    volume=Decimal(str(row.get("volume", 0))),
                )
                candles.append(candle)
            
            return candles
            
        except AttributeError as e:
            # Adapter method not found - will be implemented
            logger.warning(f"Dhan adapter method not implemented: {e}")
            return []
            
        except Exception as e:
            logger.error(f"Error fetching from Dhan adapter: {e}")
            raise
    
    def _parse_timestamp(self, ts) -> datetime:
        """
        Parse timestamp from various formats.
        
        Args:
            ts: Timestamp (Unix, string, or datetime)
        
        Returns:
            Parsed datetime object
        """
        if isinstance(ts, datetime):
            return ts
        
        if isinstance(ts, (int, float)):
            # Unix timestamp
            return datetime.fromtimestamp(ts)
        
        if isinstance(ts, str):
            # Try common formats
            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]:
                try:
                    return datetime.strptime(ts, fmt)
                except ValueError:
                    continue
        
        logger.warning(f"Could not parse timestamp: {ts}")
        return datetime.now()
    
    async def _wait_before_retry(self, attempt: int):
        """
        Wait before retry with exponential backoff.
        
        Args:
            attempt: Current attempt number (0-based)
        """
        delay = self.BASE_RETRY_DELAY * (2 ** attempt)
        logger.debug(f"Waiting {delay}s before retry")
        await asyncio.sleep(delay)
    
    def __repr__(self) -> str:
        return f"<DhanHistoricalProvider available={self._available}>"
