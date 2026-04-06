"""Telegram Bot API notification adapter."""
from __future__ import annotations
import asyncio
import logging
import time
from app.domain.ports.notifications import NotificationPort

logger = logging.getLogger(__name__)

_LEVEL_PREFIX = {"INFO": "ℹ️", "WARNING": "⚠️", "CRITICAL": "🚨"}


class TelegramAdapter(NotificationPort):
    """Send alerts via Telegram Bot API. Non-blocking — uses asyncio tasks."""

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._token = bot_token
        self._chat_id = chat_id
        self._last_sent: dict[str, float] = {}   # level → timestamp
        self._min_interval = 5.0                  # seconds between same-level messages

    async def send(self, message: str, level: str = "INFO") -> None:
        now = time.monotonic()
        if now - self._last_sent.get(level, 0) < self._min_interval:
            logger.debug("Telegram rate-limited: %s", message[:60])
            return
        self._last_sent[level] = now

        prefix = _LEVEL_PREFIX.get(level, "")
        text = f"{prefix} *GlassyTrade*\n{message}"
        try:
            import httpx
            async with httpx.AsyncClient(timeout=5.0) as client:
                await client.post(
                    f"https://api.telegram.org/bot{self._token}/sendMessage",
                    json={"chat_id": self._chat_id, "text": text, "parse_mode": "Markdown"},
                )
        except Exception as exc:
            logger.warning("Telegram send failed: %s", exc)

    def send_sync(self, message: str, level: str = "INFO") -> None:
        try:
            loop = asyncio.get_event_loop()
            if loop.is_running():
                asyncio.create_task(self.send(message, level))
            else:
                loop.run_until_complete(self.send(message, level))
        except Exception as exc:
            logger.debug("Telegram send_sync failed: %s", exc)
