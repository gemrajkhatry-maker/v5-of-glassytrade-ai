"""Standardized error handling utilities.

This module provides consistent error handling patterns across
the codebase, improving debugging and error propagation.
"""

from __future__ import annotations

import functools
import logging
import traceback
from typing import Any, Callable, Dict, Optional, TypeVar

logger = logging.getLogger(__name__)

F = TypeVar('F', bound=Callable[..., Any])


class TradingError(Exception):
    """Base exception for trading-related errors."""
    
    def __init__(
        self,
        message: str,
        error_code: str = "TRADING_ERROR",
        context: Optional[Dict[str, Any]] = None,
    ):
        super().__init__(message)
        self.error_code = error_code
        self.context = context or {}
        self.message = message


class SignalError(TradingError):
    """Signal construction or validation error."""
    
    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(message, "SIGNAL_ERROR", context)


class GateError(TradingError):
    """Entry gate validation error."""
    
    def __init__(self, message: str, gate_name: str, context: Optional[Dict[str, Any]] = None):
        ctx = context or {}
        ctx["gate_name"] = gate_name
        super().__init__(message, "GATE_ERROR", ctx)


class LLMError(TradingError):
    """LLM inference error."""
    
    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(message, "LLM_ERROR", context)


class StorageError(TradingError):
    """Storage/persistence error."""
    
    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(message, "STORAGE_ERROR", context)


class RiskError(TradingError):
    """Risk management error."""
    
    def __init__(self, message: str, context: Optional[Dict[str, Any]] = None):
        super().__init__(message, "RISK_ERROR", context)


def handle_errors(
    error_types: tuple[type[Exception], ...] = (Exception,),
    default_return: Any = None,
    log_level: int = logging.ERROR,
    reraise: bool = False,
) -> Callable[[F], F]:
    """Decorator for standardized error handling.
    
    Args:
        error_types: Tuple of exception types to catch
        default_return: Default value to return on error
        log_level: Logging level for errors
        reraise: Whether to reraise the exception after logging
    
    Returns:
        Decorated function with error handling
    """
    def decorator(func: F) -> F:
        @functools.wraps(func)
        def wrapper(*args, **kwargs):
            try:
                return func(*args, **kwargs)
            except error_types as e:
                # Build context
                context = {
                    "function": func.__name__,
                    "module": func.__module__,
                    "args": str(args)[:200],  # Truncate for logging
                    "kwargs": str(kwargs)[:200],
                }
                
                # Log error
                logger.log(
                    log_level,
                    "Error in %s.%s: %s",
                    func.__module__,
                    func.__name__,
                    str(e),
                    exc_info=True,
                    extra={"context": context},
                )
                
                if reraise:
                    raise
                
                return default_return
        
        return wrapper  # type: ignore
    return decorator


def log_and_continue(
    message: str,
    level: int = logging.WARNING,
    exc_info: bool = True,
    **extra_context,
) -> None:
    """Log an error and continue execution.
    
    Use this for non-critical errors where execution should continue.
    """
    logger.log(
        level,
        message,
        exc_info=exc_info,
        extra={"context": extra_context},
    )


def safe_execute(
    func: Callable[..., Any],
    *args,
    default_return: Any = None,
    error_message: str = "Operation failed",
    **kwargs,
) -> Any:
    """Safely execute a function with error handling.
    
    Args:
        func: Function to execute
        *args: Positional arguments for function
        default_return: Default value on error
        error_message: Message to log on error
        **kwargs: Keyword arguments for function
    
    Returns:
        Function result or default_return on error
    """
    try:
        return func(*args, **kwargs)
    except Exception as e:
        logger.error(
            "%s: %s",
            error_message,
            str(e),
            exc_info=True,
            extra={
                "function": func.__name__,
                "args": str(args)[:200],
                "kwargs": str(kwargs)[:200],
            },
        )
        return default_return


class ErrorContext:
    """Context manager for error handling with automatic logging."""
    
    def __init__(
        self,
        operation: str,
        reraise: bool = False,
        default_return: Any = None,
    ):
        self.operation = operation
        self.reraise = reraise
        self.default_return = default_return
        self.error: Exception | None = None
    
    def __enter__(self):
        return self
    
    def __exit__(self, exc_type, exc_val, exc_tb):
        if exc_type is not None:
            self.error = exc_val
            logger.error(
                "Error during %s: %s",
                self.operation,
                str(exc_val),
                exc_info=True,
            )
            return not self.reraise  # Suppress if not reraising
        return False