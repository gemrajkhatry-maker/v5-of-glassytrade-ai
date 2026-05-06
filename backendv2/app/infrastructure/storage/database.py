"""SQLite storage adapter — persists ticks, trades, LLM decisions, positions.

Ported from backend/app/infrastructure/storage/database.py (953L).
Thread-safe via persistent connection + lock. Ticks batched (50 or 5s).
Auto-creates tables on first use with WAL mode.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from typing import Any
from uuid import uuid4

from app.domain.shared.port.storage import IStorage

logger = logging.getLogger(name=__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ticks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    time TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL,
    volume REAL, delta REAL,
    extra TEXT,
    created_at TEXT DEFAULT (datetime('now', '+5:30 hours'))
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
    llm_analysis TEXT,
    created_at TEXT DEFAULT (datetime('now', '+5:30 hours'))
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
    vah REAL, val REAL, poc REAL,
    delta REAL, volume REAL,
    profile_shape TEXT,
    extra TEXT,
    created_at TEXT DEFAULT (datetime('now', '+5:30 hours'))
);

CREATE TABLE IF NOT EXISTS performance_snapshots (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT, equity REAL, balance REAL,
    open_pnl REAL, open_positions INTEGER,
    total_trades INTEGER, win_rate REAL,
    extra TEXT,
    created_at TEXT DEFAULT (datetime('now', '+5:30 hours'))
);

CREATE TABLE IF NOT EXISTS session_profiles (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    market TEXT NOT NULL DEFAULT 'NSE',
    session_date TEXT NOT NULL,
    poc REAL, vah REAL, val REAL,
    profile_shape TEXT, total_volume REAL,
    extra TEXT,
    created_at TEXT DEFAULT (datetime('now', '+5:30 hours'))
);

CREATE TABLE IF NOT EXISTS open_positions (
    id TEXT PRIMARY KEY,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    entry_price REAL, size REAL,
    stop_loss REAL, take_profit REAL,
    source TEXT, opened_at TEXT, extra TEXT
);

CREATE TABLE IF NOT EXISTS position_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id TEXT, symbol TEXT,
    event_type TEXT NOT NULL,
    event_time TEXT, extra TEXT,
    created_at TEXT DEFAULT (datetime('now', '+5:30 hours'))
);

CREATE TABLE IF NOT EXISTS npoc_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    underlying TEXT NOT NULL,
    session_date TEXT NOT NULL,
    poc_price REAL NOT NULL,
    is_filled INTEGER DEFAULT 0,
    filled_at TEXT,
    created_at TEXT DEFAULT (datetime('now', '+5:30 hours'))
);

CREATE TABLE IF NOT EXISTS fine_tuning_features (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER, symbol TEXT NOT NULL,
    direction TEXT, market_state TEXT,
    poc REAL, vah REAL, val REAL,
    aggression REAL, cvd_slope REAL,
    delta_normalized REAL, volume REAL,
    imbalance REAL, setup_type TEXT,
    result TEXT, pnl_r REAL,
    created_at TEXT DEFAULT (datetime('now', '+5:30 hours'))
);

CREATE TABLE IF NOT EXISTS kv_store (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now', '+5:30 hours'))
);

CREATE INDEX IF NOT EXISTS idx_ticks_symbol_time ON ticks(symbol, time);
CREATE INDEX IF NOT EXISTS idx_trades_closed_at ON trades(closed_at);
CREATE INDEX IF NOT EXISTS idx_llm_created ON llm_decisions(created_at);
CREATE INDEX IF NOT EXISTS idx_session_profiles ON session_profiles(symbol, market, session_date);
CREATE INDEX IF NOT EXISTS idx_position_events_pos_time ON position_events(position_id, created_at);
CREATE INDEX IF NOT EXISTS idx_position_events_symbol_time ON position_events(symbol, created_at);
CREATE INDEX IF NOT EXISTS idx_npoc_underlying_date ON npoc_records(underlying, session_date);
CREATE INDEX IF NOT EXISTS idx_finetune_result ON fine_tuning_features(result);
"""

_TICK_BATCH_SIZE = 50
_TICK_FLUSH_INTERVAL = 5.0


