"""
Compatibility shim — infrastructure/retry_manager.py.

The canonical implementation has moved to:
    brokersv2.resilience.policies.retry

All public names (RetryPolicy, RetryManager, RetryExhaustedError, RetryMetrics)
are re-exported here so existing importers continue to work without changes.

Usage note for callers that previously passed a pre-built coroutine:
    Old: await manager.execute_with_retry(my_coro)
    New: await manager.execute(lambda: my_async_func())
    The old single-coroutine path is preserved via execute_with_retry_operation()
    but will only succeed on the first attempt (can't re-run a spent coroutine).
"""
import warnings as _warnings

_warnings.warn(
    "brokersv2.infrastructure.retry_manager is deprecated. "
    "Import from brokersv2.resilience.policies.retry instead.",
    DeprecationWarning,
    stacklevel=2,
)

from brokersv2.resilience.policies.retry import (  # noqa: E402, F401
    RetryPolicy,
    RetryManager,
    RetryExhaustedError,
    RetryMetrics,
)

__all__ = ["RetryPolicy", "RetryManager", "RetryExhaustedError", "RetryMetrics"]
