"""
Provider metrics and observability.

Tracks provider usage, fallback statistics, and health indicators.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from typing import Optional
import logging

logger = logging.getLogger(__name__)


@dataclass
class ProviderMetrics:
    """
    Track provider usage and fallback statistics.
    
    Provides visibility into:
    - Primary provider reliability
    - Fallback frequency
    - Provider health status
    """
    
    # Primary provider (Dhan) metrics
    primary_success: int = 0
    primary_failure: int = 0
    primary_timeout: int = 0
    primary_rate_limit: int = 0
    
    # Fallback provider (OpenChart) metrics
    fallback_success: int = 0
    fallback_failure: int = 0
    fallback_timeout: int = 0
    fallback_rate_limit: int = 0
    
    # Aggregate metrics
    total_requests: int = 0
    total_fallbacks: int = 0
    total_candles_fetched: int = 0
    
    # Timing
    last_primary_failure: Optional[datetime] = None
    last_fallback_failure: Optional[datetime] = None
    last_request_time: Optional[datetime] = None
    
    # Performance
    _total_response_time: float = 0.0
    _request_count: int = 0
    
    def record_primary_success(self, candles_count: int = 0, response_time: float = 0.0):
        """Record successful primary provider request."""
        self.primary_success += 1
        self.total_requests += 1
        self.total_candles_fetched += candles_count
        self.last_request_time = datetime.now()
        self._record_response_time(response_time)
        logger.debug(f"Primary provider success: {candles_count} candles in {response_time:.2f}s")
    
    def record_primary_failure(self, failure_type: str = "unknown"):
        """Record primary provider failure."""
        self.primary_failure += 1
        self.total_requests += 1
        self.total_fallbacks += 1
        self.last_primary_failure = datetime.now()
        self.last_request_time = datetime.now()
        logger.warning(f"Primary provider failure: {failure_type}")
        
        if failure_type == "timeout":
            self.primary_timeout += 1
        elif failure_type == "rate_limit":
            self.primary_rate_limit += 1
    
    def record_fallback_success(self, candles_count: int = 0, response_time: float = 0.0):
        """Record successful fallback provider request."""
        self.fallback_success += 1
        self.total_candles_fetched += candles_count
        self.last_request_time = datetime.now()
        self._record_response_time(response_time)
        logger.info(f"Fallback provider success: {candles_count} candles in {response_time:.2f}s")
    
    def record_fallback_failure(self, failure_type: str = "unknown"):
        """Record fallback provider failure."""
        self.fallback_failure += 1
        self.last_fallback_failure = datetime.now()
        self.last_request_time = datetime.now()
        logger.error(f"Fallback provider failure: {failure_type}")
        
        if failure_type == "timeout":
            self.fallback_timeout += 1
        elif failure_type == "rate_limit":
            self.fallback_rate_limit += 1
    
    @property
    def fallback_rate(self) -> float:
        """
        Percentage of requests that used fallback.
        
        Returns:
            Fallback rate as percentage (0.0 to 100.0)
        """
        if self.total_requests == 0:
            return 0.0
        return (self.total_fallbacks / self.total_requests) * 100.0
    
    @property
    def primary_success_rate(self) -> float:
        """
        Primary provider success rate.
        
        Returns:
            Success rate as percentage (0.0 to 100.0)
        """
        total = self.primary_success + self.primary_failure
        if total == 0:
            return 100.0
        return (self.primary_success / total) * 100.0
    
    @property
    def primary_health(self) -> str:
        """
        Simple health indicator for primary provider.
        
        Returns:
            "healthy", "warning", or "degraded"
        """
        if self.primary_failure == 0:
            return "healthy"
        
        failure_rate = self.primary_failure / max(1, self.primary_success + self.primary_failure)
        
        if failure_rate > 0.5:
            return "degraded"
        elif failure_rate > 0.2:
            return "warning"
        else:
            return "healthy"
    
    @property
    def average_response_time(self) -> float:
        """
        Average response time across all requests.
        
        Returns:
            Average response time in seconds
        """
        if self._request_count == 0:
            return 0.0
        return self._total_response_time / self._request_count
    
    def get_summary(self) -> dict:
        """
        Get comprehensive metrics summary.
        
        Returns:
            Dictionary with all metrics
        """
        return {
            "total_requests": self.total_requests,
            "total_fallbacks": self.total_fallbacks,
            "total_candles_fetched": self.total_candles_fetched,
            "fallback_rate_pct": round(self.fallback_rate, 2),
            "primary_success_rate_pct": round(self.primary_success_rate, 2),
            "primary_health": self.primary_health,
            "primary_success": self.primary_success,
            "primary_failure": self.primary_failure,
            "primary_timeout": self.primary_timeout,
            "primary_rate_limit": self.primary_rate_limit,
            "fallback_success": self.fallback_success,
            "fallback_failure": self.fallback_failure,
            "fallback_timeout": self.fallback_timeout,
            "fallback_rate_limit": self.fallback_rate_limit,
            "average_response_time_ms": round(self.average_response_time * 1000, 2),
            "last_primary_failure": self.last_primary_failure.isoformat() if self.last_primary_failure else None,
            "last_fallback_failure": self.last_fallback_failure.isoformat() if self.last_fallback_failure else None,
        }
    
    def reset(self):
        """Reset all metrics."""
        self.__init__()
        logger.info("Provider metrics reset")
    
    def _record_response_time(self, response_time: float):
        """Record response time for averaging."""
        if response_time > 0:
            self._total_response_time += response_time
            self._request_count += 1
    
    def __repr__(self) -> str:
        return (
            f"<ProviderMetrics requests={self.total_requests} "
            f"fallbacks={self.total_fallbacks} "
            f"primary_health={self.primary_health}>"
        )
