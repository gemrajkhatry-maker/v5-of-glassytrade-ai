"""Notification port — abstract interface for sending alerts."""
from __future__ import annotations
from abc import ABC, abstractmethod


class INotification(ABC):
    """Send operational alerts (circuit breakers, feed gaps, daily PnL)."""

    @abstractmethod
    async def send(self, message: str, level: str = "INFO") -> None:
        """Send a message.

        level: "INFO" | "WARNING" | "CRITICAL"
        Must be non-blocking — never delay tick processing.
        """
        ...

    @abstractmethod
    def send_sync(self, message: str, level: str = "INFO") -> None:
        """Synchronous fire-and-forget wrapper (for non-async callers)."""
        ...
