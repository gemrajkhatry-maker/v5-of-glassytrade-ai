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
from uuid import uuid4

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

CREATE TABLE IF NOT EXISTS position_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id TEXT,
    symbol TEXT,
    event_type TEXT NOT NULL,
    event_time TEXT,
    extra TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);

CREATE INDEX IF NOT EXISTS idx_ticks_symbol_time ON ticks(symbol, time);
CREATE INDEX IF NOT EXISTS idx_trades_closed_at ON trades(closed_at);
CREATE INDEX IF NOT EXISTS idx_llm_created ON llm_decisions(created_at);
CREATE INDEX IF NOT EXISTS idx_perf_created ON performance_snapshots(created_at);
CREATE INDEX IF NOT EXISTS idx_session_profiles ON session_profiles(symbol, market, session_date);
CREATE INDEX IF NOT EXISTS idx_position_events_pos_time ON position_events(position_id, created_at);
CREATE INDEX IF NOT EXISTS idx_position_events_symbol_time ON position_events(symbol, created_at);


CREATE TABLE IF NOT EXISTS npoc_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    underlying TEXT NOT NULL,
    session_date TEXT NOT NULL,
    poc_price REAL NOT NULL,
    is_filled INTEGER DEFAULT 0,
    filled_at TEXT,
    created_at TEXT DEFAULT (datetime('now'))
);
CREATE INDEX IF NOT EXISTS idx_npoc_underlying_date ON npoc_records(underlying, session_date);

