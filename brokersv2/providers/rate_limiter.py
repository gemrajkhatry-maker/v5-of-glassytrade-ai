"""
Compatibility shim — providers/rate_limiter.py.

The canonical implementation has moved to:
    brokersv2.resilience.policies.rate_limit.ProviderRateLimiter

TokenBucketRateLimiter is re-exported here so all existing importers
continue to work without changes.
"""
import warnings as _warnings

_warnings.warn(
    "brokersv2.providers.rate_limiter is deprecated. "
    "Import from brokersv2.resilience.policies.rate_limit instead.",
    DeprecationWarning,
    stacklevel=2,
)

from brokersv2.resilience.policies.rate_limit import (  # noqa: E402, F401
    ProviderRateLimiter,
    ProviderRateLimiter as TokenBucketRateLimiter,
)

__all__ = ["TokenBucketRateLimiter", "ProviderRateLimiter"]
