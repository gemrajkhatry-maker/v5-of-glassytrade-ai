"""
Base historical data provider interface.

All historical data providers must implement this interface.
Strategies and application layers depend on THIS interface only,
never on concrete provider implementations.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import List, Optional
from datetime import datetime

from brokersv2.domain.market.models import Candle
from brokersv2.domain.instrument.models import CanonicalInstrument


class BaseHistoricalProvider(ABC):
    """
    Abstract base for all historical data providers.
    
    Implementations:
    - DhanHistoricalProvider (primary)
    - OpenChartHistoricalProvider (fallback)
    
    Strategies should ONLY interact with this interface.
    """
    
    @abstractmethod
    async def get_candles(
        self,
        instrument: CanonicalInstrument,
        timeframe: str,
        from_date: str,
        to_date: str,
    ) -> List[Candle]:
        """
        Fetch historical candles.
        
        Args:
            instrument: Canonical instrument to fetch data for
            timeframe: Timeframe (e.g., "1m", "5m", "15m", "1h", "1d")
            from_date: Start date in YYYY-MM-DD format
            to_date: End date in YYYY-MM-DD format
        
        Returns:
            List of Candle objects sorted by timestamp
        
        Raises:
            ProviderUnavailableError: If provider is down
            RateLimitExceededError: If rate limit exceeded
            SymbolNotFoundError: If symbol not found
            ProviderTimeoutError: If request times out
        """
        ...
    
    @abstractmethod
    async def search_symbol(self, query: str) -> List[CanonicalInstrument]:
        """
        Search for symbols matching query.
        
        Args:
            query: Search query (e.g., "RELI", "NIFTY")
        
        Returns:
            List of matching CanonicalInstrument objects
        """
        ...
    
    @property
    @abstractmethod
    def provider_name(self) -> str:
        """
        Provider identifier.
        
        Returns:
            Provider name (e.g., "dhan", "opencart")
        """
        ...
    
    @property
    @abstractmethod
    def supported_timeframes(self) -> List[str]:
        """
        List of supported timeframes.
        
        Returns:
            List of timeframe strings (e.g., ["1m", "5m", "15m", "1h", "1d"])
        """
        ...
    
    @property
    @abstractmethod
    def is_available(self) -> bool:
        """
        Health check for provider.
        
        Returns:
            True if provider is available, False otherwise
        """
        ...
    
    def __repr__(self) -> str:
        return f"<{self.__class__.__name__} provider={self.provider_name}>"
