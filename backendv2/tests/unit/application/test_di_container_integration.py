"""Tests for DI Container integration — wiring core services.

Behavior: DI container registers and resolves core services,
injecting them into FastAPI app state for request handlers.
"""
from __future__ import annotations

import pytest

from app.application.di.container import Container
from app.core.metrics import MetricsRegistry
from app.core.circuit_breaker import CircuitBreaker, CircuitBreakerConfig
from app.core.event_store import EventStore
from app.core.feature_flags import FeatureFlags


class TestDIContainerIntegration:
    """Tests for DI container wiring core services."""

    def test_register_and_resolve_singleton(self):
        """Should register and resolve a singleton instance."""
        container = Container()
        metrics = MetricsRegistry()
        
        container.register(MetricsRegistry, metrics)
        resolved = container.resolve(MetricsRegistry)
        
        assert resolved is metrics

    def test_register_and_resolve_multiple_services(self):
        """Should register and resolve multiple core services."""
        container = Container()
        
        container.register(MetricsRegistry, MetricsRegistry())
        container.register(CircuitBreaker, CircuitBreaker())
        container.register(EventStore, EventStore())
        container.register(FeatureFlags, FeatureFlags())
        
        assert container.resolve(MetricsRegistry) is not None
        assert container.resolve(CircuitBreaker) is not None
        assert container.resolve(EventStore) is not None
        assert container.resolve(FeatureFlags) is not None

    def test_resolve_returns_same_instance(self):
        """Should return the same instance for multiple resolves."""
        container = Container()
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=3))
        
        container.register(CircuitBreaker, cb)
        
        first = container.resolve(CircuitBreaker)
        second = container.resolve(CircuitBreaker)
        
        assert first is second
        assert first.state is not None  # Verify it's a valid CircuitBreaker

    def test_has_method_checks_registration(self):
        """Should return True if interface is registered."""
        container = Container()
        
        assert not container.has(MetricsRegistry)
        
        container.register(MetricsRegistry, MetricsRegistry())
        
        assert container.has(MetricsRegistry)
        assert not container.has(CircuitBreaker)

    def test_reset_clears_all_registrations(self):
        """Should clear all registrations on reset."""
        container = Container()
        container.register(MetricsRegistry, MetricsRegistry())
        container.register(CircuitBreaker, CircuitBreaker())
        
        container.reset()
        
        assert not container.has(MetricsRegistry)
        assert not container.has(CircuitBreaker)

    def test_factory_registration(self):
        """Should create new instances via factory."""
        container = Container()
        call_count = [0]
        
        def create_metrics(c: Container) -> MetricsRegistry:
            call_count[0] += 1
            return MetricsRegistry()
        
        container.register_factory(MetricsRegistry, create_metrics)
        
        first = container.resolve(MetricsRegistry)
        second = container.resolve(MetricsRegistry)  # Should use cached instance
        
        assert first is second
        assert call_count[0] == 1  # Factory called only once

    def test_lazy_registration(self):
        """Should defer instantiation until first resolve."""
        container = Container()
        call_count = [0]
        
        def create_cb(c: Container) -> CircuitBreaker:
            call_count[0] += 1
            return CircuitBreaker()
        
        container.register_lazy(CircuitBreaker, create_cb)
        
        assert call_count[0] == 0  # Not created yet
        
        cb = container.resolve(CircuitBreaker)
        
        assert call_count[0] == 1
        assert cb is not None

    def test_key_error_on_unregistered(self):
        """Should raise KeyError for unregistered interface."""
        container = Container()
        
        with pytest.raises(KeyError, match="No registration found for"):
            container.resolve(MetricsRegistry)

    def test_get_stats(self):
        """Should return registration statistics."""
        container = Container()
        container.register(MetricsRegistry, MetricsRegistry())
        container.register(CircuitBreaker, CircuitBreaker())
        
        stats = container.get_stats()
        
        assert stats["singletons"] == 2
        assert stats["factories"] == 0
        assert stats["instances"] == 0
        assert stats["lazy"] == 0
