"""
Brokers Logging Package

Provides structured logging with correlation ID tracking for request tracing
and execution hierarchy monitoring.

Quick Start:
    >>> from brokers.broker.logging import (
    ...     get_logger,
    ...     setup_logging,
    ...     correlation_context,
    ...     execution_context,
    ... )
    >>>
    >>> # Setup logging
    >>> setup_logging(level=logging.INFO, format_type="json")
    >>>
    >>> # Use in your code
    >>> logger = get_logger("MyService")
    >>>
    >>> with correlation_context("req-123"):
    ...     with execution_context("MyService.process"):
    ...         logger.info("Processing request", extra={"user_id": "abc"})
"""

# Context management
from .logging_context import (
    get_correlation_id,
    set_correlation_id,
    clear_correlation_id,
    correlation_context,
    CorrelationIdMixin,
    get_execution_stack,
    push_execution_context,
    pop_execution_context,
    clear_execution_stack,
    execution_context,
    format_execution_path,
    ExecutionTracer,
)

# Logging configuration
from .logging_config import (
    JSONFormatter,
    StructuredTextFormatter,
    setup_logging,
    get_logger,
    LoggerMixin,
)

__all__ = [
    # Context management
    "get_correlation_id",
    "set_correlation_id",
    "clear_correlation_id",
    "correlation_context",
    "CorrelationIdMixin",
    "get_execution_stack",
    "push_execution_context",
    "pop_execution_context",
    "clear_execution_stack",
    "execution_context",
    "format_execution_path",
    "ExecutionTracer",
    # Logging configuration
    "JSONFormatter",
    "StructuredTextFormatter",
    "setup_logging",
    "get_logger",
    "LoggerMixin",
]
