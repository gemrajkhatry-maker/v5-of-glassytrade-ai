"""Event bus infrastructure for domain events."""
from typing import Callable, Dict, List, Type, Set
from app.domain.shared.event.domain_events import DomainEvent


class EventBus:
    """
    Simple in-memory event bus with idempotency.
    
    Supports:
    - Publish/subscribe pattern
    - Event type filtering
    - Idempotency (duplicate event prevention)
    """
    
    def __init__(self):
        self._handlers: Dict[Type[DomainEvent], List[Callable]] = {}
        self._seen_event_ids: Set[str] = set()
    
    def subscribe(self, event_type: Type[DomainEvent], handler: Callable) -> None:
        """Subscribe a handler to an event type."""
        if event_type not in self._handlers:
            self._handlers[event_type] = []
        self._handlers[event_type].append(handler)
    
    def unsubscribe(self, event_type: Type[DomainEvent], handler: Callable) -> None:
        """Unsubscribe a handler from an event type."""
        if event_type in self._handlers:
            self._handlers[event_type] = [
                h for h in self._handlers[event_type] if h != handler
            ]
    
    def publish(self, event: DomainEvent) -> None:
        """Publish an event to all subscribers."""
        # Idempotency check - skip if we've seen this event_id
        if event.event_id in self._seen_event_ids:
            return
        
        self._seen_event_ids.add(event.event_id)
        
        # Clean up old event IDs (keep last 10000)
        if len(self._seen_event_ids) > 10000:
            # Remove oldest entries
            self._seen_event_ids = set(list(self._seen_event_ids)[-5000:])
        
        # Get handlers for this specific event type
        event_type = type(event)
        if event_type in self._handlers:
            for handler in self._handlers[event_type]:
                try:
                    handler(event)
                except Exception as e:
                    # Log error but don't crash
                    print(f"Handler error: {e}")
    
    def clear_seen_ids(self) -> None:
        """Clear the seen event IDs cache (for testing)."""
        self._seen_event_ids.clear()