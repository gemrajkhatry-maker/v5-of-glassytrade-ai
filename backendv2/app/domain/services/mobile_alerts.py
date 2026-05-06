"""Mobile alerting facade over domain notification port."""
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

from app.domain.shared.port.notifications import INotification

logger = logging.getLogger(__name__)


class AlertLevel(str, Enum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass(frozen=True)
class Alert:
    level: AlertLevel
    symbol: str
    message: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class MobileAlertSystem:
    """Emit trade and risk alerts through the notification port."""

    def __init__(self, adapter: INotification | None = None, enabled: bool = True) -> None:
        self._adapter = adapter
        self._enabled = enabled
        self._alerts_sent: list[Alert] = []
        self._last_critical = ""

    def send_critical(self, symbol: str, message: str) -> None:
        self._send(AlertLevel.CRITICAL, symbol, message)

    def send_warning(self, symbol: str, message: str) -> None:
        self._send(AlertLevel.WARNING, symbol, message)

    def send_info(self, symbol: str, message: str) -> None:
        self._send(AlertLevel.INFO, symbol, message)

    def send_trade(self, symbol: str, side: str, price: float, pnl: float | None = None) -> None:
        self._send_trade(AlertLevel.INFO, symbol, side, price, pnl)

    def _send(self, level: AlertLevel, symbol: str, message: str) -> None:
        alert = Alert(level=level, symbol=symbol, message=message)
        self._alerts_sent.append(alert)

        emoji = {"CRITICAL": "🚨", "WARNING": "⚠️", "INFO": "ℹ️"}.get(level.value, "")
        formatted = f"{emoji} {level.value} | {symbol} | {message}\n{alert.timestamp}"
        if level == AlertLevel.CRITICAL:
            logger.critical("ALERT: %s", formatted)
            self._last_critical = formatted
        elif level == AlertLevel.WARNING:
            logger.warning("ALERT: %s", formatted)
        else:
            logger.info("ALERT: %s", formatted)

        if self._enabled and self._adapter is not None:
            try:
                self._adapter.send_alert(level.value, message, {"symbol": symbol, "time": alert.timestamp})
            except Exception as exc:
                logger.error("Failed to send alert for %s: %s", symbol, exc)

    def _send_trade(self, level: AlertLevel, symbol: str, side: str, price: float, pnl: float | None = None) -> None:
        alert = Alert(level=level, symbol=symbol, message=f"{side} {symbol} @ {price}")
        self._alerts_sent.append(alert)
        payload = {"side": side, "price": price}
        if pnl is not None:
            payload["pnl"] = pnl

        if self._enabled and self._adapter is not None:
            try:
                self._adapter.send_trade_alert(symbol, side, price, pnl=pnl)
            except Exception as exc:
                logger.error("Failed to send trade alert for %s: %s", symbol, exc)

    def get_alerts(self, level: AlertLevel | None = None, since: str | None = None) -> list[Alert]:
        alerts = self._alerts_sent
        if level:
            alerts = [a for a in alerts if a.level == level]
        if since:
            alerts = [a for a in alerts if a.timestamp > since]
        return alerts

    def get_stats(self) -> dict:
        return {
            "total": len(self._alerts_sent),
            "critical": len([a for a in self._alerts_sent if a.level == AlertLevel.CRITICAL]),
            "warning": len([a for a in self._alerts_sent if a.level == AlertLevel.WARNING]),
            "info": len([a for a in self._alerts_sent if a.level == AlertLevel.INFO]),
            "last_critical": self._last_critical,
        }

