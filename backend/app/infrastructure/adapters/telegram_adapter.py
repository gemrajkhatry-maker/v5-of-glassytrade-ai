"""Telegram transport adapter for domain notification delivery."""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request

from app.domain.ports.notification_adapter import INotificationAdapter

log = logging.getLogger(__name__)


class TelegramAdapter(INotificationAdapter):
    """HTTP adapter that sends alert messages via Telegram Bot API."""

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id

    def send(self, message: str) -> None:
        if not self._bot_token or not self._chat_id:
            return

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
            raise RuntimeError(f"Telegram API error: {result}")
        return None
