"""Tests for core infrastructure components."""
import pytest
import asyncio
from app.core.core_components import (
    CircuitBreaker, CircuitBreakerConfig, CircuitState,
    EventStore, Event, MetricsRegistry, FeatureFlags, Feature
)


class TestCircuitBreaker:
    """Tests for circuit breaker."""
    
    def test_starts_closed(self):
        cb = CircuitBreaker()
        assert cb.state == CircuitState.CLOSED
        assert not cb.is_open
    
    def test_opens_after_failures(self):
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=3))
        cb.record_failure()
        cb.record_failure()
        cb.record_failure()
        assert cb.state == CircuitState.OPEN
        assert cb.is_open
    
    def test_resets_after_timeout(self):
        import time
        cb = CircuitBreaker(CircuitBreakerConfig(timeout_seconds=0.1, failure_threshold=1))
        cb.record_failure()
        assert cb.is_open
        time.sleep(0.2)
        assert cb.state == CircuitState.HALF_OPEN
    
    @pytest.mark.asyncio
    async def test_decorator(self):
        cb = CircuitBreaker(CircuitBreakerConfig(failure_threshold=2))
        
        @cb
        async def failing_func():
            raise ValueError("fail")
        
        # First failure
        with pytest.raises(ValueError):
            await failing_func()
        
        # Second failure opens circuit
        with pytest.raises(ValueError):
            await failing_func()
        
        # Circuit is now open - should raise RuntimeError
        with pytest.raises(RuntimeError, match="OPEN"):
            await failing_func()


class TestEventStore:
    """Tests for event store."""
    
    def test_stores_and_tracks_events(self):
        store = EventStore()
        
        store.append(Event("TICK", 1234567890.0, {"price": 50000}))
        store.append(Event("SIGNAL", 1234567891.0, {"type": "LONG"}))
        
        events = store.read_all()
        assert len(events) == 2
    
    def test_filters_by_type(self):
        store = EventStore()
        store.append(Event("TICK", 1.0, {}))
        store.append(Event("SIGNAL", 2.0, {}))
        
        ticks = store.get_events("TICK")
        assert len(ticks) == 1


class TestMetricsRegistry:
    """Tests for metrics registry."""
    
    def test_counter(self):
        registry = MetricsRegistry()
        registry.counter("trades")
        registry.counter("trades")
        assert registry.get_counter("trades") == 2
    
    def test_gauge(self):
        registry = MetricsRegistry()
        registry.gauge("pnl", 100.0)
        snapshot = registry.snapshot()
        assert snapshot["gauges"]["pnl"] == 100.0


class TestFeatureFlags:
    """Tests for feature flags."""
    
    def test_default_disabled(self):
        flags = FeatureFlags()
        assert not flags.is_enabled(Feature.TRADING_ENABLED)
    
    def test_enable_disable(self):
        flags = FeatureFlags()
        flags.enable(Feature.TRADING_ENABLED)
        assert flags.is_enabled(Feature.TRADING_ENABLED)
        
        flags.disable(Feature.TRADING_ENABLED)
        assert not flags.is_enabled(Feature.TRADING_ENABLED)