CREATE TABLE IF NOT EXISTS kv_store (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now'))
);
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
            self._conn.execute("PRAGMA wal_autocheckpoint=500")
            self._conn.executescript(_SCHEMA)
            # Upgrade to UNIQUE index on (symbol, time): dedup rows first, then swap index.
            try:
                self._conn.execute(
                    "DELETE FROM ticks WHERE id NOT IN ("
                    "  SELECT MAX(id) FROM ticks GROUP BY symbol, time"
                    ")"
                )
                self._conn.execute("DROP INDEX IF EXISTS idx_ticks_symbol_time")
                self._conn.execute(
                    "CREATE UNIQUE INDEX IF NOT EXISTS idx_ticks_symbol_time ON ticks(symbol, time)"
                )
            except Exception:
                logger.debug("Exception handled silently", exc_info=True)
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
            self._flush_ticks_unlocked()

    def _flush_ticks_unlocked(self) -> None:
        """Internal flush — caller MUST hold self._lock."""
        if not self._tick_buffer:
            return
        batch = self._tick_buffer[:]
        self._tick_buffer.clear()
        self._last_flush_time = time.time()
        try:
            self._conn.executemany(
                "INSERT OR REPLACE INTO ticks (symbol, time, open, high, low, close, volume, delta, extra) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                batch,
            )
            self._conn.commit()
        except Exception:
            self._conn.rollback()
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
            if len(self._tick_buffer) >= _TICK_BATCH_SIZE:
                self._flush_ticks_unlocked()
            else:
                self._schedule_flush()

    def save_trade(self, trade_data: dict[str, Any], *, auto_commit: bool = True) -> None:
        # Helper to convert Decimal to float for SQLite
        def _f(val):
            return float(val) if val is not None and hasattr(val, '__float__') else (val or 0.0)
        
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO trades (position_id, symbol, side, entry_price, exit_price, "
                    "size, pnl, source, reason, opened_at, closed_at, extra) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(trade_data.get("position_id", "")),
                        str(trade_data.get("symbol", "")),
                        str(trade_data.get("side", "")),
                        _f(trade_data.get("entry_price")),
                        _f(trade_data.get("exit_price")),
                        _f(trade_data.get("size")),
                        _f(trade_data.get("pnl")),
                        str(trade_data.get("source", "")),
                        str(trade_data.get("reason", "")),
                        str(trade_data.get("opened_at", "")),
                        str(trade_data.get("closed_at", "")),
                        json.dumps({k: v for k, v in trade_data.items()
                                    if k not in ("position_id", "symbol", "side", "entry_price",
                                                 "exit_price", "size", "pnl", "source", "reason",
                                                 "opened_at", "closed_at")}),
                    ),
                )
                if auto_commit:
                    self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def save_llm_decision(self, decision_data: dict[str, Any], *, auto_commit: bool = True) -> None:
        _KNOWN_KEYS = {"symbol", "direction", "confidence", "rationale",
                        "input_prompt", "raw_output", "market_state", "aggression",
                        "price", "vah", "val", "poc", "delta", "volume", "profile_shape"}
        with self._lock:
            try:
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
                if auto_commit:
                    self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def flush(self) -> None:
        """Explicit commit -- called by persistence bus after processing a batch."""
        with self._lock:
            try:
                self._conn.commit()
            except Exception:
                logger.debug("flush commit failed", exc_info=True)

    def save_performance_snapshot(self, snapshot: dict[str, Any]) -> None:
        with self._lock:
            try:
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
            except Exception:
                self._conn.rollback()
                raise

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
        symbols: list[str] | None = None,
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
            if symbols:
                placeholders = ",".join(["?"] * len(symbols))
                query += f" AND symbol IN ({placeholders})"
                params.extend(symbols)
            query += " ORDER BY created_at ASC"
            rows = self._conn.execute(query, params).fetchall()
            return [dict(r) for r in rows]

    def save_session_profile(self, profile_data: dict[str, Any]) -> None:
        with self._lock:
            try:
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
            except Exception:
                self._conn.rollback()
                raise

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
            try:
                # Convert Decimal to float for SQLite
                def _to_float(val):
                    if val is None:
                        return 0.0
                    return float(val) if hasattr(val, '__float__') else val
                
                self._conn.execute(
                    "INSERT OR REPLACE INTO open_positions "
                    "(id, symbol, side, entry_price, size, stop_loss, take_profit, source, opened_at, extra) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(position.get("id", "")),
                        str(position.get("symbol", "")),
                        str(position.get("side", "")),
                        _to_float(position.get("entry_price")),
                        _to_float(position.get("size")),
                        _to_float(position.get("stop_loss")),
                        _to_float(position.get("take_profit")),
                        position.get("source", ""),
                        position.get("opened_at", ""),
                        json.dumps({k: v for k, v in position.items()
                                    if k not in ("id", "symbol", "side", "entry_price", "size",
                                                 "stop_loss", "take_profit", "source", "opened_at")}),
                    ),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def delete_open_position(self, position_id: str) -> None:
        with self._lock:
            try:
                self._conn.execute("DELETE FROM open_positions WHERE id = ?", (position_id,))
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

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

    def save_position_event(self, event: dict[str, Any]) -> None:
        with self._lock:
            try:
                payload = dict(event)
                payload.setdefault("event_id", str(uuid4()))
                self._conn.execute(
                    "INSERT INTO position_events (position_id, symbol, event_type, event_time, extra) "
                    "VALUES (?, ?, ?, ?, ?)",
                    (
                        payload.get("position_id", ""),
                        payload.get("symbol", ""),
                        payload.get("event_type", ""),
                        payload.get("event_time", ""),
                        json.dumps({
                            k: (float(v) if isinstance(v, (int, float)) or hasattr(v, '__float__') else v)
                            for k, v in payload.items()
                            if k not in ("position_id", "symbol", "event_type", "event_time")
                        }),
                    ),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def query_position_events(
        self, position_id: str | None = None, symbol: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            query = "SELECT * FROM position_events WHERE 1=1"
            params: list[Any] = []
            if position_id:
                query += " AND position_id = ?"
                params.append(position_id)
            if symbol:
                query += " AND symbol = ?"
                params.append(symbol)
            query += " ORDER BY created_at ASC"
            rows = self._conn.execute(query, params).fetchall()
            result: list[dict[str, Any]] = []
            for row in rows:
                d = dict(row)
                extra = json.loads(d.pop("extra", "{}") or "{}")
                d.update(extra)
                result.append(d)
            return result

    # ------------------------------------------------------------------
    # Key-Value store (crash-safe state persistence)
    # ------------------------------------------------------------------

    def kv_set(self, key: str, value: str) -> None:
        """Persist a key-value pair (upsert)."""
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO kv_store (key, value, updated_at) VALUES (?, ?, datetime('now')) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                    (key, value),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise


    # ------------------------------------------------------------------
    # NPOC (Naked POC) persistence
    # ------------------------------------------------------------------

    def save_npoc(self, underlying: str, session_date: str, poc_price: float) -> None:
        """Persist a new naked POC record for tracking."""
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO npoc_records (underlying, session_date, poc_price) "
                    "VALUES (?, ?, ?)",
                    (underlying, session_date, poc_price),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def mark_npoc_filled(self, underlying: str, session_date: str, filled_at: str) -> None:
        """Mark an NPOC as filled when price revisits the level."""
        with self._lock:
            try:
                self._conn.execute(
                    "UPDATE npoc_records SET is_filled = 1, filled_at = ? "
                    "WHERE underlying = ? AND session_date = ? AND is_filled = 0",
                    (filled_at, underlying, session_date),
                )
                self._conn.commit()
            except Exception:
                self._conn.rollback()
                raise

    def get_active_npocs(self, underlying: str) -> list[dict[str, Any]]:
        """Retrieve all unfilled NPOC records for an underlying."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM npoc_records WHERE underlying = ? AND is_filled = 0 "
                "ORDER BY session_date DESC",
                (underlying,),
            ).fetchall()
            return [dict(r) for r in rows]

    def kv_get(self, key: str) -> str | None:
        """Retrieve a value by key, or None if not found."""
        with self._lock:
            row = self._conn.execute(
                "SELECT value FROM kv_store WHERE key = ?", (key,),
            ).fetchone()
            return row[0] if row else None

    # ------------------------------------------------------------------
    # Composite profile queries (Gap #4)
    # ------------------------------------------------------------------

    def load_composite_profiles(
        self, symbol: str, market: str = "NSE", limit: int = 5,
    ) -> list[dict[str, Any]]:
        """Load last N session profiles for composite profile calculation."""
        with self._lock:
            rows = self._conn.execute(
                "SELECT * FROM session_profiles WHERE symbol = ? AND market = ? "
                "ORDER BY session_date DESC LIMIT ?",
                (symbol, market, limit),
            ).fetchall()
            result = []
            for row in rows:
                d = dict(row)
                extra = json.loads(d.pop("extra", "{}") or "{}")
                d.update(extra)
                result.append(d)
            return result

