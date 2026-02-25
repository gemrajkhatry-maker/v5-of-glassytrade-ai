"""SQLite storage adapter — persists ticks, trades, and LLM decisions.

Auto-creates tables on first use.  Thread-safe via a single persistent
connection protected by a threading lock.  Ticks are batched (flush every
50 ticks or every 5 seconds) to reduce write overhead.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from typing import Any

from app.domain.ports.storage import StoragePort

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ticks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    time TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL,
    volume REAL, delta REAL,
    extra TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS trades (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id TEXT,
    symbol TEXT,
    side TEXT,
    entry_price REAL,
    exit_price REAL,
    size REAL,
    pnl REAL,
    source TEXT,
    reason TEXT,
    opened_at TEXT,
    closed_at TEXT,
    extra TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS llm_decisions (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    direction TEXT,
    confidence TEXT,
    rationale TEXT,
    input_prompt TEXT,
    raw_output TEXT,
    market_state TEXT,
    aggression TEXT,
    price REAL,
    vah REAL,
    val REAL,
    poc REAL,
    delta REAL,
    volume REAL,
    profile_shape TEXT,
    extra TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS performance_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT,
    equity REAL,
    balance REAL,
    open_pnl REAL,
    open_positions INTEGER,
    total_trades INTEGER,
    win_rate REAL,
    extra TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS session_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    market TEXT NOT NULL DEFAULT 'NSE',
    session_date TEXT NOT NULL,
    poc REAL, vah REAL, val REAL,
    profile_shape TEXT,
    total_volume REAL,
    extra TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE TABLE IF NOT EXISTS open_positions (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_price REAL,
    size REAL,
    stop_loss REAL,
    take_profit REAL,
    source TEXT,
    opened_at TEXT,
    extra TEXT
);

CREATE INDEX IF NOT EXISTS idx_ticks_symbol_time ON ticks(symbol, time);
CREATE INDEX IF NOT EXISTS idx_trades_closed_at ON trades(closed_at);
CREATE INDEX IF NOT EXISTS idx_llm_created ON llm_decisions(created_at);
CREATE INDEX IF NOT EXISTS idx_perf_created ON performance_snapshots(created_at);
CREATE INDEX IF NOT EXISTS idx_session_profiles ON session_profiles(symbol, market, session_date);
"""

# Tick batch settings
_TICK_BATCH_SIZE = 50
_TICK_FLUSH_INTERVAL = 5.0  # seconds


