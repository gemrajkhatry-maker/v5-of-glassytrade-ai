"""Event bus port — defines the interface for publishing and subscribing to domain events."""
from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Callable, List, Type

from app.domain.shared.event.base import DomainEvent


class IEventBus(ABC):
    """Port for event bus implementations."""

    @abstractmethod
    def publish(self, event: DomainEvent) -> int:
        """Publish an event and return the number of handlers that successfully processed it."""
        ...

    @abstractmethod
    def subscribe(self, event_type: Type[DomainEvent], handler: Callable[[DomainEvent], None]) -> None:
        """Subscribe a handler to a specific event type."""
        ...

    @abstractmethod
    def unsubscribe(self, event_type: Type[DomainEvent], handler: Callable[[DomainEvent], None]) -> None:
        """Unsubscribe a handler from an event type."""
        ...

    @abstractmethod
    def get_subscribers(self, event_type: Type[DomainEvent]) -> List[Callable[[DomainEvent], None]]:
        """Get all subscribers for an event type."""
        ...
