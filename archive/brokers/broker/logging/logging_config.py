"""
Structured Logging Configuration

Provides JSON and text format logging with correlation ID support.
All logs include request tracing information.

Example:
    >>> from brokers.broker.logging import get_logger, correlation_context
    >>>
    >>> logger = get_logger("OrderService")
    >>>
    >>> with correlation_context("req-123"):
    ...     logger.info("Processing order", extra={"order_id": "ABC123"})
    ...     # Output: {"timestamp": "2025-01-15T10:30:00", "level": "INFO",
    ...     #          "logger": "OrderService", "correlation_id": "req-123",
    ...     #          "message": "Processing order", "order_id": "ABC123"}
"""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from .logging_context import get_correlation_id, get_execution_stack


class JSONFormatter(logging.Formatter):
    """
    JSON log formatter with correlation ID and execution context.

    Outputs structured JSON logs for log aggregation and analysis.

    Example Output:
        {
            "timestamp": "2025-01-15T10:30:00.123456",
            "level": "INFO",
            "logger": "DhanBroker",
            "correlation_id": "550e8400-e29b-41d4-a716-446655440000",
            "execution_stack": ["DhanBroker.get_quote", "HttpClient.get"],
            "message": "Retrieved quote for RELIANCE",
            "symbol": "RELIANCE",
            "ltp": 2456.50
        }
    """

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as JSON."""
        log_data: Dict[str, Any] = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
        }

        # Add correlation ID if available
        corr_id = get_correlation_id()
        if corr_id:
            log_data["correlation_id"] = corr_id

        # Add execution stack
        exec_stack = get_execution_stack()
        if exec_stack:
            log_data["execution_stack"] = exec_stack

        # Add extra fields from record
        for key, value in record.__dict__.items():
            if key not in [
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "message",
            ]:
                log_data[key] = value

        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)

        return json.dumps(log_data, default=str)


class StructuredTextFormatter(logging.Formatter):
    """
    Text log formatter with correlation ID and structured information.

    Human-readable format with all context information.

    Example Output:
        2025-01-15 10:30:00 [INFO] [corr:550e8400] DhanBroker: Processing order | symbol=RELIANCE ltp=2456.50
    """

    def __init__(
        self,
        fmt: Optional[str] = None,
        datefmt: Optional[str] = None,
        include_correlation: bool = True,
        include_stack: bool = False,
    ):
        super().__init__(fmt, datefmt)
        self.include_correlation = include_correlation
        self.include_stack = include_stack

    def format(self, record: logging.LogRecord) -> str:
        """Format log record as structured text."""
        parts = []

        # Timestamp
        parts.append(self.formatTime(record, self.datefmt))

        # Level
        parts.append(f"[{record.levelname}]")

        # Correlation ID
        if self.include_correlation:
            corr_id = get_correlation_id()
            if corr_id:
                short_id = corr_id[:8] if len(corr_id) > 8 else corr_id
                parts.append(f"[corr:{short_id}]")

        # Logger name
        parts.append(f"{record.name}:")

        # Message
        parts.append(record.getMessage())

        # Extra fields
        extras = []
        for key, value in record.__dict__.items():
            if key not in [
                "name",
                "msg",
                "args",
                "levelname",
                "levelno",
                "pathname",
                "filename",
                "module",
                "exc_info",
                "exc_text",
                "stack_info",
                "lineno",
                "funcName",
                "created",
                "msecs",
                "relativeCreated",
                "thread",
                "threadName",
                "processName",
                "process",
                "message",
            ]:
                extras.append(f"{key}={value}")

        if extras:
            parts.append("| " + " ".join(extras))

        # Execution stack
        if self.include_stack:
            stack = get_execution_stack()
            if stack:
                parts.append(f"[stack: {' > '.join(stack)}]")

        # Exception
        if record.exc_info:
            parts.append("\n" + self.formatException(record.exc_info))

        return " ".join(parts)


def setup_logging(
    level: int = logging.INFO,
    format_type: str = "json",
    include_correlation: bool = True,
    include_stack: bool = False,
) -> None:
    """
    Setup structured logging for the application.

    Args:
        level: Logging level (DEBUG, INFO, WARNING, ERROR)
        format_type: "json" or "text"
        include_correlation: Include correlation ID in logs
        include_stack: Include execution stack in logs

    Example:
        >>> setup_logging(level=logging.DEBUG, format_type="json")
        >>> logger = logging.getLogger("MyApp")
        >>> logger.info("Application started")
    """
    # Create handler
    handler = logging.StreamHandler(sys.stdout)

    # Set formatter
    if format_type == "json":
        handler.setFormatter(JSONFormatter())
    else:
        handler.setFormatter(
            StructuredTextFormatter(
                include_correlation=include_correlation, include_stack=include_stack
            )
        )

    # Configure root logger
    root_logger = logging.getLogger()
    root_logger.setLevel(level)
    root_logger.handlers = []  # Clear existing handlers
    root_logger.addHandler(handler)

    # Configure brokers logger
    brokers_logger = logging.getLogger("brokers")
    brokers_logger.setLevel(level)


def get_logger(name: str) -> logging.Logger:
    """
    Get a logger with the brokers namespace.

    Args:
        name: Logger name (e.g., "DhanBroker", "OrderService")

    Returns:
        Configured logger instance

    Example:
        >>> logger = get_logger("DhanBroker")
        >>> logger.info("Connected to API")
    """
    return logging.getLogger(f"brokers.{name}")


class LoggerMixin:
    """
    Mixin that provides structured logging capabilities to classes.

    Automatically includes correlation ID and class context in all logs.

    Example:
        >>> class OrderService(LoggerMixin):
        ...     def __init__(self):
        ...         super().__init__()
        ...
        ...     def process_order(self, order_id: str):
        ...         self.logger.info("Processing order", extra={"order_id": order_id})
        ...         # Logs: {"logger": "OrderService", "correlation_id": "...",
        ...         #       "message": "Processing order", "order_id": "123"}
    """

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self._logger: Optional[logging.Logger] = None

    @property
    def logger(self) -> logging.Logger:
        """Get logger for this class."""
        if self._logger is None:
            class_name = self.__class__.__name__
            module_name = self.__class__.__module__
            self._logger = get_logger(f"{module_name}.{class_name}")
        return self._logger

    def log_info(self, message: str, **extra) -> None:
        """Log info with extra context."""
        self.logger.info(message, extra=extra)

    def log_warning(self, message: str, **extra) -> None:
        """Log warning with extra context."""
        self.logger.warning(message, extra=extra)

    def log_error(self, message: str, **extra) -> None:
        """Log error with extra context."""
        self.logger.error(message, extra=extra)

    def log_debug(self, message: str, **extra) -> None:
        """Log debug with extra context."""
        self.logger.debug(message, extra=extra)
