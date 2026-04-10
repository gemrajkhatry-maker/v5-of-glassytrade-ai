"""SQLite Storage Adapter — async persistence via background writes."""

from __future__ import annotations

import sqlite3
import json
import logging
import threading
from pathlib import Path
from typing import Any
from appv2.domain.ports.storage import StoragePort

logger = logging.getLogger(__name__)


class SQLiteStorageAdapter(StoragePort):
    """SQLite storage with background write thread."""

    def __init__(self, db_path: str = "appv2/data/trading.db"):
        Path(db_path).parent.mkdir(parents=True, exist_ok=True)
        self._db_path = db_path
        self._write_queue: list[tuple[str, tuple, dict]] = []
        self._lock = threading.Lock()
        self._stop_event = threading.Event()
        self._conn = sqlite3.connect(db_path)
        self._init_db()
        # Background writer thread
        self._writer_thread = threading.Thread(target=self._writer_loop, daemon=True)
        self._writer_thread.start()

    def _init_db(self):
        """Create tables if they don't exist."""
        c = self._conn.cursor()
        c.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                trade_id TEXT PRIMARY KEY,
                data TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                signal_id INTEGER PRIMARY KEY AUTOINCREMENT,
                data TEXT NOT NULL,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS kv_store (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
        """)
        c.execute("""
            CREATE TABLE IF NOT EXISTS daily_pnl (
                date TEXT PRIMARY KEY,
                pnl REAL NOT NULL
            )
        """)
        self._conn.commit()

    def _writer_loop(self):
        """Background thread that processes write queue."""
        while not self._stop_event.is_set():
            with self._lock:
                queue = self._write_queue[:]
                self._write_queue.clear()
            for op, args, data in queue:
                try:
                    if op == "trade":
                        self._conn.execute(
                            "INSERT OR REPLACE INTO trades VALUES (?, ?, CURRENT_TIMESTAMP)",
                            args,
                        )
                    elif op == "signal":
                        self._conn.execute(
                            "INSERT INTO signals (data) VALUES (?)",
                            (json.dumps(data),),
                        )
                    elif op == "kv_set":
                        self._conn.execute(
                            "INSERT OR REPLACE INTO kv_store VALUES (?, ?)",
                            args,
                        )
                    elif op == "daily_pnl":
                        self._conn.execute(
                            "INSERT OR REPLACE INTO daily_pnl VALUES (?, ?)",
                            args,
                        )
                    self._conn.commit()
                except Exception as e:
                    logger.error("Storage write error: %s", e)
            self._stop_event.wait(0.1)

    def _queue_write(self, op: str, args: tuple, data: dict | None = None):
        with self._lock:
            self._write_queue.append((op, args, data or {}))

    async def save_trade(self, trade_data: dict) -> str:
        tid = trade_data.get("trade_id", "")
        self._queue_write("trade", (tid, json.dumps(trade_data)), trade_data)
        return tid

    async def update_trade(self, trade_id: str, updates: dict) -> None:
        existing = await self.get_trade(trade_id)
        if existing:
            existing.update(updates)
            self._queue_write("trade", (trade_id, json.dumps(existing)), existing)

    async def get_trade(self, trade_id: str) -> dict | None:
        c = self._conn.cursor()
        c.execute("SELECT data FROM trades WHERE trade_id = ?", (trade_id,))
        row = c.fetchone()
        return json.loads(row[0]) if row else None

    async def get_open_trades(self, symbol: str = "") -> list[dict]:
        c = self._conn.cursor()
        c.execute("SELECT data FROM trades")
        trades = [json.loads(r[0]) for r in c.fetchall()]
        open_trades = [t for t in trades if t.get("status") == "OPEN"]
        if symbol:
            open_trades = [t for t in open_trades if t.get("symbol") == symbol]
        return open_trades

    async def get_trades_by_date(self, date_str: str) -> list[dict]:
        c = self._conn.cursor()
        c.execute("SELECT data FROM trades WHERE created_at LIKE ?", (f"{date_str}%",))
        return [json.loads(r[0]) for r in c.fetchall()]

    async def save_signal(self, signal_data: dict) -> str:
        self._queue_write("signal", (), signal_data)
        return "signal-saved"

    async def kv_set(self, key: str, value: str) -> None:
        self._queue_write("kv_set", (key, value))

    async def kv_get(self, key: str) -> str | None:
        c = self._conn.cursor()
        c.execute("SELECT value FROM kv_store WHERE key = ?", (key,))
        row = c.fetchone()
        return row[0] if row else None

    async def kv_delete(self, key: str) -> None:
        self._conn.execute("DELETE FROM kv_store WHERE key = ?", (key,))
        self._conn.commit()

    async def save_daily_pnl(self, date_str: str, pnl: float) -> None:
        self._queue_write("daily_pnl", (date_str, pnl))

    async def get_daily_pnl(self, date_str: str) -> float:
        c = self._conn.cursor()
        c.execute("SELECT pnl FROM daily_pnl WHERE date = ?", (date_str,))
        row = c.fetchone()
        return row[0] if row else 0.0

    def close(self):
        self._stop_event.set()
        self._writer_thread.join(timeout=5)
        self._conn.close()
