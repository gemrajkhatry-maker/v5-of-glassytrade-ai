"""
Compatibility shim — infrastructure/rate_limiter/token_bucket.py.

The canonical implementation has moved to:
    brokersv2.resilience.policies.rate_limit.BrokerRateLimiter

RateLimiter and TokenBucket are re-exported here so all existing importers
continue to work without changes.
"""
import warnings as _warnings

_warnings.warn(
    "brokersv2.infrastructure.rate_limiter.token_bucket is deprecated. "
    "Import from brokersv2.resilience.policies.rate_limit instead.",
    DeprecationWarning,
    stacklevel=2,
)

from brokersv2.resilience.policies.rate_limit import (  # noqa: E402, F401
    BrokerRateLimiter,
    BrokerRateLimiter as RateLimiter,
    _TokenBucket as TokenBucket,
    RateLimit,
    RequestScheduler,
)

__all__ = ["RateLimiter", "BrokerRateLimiter", "TokenBucket", "RateLimit", "RequestScheduler"]
