"""
Observability Framework for GlassyTrade AI Trading System

This module provides structured logging and tracing for all trading system components,
enabling AI agents to analyze behavior, diagnose problems, and recommend improvements.

Architecture:
- Event-based tracing across all components
- Structured JSONL logging with correlation IDs
- Model inference capture with feature attribution
- Trade reconstruction from journal entries
- Async logging to prevent performance degradation
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import time
import uuid
from abc import ABC, abstractmethod
from contextvars import ContextVar
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from enum import Enum
from pathlib import Path
from threading import Lock
from typing import Any, Callable
from functools import wraps

logger = logging.getLogger(__name__)

# Context variable for trace correlation
_correlation_id: ContextVar[str] = ContextVar("correlation_id", default="")
_span_stack: ContextVar[list[str]] = ContextVar("span_stack", default=[])


class EventType(str, Enum):
    """Event categories for observability."""

    MARKET_DATA = "MARKET_DATA"
    FEATURE_GENERATION = "FEATURE_GENERATION"
    MODEL_INFERENCE = "MODEL_INFERENCE"
    STRATEGY_DECISION = "STRATEGY_DECISION"
    RISK_VALIDATION = "RISK_VALIDATION"
    SIGNAL_GENERATED = "SIGNAL_GENERATED"
    ORDER_SUBMITTED = "ORDER_SUBMITTED"
    ORDER_FILLED = "ORDER_FILLED"
    ORDER_CANCELLED = "ORDER_CANCELLED"
    POSITION_OPENED = "POSITION_OPENED"
    POSITION_CLOSED = "POSITION_CLOSED"
    OVERSEER_ACTION = "OVERSEER_ACTION"


class LogLevel(str, Enum):
    """Structured log levels."""

    TRACE = "TRACE"
    DEBUG = "DEBUG"
    INFO = "INFO"
    WARNING = "WARNING"
    ERROR = "ERROR"
    CRITICAL = "CRITICAL"


@dataclass
class TraceContext:
    """Context for distributed tracing."""

    correlation_id: str = ""
    span_id: str = ""
    parent_span_id: str = ""
    component: str = ""
    timestamp: str = ""

    def to_dict(self) -> dict:
        return asdict(self)


@dataclass
class ObservabilityEvent:
    """Base event for observability logging."""

    event_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    timestamp: str = field(
        default_factory=lambda: datetime.now(timezone.utc).isoformat()
    )
    event_type: EventType = EventType.STRATEGY_DECISION
    level: LogLevel = LogLevel.INFO
    trace: TraceContext = field(default_factory=TraceContext)
    data: dict = field(default_factory=dict)
    errors: list[dict] = field(default_factory=list)
    latency_ms: float = 0.0

    def to_json(self) -> str:
        return json.dumps(asdict(self), default=str)

    def to_dict(self) -> dict:
        return asdict(self)


class ObservabilityWriter(ABC):
    """Abstract writer for observability events."""

    @abstractmethod
    def write(self, event: ObservabilityEvent) -> None:
        pass

    @abstractmethod
    def flush(self) -> None:
        pass


class AsyncJSONLWriter(ObservabilityWriter):
    """Async JSONL writer with batching for performance."""

    def __init__(
        self, filepath: str, batch_size: int = 100, flush_interval: float = 1.0
    ):
        self.filepath = Path(filepath)
        self.batch_size = batch_size
        self.flush_interval = flush_interval
        self._buffer: list[str] = []
        self._lock = Lock()
        self._last_flush = time.time()

        # Ensure directory exists
        self.filepath.parent.mkdir(parents=True, exist_ok=True)

    def write(self, event: ObservabilityEvent) -> None:
        with self._lock:
            self._buffer.append(event.to_json())

            # Flush if batch full or interval elapsed
            if (
                len(self._buffer) >= self.batch_size
                or (time.time() - self._last_flush) > self.flush_interval
            ):
                self._flush_unlocked()

    def _flush_unlocked(self) -> None:
        if self._buffer:
            with open(self.filepath, "a") as f:
                f.write("\n".join(self._buffer) + "\n")
            self._buffer.clear()
            self._last_flush = time.time()

    def flush(self) -> None:
        with self._lock:
            self._flush_unlocked()


class ObservabilityHub:
    """
    Central hub for all observability logging.

    Provides:
    - Structured event logging
    - Trace context management
    - Correlation ID propagation
    - Multiple writer support
    """

    _instance: "ObservabilityHub | None" = None
    _lock = Lock()

    def __init__(self):
        self._writers: dict[str, ObservabilityWriter] = {}
        self._filters: list[Callable[[ObservabilityEvent], bool]] = []
        self._enabled = True
        self._default_correlation: str | None = None

    @classmethod
    def get_instance(cls) -> "ObservabilityHub":
        if cls._instance is None:
            with cls._lock:
                if cls._instance is None:
                    cls._instance = cls()
        return cls._instance

    def add_writer(self, name: str, writer: ObservabilityWriter) -> None:
        self._writers[name] = writer

    def add_filter(self, filter_fn: Callable[[ObservabilityEvent], bool]) -> None:
        self._filters.append(filter_fn)

    def disable(self) -> None:
        self._enabled = False

    def enable(self) -> None:
        self._enabled = True

    def start_trace(
        self, component: str, correlation_id: str | None = None
    ) -> TraceContext:
        """Start a new trace span."""
        if correlation_id is None:
            correlation_id = str(uuid.uuid4())

        _correlation_id.set(correlation_id)

        parent_stack = _span_stack.get()
        parent_id = parent_stack[-1] if parent_stack else ""

        span_id = str(uuid.uuid4())[:8]
        _span_stack.set(parent_stack + [span_id])

        return TraceContext(
            correlation_id=correlation_id,
            span_id=span_id,
            parent_span_id=parent_id,
            component=component,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    def end_trace(self) -> None:
        """End current trace span."""
        stack = _span_stack.get()
        if stack:
            _span_stack.set(stack[:-1])

    def log_event(
        self,
        event_type: EventType,
        level: LogLevel,
        data: dict,
        component: str = "",
        latency_ms: float = 0.0,
        errors: list[dict] | None = None,
    ) -> None:
        """Log a structured observability event."""
        if not self._enabled:
            return

        # Apply filters
        trace = TraceContext(
            correlation_id=_correlation_id.get(),
            component=component,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

        event = ObservabilityEvent(
            event_type=event_type,
            level=level,
            trace=trace,
            data=data,
            errors=errors or [],
            latency_ms=latency_ms,
        )

        # Apply filters
        for filter_fn in self._filters:
            if not filter_fn(event):
                return

        # Write to all writers
        for writer in self._writers.values():
            try:
                writer.write(event)
            except Exception:
                logger.exception("Failed to write observability event")


# Decorator for automatic tracing
def traced(
    event_type: EventType,
    component: str = "",
    include_args: bool = True,
    include_result: bool = True,
):
    """Decorator to automatically trace function execution."""

    def decorator(func):
        @wraps(func)
        def sync_wrapper(*args, **kwargs):
            hub = ObservabilityHub.get_instance()
            trace = hub.start_trace(component or func.__module__)
            start_time = time.time()

            result = None
            errors = []
            try:
                result = func(*args, **kwargs)
                return result
            except Exception as e:
                errors.append(
                    {
                        "type": type(e).__name__,
                        "message": str(e),
                    }
                )
                raise
            finally:
                latency = (time.time() - start_time) * 1000

                data = {
                    "function": func.__name__,
                    "module": func.__module__,
                }

                if include_args and args:
                    data["args"] = str(args)[:500]
                if include_args and kwargs:
                    data["kwargs"] = str(kwargs)[:500]
                if include_result and result is not None:
                    data["result"] = str(result)[:500]

                hub.log_event(
                    event_type=event_type,
                    level=LogLevel.ERROR if errors else LogLevel.INFO,
                    data=data,
                    component=component or func.__module__,
                    latency_ms=latency,
                    errors=errors,
                )
                hub.end_trace()

        @wraps(func)
        async def async_wrapper(*args, **kwargs):
            hub = ObservabilityHub.get_instance()
            trace = hub.start_trace(component or func.__module__)
            start_time = time.time()

            result = None
            errors = []
            try:
                result = await func(*args, **kwargs)
                return result
            except Exception as e:
                errors.append(
                    {
                        "type": type(e).__name__,
                        "message": str(e),
                    }
                )
                raise
            finally:
                latency = (time.time() - start_time) * 1000

                data = {
                    "function": func.__name__,
                    "module": func.__module__,
                }

                if include_args and args:
                    data["args"] = str(args)[:500]
                if include_args and kwargs:
                    data["kwargs"] = str(kwargs)[:500]
                if include_result and result is not None:
                    data["result"] = str(result)[:500]

                hub.log_event(
                    event_type=event_type,
                    level=LogLevel.ERROR if errors else LogLevel.INFO,
                    data=data,
                    component=component or func.__module__,
                    latency_ms=latency,
                    errors=errors,
                )
                hub.end_trace()

        import asyncio

        if asyncio.iscoroutinefunction(func):
            return async_wrapper
        return sync_wrapper

    return decorator


def get_hub() -> ObservabilityHub:
    """Get the singleton observability hub."""
    return ObservabilityHub.get_instance()


def configure_observability(
    log_dir: str = "logs/observability",
    enable_all: bool = True,
) -> None:
    """
    Configure the observability system with default writers.

    Creates writers for:
    - data_events.log
    - feature_values.log
    - model_inference.log
    - model_explainability.log
    - strategy_decisions.log
    - risk_engine.log
    - order_lifecycle.log
    - event_flow.log
    """
    hub = ObservabilityHub.get_instance()

    if not enable_all:
        hub.disable()
        return

    log_path = Path(log_dir)
    log_path.mkdir(parents=True, exist_ok=True)

    # Add all log writers
    writers = {
        "data": str(log_path / "data_events.log"),
        "features": str(log_path / "feature_values.log"),
        "inference": str(log_path / "model_inference.log"),
        "explainability": str(log_path / "model_explainability.log"),
        "strategy": str(log_path / "strategy_decisions.log"),
        "risk": str(log_path / "risk_engine.log"),
        "orders": str(log_path / "order_lifecycle.log"),
        "flow": str(log_path / "event_flow.log"),
    }

    for name, path in writers.items():
        hub.add_writer(name, AsyncJSONLWriter(path))

    logger.info(f"Observability configured with {len(writers)} writers at {log_dir}")
