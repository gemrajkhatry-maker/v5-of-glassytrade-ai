"""No-op notification adapter fallback."""

from __future__ import annotations

import logging

from app.domain.shared.port.notifications import INotification

logger = logging.getLogger(__name__)


class NullNotificationAdapter(INotification):
    """Discards all alerts while preserving interface compatibility."""

    def send_alert(self, title: str, message: str, data: dict | None = None) -> bool:
        logger.debug("[NOTIFICATION/%s] %s %s", title, message, data)
        return True

    def send_trade_alert(self, symbol: str, side: str, price: float, pnl: float | None = None) -> bool:
        logger.debug("[TRADE-ALERT] %s %s %.2f %s", symbol, side, price, f"PnL={pnl:.2f}" if pnl is not None else "")
        return True
