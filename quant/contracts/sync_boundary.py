"""Async boundary guards for strict sync/async adapter contracts."""

from __future__ import annotations

import inspect
from typing import Any, Callable


def ensure_sync_adapter_result(
    adapter_name: str,
    callable_obj: Callable[..., Any],
    *args,
    **kwargs,
) -> Any:
    """Invoke a sync adapter/broker method and fail fast on coroutine misuse."""
    if inspect.iscoroutinefunction(callable_obj):
        raise RuntimeError(
            f"{adapter_name} is defined as coroutine; this call path requires sync behavior"
        )

    result = callable_obj(*args, **kwargs)
    if inspect.isawaitable(result):
        if inspect.iscoroutine(result):
            result.close()
        raise RuntimeError(
            f"{adapter_name} returned awaitable in sync context; use async boundary or offload"
        )
    return result


def ensure_async_adapter_result(
    adapter_name: str,
    callable_obj: Callable[..., Any],
    *args,
    **kwargs,
) -> Any:
    """Invoke an async adapter/broker method and fail fast on sync mismatch."""
    if not inspect.iscoroutinefunction(callable_obj):
        raise RuntimeError(
            f"{adapter_name} is defined as sync; this async path expects awaitable return"
        )

    return callable_obj(*args, **kwargs)
