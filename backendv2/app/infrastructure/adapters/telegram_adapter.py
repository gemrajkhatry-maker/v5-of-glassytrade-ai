"""Telegram notification adapter for v2 — sends alerts via Telegram Bot API."""

from __future__ import annotations

import json
import logging
import urllib.parse
import urllib.request
from typing import Any

from app.domain.shared.port.notifications import INotification

log = logging.getLogger(__name__)


class TelegramAdapter(INotification):
    """HTTP adapter that delivers notifications through the Telegram Bot API.

    The adapter maps the domain INotification contract to Telegram's
    sendMessage endpoint.  All network errors are logged and swallowed so
    that a Telegram outage never stops trade execution.
    """

    def __init__(self, bot_token: str, chat_id: str) -> None:
        self._bot_token = bot_token
        self._chat_id = chat_id

    # ------------------------------------------------------------------
    # INotification implementation
    # ------------------------------------------------------------------

    def send_alert(
        self, title: str, message: str, data: dict[str, Any] | None = None
    ) -> bool:
        """Send a generic alert (title + message + optional structured data)."""
        text = f"<b>{title}</b>\n{message}"
        if data:
            extras = "\n".join(f"  {k}: {v}" for k, v in data.items())
            text += f"\n<pre>{extras}</pre>"
        return self._send(text)

    def send_trade_alert(
        self,
        symbol: str,
        side: str,
        price: float,
        pnl: float | None = None,
    ) -> bool:
        """Send a trade-specific alert."""
        pnl_str = f" | PnL: {pnl:+.2f}" if pnl is not None else ""
        text = (
            f"<b>Trade: {symbol}</b>\n"
            f"Side: {side} | Price: {price:.2f}{pnl_str}"
        )
        return self._send(text)

    # ------------------------------------------------------------------
    # Internal
    # ------------------------------------------------------------------

    def _send(self, text: str) -> bool:
        """POST a text message.  Returns True on success."""
        if not self._bot_token or not self._chat_id:
            log.debug("TelegramAdapter: bot_token or chat_id not configured — skipping")
            return False

        url = f"https://api.telegram.org/bot{self._bot_token}/sendMessage"
        payload = urllib.parse.urlencode(
            {
                "chat_id": self._chat_id,
                "text": text,
                "parse_mode": "HTML",
            }
        ).encode()

        req = urllib.request.Request(url, data=payload, method="POST")
        try:
            with urllib.request.urlopen(req, timeout=10) as resp:
                result = json.loads(resp.read())
            if not result.get("ok"):
                log.warning("Telegram API error: %s", result)
                return False
            return True
        except OSError as exc:
            log.warning("Telegram send failed (network): %s", exc)
            return False
        except Exception as exc:  # noqa: BLE001
            log.warning("Telegram send failed: %s", exc)
            return False
