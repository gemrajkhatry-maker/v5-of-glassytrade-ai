"""Episodic memory loader for LLM context."""

from __future__ import annotations

import logging
from datetime import datetime

from app.shared.timezones import IST

logger = logging.getLogger(__name__)


def load_episodic_memory(storage) -> str:
    if not storage:
        return ""
    try:
        today = datetime.now(IST).strftime("%Y-%m-%d")
        recent_trades = storage.get_recent_trades(limit=10)
        if not recent_trades:
            return ""

        today_trades = [t for t in recent_trades if today in str(t.get("time", ""))]
        if not today_trades:
            today_trades = recent_trades[:5]

        parts: list[str] = []
        session_pnl = 0.0
        for i, trade in enumerate(today_trades, 1):
            side = trade.get("side", "?")
            pnl = float(trade.get("pnl", 0))
            reason = trade.get("reason", "")
            session_pnl += pnl
            sign = "+" if pnl >= 0 else ""
            parts.append(f"{i}) {side} {sign}Rs{pnl:.0f} ({reason})")

        pnl_sign = "+" if session_pnl >= 0 else ""
        return (
            f"Session P&L: {pnl_sign}Rs{session_pnl:.0f} "
            f"({len(today_trades)} trades). " + ", ".join(parts) + "."
        )
    except Exception:
        logger.debug("Failed to load episodic memory", exc_info=True)
        return ""


def format_trade_history(trades: list) -> str:
    if not trades:
        return "No recent trades"
    lines = []
    for i, trade in enumerate(trades[:10], 1):
        side = trade.get("side", "?")
        pnl = float(trade.get("pnl", 0))
        sign = "+" if pnl >= 0 else ""
        lines.append(f"{i}. {side}: {sign}{pnl:.0f}")
    return "\n".join(lines)
