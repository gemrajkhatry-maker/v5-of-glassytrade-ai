"""Daily PnL reporter — sends summary at 15:35 IST after NSE close."""
from __future__ import annotations
import asyncio
import logging
from datetime import datetime
from zoneinfo import ZoneInfo

logger = logging.getLogger(__name__)
_IST = ZoneInfo("Asia/Kolkata")


class DailyReporter:
    """Runs as background asyncio task, fires daily report at 15:35 IST."""

    def __init__(self, storage, notifications) -> None:
        self._storage = storage
        self._notifications = notifications

    async def run(self) -> None:
        logger.info("DailyReporter started")
        while True:
            await self._wait_until_report_time()
            await self._send_report()
            await asyncio.sleep(60)   # ensure we don't double-fire

    async def _wait_until_report_time(self) -> None:
        while True:
            now = datetime.now(_IST)
            if now.hour == 15 and now.minute >= 35:
                return
            await asyncio.sleep(30)

    async def _send_report(self) -> None:
        try:
            trades = self._storage.get_today_trades()
            if not trades:
                await self._notifications.send("Daily Report: No trades today", "INFO")
                return

            wins = [t for t in trades if t.get("pnl", 0) > 0]
            losses = [t for t in trades if t.get("pnl", 0) <= 0]
            total_pnl = sum(t.get("pnl", 0) for t in trades)
            win_rate = len(wins) / len(trades) * 100 if trades else 0

            msg = (
                f"*Daily Report — {datetime.now(_IST).strftime('%d %b %Y')}*\n"
                f"Trades: {len(trades)} | Wins: {len(wins)} | Losses: {len(losses)}\n"
                f"Win Rate: {win_rate:.1f}%\n"
                f"Total PnL: Rs{total_pnl:,.0f}\n"
                f"Best: Rs{max((t.get('pnl', 0) for t in trades), default=0):,.0f}\n"
                f"Worst: Rs{min((t.get('pnl', 0) for t in trades), default=0):,.0f}"
            )
            await self._notifications.send(msg, "INFO")
        except Exception as exc:
            logger.error("DailyReporter failed: %s", exc)
