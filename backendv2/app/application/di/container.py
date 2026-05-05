"""Dependency Injection Container.

Constructor-based injection. No service locator.
Domain services receive ports (interfaces), not concrete implementations.
"""

from __future__ import annotations

import logging
from typing import Any, Callable, Type, TypeVar

logger = logging.getLogger(__name__)

T = TypeVar("T")


class Container:
    """Simple DI container with singleton and factory support.

    Usage:
        container = Container()

        # Register
        container.register(IBroker, DhanAdapter(...))
        container.register_factory(IStorage, lambda c: SQLiteStorage(...))

        # Resolve
        broker = container.resolve(IBroker)
    """

    def __init__(self):
        self._singletons: dict[type, Any] = {}
        self._factories: dict[type, Callable] = {}
        self._instances: dict[type, Any] = {}
        self._lazy: dict[type, Callable] = {}

    def register(self, interface: Type, instance: Any) -> None:
        """Register a singleton instance."""
        self._singletons[interface] = instance

    def register_factory(self, interface: Type, factory: Callable) -> None:
        """Register a factory function that creates the instance."""
        self._factories[interface] = factory

    def register_lazy(self, interface: Type, factory: Callable) -> None:
        """Register a lazy factory — called only on first resolve."""
        self._lazy[interface] = factory

    def resolve(self, interface: Type[T]) -> T:
        """Resolve an interface to its implementation."""
        # Check singletons
        if interface in self._singletons:
            return self._singletons[interface]

        # Check cached instances
        if interface in self._instances:
            return self._instances[interface]

        # Check lazy factories
        if interface in self._lazy:
            instance = self._lazy[interface](self)
            self._instances[interface] = instance
            del self._lazy[interface]
            logger.debug("Lazy-resolved %s", interface.__name__)
            return instance

        # Check factories
        if interface in self._factories:
            instance = self._factories[interface](self)
            self._instances[interface] = instance
            logger.debug("Factory-resolved %s", interface.__name__)
            return instance

        raise KeyError(f"No registration found for {interface.__name__}")

    def has(self, interface: Type) -> bool:
        """Check if an interface is registered."""
        return (
            interface in self._singletons
            or interface in self._factories
            or interface in self._lazy
            or interface in self._instances
        )

    def reset(self) -> None:
        """Reset all registrations (for testing)."""
        self._singletons.clear()
        self._factories.clear()
        self._instances.clear()
        self._lazy.clear()

    def get_stats(self) -> dict:
        return {
            "singletons": len(self._singletons),
            "factories": len(self._factories),
            "instances": len(self._instances),
            "lazy": len(self._lazy),
        }
