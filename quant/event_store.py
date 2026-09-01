"""Phase 3: Event sourcing foundation.

EventStore is an append-only log of events. It is the source of truth.
State is derived by folding events through apply_event().

This module provides:
- EventStore: append-only event log with sequence numbers
- fold(): derive state from events
- export/import: persistence support

Hardening features:
- SHA-256 checksum chain (tamper-evident)
- Dead-letter queue for failed handlers
"""

from __future__ import annotations

import hashlib
import hmac
import json
import os
from typing import Any, Callable, TypeVar

from quant.events import Event
from quant.state_machine import EngineState
from quant.transitions import apply_event

E = TypeVar("E", bound=Event)

# Genesis secret — in production, load from env or secure key store
# This ensures checksums cannot be forged without the secret
_GENESIS_SECRET = os.environ.get("EVENT_STORE_SECRET", "glassytrade-genesis-secret-2026")


class EventStore:
    """Append-only event log. Source of truth for engine state.

    Events are never modified or deleted. State is derived by folding
    events through apply_event().

    Thread safety: this class is NOT thread-safe. It should only be
    accessed from the engine's single thread.
    """

    def __init__(self) -> None:
        self._events: list[Event] = []
        self._sequence: int = 0
        self._checksums: list[str] = []  # Stored HMAC checksums for tamper detection
        self._handlers: dict[type[Event], list[tuple[int, Callable[[Event], None]]]] = {}
        self._dead_letter_queue: list[tuple[Event, Exception]] = []

    def append(self, event: Event) -> int:
        """Append an event. Returns the sequence number.

        Args:
            event: Event to append (immutable)

        Returns:
            Sequence number (1-based, monotonic)
        """
        self._sequence += 1
        self._events.append(event)
        # Compute and store HMAC checksum (tamper-evident)
        prev_checksum = self._checksums[-1] if self._checksums else "GENESIS"
        checksum = self._compute_checksum(prev_checksum, event)
        self._checksums.append(checksum)
        return self._sequence

    def _compute_checksum(self, prev_checksum: str, event: Event) -> str:
        """Compute HMAC-SHA256 checksum of previous checksum + full event payload.

        Uses HMAC with a secret key so checksums cannot be forged
        without access to the secret.
        """
        payload = self._event_to_dict(event)
        data = json.dumps(
            {
                "prev": prev_checksum,
                "sequence": self._sequence,
                "payload": payload,
            },
            sort_keys=True,
        )
        return hmac.new(
            _GENESIS_SECRET.encode(),
            data.encode(),
            hashlib.sha256,
        ).hexdigest()

    def verify_chain(self) -> bool:
        """Verify the integrity of the checksum chain.

        Recomputes the entire chain from genesis using HMAC-SHA256
        and compares against stored checksums. Any modification to
        events, sequence, or checksums will be detected.

        Returns True if the chain is intact, False if tampering detected.
        """
        if len(self._events) != len(self._checksums):
            return False  # Length mismatch indicates tampering

        prev_checksum = "GENESIS"
        for i, event in enumerate(self._events):
            expected = self._compute_checksum(prev_checksum, event)
            if self._checksums[i] != expected:
                return False  # Checksum mismatch indicates tampering
            prev_checksum = expected
        return True

    @staticmethod
    def _event_to_dict(event: Event) -> dict[str, Any]:
        """Convert event to dictionary."""
        from dataclasses import asdict, is_dataclass

        if is_dataclass(event):
            return asdict(event)
        return {"repr": repr(event)}

    def subscribe(
        self,
        event_type: type[E],
        handler: Callable[[E], None],
        priority: int = 0,
    ) -> None:
        """Subscribe a handler to an event type with optional priority."""
        handlers = self._handlers.setdefault(event_type, [])
        handlers.append((priority, handler))
        handlers.sort(key=lambda x: x[0], reverse=True)

    def publish_with_dead_letter(self, event: Event) -> None:
        """Publish an event to all subscribed handlers with dead-letter queue.

        Failed handlers are captured in the dead-letter queue instead of
        propagating exceptions.
        """
        import logging

        logger = logging.getLogger(__name__)
        for _, handler in self._handlers.get(type(event), ()):
            try:
                handler(event)
            except Exception as exc:
                self._dead_letter_queue.append((event, exc))
                logger.exception(
                    "Handler %r failed for %s — moved to dead-letter queue",
                    getattr(handler, "__name__", repr(handler)),
                    type(event).__name__,
                )

    def get_dead_letter_queue(self) -> list[tuple[Event, Exception]]:
        """Return the dead-letter queue."""
        return list(self._dead_letter_queue)

    def clear_dead_letter_queue(self) -> None:
        """Clear the dead-letter queue."""
        self._dead_letter_queue = []

    def get_all(self) -> list[Event]:
        """Return all events in insertion order."""
        return list(self._events)

    def get_since(self, sequence: int) -> list[Event]:
        """Return events from a sequence number onward.

        Args:
            sequence: Starting sequence number (inclusive)

        Returns:
            List of events with sequence >= given sequence
        """
        # Events are 1-indexed in sequence
        start_idx = max(0, sequence - 1)
        return list(self._events[start_idx:])

    def get_last(self) -> Event | None:
        """Return the most recent event, or None if empty."""
        if not self._events:
            return None
        return self._events[-1]

    def fold(self) -> EngineState:
        """Derive current state from event log.

        Applies each event in sequence through apply_event().
        This is the ONLY way to derive state from events.

        Returns:
            Current engine state (empty if no events)
        """
        if not self._events:
            return EngineState(symbol="")
        
        # Initialize symbol from first event
        state = EngineState(symbol=self._events[0].symbol)

        for event in self._events:
            try:
                state = apply_event(state, event)
            except ValueError as e:
                # Log but don't crash on invalid transitions (e.g., replay of stale events)
                logger.warning(
                    "EventStore.fold: skipping invalid event %s: %s",
                    type(event).__name__, e,
                )
                continue

        return state

    def export(self) -> list[dict[str, Any]]:
        """Export events as dictionaries for persistence.

        Returns:
            List of event dictionaries
        """
        exported = []
        for i, event in enumerate(self._events, 1):
            event_dict = {
                "sequence": i,
                "symbol": event.symbol,
                "time": event.time,
                "event_type": type(event).__name__,
                "payload": self._event_to_dict(event),
            }
            exported.append(event_dict)
        return exported

    def import_(self, events: list[dict[str, Any]]) -> None:
        """Import events from dictionaries.

        Args:
            events: List of event dictionaries (from export)
        """
        # Clear existing events
        self._events = []
        self._sequence = 0
        self._checksums = []

        # Import events - reconstruct Event objects from payload
        prev_checksum = "GENESIS"
        for event_dict in events:
            self._sequence += 1
            event = self._dict_to_event(event_dict)
            if event is not None:
                self._events.append(event)
                checksum = self._compute_checksum(prev_checksum, event)
                self._checksums.append(checksum)
                prev_checksum = checksum

    @staticmethod
    def _dict_to_event(event_dict: dict[str, Any]) -> Event | None:
        """Reconstruct an Event from a dictionary.

        Args:
            event_dict: Event dictionary from export

        Returns:
            Reconstructed Event, or None if type is unknown
        """
        from quant.events import (
            BarClosed,
            PositionClosed,
            PositionOpened,
            RiskUpdated,
        )
        from quant.execution.order import Fill, Order, Position
        from quant.state_machine import Bar, PositionState, RiskState

        event_type = event_dict.get("event_type", "")
        payload = event_dict.get("payload", {})
        symbol = event_dict.get("symbol", "")
        time = event_dict.get("time", "")

        if event_type == "BarClosed":
            bar_data = payload.get("bar", {})
            bar = Bar(
                time=bar_data.get("time", ""),
                open=bar_data.get("open", 0.0),
                high=bar_data.get("high", 0.0),
                low=bar_data.get("low", 0.0),
                close=bar_data.get("close", 0.0),
                volume=bar_data.get("volume", 0.0),
                vwap=bar_data.get("vwap", 0.0),
                buy_volume=bar_data.get("buy_volume", 0.0),
                sell_volume=bar_data.get("sell_volume", 0.0),
                oi=bar_data.get("oi", 0.0),
            )
            return BarClosed(symbol=symbol, time=time, bar=bar)

        elif event_type == "PositionOpened":
            pos_data = payload.get("position", {})
            pos = PositionState(
                id=pos_data.get("id", ""),
                entry=pos_data.get("entry", 0.0),
                size=pos_data.get("size", 0.0),
                sl=pos_data.get("sl", 0.0),
                tp=pos_data.get("tp", 0.0),
                side=pos_data.get("side", "LONG"),
                pyramid_level=pos_data.get("pyramid_level", 0),
                is_pyramid=pos_data.get("is_pyramid", False),
            )
            return PositionOpened(symbol=symbol, time=time, position=pos)

        elif event_type == "PositionClosed":
            fill_data = payload.get("fill", {})
            pos_data = fill_data.get("position", {})
            pos = Position(
                order=None,  # Will be reconstructed from signal data if available
                open_price=pos_data.get("open_price", 0.0),
                open_time=pos_data.get("open_time", ""),
                size=pos_data.get("size", 0.0),
                realized_pnl=pos_data.get("realized_pnl", 0.0),
                pyramid_level=pos_data.get("pyramid_level", 0),
                is_pyramid=pos_data.get("is_pyramid", False),
                _id=pos_data.get("_id", ""),
            )
            fill = Fill(
                position=pos,
                close_price=fill_data.get("close_price", 0.0),
                close_time=fill_data.get("close_time", ""),
                reason=fill_data.get("reason", ""),
                pnl=fill_data.get("pnl", 0.0),
            )
            return PositionClosed(symbol=symbol, time=time, fill=fill)

        elif event_type == "RiskUpdated":
            risk_data = payload.get("risk", {})
            risk = RiskState(
                daily_pnl=risk_data.get("daily_pnl", 0.0),
                trades_today=risk_data.get("trades_today", 0),
                halted=risk_data.get("halted", False),
                halt_reason=risk_data.get("halt_reason", ""),
            )
            return RiskUpdated(symbol=symbol, time=time, risk=risk)

        else:
            # Unknown event type - return base Event
            return Event(symbol=symbol, time=time)

    @staticmethod
    def _event_to_dict(event: Event) -> dict[str, Any]:
        """Convert event to dictionary."""
        from dataclasses import asdict, is_dataclass

        if is_dataclass(event):
            return asdict(event)
        return {"repr": repr(event)}

    def __len__(self) -> int:
        return len(self._events)

    def __repr__(self) -> str:
        return f"EventStore(events={len(self._events)}, sequence={self._sequence})"