class SQLiteStorageAdapter(StoragePort):
    """SQLite-backed persistent storage with WAL mode and tick batching."""

    def __init__(self, db_path: str = "glassytrade.db") -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        # Single persistent connection
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        # Tick batch buffer
        self._tick_buffer: list[tuple] = []
        self._last_flush_time: float = time.time()
        self._flush_timer: threading.Timer | None = None
        self._init_db()

    def _init_db(self) -> None:
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
            logger.info("SQLite database initialized at %s (WAL mode)", self._db_path)

    def _schedule_flush(self) -> None:
        """Schedule a background flush if not already scheduled."""
        if self._flush_timer is None or not self._flush_timer.is_alive():
            self._flush_timer = threading.Timer(_TICK_FLUSH_INTERVAL, self._flush_ticks)
            self._flush_timer.daemon = True
            self._flush_timer.start()

    def _flush_ticks(self) -> None:
        """Flush the tick buffer to the database in a single transaction."""
        with self._lock:
            if not self._tick_buffer:
                return
            batch = self._tick_buffer[:]
            self._tick_buffer.clear()
            self._last_flush_time = time.time()
        # Write outside the buffer lock but inside db access
        # (the lock already covers the connection since it's single-threaded access)
        with self._lock:
            try:
                self._conn.executemany(
                    "INSERT INTO ticks (symbol, time, open, high, low, close, volume, delta, extra) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    batch,
                )
                self._conn.commit()
            except Exception:
                logger.debug("Failed to flush tick batch", exc_info=True)

    # ------------------------------------------------------------------
    # Writes
    # ------------------------------------------------------------------

    def save_tick(self, symbol: str, tick_data: dict[str, Any]) -> None:
        row = (
            symbol,
            tick_data.get("time", ""),
            tick_data.get("open", 0),
            tick_data.get("high", 0),
            tick_data.get("low", 0),
            tick_data.get("close", 0),
            tick_data.get("volume", 0),
            tick_data.get("delta", 0),
            json.dumps({k: v for k, v in tick_data.items()
                        if k not in ("time", "open", "high", "low", "close", "volume", "delta")}),
        )
        with self._lock:
            self._tick_buffer.append(row)
            should_flush = len(self._tick_buffer) >= _TICK_BATCH_SIZE
        if should_flush:
            self._flush_ticks()
        else:
            self._schedule_flush()

    def save_trade(self, trade_data: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO trades (position_id, symbol, side, entry_price, exit_price, "
                "size, pnl, source, reason, opened_at, closed_at, extra) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    trade_data.get("position_id", ""),
                    trade_data.get("symbol", ""),
                    trade_data.get("side", ""),
                    trade_data.get("entry_price", 0),
                    trade_data.get("exit_price", 0),
                    trade_data.get("size", 0),
                    trade_data.get("pnl", 0),
                    trade_data.get("source", ""),
                    trade_data.get("reason", ""),
                    trade_data.get("opened_at", ""),
                    trade_data.get("closed_at", ""),
                    json.dumps({k: v for k, v in trade_data.items()
                                if k not in ("position_id", "symbol", "side", "entry_price",
                                             "exit_price", "size", "pnl", "source", "reason",
                                             "opened_at", "closed_at")}),
                ),
            )
            self._conn.commit()

    def save_llm_decision(self, decision_data: dict[str, Any]) -> None:
        _KNOWN_KEYS = {"symbol", "direction", "confidence", "rationale",
                        "input_prompt", "raw_output", "market_state", "aggression",
                        "price", "vah", "val", "poc", "delta", "volume", "profile_shape"}
        with self._lock:
            self._conn.execute(
                "INSERT INTO llm_decisions (symbol, direction, confidence, rationale, "
                "input_prompt, raw_output, market_state, aggression, "
                "price, vah, val, poc, delta, volume, profile_shape, extra) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    decision_data.get("symbol", ""),
                    decision_data.get("direction", ""),
                    decision_data.get("confidence", ""),
                    decision_data.get("rationale", ""),
                    decision_data.get("input_prompt", ""),
                    decision_data.get("raw_output", ""),
                    decision_data.get("market_state", ""),
                    decision_data.get("aggression", ""),
                    decision_data.get("price", 0),
                    decision_data.get("vah", 0),
                    decision_data.get("val", 0),
                    decision_data.get("poc", 0),
                    decision_data.get("delta", 0),
                    decision_data.get("volume", 0),
                    decision_data.get("profile_shape", ""),
                    json.dumps({k: v for k, v in decision_data.items()
                                if k not in _KNOWN_KEYS}),
                ),
            )
            self._conn.commit()

    def save_performance_snapshot(self, snapshot: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO performance_snapshots (symbol, equity, balance, open_pnl, "
                "open_positions, total_trades, win_rate, extra) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    snapshot.get("symbol", ""),
                    snapshot.get("equity", 0),
                    snapshot.get("balance", 0),
                    snapshot.get("open_pnl", 0),
                    snapshot.get("open_positions", 0),
                    snapshot.get("total_trades", 0),
                    snapshot.get("win_rate", 0),
                    json.dumps({k: v for k, v in snapshot.items()
                                if k not in ("symbol", "equity", "balance", "open_pnl",
                                             "open_positions", "total_trades", "win_rate")}),
                ),
            )
            self._conn.commit()

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def query_ticks(
        self, symbol: str, start: str | None = None, end: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        # Flush pending ticks so queries see latest data
        self._flush_ticks()
        with self._lock:
            query = "SELECT * FROM ticks WHERE symbol = ?"
            params: list[Any] = [symbol]
            if start:
                query += " AND time >= ?"
                params.append(start)
            if end:
                query += " AND time <= ?"
                params.append(end)
            query += " ORDER BY time ASC LIMIT ?"
            params.append(limit)
            rows = self._conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def query_trades(
        self, start: str | None = None, end: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            query = "SELECT * FROM trades WHERE 1=1"
            params: list[Any] = []
            if start:
                query += " AND closed_at >= ?"
                params.append(start)
            if end:
                query += " AND closed_at <= ?"
                params.append(end)
            query += " ORDER BY closed_at ASC"
            rows = self._conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def query_llm_decisions(
        self, start: str | None = None, end: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            query = "SELECT * FROM llm_decisions WHERE 1=1"
            params: list[Any] = []
            if start:
                query += " AND created_at >= ?"
                params.append(start)
            if end:
                query += " AND created_at <= ?"
                params.append(end)
            query += " ORDER BY created_at ASC"
            rows = self._conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def save_session_profile(self, profile_data: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO session_profiles (symbol, market, session_date, poc, vah, val, "
                "profile_shape, total_volume, extra) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    profile_data.get("symbol", ""),
                    profile_data.get("market", "NSE"),
                    profile_data.get("session_date", ""),
                    profile_data.get("poc", 0),
                    profile_data.get("vah", 0),
                    profile_data.get("val", 0),
                    profile_data.get("profile_shape", ""),
                    profile_data.get("total_volume", 0),
                    json.dumps({k: v for k, v in profile_data.items()
                                if k not in ("symbol", "market", "session_date", "poc",
                                             "vah", "val", "profile_shape", "total_volume")}),
                ),
            )
            self._conn.commit()

    def get_previous_session_profile(
        self, symbol: str, market: str = "NSE",
    ) -> dict[str, Any] | None:
        with self._lock:
            row = self._conn.execute(
                "SELECT * FROM session_profiles WHERE symbol = ? AND market = ? "
                "ORDER BY session_date DESC LIMIT 1",
                (symbol, market),
            ).fetchone()
            return dict(row) if row else None

    # ------------------------------------------------------------------
    # Open position persistence (survive restarts)
    # ------------------------------------------------------------------

    def save_open_position(self, position: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT OR REPLACE INTO open_positions "
                "(id, symbol, side, entry_price, size, stop_loss, take_profit, source, opened_at, extra) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    position.get("id", ""),
                    position.get("symbol", ""),
                    position.get("side", ""),
                    position.get("entry_price", 0.0),
                    position.get("size", 0.0),
                    position.get("stop_loss", 0.0),
                    position.get("take_profit", 0.0),
                    position.get("source", ""),
                    position.get("opened_at", ""),
                    json.dumps({k: v for k, v in position.items()
                                if k not in ("id", "symbol", "side", "entry_price", "size",
                                             "stop_loss", "take_profit", "source", "opened_at")}),
                ),
            )
            self._conn.commit()

    def delete_open_position(self, position_id: str) -> None:
        with self._lock:
            self._conn.execute("DELETE FROM open_positions WHERE id = ?", (position_id,))
            self._conn.commit()

    def load_open_positions(self) -> list[dict[str, Any]]:
        with self._lock:
            rows = self._conn.execute("SELECT * FROM open_positions").fetchall()
            result = []
            for row in rows:
                d = dict(row)
                extra = json.loads(d.pop("extra", "{}") or "{}")
                d.update(extra)
                result.append(d)
            return result

    def get_recent_trades(self, limit: int = 5) -> list[dict[str, Any]]:
        """Retrieve the most recent closed trades, newest first."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM trades ORDER BY created_at DESC LIMIT ?",
                (limit,),
            ).fetchall()
            return [dict(r) for r in rows]
