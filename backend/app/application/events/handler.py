"""Event handler interface.

All domain event handlers implement this interface. Handlers are
notified by the EventBus when events of their subscribed type are
published.
"""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Generic, TypeVar

from app.domain.trading.events import DomainEvent

T = TypeVar("T", bound=DomainEvent)


class IEventHandler(ABC, Generic[T]):
    """Interface for domain event handlers.

    Implementations should:
    - Be thread-safe (handlers may be called from different threads)
    - Handle errors gracefully (log and continue, don't crash)
    - Be idempotent (same event processed twice should have same effect)
    - Be fast (don't block the event loop)
    """

    @property
    @abstractmethod
    def handled_event_type(self) -> type[DomainEvent]:
        """Returns the event type this handler processes."""
        ...

    @abstractmethod
    def handle(self, event: T) -> None:
        """Handle the event.

        May publish additional events via the EventBus.
        Should not raise exceptions — catch and log instead.
        """
        ...
