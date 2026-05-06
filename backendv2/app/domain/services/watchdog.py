"""Session watchdog for async task crash detection."""
from __future__ import annotations

import asyncio
import logging
from dataclasses import dataclass
from datetime import date, datetime

logger = logging.getLogger(__name__)


@dataclass
class SessionWatchEntry:
    symbol: str
    task: asyncio.Task | None = None
    restart_count: int = 0
    last_restart_date: str = ""
    last_error: str = ""
    crashed: bool = False
    max_restarts_per_day: int = 3


class Watchdog:
    def __init__(self, check_interval: float = 30.0) -> None:
        self._check_interval = float(check_interval)
        self._sessions: dict[str, SessionWatchEntry] = {}
        self._running = False
        self._alerts: list[dict] = []

    def register_session(self, symbol: str, task: asyncio.Task) -> None:
        self._sessions[symbol] = SessionWatchEntry(symbol=symbol, task=task)

    def unregister_session(self, symbol: str) -> None:
        self._sessions.pop(symbol, None)

    async def start(self) -> None:
        self._running = True
        logger.info("Watchdog started (interval=%.0fs)", self._check_interval)
        while self._running:
            await self._check_sessions()
            await asyncio.sleep(self._check_interval)

    def stop(self) -> None:
        self._running = False

    async def _check_sessions(self) -> None:
        today = date.today().isoformat()
        for symbol, entry in list(self._sessions.items()):
            if entry.task is None:
                continue

            if entry.last_restart_date != today:
                entry.restart_count = 0
                entry.last_restart_date = today

            if entry.task.done() and not entry.task.cancelled():
                try:
                    error = entry.task.exception()
                except Exception as e:  # pragma: no cover
                    error = e

                if error is None:
                    continue

                entry.crashed = True
                entry.last_error = str(error)
                logger.critical("WATCHDOG: Session crashed — %s: %s", symbol, error)

                self._alerts.append(
                    {
                        "symbol": symbol,
                        "error": str(error),
                        "timestamp": datetime.now().isoformat(),
                        "restart_count": entry.restart_count,
                    }
                )

                if entry.restart_count < entry.max_restarts_per_day:
                    entry.restart_count += 1
                    logger.info(
                        "WATCHDOG: restart allowed for %s (%d/%d)",
                        symbol,
                        entry.restart_count,
                        entry.max_restarts_per_day,
                    )
                else:
                    logger.critical(
                        "WATCHDOG: max restarts reached for %s (%d) — manual intervention required",
                        symbol,
                        entry.max_restarts_per_day,
                    )

    def get_alerts(self, since: str | None = None) -> list[dict]:
        if since is None:
            return list(self._alerts)
        return [item for item in self._alerts if item["timestamp"] > since]

    def get_status(self) -> dict:
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

