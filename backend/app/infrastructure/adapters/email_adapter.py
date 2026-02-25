"""SMTP email notification adapter."""
from __future__ import annotations
import asyncio
import logging
import smtplib
from email.mime.multipart import MIMEMultipart
from email.mime.text import MIMEText
from app.domain.ports.notifications import NotificationPort

logger = logging.getLogger(__name__)


class EmailAdapter(NotificationPort):
    """Send alerts via SMTP. Only fires for WARNING and CRITICAL levels."""

    def __init__(self, host: str, port: int, user: str, password: str, to: str) -> None:
        self._host = host
        self._port = port
        self._user = user
        self._password = password
        self._to = to

    async def send(self, message: str, level: str = "INFO") -> None:
        if level == "INFO":
            return  # Email only for WARNING/CRITICAL
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, self._send_blocking, message, level)

    def send_sync(self, message: str, level: str = "INFO") -> None:
        if level == "INFO":
            return
        try:
            self._send_blocking(message, level)
        except Exception as exc:
            logger.warning("Email send_sync failed: %s", exc)

    def _send_blocking(self, message: str, level: str) -> None:
        try:
            msg = MIMEMultipart("alternative")
            msg["Subject"] = f"[GlassyTrade {level}] Alert"
            msg["From"] = self._user
            msg["To"] = self._to
            html = f"""<html><body>
<h2 style="color:{'red' if level == 'CRITICAL' else 'orange'}">GlassyTrade {level}</h2>
<pre>{message}</pre>
</body></html>"""
            msg.attach(MIMEText(html, "html"))
            with smtplib.SMTP(self._host, self._port, timeout=10) as s:
                s.starttls()
                s.login(self._user, self._password)
                s.sendmail(self._user, [self._to], msg.as_string())
        except Exception as exc:
            logger.warning("Email send failed: %s", exc)