class SQLiteStorageAdapter(IStorage):
    """SQLite-backed persistent storage with WAL mode and tick batching."""

    def __init__(self, db_path: str = "glassytrade.db") -> None:
        self._db_path = db_path
        self._lock = threading.Lock()
        self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
        self._conn.row_factory = sqlite3.Row
        self._tick_buffer: list[tuple] = []
        self._last_flush_time: float = time.time()
        self._flush_timer: threading.Timer | None = None
        self._init_db()

    def init(self, db_path: str = "glassytrade.db") -> None:
        """Compatibility helper for callers still using explicit init."""
        if getattr(self, "_db_path", None) == db_path and getattr(self, "_conn", None):
            self._init_db()
            return
        old_conn = getattr(self, "_conn", None)
        if old_conn is not None:
            try:
                old_conn.close()
            except Exception:
                logger.debug("Failed to close previous SQLite connection before init()", exc_info=True)
        self.__init__(db_path)

    def _init_db(self) -> None:
        with self._lock:
            self._conn.execute("PRAGMA journal_mode=WAL")
            self._conn.execute("PRAGMA synchronous=NORMAL")
            self._conn.execute("PRAGMA wal_autocheckpoint=500")
            self._conn.executescript(_SCHEMA)
            self._conn.commit()
            logger.info("SQLite DB initialized: %s (WAL)", self._db_path)

    def _execute_write(self, query: str, params: tuple = ()) -> None:
        with self._lock:
            try:
                self._conn.execute(query, params)
                self._conn.commit()
            except sqlite3.Error:
                self._conn.rollback()
                raise

    def _schedule_flush(self) -> None:
        if self._flush_timer is None or not self._flush_timer.is_alive():
            self._flush_timer = threading.Timer(_TICK_FLUSH_INTERVAL, self._flush_ticks)
            self._flush_timer.daemon = True
            self._flush_timer.start()

    def _flush_ticks(self) -> None:
        with self._lock:
            self._flush_ticks_unlocked()

    def _flush_ticks_unlocked(self) -> None:
        if not self._tick_buffer:
            return
        batch = self._tick_buffer[:]
        self._tick_buffer.clear()
        self._last_flush_time = time.time()
        try:
            self._conn.executemany(
                "INSERT OR REPLACE INTO ticks (symbol, time, open, high, low, close, volume, delta, extra) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                batch,
            )
            self._conn.commit()
        except sqlite3.Error:
            self._conn.rollback()
            raise

    def save_tick(self, symbol: str, tick_data: dict[str, Any]) -> None:
        row = (
            symbol, tick_data.get("time", ""),
            tick_data.get("open", 0), tick_data.get("high", 0),
            tick_data.get("low", 0), tick_data.get("close", 0),
            tick_data.get("volume", 0), tick_data.get("delta", 0),
            json.dumps({k: v for k, v in tick_data.items() if k not in ("time", "open", "high", "low", "close", "volume", "delta")}),
        )
        with self._lock:
            self._tick_buffer.append(row)
            if len(self._tick_buffer) >= _TICK_BATCH_SIZE:
                self._flush_ticks_unlocked()
            else:
                self._schedule_flush()

    def save_trade(self, trade_data: dict[str, Any]) -> None:
        self._execute_write(
            "INSERT INTO trades (position_id, symbol, side, entry_price, exit_price, size, pnl, source, reason, opened_at, closed_at, extra, llm_analysis) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(trade_data.get("position_id", "")), str(trade_data.get("symbol", "")),
             str(trade_data.get("side", "")), float(trade_data.get("entry_price", 0)),
             float(trade_data.get("exit_price", 0)), float(trade_data.get("size", 0)),
             float(trade_data.get("pnl", 0)), str(trade_data.get("source", "")),
             str(trade_data.get("reason", "")), str(trade_data.get("opened_at", "")),
             str(trade_data.get("closed_at", "")), json.dumps(trade_data.get("extra", {})),
             json.dumps(trade_data.get("llm_analysis", {}))),
        )

    def save_llm_decision(self, decision_data: dict[str, Any]) -> None:
        self._execute_write(
            "INSERT INTO llm_decisions (symbol, direction, confidence, rationale, input_prompt, raw_output, market_state, aggression, price, vah, val, poc, delta, volume, profile_shape, extra) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(decision_data.get("symbol", "")), str(decision_data.get("direction", "")),
             str(decision_data.get("confidence", "")), str(decision_data.get("rationale", "")),
             str(decision_data.get("input_prompt", "")), str(decision_data.get("raw_output", "")),
             str(decision_data.get("market_state", "")), str(decision_data.get("aggression", "")),
             float(decision_data.get("price", 0)), float(decision_data.get("vah", 0)),
             float(decision_data.get("val", 0)), float(decision_data.get("poc", 0)),
             float(decision_data.get("delta", 0)), float(decision_data.get("volume", 0)),
             str(decision_data.get("profile_shape", "")), json.dumps(decision_data.get("extra", {}))),
        )

    def save_performance_snapshot(self, snapshot: dict[str, Any]) -> None:
        self._execute_write(
            "INSERT INTO performance_snapshots (symbol, equity, balance, open_pnl, open_positions, total_trades, win_rate, extra) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (str(snapshot.get("symbol", "")), float(snapshot.get("equity", 0)),
             float(snapshot.get("balance", 0)), float(snapshot.get("open_pnl", 0)),
             int(snapshot.get("open_positions", 0)), int(snapshot.get("total_trades", 0)),
             float(snapshot.get("win_rate", 0)), json.dumps(snapshot.get("extra", {}))),
        )

    def save_session_profile(self, profile_data: dict[str, Any]) -> None:
        self._execute_write(
            "INSERT INTO session_profiles (symbol, market, session_date, poc, vah, val, profile_shape, total_volume, extra) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(profile_data.get("symbol", "")), str(profile_data.get("market", "NSE")),
             str(profile_data.get("session_date", "")), float(profile_data.get("poc", 0)),
             float(profile_data.get("vah", 0)), float(profile_data.get("val", 0)),
             str(profile_data.get("profile_shape", "")), float(profile_data.get("total_volume", 0)),
             json.dumps(profile_data.get("extra", {}))),
        )

    def save_npoc(self, underlying: str, date: str, poc: float) -> None:
        """Persist a naked POC candidate."""
        self._execute_write(
            "INSERT OR REPLACE INTO npoc_records (underlying, session_date, poc_price, is_filled) VALUES (?, ?, ?, 0)",
            (str(underlying), str(date), float(poc)),
        )

    def mark_npoc_filled(self, underlying: str, session_date: str, filled_at: str) -> None:
        """Mark an NPOC row as filled when price revisits it."""
        self._execute_write(
            "UPDATE npoc_records SET is_filled = 1, filled_at = ? WHERE underlying = ? AND session_date = ?",
            (str(filled_at), str(underlying), str(session_date)),
        )

    def get_active_npocs(self, underlying: str) -> list[dict]:
        """Return unfilled NPOC rows for an underlying."""
        return [
            dict(row)
            for row in self._query(
                "SELECT * FROM npoc_records WHERE underlying = ? AND is_filled = 0 ORDER BY session_date DESC",
                (str(underlying),),
            )
        ]

    def get_previous_session_profile(self, symbol: str, market: str = "NSE") -> dict | None:
        rows = self._query(
            "SELECT * FROM session_profiles WHERE symbol = ? AND market = ? ORDER BY session_date DESC LIMIT 1",
            (symbol, market),
        )
        return dict(rows[0]) if rows else None

    def save_open_position(self, position: dict[str, Any]) -> None:
        self._execute_write(
            "INSERT OR REPLACE INTO open_positions (id, symbol, side, entry_price, size, stop_loss, take_profit, source, opened_at, extra) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (str(position.get("id", "")), str(position.get("symbol", "")),
             str(position.get("side", "")), float(position.get("entry_price", 0)),
             float(position.get("size", 0)), float(position.get("stop_loss", 0)),
             float(position.get("take_profit", 0)), str(position.get("source", "")),
             str(position.get("opened_at", "")), json.dumps(position.get("extra", {}))),
        )

    def delete_open_position(self, position_id: str) -> None:
        self._execute_write("DELETE FROM open_positions WHERE id = ?", (position_id,))

    def load_open_positions(self) -> list[dict]:
        return [dict(row) for row in self._query("SELECT * FROM open_positions")]

    def clear_all_open_positions(self) -> int:
        with self._lock:
            cursor = self._conn.execute("DELETE FROM open_positions")
            self._conn.commit()
            return cursor.rowcount

    def save_position_event(self, event: dict[str, Any]) -> None:
        self._execute_write(
            "INSERT INTO position_events (position_id, symbol, event_type, event_time, extra) VALUES (?, ?, ?, ?, ?)",
            (str(event.get("position_id", "")), str(event.get("symbol", "")),
             str(event.get("event_type", "")), str(event.get("event_time", "")),
             json.dumps(event.get("extra", {}))),
        )

    def query_position_events(self, position_id: str | None = None, symbol: str | None = None) -> list[dict]:
        if position_id:
            return [dict(row) for row in self._query("SELECT * FROM position_events WHERE position_id = ? ORDER BY created_at DESC", (position_id,))]
        elif symbol:
            return [dict(row) for row in self._query("SELECT * FROM position_events WHERE symbol = ? ORDER BY created_at DESC", (symbol,))]
        return [dict(row) for row in self._query("SELECT * FROM position_events ORDER BY created_at DESC LIMIT 100")]

    def query_ticks(self, symbol: str, start: str | None = None, end: str | None = None, limit: int = 1000) -> list[dict]:
        query = "SELECT * FROM ticks WHERE symbol = ?"
        params: list[Any] = [symbol]
        if start:
            query += " AND time >= ?"
            params.append(start)
        if end:
            query += " AND time <= ?"
            params.append(end)
        query += " ORDER BY time DESC LIMIT ?"
        params.append(limit)
        return [dict(row) for row in self._query(query, tuple(params))]

    def query_trades(self, start: str | None = None, end: str | None = None) -> list[dict]:
        query = "SELECT * FROM trades WHERE 1=1"
        params: list[Any] = []

        def _normalize_filter_value(raw: str, *, is_end: bool) -> str:
            if (
                len(raw) == 10
                and raw[4] == "-"
                and raw[7] == "-"
                and "T" not in raw
            ):
                return f"{raw}T{'23:59:59.999999' if is_end else '00:00:00'}"
            return raw

        if start:
            query += " AND closed_at >= ?"
            params.append(_normalize_filter_value(start, is_end=False))
        if end:
            query += " AND closed_at <= ?"
            params.append(_normalize_filter_value(end, is_end=True))
        query += " ORDER BY closed_at DESC"
        return [dict(row) for row in self._query(query, tuple(params))]

    def query_llm_decisions(self, symbol: str | None = None, start: str | None = None, end: str | None = None) -> list[dict]:
        query = "SELECT * FROM llm_decisions WHERE 1=1"
        params: list[Any] = []
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        if start:
            query += " AND created_at >= ?"
            params.append(start)
        if end:
            query += " AND created_at <= ?"
            params.append(end)
        query += " ORDER BY created_at DESC LIMIT 1000"
        return [dict(row) for row in self._query(query, tuple(params))]

    def get_recent_trades(self, limit: int = 5) -> list[dict]:
        return [dict(row) for row in self._query("SELECT * FROM trades ORDER BY closed_at DESC LIMIT ?", (limit,))]

    def persist(self, key: str, value: str | None) -> None:
        if value is None:
            self._execute_write("DELETE FROM kv_store WHERE key = ?", (key,))
        else:
            self._execute_write("INSERT OR REPLACE INTO kv_store (key, value) VALUES (?, ?)", (key, value))

    def load(self, key: str) -> str | None:
        rows = self._query("SELECT value FROM kv_store WHERE key = ?", (key,))
        return rows[0]["value"] if rows else None

    def close(self) -> None:
        self._flush_ticks()
        if self._conn:
            self._conn.close()

    def _query(self, query: str, params: tuple = ()) -> list:
        with self._lock:
            try:
                rows = self._conn.execute(query, params).fetchall()
                return rows
            except sqlite3.Error:
                logger.debug("Query failed: %s", query, exc_info=True)
                return []
