"""Notification adapter port for transport-level notification delivery."""

from __future__ import annotations

from abc import ABC, abstractmethod


class INotificationAdapter(ABC):
    """Transport adapter for sending alerts to external channels."""

    @abstractmethod
    def send(self, message: str) -> None:
        """Send a notification message to the configured channel."""
        ...
