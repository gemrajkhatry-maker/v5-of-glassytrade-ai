"""Trade Journal — JSONL logging for all trading events.

Each line is a JSON object with:
  - event type (signal, entry, exit, rejection, etc.)
  - timestamp
  - symbol
  - relevant data

Used for:
- Post-trade analysis
- Audit trail
- Performance attribution
- ML training data
"""

from __future__ import annotations

import json
import time
import logging
from pathlib import Path
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


class TradeJournal:
    """JSONL trade journal with file rotation."""

    def __init__(self, log_dir: str = "logs"):
        self._log_dir = Path(log_dir)
        self._log_dir.mkdir(parents=True, exist_ok=True)
        self._file = None
        self._current_date = ""

    def _get_file(self):
        """Get or create today's journal file."""
        today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
        if self._current_date != today or self._file is None:
            if self._file:
                self._file.close()
            filepath = self._log_dir / f"trade_journal_{today}.jsonl"
            self._file = open(filepath, "a", encoding="utf-8")
            self._current_date = today
        return self._file

    def log(self, event_type: str, data: dict) -> None:
        """Log a trading event.

        Args:
            event_type: One of:
                SIGNAL_GENERATED, SIGNAL_EXPIRED, GATE_REJECTED,
                ORDER_PLACED, ORDER_FILLED, ORDER_REJECTED,
                POSITION_OPENED, POSITION_CLOSED, SL_HIT, TP_HIT,
                TRAIL_UPDATED, DAILY_SUMMARY
            data: Event-specific data dict
        """
        entry = {
            "timestamp": time.time(),
            "datetime": datetime.now(timezone.utc).isoformat(),
            "event": event_type,
            **data,
        }

        try:
            f = self._get_file()
            f.write(json.dumps(entry) + "\n")
            f.flush()
        except Exception as e:
            logger.error("Journal write error: %s", e)

    def log_signal(self, signal_data: dict) -> None:
        self.log("SIGNAL_GENERATED", signal_data)

    def log_gate_rejection(self, symbol: str, gate_name: str, reason: str) -> None:
        self.log("GATE_REJECTED", {
            "symbol": symbol,
            "gate": gate_name,
            "reason": reason,
        })

    def log_entry(self, trade_data: dict) -> None:
        self.log("POSITION_OPENED", trade_data)

    def log_exit(self, trade_data: dict) -> None:
        self.log("POSITION_CLOSED", trade_data)

    def log_daily_summary(
        self,
        date_str: str,
        total_trades: int,
        wins: int,
        losses: int,
        total_pnl: float,
        max_drawdown: float,
        win_rate: float,
        avg_win: float,
        avg_loss: float,
        expectancy: float,
    ) -> None:
        self.log("DAILY_SUMMARY", {
            "date": date_str,
            "total_trades": total_trades,
            "wins": wins,
            "losses": losses,
            "total_pnl": total_pnl,
            "max_drawdown": max_drawdown,
            "win_rate": win_rate,
            "avg_win": avg_win,
            "avg_loss": avg_loss,
            "expectancy": expectancy,
        })

    def close(self) -> None:
        if self._file:
            self._file.close()
            self._file = None
