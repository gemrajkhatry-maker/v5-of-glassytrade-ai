"""
Correlation ID Context Management

Provides thread-safe correlation ID tracking for request tracing across
services and components. Each request gets a unique correlation ID that
propagates through the entire execution chain.

Example:
    >>> from brokers.broker.logging import set_correlation_id, get_correlation_id
    >>>
    >>> # Set correlation ID for a request
    >>> set_correlation_id("req-123-abc")
    >>>
    >>> # Use in logs
    >>> logger.info("Processing order", extra={"correlation_id": get_correlation_id()})
    >>>
    >>> # Context manager for automatic cleanup
    >>> with correlation_context("req-456-def"):
    ...     process_request()
"""

import contextvars
import functools
import inspect
import uuid
from contextlib import contextmanager
from typing import Optional

# Thread-safe correlation ID storage
_correlation_id: contextvars.ContextVar[Optional[str]] = contextvars.ContextVar(
    "correlation_id", default=None
)

# Execution hierarchy tracking
_execution_stack: contextvars.ContextVar[list] = contextvars.ContextVar(
    "execution_stack", default=[]
)


def get_correlation_id() -> Optional[str]:
    """
    Get the current correlation ID.

    Returns:
        Current correlation ID or None if not set

    Example:
        >>> corr_id = get_correlation_id()
        >>> if corr_id:
        ...     logger.info(f"Request {corr_id}: Processing")
    """
    return _correlation_id.get()


def set_correlation_id(correlation_id: Optional[str] = None) -> str:
    """
    Set the correlation ID for the current context.

    If no ID is provided, auto-generates a UUID.

    Args:
        correlation_id: Optional correlation ID to set. If None, generates UUID.

    Returns:
        The correlation ID that was set

    Example:
        >>> # Auto-generate
        >>> corr_id = set_correlation_id()
        >>> print(corr_id)  # '550e8400-e29b-41d4-a716-446655440000'
        >>>
        >>> # Set specific ID
        >>> set_correlation_id("user-request-123")
    """
    if correlation_id is None:
        correlation_id = str(uuid.uuid4())

    _correlation_id.set(correlation_id)
    return correlation_id


def clear_correlation_id() -> None:
    """
    Clear the current correlation ID.

    Example:
        >>> set_correlation_id("test-id")
        >>> get_correlation_id()  # 'test-id'
        >>> clear_correlation_id()
        >>> get_correlation_id()  # None
    """
    _correlation_id.set(None)


@contextmanager
def correlation_context(correlation_id: Optional[str] = None):
    """
    Context manager for correlation ID scoping.

    Automatically sets correlation ID on entry and restores previous
    value on exit.

    Args:
        correlation_id: Correlation ID to use. If None, generates UUID.

    Yields:
        The correlation ID being used

    Example:
        >>> with correlation_context("req-123") as cid:
        ...     logger.info(f"Processing {cid}")
        ...     process_data()
        >>> # correlation_id automatically cleared/restored
    """
    old_id = get_correlation_id()
    new_id = set_correlation_id(correlation_id)

    try:
        yield new_id
    finally:
        if old_id is not None:
            _correlation_id.set(old_id)
        else:
            clear_correlation_id()


class CorrelationIdMixin:
    """
    Mixin for classes that need correlation ID tracking.

    Provides easy access to correlation ID and automatic context management.

    Example:
        >>> class OrderService(CorrelationIdMixin):
        ...     def process_order(self, order_id: str):
        ...         with self.correlation_scope(f"order-{order_id}"):
        ...             self.validate_order()
        ...             self.execute_order()
    """

    @property
    def correlation_id(self) -> Optional[str]:
        """Get current correlation ID."""
        return get_correlation_id()

    def set_correlation_id(self, cid: Optional[str] = None) -> str:
        """Set correlation ID."""
        return set_correlation_id(cid)

    @contextmanager
    def correlation_scope(self, cid: Optional[str] = None):
        """Context manager for correlation ID."""
        with correlation_context(cid) as new_cid:
            yield new_cid


def get_execution_stack() -> list:
    """
    Get the current execution hierarchy stack.

    Returns:
        List of execution context names in order of entry

    Example:
        >>> push_execution_context("OrderService.process_order")
        >>> push_execution_context("ValidationService.validate")
        >>> get_execution_stack()
        ['OrderService.process_order', 'ValidationService.validate']
    """
    return _execution_stack.get().copy()


def push_execution_context(context_name: str) -> None:
    """
    Push a new execution context onto the stack.

    Args:
        context_name: Name of the execution context (e.g., "Class.method")

    Example:
        >>> push_execution_context("OrderService.process_order")
        >>> # do work
        >>> pop_execution_context()
    """
    stack = _execution_stack.get()
    stack.append(context_name)
    _execution_stack.set(stack)


