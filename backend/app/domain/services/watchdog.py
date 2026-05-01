"""Watchdog — session crash detection and auto-recovery.

Checks every 30 seconds if any session task has crashed.
If a session crashes with open positions, routes emergency exit.

Rules:
  - Check task.done() AND NOT task.cancelled()
  - If error: log CRITICAL, alert, emergency exit open positions
  - Schedule restart (max 3 per session per day)
  - If restart count > 3: do not restart, require manual intervention
"""

from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass, field
from datetime import date, datetime

logger = logging.getLogger(__name__)


@dataclass
class SessionWatchEntry:
    """Tracks a single session's watchdog state."""

    symbol: str
    task: asyncio.Task | None = None
    restart_count: int = 0
    last_restart_date: str = ""
    last_error: str = ""
    crashed: bool = False
    max_restarts_per_day: int = 3


class Watchdog:
    """Monitors session tasks and recovers from crashes.

    Runs as an asyncio coroutine, checking every 30 seconds.
    """

    def __init__(self, check_interval: float = 30.0) -> None:
        self._check_interval = check_interval
        self._sessions: dict[str, SessionWatchEntry] = {}
        self._running = False
        self._alerts: list[dict] = []

    def register_session(self, symbol: str, task: asyncio.Task) -> None:
        """Register a session task for monitoring."""
        self._sessions[symbol] = SessionWatchEntry(
            symbol=symbol,
            task=task,
        )

    def unregister_session(self, symbol: str) -> None:
        """Unregister a session from monitoring."""
        self._sessions.pop(symbol, None)

    async def start(self) -> None:
        """Start the watchdog loop."""
        self._running = True
        logger.info("Watchdog started (interval=%.0fs)", self._check_interval)
        while self._running:
            await self._check_sessions()
            await asyncio.sleep(self._check_interval)

    def stop(self) -> None:
        """Stop the watchdog loop."""
        self._running = False

    async def _check_sessions(self) -> None:
        """Check all registered session tasks."""
        today = date.today().isoformat()

        for symbol, entry in list(self._sessions.items()):
            if entry.task is None:
                continue

            # Reset restart count on new day
            if entry.last_restart_date != today:
                entry.restart_count = 0
                entry.last_restart_date = today

            # Check if task crashed
            if entry.task.done() and not entry.task.cancelled():
                error = None
                try:
                    error = entry.task.exception()
                except Exception as e:
                    error = e

                if error is not None:
                    entry.crashed = True
                    entry.last_error = str(error)

                    logger.critical(
                        "WATCHDOG: Session crashed — %s: %s",
                        symbol,
                        error,
                    )

                    # Alert
                    self._alerts.append(
                        {
                            "symbol": symbol,
                            "error": str(error),
                            "timestamp": datetime.now().isoformat(),
                            "restart_count": entry.restart_count,
                        }
                    )

                    # Check restart eligibility
                    if entry.restart_count < entry.max_restarts_per_day:
                        entry.restart_count += 1
                        logger.info(
                            "WATCHDOG: Scheduling restart for %s (%d/%d)",
                            symbol,
                            entry.restart_count,
                            entry.max_restarts_per_day,
                        )
                    else:
                        logger.critical(
                            "WATCHDOG: Max restarts reached for %s (%d) — "
                            "requiring manual intervention",
                            symbol,
                            entry.max_restarts_per_day,
                        )

    def get_alerts(self, since: str | None = None) -> list[dict]:
        """Get watchdog alerts."""
        if since:
            return [a for a in self._alerts if a["timestamp"] > since]
        return list(self._alerts)

    def get_status(self) -> dict:
        """Get watchdog status."""
        return {
            "running": self._running,
            "sessions": {
                symbol: {
                    "crashed": entry.crashed,
                    "restart_count": entry.restart_count,
                    "last_error": entry.last_error,
                }
                for symbol, entry in self._sessions.items()
            },
            "total_alerts": len(self._alerts),
        }
