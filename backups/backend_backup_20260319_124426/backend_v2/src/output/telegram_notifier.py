"""
Telegram notification service.

Sends alerts for circuit breaker events, risk events, and trade updates.
"""

import asyncio
from typing import Optional

import aiohttp
import structlog

logger = structlog.get_logger()


class TelegramNotifier:
    """
    Telegram notification service.

    Sends alerts for important trading events.
    """

    def __init__(
        self,
        bot_token: Optional[str] = None,
        chat_id: Optional[str] = None,
    ):
        self._bot_token = bot_token
        self._chat_id = chat_id
        self._enabled = bool(bot_token and chat_id)
        self._base_url = f"https://api.telegram.org/bot{bot_token}" if bot_token else None

        if self._enabled:
            logger.info("telegram_notifier_enabled", chat_id=chat_id)
        else:
            logger.info("telegram_notifier_disabled")

    async def send_message(self, message: str, parse_mode: str = "HTML") -> bool:
        """
        Send a message to Telegram.

        Args:
            message: Message text
            parse_mode: Parse mode (HTML or Markdown)

        Returns:
            True if message was sent successfully.
        """
        if not self._enabled:
            return False

        try:
            url = f"{self._base_url}/sendMessage"
            payload = {
                "chat_id": self._chat_id,
                "text": message,
                "parse_mode": parse_mode,
            }

            async with aiohttp.ClientSession() as session:
                async with session.post(url, json=payload) as resp:
                    if resp.status == 200:
                        logger.debug("telegram_message_sent")
                        return True
                    else:
                        logger.warning("telegram_send_failed", status=resp.status)
                        return False

        except Exception as e:
            logger.error("telegram_send_error", error=str(e))
            return False

    async def alert_circuit_breaker(
        self,
        symbol: str,
        reason: str,
        consecutive_losses: int,
        daily_pnl_pct: float,
    ) -> None:
        """Alert for circuit breaker event."""
        message = (
            f"🛑 <b>CIRCUIT BREAKER TRIGGERED</b>\n\n"
            f"Symbol: {symbol}\n"
            f"Reason: {reason}\n"
            f"Consecutive Losses: {consecutive_losses}\n"
            f"Daily PnL: {daily_pnl_pct:.2%}\n\n"
            f"Trading halted for this symbol."
        )
        await self.send_message(message)

    async def alert_risk_event(
        self,
        symbol: str,
        event_type: str,
        details: str,
    ) -> None:
        """Alert for risk event."""
        message = (
            f"⚠️ <b>RISK EVENT</b>\n\n"
            f"Symbol: {symbol}\n"
            f"Event: {event_type}\n"
            f"Details: {details}"
        )
        await self.send_message(message)

    async def alert_trade_entry(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        stop_loss: float,
        target: float,
        lots: int,
        aggression_score: float,
    ) -> None:
        """Alert for trade entry."""
        emoji = "🟢" if direction == "LONG" else "🔴"
        message = (
            f"{emoji} <b>TRADE ENTRY</b>\n\n"
            f"Symbol: {symbol}\n"
            f"Direction: {direction}\n"
            f"Entry: {entry_price:.2f}\n"
            f"Stop Loss: {stop_loss:.2f}\n"
            f"Target: {target:.2f}\n"
            f"Lots: {lots}\n"
            f"Aggression: {aggression_score:.1f}/4.5"
        )
        await self.send_message(message)

    async def alert_trade_exit(
        self,
        symbol: str,
        direction: str,
        entry_price: float,
        exit_price: float,
        pnl: float,
        exit_reason: str,
    ) -> None:
        """Alert for trade exit."""
        emoji = "✅" if pnl > 0 else "❌"
        message = (
            f"{emoji} <b>TRADE EXIT</b>\n\n"
            f"Symbol: {symbol}\n"
            f"Direction: {direction}\n"
            f"Entry: {entry_price:.2f}\n"
            f"Exit: {exit_price:.2f}\n"
            f"PnL: {pnl:+.2f}\n"
            f"Reason: {exit_reason}"
        )
        await self.send_message(message)

    async def alert_data_quality(
        self,
        symbol: str,
        quality: str,
        details: str,
    ) -> None:
        """Alert for data quality issues."""
        message = (
            f"📡 <b>DATA QUALITY ALERT</b>\n\n"
            f"Symbol: {symbol}\n"
            f"Quality: {quality}\n"
            f"Details: {details}"
        )
        await self.send_message(message)

    async def alert_daily_summary(
        self,
        symbol: str,
        total_trades: int,
        win_rate: float,
        total_pnl: float,
        max_drawdown: float,
    ) -> None:
        """Alert for daily summary."""
        emoji = "📈" if total_pnl > 0 else "📉"
        message = (
            f"{emoji} <b>DAILY SUMMARY</b>\n\n"
            f"Symbol: {symbol}\n"
            f"Total Trades: {total_trades}\n"
            f"Win Rate: {win_rate:.1%}\n"
            f"Total PnL: {total_pnl:+.2f}\n"
            f"Max Drawdown: {max_drawdown:.2%}"
        )
        await self.send_message(message)