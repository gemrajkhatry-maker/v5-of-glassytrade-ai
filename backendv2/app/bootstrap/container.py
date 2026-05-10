"""DI container bootstrap — registers core cross-cutting services."""

from __future__ import annotations

from app.application.di.container import Container
from app.core.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from app.core.event_store import EventStore
from app.core.feature_flags import FeatureFlags
from app.core.metrics import MetricsRegistry


def bootstrap_container() -> Container:
    """Create and populate the DI container with core services."""
    container = Container()
    container.register(MetricsRegistry, MetricsRegistry())
    container.register(
        CircuitBreaker,
        CircuitBreaker(
            CircuitBreakerConfig(
                failure_threshold=5,
                timeout_seconds=300.0,
                success_threshold=3,
            )
        ),
    )
    container.register(EventStore, EventStore())
    container.register(FeatureFlags, FeatureFlags())
    return container
