"""
Subscription manager for batching instruments per WebSocket subscribe.
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import List, Set, Dict, Optional, TYPE_CHECKING
import uuid

from brokersv2.core.constants import WebSocket as WSConstants

if TYPE_CHECKING:
    from brokersv2.domain.instrument.models import CanonicalInstrument

logger = logging.getLogger(__name__)


# DhanHQ v2 WebSocket limits - imported from centralized constants
MAX_INSTRUMENTS_PER_SUBSCRIBE = WSConstants.MAX_INSTRUMENTS_PER_SUBSCRIBE
MAX_CONNECTIONS = WSConstants.MAX_CONNECTIONS
MAX_INSTRUMENTS_PER_CONNECTION = WSConstants.MAX_INSTRUMENTS_PER_CONNECTION


@dataclass
class SubscriptionBatch:
    """Batch of instruments for subscription."""
    instruments: List["CanonicalInstrument"]
    correlation_id: str = field(default_factory=lambda: str(uuid.uuid4()))
    
    def __len__(self):
        return len(self.instruments)


class SubscriptionManager:
    """
    Manages WebSocket subscriptions with batching.
    
    Handles:
    - Batching up to 100 instruments per subscribe message
    - Multiple connection management (up to 5 concurrent)
    - Deduplication of instruments
    """
    
    def __init__(self):
        self._subscribed: Set[str] = set()  # internal_uids
        self._batches: List[SubscriptionBatch] = []
        self._connection_batches: Dict[int, List[SubscriptionBatch]] = {}  # connection_id -> batches
    
    def add_instruments(
        self,
        instruments: List["CanonicalInstrument"],
    ) -> List[SubscriptionBatch]:
        """
        Add instruments for subscription, returns batches to send.
        """
        new_batches = []
        to_subscribe = []
        
        for inst in instruments:
            if inst.internal_uid not in self._subscribed:
                to_subscribe.append(inst)
                self._subscribed.add(inst.internal_uid)
        
        if not to_subscribe:
            return []
        
        # Create batches of up to 100 instruments
        for i in range(0, len(to_subscribe), MAX_INSTRUMENTS_PER_SUBSCRIBE):
            batch = SubscriptionBatch(
                instruments=to_subscribe[i:i + MAX_INSTRUMENTS_PER_SUBSCRIBE]
            )
            self._batches.append(batch)
            new_batches.append(batch)
        
        logger.info(f"Created {len(new_batches)} subscription batches for {len(to_subscribe)} instruments")
        return new_batches
    
    def remove_instruments(
        self,
        instruments: List["CanonicalInstrument"],
    ) -> List[str]:
        """
        Remove instruments from subscription, returns instrument IDs to unsubscribe.
        """
        removed = []
        for inst in instruments:
            if inst.internal_uid in self._subscribed:
                self._subscribed.remove(inst.internal_uid)
                removed.append(inst.internal_uid)
        
        return removed
    
    def get_subscribed_count(self) -> int:
        """Get count of currently subscribed instruments."""
        return len(self._subscribed)
    
    def get_connection_batches(self, connection_id: int) -> List[SubscriptionBatch]:
        """Get batches for a specific connection."""
        return self._connection_batches.get(connection_id, [])
    
    def assign_to_connections(self, num_connections: int = MAX_CONNECTIONS) -> Dict[int, List[SubscriptionBatch]]:
        """
        Assign instrument batches to connections.
        
        Returns mapping of connection index to batches.
        """
        result = {i: [] for i in range(num_connections)}
        
        for i, batch in enumerate(self._batches):
            conn_idx = i % num_connections
            result[conn_idx].append(batch)
        
        self._connection_batches = result
        return result
    
    def clear(self) -> None:
        """Clear all subscriptions."""
        self._subscribed.clear()
        self._batches.clear()
        self._connection_batches.clear()