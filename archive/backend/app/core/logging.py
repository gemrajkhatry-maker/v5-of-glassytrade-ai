"""Structured logging with correlation IDs and context."""

import json
import logging
import sys
from datetime import datetime, timezone
from typing import Any

from app.core.correlation import get_correlation_id


class StructuredFormatter(logging.Formatter):
    """JSON formatter for structured logging."""
    
    def format(self, record: logging.LogRecord) -> str:
        # Base log entry
        log_data = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "level": record.levelname,
            "logger": record.name,
            "message": record.getMessage(),
            "correlation_id": get_correlation_id(),
        }
        
        # Add exception info if present
        if record.exc_info:
            log_data["exception"] = self.formatException(record.exc_info)
        
        # Add extra fields
        extra_fields = ["symbol", "phase", "stage", "component", "duration_ms", "error_type"]
        for field in extra_fields:
            if hasattr(record, field):
                log_data[field] = getattr(record, field)
        
        return json.dumps(log_data, default=str)


def setup_logging() -> None:
    """Configure structured logging for the application."""
    handler = logging.StreamHandler(sys.stdout)
    handler.setFormatter(StructuredFormatter())
    
    root_logger = logging.getLogger()
    root_logger.handlers.clear()
    root_logger.addHandler(handler)
    root_logger.setLevel(logging.INFO)
    
    # Reduce noise from third-party libraries
    logging.getLogger("uvicorn").setLevel(logging.WARNING)
    logging.getLogger("websockets").setLevel(logging.WARNING)


class LoggerAdapter(logging.LoggerAdapter):
    """Logger adapter with structured extra fields."""
    
    def process(self, msg: str, kwargs: dict) -> tuple[str, dict]:
        # Ensure extra fields are included
        kwargs.setdefault("extra", {})
        kwargs["extra"]["correlation_id"] = get_correlation_id()
        return msg, kwargs


def get_logger(name: str) -> LoggerAdapter:
    """Get a structured logger with correlation ID support."""
    return LoggerAdapter(logging.getLogger(name), {})


# Convenience functions for common operations
def log_info(component: str, message: str, **extra: Any) -> None:
    """Log an info message with context."""
    logger = get_logger(component)
    extra["component"] = component
    logger.info(message, extra=extra)


def log_error(component: str, message: str, error: Exception | None = None, **extra: Any) -> None:
    """Log an error message with context."""
    logger = get_logger(component)
    extra["component"] = component
    extra["error_type"] = type(error).__name__ if error else None
    if error and not extra.get("extra"):
        extra["exc_info"] = error
    logger.error(message, extra=extra)