"""Position Event Sourcing — audit trail for position lifecycle events.

Provides complete audit trail of all position lifecycle events:
- Position opened
- Stop loss moved
- Take profit hit
- Partial exits
- Breakeven moved
- Position closed
- Pyramid adds

Each event is timestamped and includes the full context for replay and analysis.

Usage:
    sourcing = PositionEventSourcingService(storage)
    sourcing.record_event(PositionLifecycleEvent(
        position_id="pos_123",
        event_type="OPENED",
        timestamp=datetime.now().isoformat(),
        data={"side": "LONG", "entry_price": 100.0}
    ))
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone
from enum import Enum
from typing import Any
from uuid import uuid4

logger = logging.getLogger(__name__)


class PositionEventType(str, Enum):
    """Position lifecycle event types."""
    OPENED = "OPENED"
    STOP_LOSS_MOVED = "STOP_LOSS_MOVED"
    TAKE_PROFIT_HIT = "TAKE_PROFIT_HIT"
    PARTIAL_EXIT = "PARTIAL_EXIT"
    BREAKEVEN_MOVED = "BREAKEVEN_MOVED"
    TRAIL_SL_MOVED = "TRAIL_SL_MOVED"
    PYRAMID_ADD = "PYRAMID_ADD"
    COUNTER_AGGRESSION_EXIT = "COUNTER_AGGRESSION_EXIT"
    STOP_LOSS_HIT = "STOP_LOSS_HIT"
    CLOSED = "CLOSED"
    RECOVERED = "RECOVERED"


@dataclass
class PositionLifecycleEvent:
    """A single position lifecycle event."""
    event_id: str
    position_id: str
    event_type: str
    timestamp: str
    data: dict[str, Any]
    source: str = "SYSTEM"
    reason: str = ""


class PositionEventSourcingService:
    """Provides complete audit trail for position lifecycle events.

    Single responsibility: Record and query position lifecycle events.
    """

    def __init__(self, storage=None) -> None:
        self._storage = storage
        self._events: list[PositionLifecycleEvent] = []

    def record_event(self, event: PositionLifecycleEvent) -> None:
        """Record a position lifecycle event.

        Args:
            event: The lifecycle event to record.
        """
        self._events.append(event)

        # Persist to storage if available
        if self._storage and hasattr(self._storage, 'save_position_event'):
            try:
                self._storage.save_position_event({
                    "position_id": event.position_id,
                    "symbol": event.data.get("symbol", ""),
                    "event_type": event.event_type,
                    "event_time": event.timestamp,
                    "event_id": event.event_id,
                    "source": event.source,
                    "reason": event.reason,
                    **event.data,
                })
            except Exception as e:
                logger.debug("Failed to persist position event: %s", e)

        logger.info(
            "Position event: %s %s — %s",
            event.event_type,
            event.position_id,
            event.reason or "no reason",
        )

    def record_opened(
        self,
        position_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        stop_loss: float,
        take_profit: float,
        source: str = "SYSTEM",
    ) -> PositionLifecycleEvent:
        """Record a position opened event."""
        event = PositionLifecycleEvent(
            event_id=str(uuid4()),
            position_id=position_id,
            event_type=PositionEventType.OPENED.value,
            timestamp=datetime.now(timezone.utc).isoformat(),
            data={
                "symbol": symbol,
                "side": side,
                "entry_price": entry_price,
                "stop_loss": stop_loss,
                "take_profit": take_profit,
            },
            source=source,
            reason=f"Position opened: {side} {symbol} @ {entry_price}",
        )
        self.record_event(event)
        return event

    def record_closed(
        self,
        position_id: str,
        symbol: str,
        side: str,
        entry_price: float,
        exit_price: float,
        pnl: float,
        exit_reason: str,
        source: str = "SYSTEM",
    ) -> PositionLifecycleEvent:
        """Record a position closed event."""
        event = PositionLifecycleEvent(
            event_id=str(uuid4()),
            position_id=position_id,
            event_type=PositionEventType.CLOSED.value,
            timestamp=datetime.now(timezone.utc).isoformat(),
            data={
                "symbol": symbol,
                "side": side,
                "entry_price": entry_price,
                "exit_price": exit_price,
                "pnl": pnl,
                "exit_reason": exit_reason,
            },
            source=source,
            reason=f"Position closed: {exit_reason} — PnL: {pnl:+.2f}",
        )
        self.record_event(event)
        return event

    def record_partial_exit(
        self,
        position_id: str,
        symbol: str,
        exit_pct: float,
        exit_price: float,
        realized_pnl: float,
        reason: str,
    ) -> PositionLifecycleEvent:
        """Record a partial exit event."""
        event = PositionLifecycleEvent(
            event_id=str(uuid4()),
            position_id=position_id,
            event_type=PositionEventType.PARTIAL_EXIT.value,
            timestamp=datetime.now(timezone.utc).isoformat(),
            data={
                "symbol": symbol,
                "exit_pct": exit_pct,
                "exit_price": exit_price,
                "realized_pnl": realized_pnl,
            },
            source="SYSTEM",
            reason=reason,
        )
        self.record_event(event)
        return event

    def record_stop_loss_moved(
        self,
        position_id: str,
        symbol: str,
        old_sl: float,
        new_sl: float,
        reason: str,
    ) -> PositionLifecycleEvent:
        """Record a stop loss moved event."""
        event = PositionLifecycleEvent(
            event_id=str(uuid4()),
            position_id=position_id,
            event_type=PositionEventType.STOP_LOSS_MOVED.value,
            timestamp=datetime.now(timezone.utc).isoformat(),
            data={
                "symbol": symbol,
                "old_sl": old_sl,
                "new_sl": new_sl,
            },
            source="SYSTEM",
            reason=reason,
        )
        self.record_event(event)
        return event

    def get_events_for_position(self, position_id: str) -> list[PositionLifecycleEvent]:
        """Get all events for a specific position."""
        return [e for e in self._events if e.position_id == position_id]

    def get_events_for_symbol(self, symbol: str) -> list[PositionLifecycleEvent]:
        """Get all events for a specific symbol."""
        return [e for e in self._events if e.data.get("symbol") == symbol]

    def get_event_count(self) -> int:
        """Get total number of recorded events."""
        return len(self._events)

    def clear(self) -> None:
        """Clear all recorded events."""
        self._events.clear()