"""Notification port — abstract interface for sending alerts."""

from __future__ import annotations

from abc import ABC, abstractmethod
from typing import Any


class INotification(ABC):
    """Abstract notification sender (mobile, email, webhook, etc.)."""

    @abstractmethod
    def send_alert(self, title: str, message: str, data: dict[str, Any] | None = None) -> bool:
        """Send an alert notification."""
        ...

    @abstractmethod
    def send_trade_alert(self, symbol: str, side: str, price: float, pnl: float | None = None) -> bool:
        """Send a trade-specific alert."""
        ...
