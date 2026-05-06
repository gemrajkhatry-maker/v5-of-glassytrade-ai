"""Episodic memory loader - extracted from llm_entry_handler.py.

Loads recent trade history for LLM context.
"""

from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from app.core.async_boundary import ensure_sync_adapter_result
from app.shared.timezones import IST

logger = logging.getLogger(__name__)


def load_episodic_memory(storage: Any) -> str:
    """Load recent trade history for LLM context."""
    if not storage:
        return ""

    try:
        _today = datetime.now(IST).strftime("%Y-%m-%d")
        recent_trades = ensure_sync_adapter_result(
            "storage.get_recent_trades",
            storage.get_recent_trades,
            limit=10,
        )
        if not recent_trades:
            return ""

        today_trades = [t for t in recent_trades if _today in str(t.get("time", ""))]
        if not today_trades:
            today_trades = recent_trades[:5]

        parts = []
        session_pnl = 0.0

        for i, t in enumerate(today_trades, 1):
            side = t.get("side", "?")
            pnl = t.get("pnl", 0)
            reason = t.get("reason", "")
            session_pnl += pnl
            sign = "+" if pnl >= 0 else ""
            parts.append(f"{i}) {side} {sign}Rs{pnl:.0f} ({reason})")

        pnl_sign = "+" if session_pnl >= 0 else ""
        return f"Session P&L: {pnl_sign}Rs{session_pnl:.0f} ({len(today_trades)} trades). " + ", ".join(parts) + "."
    except Exception:
        logger.debug("Failed to load episodic memory", exc_info=True)
        return ""


def format_trade_history(trades: list) -> str:
    """Format trade history for display."""
    if not trades:
        return "No recent trades"

    lines = []
    for i, t in enumerate(trades[:10], 1):
        side = t.get("side", "?")
        pnl = t.get("pnl", 0)
        sign = "+" if pnl >= 0 else ""
        lines.append(f"{i}. {side}: {sign}{pnl:.0f}")
    return "\n".join(lines)