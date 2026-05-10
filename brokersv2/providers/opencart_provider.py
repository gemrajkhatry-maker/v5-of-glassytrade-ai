"""
OpenChart historical data provider implementation.

Fallback provider using opencart library for NSE historical data.
Includes rate limiting and graceful error handling.

IMPORTANT: OpenChart is ONLY for historical data, NOT live trading decisions.
"""

from __future__ import annotations

from typing import List
from datetime import datetime
from decimal import Decimal
import logging

from brokersv2.providers.base import BaseHistoricalProvider
from brokersv2.providers.rate_limiter import TokenBucketRateLimiter
from brokersv2.providers.symbol_mapper import SymbolMapper
from brokersv2.providers.exceptions import (
    ProviderUnavailableError,
    RateLimitExceededError,
    SymbolNotFoundError,
)
from brokersv2.domain.market.models import Candle
from brokersv2.domain.instrument.models import CanonicalInstrument

logger = logging.getLogger(__name__)

# Lazy import to avoid hard dependency
try:
    from opencart import OpenChart
    OPENCART_AVAILABLE = True
except ImportError:
    OPENCART_AVAILABLE = False
    OpenChart = None


class OpenChartHistoricalProvider(BaseHistoricalProvider):
    """
    OpenChart historical data provider (fallback only).
    
    Uses unofficial NSE chart APIs via opencart library.
    Features:
    - Rate limiting to prevent abuse
    - Symbol mapping for NSE variations
    - Graceful degradation on failures
    - DataFrame to Candle conversion
    
    WARNING: This provider may fail intermittently due to NSE API changes.
    NEVER use for live trading decisions - historical data only.
    """
    
    SUPPORTED_TIMEFRAMES = ["1m", "5m", "15m", "1h", "1d"]
    
    def __init__(
        self,
        rate_limiter: TokenBucketRateLimiter = None,
        timeout: float = 15.0,
    ):
        """
        Initialize OpenChart provider.
        
        Args:
            rate_limiter: Rate limiter for request pacing
            timeout: Request timeout in seconds
        """
        if not OPENCART_AVAILABLE:
            raise ImportError(
                "OpenChart not installed. Run: pip install opencart"
            )
        
        self._client = OpenChart()
        self._rate_limiter = rate_limiter or TokenBucketRateLimiter()
        self._symbol_mapper = SymbolMapper()
        self._timeout = timeout
        self._available = True
    
    @property
    def provider_name(self) -> str:
        return "opencart"
    
    @property
    def supported_timeframes(self) -> List[str]:
        return self.SUPPORTED_TIMEFRAMES
    
    @property
    def is_available(self) -> bool:
        return self._available and OPENCART_AVAILABLE
    
    async def get_candles(
        self,
        instrument: CanonicalInstrument,
        timeframe: str,
        from_date: str,
        to_date: str,
    ) -> List[Candle]:
        """
        Fetch historical candles from OpenChart with rate limiting.
        
        Args:
            instrument: Instrument to fetch data for
            timeframe: Timeframe (e.g., "5m", "1h")
            from_date: Start date YYYY-MM-DD
            to_date: End date YYYY-MM-DD
        
        Returns:
            List of Candle objects
        
        Raises:
            ProviderUnavailableError: If OpenChart/NSE is down
            RateLimitExceededError: If rate limit exceeded
        """
        if timeframe not in self.SUPPORTED_TIMEFRAMES:
            raise ValueError(
                f"Unsupported timeframe: {timeframe}. "
                f"Supported: {self.SUPPORTED_TIMEFRAMES}"
            )
        
        # Apply rate limiter (critical for OpenChart)
        await self._rate_limiter.acquire()
        
        try:
            logger.debug(
                f"OpenChart provider: fetching {instrument.symbol} "
                f"{timeframe} ({from_date} to {to_date})"
            )
            
            # Convert canonical symbol to OpenChart format
            symbol = self._symbol_mapper.to_provider_symbol(
                instrument.symbol, "opencart"
            )
            
            # Fetch data from OpenChart (blocking call)
            df = await self._fetch_with_timeout(
                symbol, timeframe, from_date, to_date
            )
            
            if df is None or (hasattr(df, 'empty') and df.empty):
                logger.warning(f"OpenChart provider: empty response for {symbol}")
                self._rate_limiter.record_success()
                return []
            
            # Convert DataFrame to Candle objects
            candles = self._convert_dataframe_to_candles(
                df, instrument, timeframe
            )
            
            # Record success
            self._rate_limiter.record_success()
            self._available = True
            
            logger.info(
                f"OpenChart provider: fetched {len(candles)} candles "
                f"for {symbol} {timeframe}"
            )
            
            return candles
            
        except RateLimitExceededError as e:
            self._rate_limiter.record_failure()
            raise
            
        except Exception as e:
            self._rate_limiter.record_failure()
            self._available = False
            
            error_msg = str(e).lower()
            
            # Detect specific error types
            if "429" in error_msg or "rate" in error_msg:
                raise RateLimitExceededError(
                    f"OpenChart rate limit exceeded: {e}",
                    provider="opencart"
                ) from e
            
            if "401" in error_msg or "403" in error_msg:
                raise ProviderUnavailableError(
                    f"OpenChart auth/forbidden error: {e}",
                    provider="opencart"
                ) from e
            
            # Generic provider error
            raise ProviderUnavailableError(
                f"OpenChart failed: {e}",
                provider="opencart"
            ) from e
    
    async def search_symbol(self, query: str) -> List[CanonicalInstrument]:
        """
        Search for symbols on NSE using the public NSE symbol search API.

        Args:
            query: Search query (case-insensitive substring match)

        Returns:
            List of matching CanonicalInstrument objects
        """
        if not query or not query.strip():
            return []

        query_lower = query.strip().lower()

        try:
            import aiohttp
            import asyncio

            # NSE public symbol search endpoint
            search_url = (
                "https://www.nseindia.com/api/search/autocomplete"
                f"?q={query_lower}"
            )

            headers = {
                "User-Agent": (
                    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
                    "AppleWebKit/537.36 (KHTML, like Gecko) "
                    "Chrome/120.0.0.0 Safari/537.36"
                ),
                "Accept": "application/json",
            }

            async with aiohttp.ClientSession(headers=headers) as session:
                async with session.get(search_url, timeout=aiohttp.ClientTimeout(total=10)) as response:
                    if response.status != 200:
                        logger.warning(
                            "NSE search API returned %s", response.status
                        )
                        return []
                    data = await response.json()

            symbols = data.get("symbols", []) if isinstance(data, dict) else []
            if not symbols:
                return []

            results: List[CanonicalInstrument] = []
            for sym in symbols:
                if not isinstance(sym, dict):
                    continue
                symbol_name = str(sym.get("symbol", ""))
                if not symbol_name:
                    continue

                # Filter to ensure relevance
                if query_lower not in symbol_name.lower():
                    continue

                instrument = CanonicalInstrument.create_equity(
                    symbol=symbol_name.upper(),
                    exchange=Exchange.NSE,
                    lot_size=1,
                    tick_size=Decimal("0.01"),
                )
                results.append(instrument)

            logger.info(
                "OpenChart symbol search for '%s' returned %d results",
                query, len(results),
            )
            return results

        except asyncio.TimeoutError:
            logger.error("NSE symbol search timed out")
            raise ProviderUnavailableError(
                "NSE symbol search timed out", provider="opencart"
            )
        except Exception as exc:
            logger.error("OpenChart symbol search failed: %s", exc)
            raise ProviderUnavailableError(
                f"OpenChart symbol search failed: {exc}", provider="opencart"
            ) from exc
    
    async def _fetch_with_timeout(self, symbol: str, timeframe: str, from_date: str, to_date: str):
        """
        Fetch data with timeout wrapper.
        
        Args:
            symbol: Symbol to fetch
            timeframe: Timeframe
            from_date: Start date
            to_date: End date
        
        Returns:
            DataFrame with candle data
        """
        import asyncio
        
        def _fetch_blocking():
            """Blocking OpenChart call."""
            return self._client.get_historical(
                symbol=symbol,
                interval=timeframe,
                start_date=from_date,
                end_date=to_date,
            )
        
        try:
            # Run blocking call in thread pool
            loop = asyncio.get_running_loop()
            df = await asyncio.wait_for(
                loop.run_in_executor(None, _fetch_blocking),
                timeout=self._timeout,
            )
            return df
            
        except asyncio.TimeoutError:
            logger.error(f"OpenChart timeout after {self._timeout}s")
            raise ProviderUnavailableError(
                f"OpenChart timeout after {self._timeout}s",
                provider="opencart"
            )
    
    def _convert_dataframe_to_candles(
        self,
        df,
        instrument: CanonicalInstrument,
        timeframe: str,
    ) -> List[Candle]:
        """
        Convert DataFrame to List[Candle].
        
        Args:
            df: DataFrame with OHLCV data
            instrument: Instrument
            timeframe: Timeframe
        
        Returns:
            List of Candle objects
        """
        candles = []
        
        for _, row in df.iterrows():
            try:
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
                
            except Exception as e:
                logger.warning(f"Failed to convert row to candle: {e}")
                continue
        
        return candles
    
    def _parse_timestamp(self, ts) -> datetime:
        """
        Parse timestamp from various formats.
        
        Args:
            ts: Timestamp value
        
        Returns:
            Parsed datetime
        """
        if isinstance(ts, datetime):
            return ts
        
        if isinstance(ts, (int, float)):
            return datetime.fromtimestamp(ts)
        
        if isinstance(ts, str):
            for fmt in ["%Y-%m-%d %H:%M:%S", "%Y-%m-%dT%H:%M:%S", "%Y-%m-%d"]:
                try:
                    return datetime.strptime(ts, fmt)
                except ValueError:
                    continue
        
        logger.warning(f"Could not parse timestamp: {ts}")
        return datetime.now()
    
    def __repr__(self) -> str:
        return f"<OpenChartHistoricalProvider available={self._available}>"
