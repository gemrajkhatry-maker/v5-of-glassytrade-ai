"""Application layer compatibility adapter for event transport.

The runtime now uses :class:`app.infrastructure.messaging.event_bus.EventBus`
as the canonical in-memory transport. This module re-exports that bus so
existing imports from application handlers keep working while remaining on the
same transport implementation.
"""

from __future__ import annotations

from app.infrastructure.messaging.event_bus import EventBus

__all__ = ["EventBus"]
