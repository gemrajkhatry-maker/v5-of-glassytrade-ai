"""
Exception hierarchy for historical data providers.

Provides structured exceptions for precise error handling and fallback logic.
"""


class HistoricalDataError(Exception):
    """Base exception for historical data operations."""
    
    def __init__(self, message: str, provider: str = None):
        super().__init__(message)
        self.message = message
        self.provider = provider


class ProviderUnavailableError(HistoricalDataError):
    """Provider is temporarily unavailable (401/403/network error)."""
    pass


class RateLimitExceededError(HistoricalDataError):
    """Rate limit exceeded for provider (429)."""
    pass


class SymbolNotFoundError(HistoricalDataError):
    """Symbol not found in provider."""
    pass


class InvalidCandleError(HistoricalDataError):
    """Candle data validation failed."""
    pass


class ProviderTimeoutError(HistoricalDataError):
    """Provider request timed out."""
    pass


class DataQualityError(HistoricalDataError):
    """Data quality issues detected (gaps, duplicates, out-of-order)."""
    pass
