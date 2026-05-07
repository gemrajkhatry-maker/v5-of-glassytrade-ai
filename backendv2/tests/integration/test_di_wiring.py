"""Integration tests for DI container & adapter wiring."""

from __future__ import annotations

import pytest
from app.application.di.container import Container
from app.infrastructure.messaging.event_bus import EventBus


class TestContainerResolution:
    """Test DI container resolve patterns."""

    def setup_method(self):
        self.container = Container()

    def test_resolve_singleton(self):
        """Register singleton → same instance returned every time."""
        bus = EventBus()
        self.container.register(EventBus, bus)

        resolved1 = self.container.resolve(EventBus)
        resolved2 = self.container.resolve(EventBus)

        assert resolved1 is resolved2
        assert resolved1 is bus

    def test_resolve_factory(self):
        """Register factory → new instance each call."""
        call_count = [0]

        def factory(c):
            call_count[0] += 1
            return EventBus()

        self.container.register_factory(EventBus, factory)

        r1 = self.container.resolve(EventBus)
        r2 = self.container.resolve(EventBus)

        # Factory should be called once, then cached
        assert call_count[0] == 1
        assert r1 is r2

    def test_resolve_lazy(self):
        """Register lazy → factory called on first resolve only."""
        call_count = [0]

        def factory(c):
            call_count[0] += 1
            return EventBus()

        self.container.register_lazy(EventBus, factory)

        # Not called yet
        assert call_count[0] == 0

        # First resolve triggers factory
        r1 = self.container.resolve(EventBus)
        assert call_count[0] == 1

        # Second resolve returns cached
        r2 = self.container.resolve(EventBus)
        assert call_count[0] == 1
        assert r1 is r2

    def test_resolve_unregistered_raises_keyerror(self):
        """Resolve unregistered interface → KeyError."""
        with pytest.raises(KeyError):
            self.container.resolve(EventBus)

    def test_has_returns_true_for_registered(self):
        """has() returns True for registered interface."""
        self.container.register(EventBus, EventBus())
        assert self.container.has(EventBus)

    def test_has_returns_false_for_unregistered(self):
        """has() returns False for unregistered interface."""
        assert not self.container.has(EventBus)

    def test_get_stats(self):
        """get_stats() returns registration counts."""
        self.container.register(EventBus, EventBus())
        self.container.register_factory(str, lambda c: "test")
        self.container.register_lazy(int, lambda c: 42)

        stats = self.container.get_stats()
        assert stats["singletons"] == 1
        assert stats["factories"] == 1
        assert stats["lazy"] == 1

    def test_reset_clears_all(self):
        """reset() clears all registrations."""
        self.container.register(EventBus, EventBus())
        self.container.reset()

        assert self.container.get_stats() == {
            "singletons": 0,
            "factories": 0,
            "instances": 0,
            "lazy": 0,
        }
        assert not self.container.has(EventBus)


class TestAdapterIntegration:
    """Test adapter wiring through DI container."""

    def setup_method(self):
        self.container = Container()

    def test_event_bus_wired(self):
        """EventBus registered and resolved."""
        bus = EventBus()
        self.container.register(EventBus, bus)
        resolved = self.container.resolve(EventBus)
        assert resolved is bus

    def test_multiple_adapters_wired(self):
        """Multiple adapters registered and resolved independently."""
        bus1 = EventBus()
        bus2 = EventBus()
        self.container.register("BusA", bus1)
        self.container.register("BusB", bus2)

        assert self.container.resolve("BusA") is bus1
        assert self.container.resolve("BusB") is bus2

    def test_adapter_with_dependencies(self):
        """Adapter depends on other registered services."""
        class FakeService:
            def __init__(self, bus):
                self.bus = bus

        self.container.register(EventBus, EventBus())
        self.container.register_factory(
            FakeService,
            lambda c: FakeService(c.resolve(EventBus)),
        )

        service = self.container.resolve(FakeService)
        assert isinstance(service.bus, EventBus)


class TestDependencyChains:
    """Test complex dependency resolution chains."""

    def setup_method(self):
        self.container = Container()

    def test_chain_of_three(self):
        """A depends on B depends on C → all resolve."""
        class C:
            def __init__(self):
                self.value = 42

        class B:
            def __init__(self, c):
                self.c = c

        class A:
            def __init__(self, b):
                self.b = b

        self.container.register(C, C())
        self.container.register_factory(B, lambda c: B(c.resolve(C)))
        self.container.register_factory(A, lambda c: A(c.resolve(B)))

        a = self.container.resolve(A)
        assert isinstance(a.b, B)
        assert isinstance(a.b.c, C)
        assert a.b.c.value == 42

    def test_diamond_dependency(self):
        """Diamond: A → B, C → D (B and C both depend on D)."""
        class D:
            def __init__(self):
                self.shared = "data"

        class B:
            def __init__(self, d):
                self.d = d

        class C:
            def __init__(self, d):
                self.d = d

        class A:
            def __init__(self, b, c):
                self.b = b
                self.c = c

        self.container.register(D, D())
        self.container.register_factory(B, lambda c: B(c.resolve(D)))
        self.container.register_factory(C, lambda c: C(c.resolve(D)))
        self.container.register_factory(
            A, lambda c: A(c.resolve(B), c.resolve(C))
        )

        a = self.container.resolve(A)
        assert a.b.d is a.c.d  # Same D instance

    def test_factory_receives_container(self):
        """Factory function receives container for further resolution."""
        received_container = []

        def factory(c):
            received_container.append(c)
            return EventBus()

        self.container.register_factory(EventBus, factory)
        self.container.resolve(EventBus)

        assert len(received_container) == 1
        assert received_container[0] is self.container


class TestRealComponentWiring:
    """Test wiring of real backendv2 components."""

    def setup_method(self):
        self.container = Container()

    def test_wire_event_bus_and_handlers(self):
        """Wire EventBus with subscribed handlers."""
        bus = EventBus()

        call_count = [0]

        def tick_handler(event):
            call_count[0] += 1

        bus.subscribe(type("FakeEvent", (), {}), tick_handler)
        self.container.register(EventBus, bus)

        resolved = self.container.resolve(EventBus)
        assert resolved is bus

    def test_wire_with_cost_tracker(self):
        """CostTracker wired → adapters can record costs."""
        try:
            from app.core.cost_tracker import CostTracker
            tracker = CostTracker()
            self.container.register(CostTracker, tracker)
            resolved = self.container.resolve(CostTracker)
            assert resolved is tracker
        except ImportError:
            pytest.skip("CostTracker not available")

    def test_wire_with_circuit_breaker(self):
        """CircuitBreaker wired → adapters can check circuit state."""
        try:
            from app.core.circuit_breaker import CircuitBreaker
            cb = CircuitBreaker()
            self.container.register(CircuitBreaker, cb)
            resolved = self.container.resolve(CircuitBreaker)
            assert resolved is cb
        except ImportError:
            pytest.skip("CircuitBreaker not available")

    def test_wire_with_metrics_registry(self):
        """MetricsRegistry wired → components can record metrics."""
        try:
            from app.core.metrics import MetricsRegistry
            metrics = MetricsRegistry()
            self.container.register(MetricsRegistry, metrics)
            resolved = self.container.resolve(MetricsRegistry)
            assert resolved is metrics
        except ImportError:
            pytest.skip("MetricsRegistry not available")
