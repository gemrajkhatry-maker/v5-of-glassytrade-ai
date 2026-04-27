"""Structured logging utilities."""

import logging
import threading
from contextvars import ContextVar
from typing import Any

# Thread-safe trading context storage
_trading_context: ContextVar[dict[str, Any]] = ContextVar("trading_context", default={})


class TradingContextFilter(logging.Filter):
    """Logging filter that injects trading context (symbol, session_id) into log records."""

    def filter(self, record: logging.LogRecord) -> bool:
        ctx = _trading_context.get()
        record.symbol = ctx.get("symbol", "-")
        record.session_id = ctx.get("session_id", "-")
        return True


def set_trading_context(**kwargs: Any) -> None:
    """Set trading context for the current thread/coroutine.

    Usage:
        with trading_context(symbol="CRUDEOILM25APR"):
            logger.info("Processing tick")
    """
    current = _trading_context.get().copy()
    current.update(kwargs)
    token = _trading_context.set(current)
    return token


def clear_trading_context(token=None) -> None:
    """Clear trading context, optionally restoring a previous token."""
    if token is not None:
        _trading_context.reset(token)
    else:
        _trading_context.set({})


class trading_context:
    """Context manager for trading context in logs.

    Usage:
        with trading_context(symbol="CRUDEOILM25APR"):
            logger.info("Processing tick")  # includes symbol=CRUDEOILM25APR
    """

    def __init__(self, **kwargs: Any) -> None:
        self._kwargs = kwargs
        self._token = None

    def __enter__(self) -> "trading_context":
        self._token = set_trading_context(**self._kwargs)
        return self

    def __exit__(self, *args: Any) -> None:
        clear_trading_context(self._token)


def configure_structured_logging(handler: logging.Handler | None = None) -> None:
    """Add TradingContextFilter to the root logger.

    Usage in main.py:
        from app.shared.logging import configure_structured_logging
        configure_structured_logging()
    """
    root = logging.getLogger()
    f = TradingContextFilter()
    root.addFilter(f)

    # Add context to formatter if handler uses a format string
    if handler is None:
        for h in root.handlers:
            if isinstance(h.formatter, logging.Formatter):
                fmt = h.formatter._fmt
                if "%(symbol)" not in fmt:
                    h.formatter._fmt = fmt.replace(
                        "%(message)s", "[%(symbol)s] %(message)s"
                    )
    elif isinstance(handler.formatter, logging.Formatter):
        fmt = handler.formatter._fmt
        if "%(symbol)" not in fmt:
            handler.formatter._fmt = fmt.replace(
                "%(message)s", "[%(symbol)s] %(message)s"
            )
