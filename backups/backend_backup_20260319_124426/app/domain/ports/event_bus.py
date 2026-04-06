"""EventBus port — abstract interface for publish/subscribe event dispatch."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any, Callable

from app.domain.trading.events import DomainEvent


class EventBusPort(ABC):
    """Abstract event bus for decoupled communication between domain services."""

    @abstractmethod
    def subscribe(self, event_type: type[DomainEvent], handler: Callable[..., Any]) -> None:
        """Register *handler* to be called when *event_type* is published."""
        ...

    @abstractmethod
    def publish(self, event: DomainEvent) -> None:
        """Dispatch *event* to all registered handlers."""
        ...
