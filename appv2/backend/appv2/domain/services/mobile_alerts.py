"""Mobile Alert System — Telegram notifications for trading events.

Sends alerts for:
- Trade entries
- Trade exits
- Risk alerts (circuit breaker, daily loss)
- System alerts (reconnect, errors)
"""

from __future__ import annotations

import logging
import asyncio
import aiohttp
from enum import Enum

logger = logging.getLogger(__name__)


class AlertLevel(str, Enum):
    CRITICAL = "🔴 CRITICAL"
    WARNING = "🟡 WARNING"
    INFO = "🔵 INFO"


class MobileAlertSystem:
    """Sends Telegram bot notifications."""

    def __init__(self, bot_token: str = "", chat_id: str = ""):
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._enabled = bool(bot_token and chat_id)
        self._base_url = f"https://api.telegram.org/bot{bot_token}"

    async def send(
        self,
        message: str,
        level: AlertLevel = AlertLevel.INFO,
        parse_mode: str = "HTML",
    ) -> bool:
        """Send a Telegram message."""
        if not self._enabled:
            logger.debug("Alerts disabled: no bot token or chat ID")
            return False

        formatted = f"{level.value}\n{message}"

        try:
            async with aiohttp.ClientSession() as session:
                url = f"{self._base_url}/sendMessage"
                payload = {
                    "chat_id": self._chat_id,
                    "text": formatted,
                    "parse_mode": parse_mode,
                }
                async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=10)) as resp:
                    if resp.status != 200:
                        logger.warning("Telegram API returned %d", resp.status)
                        return False
                    return True
        except Exception as e:
            logger.error("Failed to send Telegram alert: %s", e)
            return False

    async def alert_entry(self, symbol: str, direction: str, price: float, sl: float, tp: float) -> None:
        """Alert for trade entry."""
        msg = (
            f"<b>ENTRY</b>\n"
            f"Symbol: {symbol}\n"
            f"Direction: {direction}\n"
            f"Entry: {price:.2f}\n"
            f"SL: {sl:.2f}\n"
            f"TP: {tp:.2f}"
        )
        await self.send(msg, AlertLevel.INFO)

    async def alert_exit(self, symbol: str, pnl: float, reason: str) -> None:
        """Alert for trade exit."""
        emoji = "✅" if pnl > 0 else "❌"
        msg = (
            f"<b>EXIT {emoji}</b>\n"
            f"Symbol: {symbol}\n"
            f"P&L: ₹{pnl:.2f}\n"
            f"Reason: {reason}"
        )
        level = AlertLevel.INFO if pnl > 0 else AlertLevel.WARNING
        await self.send(msg, level)

    async def alert_risk(self, message: str) -> None:
        """Risk alert."""
        await self.send(f"<b>RISK ALERT</b>\n{message}", AlertLevel.CRITICAL)

    async def alert_system(self, message: str) -> None:
        """System alert."""
        await self.send(f"<b>SYSTEM</b>\n{message}", AlertLevel.WARNING)
