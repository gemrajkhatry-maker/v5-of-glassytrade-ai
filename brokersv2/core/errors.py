"""
Error hierarchy for brokersv2.

All custom exceptions inherit from BrokersV2Error for easy catching.
"""

from __future__ import annotations

from typing import Optional


class BrokersV2Error(Exception):
    """Base exception for all brokersv2 errors."""
    pass


class BrokerConnectionError(BrokersV2Error):
    """Connection to broker failed."""
    pass


class BrokerAuthenticationError(BrokersV2Error):
    """Authentication/authorization failed."""
    pass


class BrokerRateLimitError(BrokersV2Error):
    """Rate limit exceeded."""
    pass


class BrokerOrderError(BrokersV2Error):
    """Order execution failed."""
    
    def __init__(
        self,
        message: str,
        order_id: Optional[str] = None,
        reason: Optional[str] = None,
    ):
        super().__init__(message)
        self.order_id = order_id
        self.reason = reason


class BrokerDataError(BrokersV2Error):
    """Market data error."""
    pass


class CircuitBreakerOpenError(BrokersV2Error):
    """Circuit breaker is open, request rejected."""
    pass


class InstrumentNotFoundError(BrokersV2Error):
    """Instrument not found in registry."""
    
    def __init__(self, symbol: str):
        super().__init__(f"Instrument not found: {symbol}")
        self.symbol = symbol
