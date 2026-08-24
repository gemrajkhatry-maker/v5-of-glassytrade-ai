"""Dependency Injection Container.

A lightweight, OCP-compliant DI container that replaces the if/elif chain
in ServiceGraph._create_service(). Uses factory registration instead of
hardcoded type checks.

Usage:
    container = DIContainer()
    container.register_singleton(IBrokerPort, lambda c: DhanBrokerAdapter(c.resolve(Config)))
    container.register(ITradeRepository, lambda c: SQLiteStorageAdapter())

    broker = container.resolve(IBrokerPort)  # Lazy, singleton
"""

from __future__ import annotations

import threading
from contextlib import contextmanager
from typing import Any, Callable, TypeVar

T = TypeVar("T")
Factory = Callable[["DIContainer"], T]


class CircularDependencyError(Exception):
    """Raised when a circular dependency is detected during resolution."""


class DependencyNotFoundError(Exception):
    """Raised when no factory is registered for a type."""


class DIContainer:
    """Lightweight dependency injection container.

    Features:
        - OCP-compliant: no if/elif chains, just factory registration
        - Lazy resolution: instances created on first resolve()
        - Singleton by default: instance cached after first creation
        - Circular dependency detection: raises at resolution time
        - Thread-safe: uses RLock for concurrent resolution
        - Transient scope support: for per-request scopes

    Design:
        Factories receive the container as their only argument, enabling
        them to resolve their own dependencies. This avoids the need for
        complex type introspection and keeps the API simple.
    """

    def __init__(self) -> None:
        self._factories: dict[type, Factory] = {}
        self._singletons: dict[type, Any] = {}
        self._building: set[type] = set()
        self._lock = threading.RLock()

    def register(self, interface: type[T], factory: Factory[T]) -> None:
        """Register a factory. Each resolve() creates a new instance."""
        with self._lock:
            self._factories[interface] = factory
            # Remove any cached singleton for this interface
            self._singletons.pop(interface, None)

    def register_singleton(self, interface: type[T], factory: Factory[T]) -> None:
        """Register a singleton factory. Instance created once and cached."""
        with self._lock:
            self._factories[interface] = factory

    def resolve(self, interface: type[T]) -> T:
        """Resolve a dependency.

        For singletons: returns cached instance or creates and caches.
        For non-singletons: creates a new instance each time.

        Raises:
            CircularDependencyError: If a cycle is detected.
            DependencyNotFoundError: If no factory is registered.
        """
        with self._lock:
            # Check singleton cache
            if interface in self._singletons:
                return self._singletons[interface]

            # Cycle detection
            if interface in self._building:
                cycle = " -> ".join(
                    getattr(t, "__name__", str(t)) for t in self._building
                )
                raise CircularDependencyError(
                    f"Circular dependency detected: {getattr(interface, '__name__', interface)} "
                    f"is already being built. Building chain: {cycle}"
                )

            # Factory lookup
            if interface not in self._factories:
                raise DependencyNotFoundError(
                    f"No factory registered for {getattr(interface, '__name__', interface)}"
                )

            # Build the instance
            self._building.add(interface)
            try:
                factory = self._factories[interface]
                instance = factory(self)
                # Cache as singleton
                self._singletons[interface] = instance
                return instance
            finally:
                self._building.discard(interface)

    def resolve_transient(self, interface: type[T]) -> T:
        """Resolve a dependency without caching (always creates new instance)."""
        with self._lock:
            if interface not in self._factories:
                raise DependencyNotFoundError(
                    f"No factory registered for {getattr(interface, '__name__', interface)}"
                )
            factory = self._factories[interface]
            return factory(self)

    @contextmanager
    def transient_scope(self):
        """Create a transient resolution scope.

        Within the context, all resolutions are transient (no caching).
        Useful for request-scoped or tick-scoped objects.

        Usage:
            with container.transient_scope():
                handler = container.resolve(TickHandler)
                handler.process(tick)
        """
        with self._lock:
            cached = self._singletons.copy()
            self._singletons = {}
        try:
            yield self
        finally:
            with self._lock:
                self._singletons = cached

    def reset(self) -> None:
        """Reset all singletons. Useful for testing.

        Warning: Does NOT destroy existing instances. They will continue
        to work but new resolve() calls will create fresh instances.
        """
        with self._lock:
            self._singletons.clear()
            self._building.clear()

    def has(self, interface: type) -> bool:
        """Check if a factory is registered for the interface."""
        return interface in self._factories

    def registered_types(self) -> list[type]:
        """Return all registered interface types."""
        return list(self._factories.keys())
