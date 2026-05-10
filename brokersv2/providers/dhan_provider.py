"""
Dhan historical data provider implementation.

Wraps DhanBrokerAdapter with BaseHistoricalProvider interface.
Retry logic is delegated to the platform RetryPolicy (canonical).
"""

from __future__ import annotations

from typing import List
from datetime import datetime
from decimal import Decimal
import logging
import asyncio

from brokersv2.core.constants import Retry, HistoricalRouter
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
from brokersv2.resilience.policies.retry import RetryPolicy, RetryManager, RetryExhaustedError

logger = logging.getLogger(__name__)

# Default retry policy for Dhan historical API calls - from centralized constants
_DEFAULT_RETRY_POLICY = RetryPolicy(
    max_retries=Retry.MAX_RETRIES,
    base_delay=Retry.BASE_DELAY,
    max_delay=Retry.MAX_DELAY,
    retryable_exceptions=Retry.DEFAULT_RETRYABLE_EXCEPTIONS,
    log_retries=True,
)


class DhanHistoricalProvider(BaseHistoricalProvider):
    """
    Dhan historical data provider.

    Primary provider for historical candle data.
    Wraps DhanBrokerAdapter and adds:
    - Platform RetryPolicy (exponential backoff with jitter)
    - Candle conversion
    - Structured error handling
    - Health monitoring
    """

    SUPPORTED_TIMEFRAMES = ["1m", "5m", "15m", "25m", "1h", "1d"]

    def __init__(
        self,
        adapter: DhanBrokerAdapter,
        timeout: float = HistoricalRouter.PRIMARY_TIMEOUT,
        retry_policy: RetryPolicy | None = None,
    ):
        """
        Initialize Dhan provider.

        Args:
            adapter: DhanBrokerAdapter instance
            timeout: Request timeout in seconds
            retry_policy: Override the default RetryPolicy (optional)
        """
        self._adapter = adapter
        self._timeout = timeout
        self._available = True
        self._retry_policy = retry_policy or _DEFAULT_RETRY_POLICY
        self._retry_manager = RetryManager(policy=self._retry_policy)
    
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

        logger.debug(
            "Dhan provider: fetching %s %s (%s to %s)",
            instrument.symbol, timeframe, from_date, to_date,
        )

        try:
            candles = await self._retry_manager.execute(
                lambda: self._fetch_candles_with_timeout(
                    instrument, timeframe, from_date, to_date
                )
            )
        except RateLimitExceededError as exc:
            self._available = False
            raise ProviderUnavailableError(f"Dhan rate limit exceeded: {exc}") from exc
        except RetryExhaustedError as exc:
            self._available = False
            raise ProviderUnavailableError(
                f"Dhan provider failed after {self._retry_policy.max_retries} attempts: {exc.last_exception}"
            ) from exc.last_exception
        except Exception as exc:
            err_str = str(exc)
            if "401" in err_str or "403" in err_str:
                self._available = False
                raise ProviderUnavailableError(f"Dhan auth failed: {exc}") from exc
            raise

        if candles is None:
            return []

        self._available = True
        logger.info(
            "Dhan provider: fetched %d candles for %s %s",
            len(candles), instrument.symbol, timeframe,
        )
        return candles
    
    async def search_symbol(self, query: str) -> List[CanonicalInstrument]:
        """
        Search for symbols on Dhan.

        Downloads the Dhan master instrument file, parses it, and
        returns instruments whose trading symbol or name matches the query.

        Args:
            query: Search query (case-insensitive substring match)

        Returns:
            List of matching CanonicalInstrument objects
        """
        if not query or not query.strip():
            return []

        query_lower = query.strip().lower()

        try:
            # Fetch master instrument list from Dhan
            master_data = await self._adapter._client._request(
                "GET", "/master", bucket="non_trading"
            )

            if not isinstance(master_data, list):
                logger.warning("Dhan master data unexpected format")
                return []

            results: List[CanonicalInstrument] = []
            for item in master_data:
                if not isinstance(item, dict):
                    continue

                symbol = str(item.get("SEM_TRADING_SYMBOL", ""))
                name = str(item.get("SEM_SMST_SYMBOL_NAME", ""))

                if query_lower in symbol.lower() or query_lower in name.lower():
                    instrument = self._parse_master_item(item)
                    if instrument:
                        results.append(instrument)

            logger.info(
                "Dhan symbol search for '%s' returned %d results",
                query, len(results),
            )
            return results

        except Exception as exc:
            logger.error("Dhan symbol search failed: %s", exc)
            raise SymbolNotFoundError(
                f"Dhan symbol search failed for '{query}': {exc}"
            ) from exc

    def _parse_master_item(self, item: dict) -> Optional[CanonicalInstrument]:
        """Parse a Dhan master instrument dict into CanonicalInstrument."""
        from brokersv2.core.types import InstrumentType, OptionType
        from decimal import Decimal
        from datetime import datetime

        try:
            symbol = str(item.get("SEM_TRADING_SYMBOL", ""))
            exchange_code = str(item.get("SEM_EXM_EXCH_ID", "NSE"))
            inst_type = str(item.get("SEM_INSTRUMENT_NAME", "EQ"))
            lot_size = int(item.get("SEM_LOT_SIZE", 1) or 1)
            tick_size = Decimal(str(item.get("SEM_TICK_SIZE", "0.01") or "0.01"))

            exchange = Exchange.NSE if exchange_code == "NSE" else Exchange.BSE

            if inst_type in ("OPTSTK", "OPTIDX"):
                expiry_str = str(item.get("SEM_EXPIRY_DATE", ""))
                strike = Decimal(str(item.get("SEM_STRIKE_PRICE", 0) or 0))
                opt_type = OptionType.CALL if str(item.get("SEM_OPTION_TYPE", "")).upper() == "CE" else OptionType.PUT
                expiry = datetime.strptime(expiry_str, "%Y-%m-%d").date() if expiry_str else None
                if expiry:
                    return CanonicalInstrument.create_option(
                        symbol=symbol, exchange=exchange, expiry=expiry,
                        strike=strike, option_type=opt_type, lot_size=lot_size, tick_size=tick_size,
                    )
            elif inst_type in ("FUTSTK", "FUTIDX"):
                expiry_str = str(item.get("SEM_EXPIRY_DATE", ""))
                expiry = datetime.strptime(expiry_str, "%Y-%m-%d").date() if expiry_str else None
                if expiry:
                    return CanonicalInstrument.create_future(
                        symbol=symbol, exchange=exchange, expiry=expiry,
                        lot_size=lot_size, tick_size=tick_size,
                    )
            else:
                return CanonicalInstrument.create_equity(
                    symbol=symbol, exchange=exchange, lot_size=lot_size, tick_size=tick_size,
                )
        except Exception as exc:
            logger.debug("Failed to parse master item: %s", exc)
            return None
        return None
    
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
    
    def __repr__(self) -> str:
        return f"<DhanHistoricalProvider available={self._available}>"