def pop_execution_context() -> Optional[str]:
    """
    Pop the last execution context from the stack.

    Returns:
        The popped context name or None if stack empty

    Example:
        >>> push_execution_context("test")
        >>> pop_execution_context()  # 'test'
        >>> pop_execution_context()  # None
    """
    stack = _execution_stack.get()
    if stack:
        context = stack.pop()
        _execution_stack.set(stack)
        return context
    return None


def clear_execution_stack() -> None:
    """Clear the entire execution stack."""
    _execution_stack.set([])


@contextmanager
def execution_context(context_name: str):
    """
    Context manager for execution hierarchy tracking.

    Automatically pushes context on entry and pops on exit.

    Args:
        context_name: Name of the execution context

    Yields:
        Current execution stack

    Example:
        >>> with execution_context("OrderService.process"):
        ...     with execution_context("ValidationService.check"):
        ...         print(get_execution_stack())
        ...         # ['OrderService.process', 'ValidationService.check']
    """
    push_execution_context(context_name)
    try:
        yield get_execution_stack()
    finally:
        pop_execution_context()


def format_execution_path() -> str:
    """
    Format the execution stack as a path string.

    Returns:
        String representation of execution hierarchy

    Example:
        >>> push_execution_context("Broker.place_order")
        >>> push_execution_context("OrderValidator.validate")
        >>> format_execution_path()
        'Broker.place_order > OrderValidator.validate'
    """
    stack = get_execution_stack()
    return " > ".join(stack) if stack else "root"


class ExecutionTracer:
    """
    Decorator/context manager for automatic execution tracing.

    Tracks entry/exit of functions and logs execution hierarchy.

    Example:
        >>> tracer = ExecutionTracer(logger)
        >>>
        >>> @tracer.trace("OrderService.process")
        ... def process_order(order_id: str):
        ...     pass  # Logs entry and exit with correlation ID
        >>>
        >>> # Or as context manager
        >>> with tracer.context("processing"):
        ...     do_work()
    """

    def __init__(self, logger):
        self.logger = logger

    def trace(self, context_name: str):
        """Decorator for tracing function execution (sync and async)."""

        def decorator(func):
            if inspect.iscoroutinefunction(func):
                @functools.wraps(func)
                async def async_wrapper(*args, **kwargs):
                    cid = get_correlation_id() or "no-corr-id"
                    self.logger.debug(
                        f"[{cid}] ENTER {context_name}",
                        extra={
                            "correlation_id": cid,
                            "execution_context": context_name,
                            "execution_path": format_execution_path(),
                        },
                    )
                    push_execution_context(context_name)
                    try:
                        result = await func(*args, **kwargs)
                        self.logger.debug(
                            f"[{cid}] EXIT {context_name} - SUCCESS",
                            extra={
                                "correlation_id": cid,
                                "execution_context": context_name,
                            },
                        )
                        return result
                    except Exception as e:
                        self.logger.error(
                            f"[{cid}] EXIT {context_name} - ERROR: {e}",
                            exc_info=True,
                            extra={
                                "correlation_id": cid,
                                "execution_context": context_name,
                                "error": str(e),
                            },
                        )
                        raise
                    finally:
                        pop_execution_context()

                return async_wrapper
            else:
                @functools.wraps(func)
                def wrapper(*args, **kwargs):
                    cid = get_correlation_id() or "no-corr-id"
                    self.logger.debug(
                        f"[{cid}] ENTER {context_name}",
                        extra={
                            "correlation_id": cid,
                            "execution_context": context_name,
                            "execution_path": format_execution_path(),
                        },
                    )
                    push_execution_context(context_name)
                    try:
                        result = func(*args, **kwargs)
                        self.logger.debug(
                            f"[{cid}] EXIT {context_name} - SUCCESS",
                            extra={
                                "correlation_id": cid,
                                "execution_context": context_name,
                            },
                        )
                        return result
                    except Exception as e:
                        self.logger.error(
                            f"[{cid}] EXIT {context_name} - ERROR: {e}",
                            exc_info=True,
                            extra={
                                "correlation_id": cid,
                                "execution_context": context_name,
                                "error": str(e),
                            },
                        )
                        raise
                    finally:
                        pop_execution_context()

                return wrapper

        return decorator

    @contextmanager
    def context(self, context_name: str):
        """Context manager for execution tracing."""
        cid = get_correlation_id() or "no-corr-id"
        self.logger.debug(
            f"[{cid}] ENTER {context_name}",
            extra={
                "correlation_id": cid,
                "execution_context": context_name,
            },
        )
        with execution_context(context_name):
            try:
                yield
                self.logger.debug(
                    f"[{cid}] EXIT {context_name} - SUCCESS",
                    extra={"correlation_id": cid},
                )
            except Exception as e:
                self.logger.error(
                    f"[{cid}] EXIT {context_name} - ERROR: {e}",
                    extra={"correlation_id": cid, "error": str(e)},
                )
                raise
