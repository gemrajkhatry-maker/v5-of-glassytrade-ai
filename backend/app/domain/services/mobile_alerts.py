"""Mobile Alert System — Telegram Bot integration for critical alerts.

Sends alerts via Telegram Bot API (free, reliable, works on all phones).
Supports CRITICAL, WARNING, and INFO levels.

Alert levels:
  CRITICAL: Daily loss limit, circuit breaker, ghost position, WebSocket disconnect
  WARNING: 50% daily loss, 3 consecutive losses, VIX spike, LLM timeout
  INFO: Session start/stop, position open/close, tier upgrade
"""

from __future__ import annotations

import logging
from dataclasses import dataclass, field
from datetime import datetime
from enum import Enum

logger = logging.getLogger(__name__)


class AlertLevel(str, Enum):
    CRITICAL = "CRITICAL"
    WARNING = "WARNING"
    INFO = "INFO"


@dataclass(frozen=True)
class Alert:
    """Immutable alert."""

    level: AlertLevel
    symbol: str
    message: str
    timestamp: str = field(default_factory=lambda: datetime.now().isoformat())


class MobileAlertSystem:
    """Telegram Bot alert system for critical trading events.

    Sends alerts via Telegram Bot API. Falls back to logging if
    Telegram is not configured.
    """

    def __init__(
        self,
        bot_token: str = "",
        chat_id: str = "",
        enabled: bool = True,
    ) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._enabled = enabled
        self._alerts_sent: list[Alert] = []
        self._last_critical: str = ""

    def send_critical(self, symbol: str, message: str) -> None:
        """Send CRITICAL alert (SMS + push)."""
        self._send(AlertLevel.CRITICAL, symbol, message)

    def send_warning(self, symbol: str, message: str) -> None:
        """Send WARNING alert (push only)."""
        self._send(AlertLevel.WARNING, symbol, message)

    def send_info(self, symbol: str, message: str) -> None:
        """Send INFO alert (log + dashboard only)."""
        self._send(AlertLevel.INFO, symbol, message)

    def _send(self, level: AlertLevel, symbol: str, message: str) -> None:
        """Send alert via Telegram or log fallback."""
        alert = Alert(level=level, symbol=symbol, message=message)
        self._alerts_sent.append(alert)

        # Format message
        emoji = {"CRITICAL": "🚨", "WARNING": "⚠️", "INFO": "ℹ️"}
        formatted = f"{emoji.get(level.value, '')} {level.value} | {symbol} | {message}\n{alert.timestamp}"

        # Log always
        if level == AlertLevel.CRITICAL:
            logger.critical("ALERT: %s", formatted)
            self._last_critical = formatted
        elif level == AlertLevel.WARNING:
            logger.warning("ALERT: %s", formatted)
        else:
            logger.info("ALERT: %s", formatted)

        # Send via Telegram if configured
        if self._enabled and self._bot_token and self._chat_id:
            try:
                self._send_telegram(formatted)
            except Exception as e:
                logger.error("Failed to send Telegram alert: %s", e)

    def _send_telegram(self, message: str) -> None:
        """Send message via Telegram Bot API."""
        import urllib.request
        import urllib.parse
        import json

        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        data = urllib.parse.urlencode(
            {
                "chat_id": self._chat_id,
                "text": message,
                "parse_mode": "HTML",
            }
        ).encode()

        req = urllib.request.Request(url, data=data, method="POST")
        with urllib.request.urlopen(req, timeout=10) as resp:
            result = json.loads(resp.read())
            if not result.get("ok"):
                logger.error("Telegram API error: %s", result)

    def get_alerts(
        self,
        level: AlertLevel | None = None,
        since: str | None = None,
    ) -> list[Alert]:
        """Get alerts filtered by level and/or time."""
        alerts = self._alerts_sent
        if level:
            alerts = [a for a in alerts if a.level == level]
        if since:
            alerts = [a for a in alerts if a.timestamp > since]
        return alerts

    def get_stats(self) -> dict:
        """Get alert statistics."""
        return {
            "total": len(self._alerts_sent),
            "critical": len(
                [a for a in self._alerts_sent if a.level == AlertLevel.CRITICAL]
            ),
            "warning": len(
                [a for a in self._alerts_sent if a.level == AlertLevel.WARNING]
            ),
            "info": len([a for a in self._alerts_sent if a.level == AlertLevel.INFO]),
            "last_critical": self._last_critical,
        }
