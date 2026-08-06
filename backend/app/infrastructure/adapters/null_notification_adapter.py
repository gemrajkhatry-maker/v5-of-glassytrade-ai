"""No-op notification adapter — default when no credentials configured."""
from __future__ import annotations
import logging
from quant.contracts.ports.notifications import INotification

logger = logging.getLogger(__name__)


class NullNotificationAdapter(INotification):
    """Discards all notifications. Used in development and testing."""

    async def send(self, message: str, level: str = "INFO") -> None:
        logger.debug("[NOTIFICATION/%s] %s", level, message[:100])

    def send_sync(self, message: str, level: str = "INFO") -> None:
        logger.debug("[NOTIFICATION/%s] %s", level, message[:100])
