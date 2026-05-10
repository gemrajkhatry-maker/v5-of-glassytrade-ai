"""
Compatibility shim — gateway/retry_manager.py.

The canonical implementation has moved to:
    brokersv2.resilience.policies.retry

RetryConfig is aliased to RetryPolicy (same fields, same semantics).
RetryManager is re-exported directly.

All call sites that previously used:
    manager.execute_with_retry(func, *args, **kwargs)
    manager.execute_with_retry_sync(func, *args, **kwargs)
continue to work without any changes.
"""
import warnings as _warnings

_warnings.warn(
    "brokersv2.gateway.retry_manager is deprecated. "
    "Import from brokersv2.resilience.policies.retry instead.",
    DeprecationWarning,
    stacklevel=2,
)

from brokersv2.resilience.policies.retry import (  # noqa: E402, F401
    RetryPolicy,
    RetryPolicy as RetryConfig,   # gateway called it RetryConfig
    RetryManager,
    RetryExhaustedError,
    RetryMetrics,
)

__all__ = [
    "RetryConfig",
    "RetryPolicy",
    "RetryManager",
    "RetryExhaustedError",
    "RetryMetrics",
]
