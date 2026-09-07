"""SQLite storage adapter — persists ticks, trades, and positions.

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

from quant.contracts.ports.storage import IStorage
from shared.money import to_float

logger = logging.getLogger(__name__)

_SCHEMA = """
CREATE TABLE IF NOT EXISTS ticks (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    symbol TEXT NOT NULL,
    time TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL,
    volume REAL, delta REAL,
    extra TEXT,
    created_at TEXT DEFAULT (datetime('now', '+330 minutes'))
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
    created_at TEXT DEFAULT (datetime('now', '+330 minutes'))
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
    created_at TEXT DEFAULT (datetime('now', '+330 minutes'))
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
    created_at TEXT DEFAULT (datetime('now', '+330 minutes'))
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

CREATE TABLE IF NOT EXISTS orders (
    order_id TEXT PRIMARY KEY,
    signal_id TEXT,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity REAL,
    order_type TEXT,
    price REAL,
    status TEXT NOT NULL,
    broker_order_id TEXT,
    filled_quantity REAL,
    avg_fill_price REAL,
    reason TEXT,
    submitted_at TEXT,
    updated_at TEXT,
    extra TEXT,
    created_at TEXT DEFAULT (datetime('now', '+330 minutes'))
);

CREATE TABLE IF NOT EXISTS position_events (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    position_id TEXT,
    symbol TEXT,
    event_type TEXT NOT NULL,
    event_time TEXT,
    extra TEXT,
    created_at TEXT DEFAULT (datetime('now', '+330 minutes'))
);

CREATE TABLE IF NOT EXISTS fill_ledger (
    fill_id TEXT PRIMARY KEY,
    order_id TEXT,
    position_id TEXT NOT NULL,
    symbol TEXT NOT NULL,
    side TEXT NOT NULL,
    quantity REAL NOT NULL,
    fill_price REAL NOT NULL,
    pnl REAL,
    event_time TEXT NOT NULL,
    extra TEXT,
    created_at TEXT DEFAULT (datetime('now', '+330 minutes'))
);

CREATE INDEX IF NOT EXISTS idx_ticks_symbol_time ON ticks(symbol, time);
CREATE INDEX IF NOT EXISTS idx_trades_closed_at ON trades(closed_at);
CREATE INDEX IF NOT EXISTS idx_perf_created ON performance_snapshots(created_at);
CREATE INDEX IF NOT EXISTS idx_session_profiles ON session_profiles(symbol, market, session_date);
CREATE INDEX IF NOT EXISTS idx_position_events_pos_time ON position_events(position_id, created_at);
CREATE INDEX IF NOT EXISTS idx_position_events_symbol_time ON position_events(symbol, created_at);
CREATE INDEX IF NOT EXISTS idx_orders_symbol_status ON orders(symbol, status);
CREATE INDEX IF NOT EXISTS idx_orders_status ON orders(status);
CREATE INDEX IF NOT EXISTS idx_fill_ledger_position_time ON fill_ledger(position_id, event_time);
CREATE INDEX IF NOT EXISTS idx_fill_ledger_symbol_time ON fill_ledger(symbol, event_time);


CREATE TABLE IF NOT EXISTS npoc_records (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    underlying TEXT NOT NULL,
    session_date TEXT NOT NULL,
    poc_price REAL NOT NULL,
    is_filled INTEGER DEFAULT 0,
    filled_at TEXT,
    created_at TEXT DEFAULT (datetime('now', '+330 minutes'))
);
CREATE INDEX IF NOT EXISTS idx_npoc_underlying_date ON npoc_records(underlying, session_date);

CREATE TABLE IF NOT EXISTS fine_tuning_features (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    trade_id INTEGER,
    symbol TEXT NOT NULL,
    direction TEXT,
    market_state TEXT,
    poc REAL, vah REAL, val REAL,
    aggression REAL,
    cvd_slope REAL,
    delta_normalized REAL,
    volume REAL,
    imbalance REAL,
    vix_normalized REAL,
    vix_regime TEXT,
    iv_rank REAL,
    pcr_oi REAL,
    ib_location TEXT,
    ib_width_pct REAL,
    lvn_count INTEGER,
    hvn_count INTEGER,
    drive_number INTEGER,
    setup_type TEXT,
    result TEXT,
    pnl_r REAL,
    created_at TEXT DEFAULT (datetime('now', '+330 minutes'))
);
CREATE INDEX IF NOT EXISTS idx_finetune_symbol ON fine_tuning_features(symbol, created_at);
CREATE INDEX IF NOT EXISTS idx_finetune_result ON fine_tuning_features(result);

CREATE TABLE IF NOT EXISTS kv_store (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT DEFAULT (datetime('now', '+330 minutes'))
);
"""

# Tick batch settings
_TICK_BATCH_SIZE = 50
_TICK_FLUSH_INTERVAL = 5.0  # seconds

# Order state machine (C4). Terminal states mean the order reached a final
# outcome; anything else is "in-flight" and must be reconciled on restart so a
# crash between place_order and the fill ack cannot silently lose an order.
ORDER_TERMINAL_STATES = {"FILLED", "REJECTED", "CANCELLED", "EXPIRED"}


class SQLiteStorageAdapter(IStorage):
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
            self._conn.execute("PRAGMA busy_timeout=5000")
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
            except sqlite3.Error:
                logger.debug("Failed to create ticks index (may already exist)", exc_info=True)
            self._conn.commit()
            logger.info("SQLite database initialized at %s (WAL mode)", self._db_path)

    def _execute_write(self, query: str, params: tuple = (), *, auto_commit: bool = True) -> None:
        """Execute a write query with lock, commit, and rollback on error.

        This eliminates the duplicated try/except/rollback pattern across
        save_trade, save_open_position, etc.
        """
        with self._lock:
            try:
                self._conn.execute(query, params)
                if auto_commit:
                    self._conn.commit()
            except sqlite3.Error:
                self._conn.rollback()
                raise

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
        except sqlite3.Error:
            self._conn.rollback()  # Exception already caught at call site or handled above
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
            json.dumps(
                {
                    k: v
                    for k, v in tick_data.items()
                    if k
                    not in ("time", "open", "high", "low", "close", "volume", "delta")
                }
            ),
        )
        with self._lock:
            self._tick_buffer.append(row)
            if len(self._tick_buffer) >= _TICK_BATCH_SIZE:
                self._flush_ticks_unlocked()
            else:
                self._schedule_flush()

    def save_trade(
        self, trade_data: dict[str, Any], *, auto_commit: bool = True
    ) -> None:
        params = (
            str(trade_data.get("position_id", "")),
            str(trade_data.get("symbol", "")),
            str(trade_data.get("side", "")),
            to_float(trade_data.get("entry_price")),
            to_float(trade_data.get("exit_price")),
            to_float(trade_data.get("size")),
            to_float(trade_data.get("pnl")),
            str(trade_data.get("source", "")),
            str(trade_data.get("reason", "")),
            str(trade_data.get("opened_at", "")),
            str(trade_data.get("closed_at", "")),
            json.dumps(
                {
                    k: v
                    for k, v in trade_data.items()
                    if k
                    not in (
                        "position_id",
                        "symbol",
                        "side",
                        "entry_price",
                        "exit_price",
                        "size",
                        "pnl",
                        "source",
                        "reason",
                        "opened_at",
                        "closed_at",
                    )
                }
            ),
        )
        self._execute_write(
            "INSERT INTO trades (position_id, symbol, side, entry_price, exit_price, "
            "size, pnl, source, reason, opened_at, closed_at, extra) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            params,
            auto_commit=auto_commit,
        )

    def flush(self) -> None:
        """Explicit commit -- called by persistence bus after processing a batch."""
        with self._lock:
            try:
                self._conn.commit()
            except sqlite3.Error:
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
                        json.dumps(
                            {
                                k: v
                                for k, v in snapshot.items()
                                if k
                                not in (
                                    "symbol",
                                    "equity",
                                    "balance",
                                    "open_pnl",
                                    "open_positions",
                                    "total_trades",
                                    "win_rate",
                                )
                            }
                        ),
                    ),
                )
                self._conn.commit()
            except sqlite3.Error:
                self._conn.rollback()  # Exception already caught at call site or handled above
                raise

    def save_fine_tuning_features(self, features: dict[str, Any]) -> None:
        """Save fine-tuning feature vector for ML model training.

        Called after each closed trade to build the training dataset.
        Features include AMT state, aggression, VIX/PCR, IB location, etc.
        """
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO fine_tuning_features "
                    "(trade_id, symbol, direction, market_state, poc, vah, val, "
                    "aggression, cvd_slope, delta_normalized, volume, imbalance, "
                    "vix_normalized, vix_regime, iv_rank, pcr_oi, "
                    "ib_location, ib_width_pct, lvn_count, hvn_count, "
                    "drive_number, setup_type, result, pnl_r) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        features.get("trade_id"),
                        features.get("symbol", ""),
                        features.get("direction", ""),
                        features.get("market_state", ""),
                        features.get("poc", 0),
                        features.get("vah", 0),
                        features.get("val", 0),
                        features.get("aggression", 0),
                        features.get("cvd_slope", 0),
                        features.get("delta_normalized", 0),
                        features.get("volume", 0),
                        features.get("imbalance", 0),
                        features.get("vix_normalized", 0),
                        features.get("vix_regime", ""),
                        features.get("iv_rank", 0),
                        features.get("pcr_oi", 0),
                        features.get("ib_location", ""),
                        features.get("ib_width_pct", 0),
                        features.get("lvn_count", 0),
                        features.get("hvn_count", 0),
                        features.get("drive_number", 0),
                        features.get("setup_type", ""),
                        features.get("result", ""),
                        features.get("pnl_r", 0),
                    ),
                )
                self._conn.commit()
            except sqlite3.Error:
                self._conn.rollback()  # Exception already caught at call site or handled above
                raise

    # ------------------------------------------------------------------
    # Queries
    # ------------------------------------------------------------------

    def query_ticks(
        self,
        symbol: str,
        start: str | None = None,
        end: str | None = None,
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
        self,
        start: str | None = None,
        end: str | None = None,
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
                        json.dumps(
                            {
                                k: v
                                for k, v in profile_data.items()
                                if k
                                not in (
                                    "symbol",
                                    "market",
                                    "session_date",
                                    "poc",
                                    "vah",
                                    "val",
                                    "profile_shape",
                                    "total_volume",
                                )
                            }
                        ),
                    ),
                )
                self._conn.commit()
            except sqlite3.Error:
                self._conn.rollback()  # Exception already caught at call site or handled above
                raise

    def get_previous_session_profile(
        self,
        symbol: str,
        market: str = "NSE",
    ) -> dict[str, Any] | None:
        with self._lock:
            # First try exact symbol match
            row = self._conn.execute(
                "SELECT * FROM session_profiles WHERE symbol = ? AND market = ? "
                "ORDER BY session_date DESC LIMIT 1",
                (symbol, market),
            ).fetchone()
            if row:
                return dict(row)
            
            # Fallback: try to find by underlying extraction
            # For options: "NIFTY 26APR 24000 CALL" -> "NIFTY"
            # For MCX: "CRUDEOIL26APR 5600 CALL" -> "CRUDEOIL"
            import re
            
            # Pattern 1: NSE style - first word before space
            underlying_match = re.match(r'^([A-Z]+)', symbol)
            if underlying_match:
                underlying = underlying_match.group(1)
                row = self._conn.execute(
                    "SELECT * FROM session_profiles WHERE symbol = ? AND market = ? "
                    "ORDER BY session_date DESC LIMIT 1",
                    (underlying, market),
                ).fetchone()
                if row:
                    return dict(row)
            
            # Pattern 2: MCX style - extract commodity name before expiry digits
            # e.g., "CRUDEOIL26APR" -> "CRUDEOIL", "GOLD26MAY" -> "GOLD"
            mcx_match = re.match(r'^([A-Z]+?)(?=\d{2}[A-Z]{3})', symbol)
            if mcx_match:
                commodity = mcx_match.group(1)
                row = self._conn.execute(
                    "SELECT * FROM session_profiles WHERE symbol = ? AND market = ? "
                    "ORDER BY session_date DESC LIMIT 1",
                    (commodity, market),
                ).fetchone()
                if row:
                    return dict(row)
            
            # Pattern 3: Try any profile for this market (most recent)
            # This is a last resort - better than nothing
            row = self._conn.execute(
                "SELECT * FROM session_profiles WHERE market = ? "
                "ORDER BY session_date DESC LIMIT 1",
                (market,),
            ).fetchone()
            if row:
                return dict(row)
            
            return None

    # ------------------------------------------------------------------
    # Open position persistence (survive restarts)
    # ------------------------------------------------------------------

    def save_open_position(self, position: dict[str, Any]) -> None:
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT OR REPLACE INTO open_positions "
                    "(id, symbol, side, entry_price, size, stop_loss, take_profit, source, opened_at, extra) "
                    "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                    (
                        str(position.get("id", "")),
                        str(position.get("symbol", "")),
                        str(position.get("side", "")),
                        to_float(position.get("entry_price")),
                        to_float(position.get("size")),
                        to_float(position.get("stop_loss")),
                        to_float(position.get("take_profit")),
                        position.get("source", ""),
                        position.get("opened_at", ""),
                        json.dumps(
                            {
                                k: v
                                for k, v in position.items()
                                if k
                                not in (
                                    "id",
                                    "symbol",
                                    "side",
                                    "entry_price",
                                    "size",
                                    "stop_loss",
                                    "take_profit",
                                    "source",
                                    "opened_at",
                                )
                            }
                        ),
                    ),
                )
                self._conn.commit()
            except sqlite3.Error:
                self._conn.rollback()  # Exception already caught at call site or handled above
                raise

    def delete_open_position(self, position_id: str) -> None:
        with self._lock:
            try:
                self._conn.execute(
                    "DELETE FROM open_positions WHERE id = ?", (position_id,)
                )
                self._conn.commit()
            except sqlite3.Error:
                self._conn.rollback()  # Exception already caught at call site or handled above
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

    def clear_all_open_positions(self) -> int:
        """Clear all open positions from the database.

        Called on startup when CLEAR_POSITIONS_ON_RESTART is True to ensure
        the system starts fresh without stale positions from previous sessions.

        Returns:
            Number of positions that were cleared.
        """
        with self._lock:
            try:
                # Count positions before clearing
                count_row = self._conn.execute("SELECT COUNT(*) FROM open_positions").fetchone()
                count = count_row[0] if count_row else 0

                if count > 0:
                    self._conn.execute("DELETE FROM open_positions")
                    self._conn.commit()
                    logger.info("STARTUP: Cleared %d stale positions from database", count)

                return count
            except sqlite3.Error:
                self._conn.rollback()
                logger.error("Failed to clear open positions", exc_info=True)
                return 0

    # ------------------------------------------------------------------
    # Order persistence (durable order state machine — C4 crash recovery)
    # ------------------------------------------------------------------

    def save_order(self, order: dict[str, Any]) -> None:
        """Upsert a durable order row (a snapshot of the order state machine)."""
        self._execute_write(
            "INSERT OR REPLACE INTO orders "
            "(order_id, signal_id, symbol, side, quantity, order_type, price, status, "
            "broker_order_id, filled_quantity, avg_fill_price, reason, submitted_at, "
            "updated_at, extra) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(order.get("order_id", "")),
                str(order.get("signal_id", "")),
                str(order.get("symbol", "")),
                str(order.get("side", "")),
                to_float(order.get("quantity")),
                str(order.get("order_type", "")),
                to_float(order.get("price")),
                str(order.get("status", "")),
                str(order.get("broker_order_id", "")),
                to_float(order.get("filled_quantity")),
                to_float(order.get("avg_fill_price")),
                str(order.get("reason", "")),
                str(order.get("submitted_at", "")),
                str(order.get("updated_at", "")),
                json.dumps(
                    {
                        k: v
                        for k, v in order.items()
                        if k
                        not in (
                            "order_id", "signal_id", "symbol", "side", "quantity",
                            "order_type", "price", "status", "broker_order_id",
                            "filled_quantity", "avg_fill_price", "reason",
                            "submitted_at", "updated_at",
                        )
                    }
                ),
            ),
        )

    def update_order_status(
        self,
        order_id: str,
        status: str,
        *,
        broker_order_id: str | None = None,
        filled_quantity: float | None = None,
        avg_fill_price: float | None = None,
    ) -> None:
        """Transition an order's state, recording fill details when provided."""
        sets = ["status = ?", "updated_at = datetime('now', '+330 minutes')"]
        params: list[Any] = [status]
        if broker_order_id is not None:
            sets.append("broker_order_id = ?")
            params.append(broker_order_id)
        if filled_quantity is not None:
            sets.append("filled_quantity = ?")
            params.append(to_float(filled_quantity))
        if avg_fill_price is not None:
            sets.append("avg_fill_price = ?")
            params.append(to_float(avg_fill_price))
        params.append(order_id)
        self._execute_write(
            f"UPDATE orders SET {', '.join(sets)} WHERE order_id = ?",
            tuple(params),
        )

    def load_orders(
        self,
        status: str | None = None,
        symbol: str | None = None,
    ) -> list[dict[str, Any]]:
        with self._lock:
            query = "SELECT * FROM orders WHERE 1=1"
            params: list[Any] = []
            if status:
                query += " AND status = ?"
                params.append(status)
            if symbol:
                query += " AND symbol = ?"
                params.append(symbol)
            query += " ORDER BY created_at ASC"
            rows = self._conn.execute(query, params).fetchall()
            result = []
            for row in rows:
                d = dict(row)
                extra = json.loads(d.pop("extra", "{}") or "{}")
                d.update(extra)
                result.append(d)
            return result

    def load_inflight_orders(self) -> list[dict[str, Any]]:
        """Orders not yet in a terminal state — must be reconciled on restart."""
        with self._lock:
            placeholders = ", ".join("?" for _ in ORDER_TERMINAL_STATES)
            query = (
                f"SELECT * FROM orders WHERE status NOT IN ({placeholders}) "
                "ORDER BY created_at ASC"
            )
            rows = self._conn.execute(query, tuple(ORDER_TERMINAL_STATES)).fetchall()
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

    def save_fill(self, fill: dict[str, Any]) -> None:
        """Persist one fill exactly once using its durable logical fill ID."""
        fill_id = str(fill.get("fill_id") or "").strip()
        if not fill_id:
            raise ValueError("fill_id is required for fill-ledger persistence")
        self._execute_write(
            "INSERT OR IGNORE INTO fill_ledger "
            "(fill_id, order_id, position_id, symbol, side, quantity, fill_price, pnl, event_time, extra) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                fill_id,
                str(fill.get("order_id") or ""),
                str(fill.get("position_id") or ""),
                str(fill.get("symbol") or ""),
                str(fill.get("side") or ""),
                to_float(fill.get("quantity")),
                to_float(fill.get("fill_price")),
                to_float(fill.get("pnl")),
                str(fill.get("event_time") or ""),
                json.dumps({
                    key: value for key, value in fill.items()
                    if key not in {
                        "fill_id", "order_id", "position_id", "symbol", "side",
                        "quantity", "fill_price", "pnl", "event_time",
                    }
                }),
            ),
        )

    def load_fills(
        self, *, position_id: str | None = None, symbol: str | None = None
    ) -> list[dict[str, Any]]:
        """Load the append-only fill ledger in event order."""
        with self._lock:
            query = "SELECT * FROM fill_ledger WHERE 1=1"
            params: list[Any] = []
            if position_id:
                query += " AND position_id = ?"
                params.append(position_id)
            if symbol:
                query += " AND symbol = ?"
                params.append(symbol)
            query += " ORDER BY event_time ASC, created_at ASC"
            rows = self._conn.execute(query, params).fetchall()
            result = []
            for row in rows:
                data = dict(row)
                extra = json.loads(data.pop("extra", "{}") or "{}")
                data.update(extra)
                result.append(data)
            return result

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
                        json.dumps(
                            {
                                k: to_float(v)
                                if isinstance(v, (int, float))
                                or hasattr(v, "__float__")
                                else v
                                for k, v in payload.items()
                                if k
                                not in (
                                    "position_id",
                                    "symbol",
                                    "event_type",
                                    "event_time",
                                )
                            }
                        ),
                    ),
                )
                self._conn.commit()
            except sqlite3.Error:
                self._conn.rollback()  # Exception already caught at call site or handled above
                raise

    def query_position_events(
        self,
        position_id: str | None = None,
        symbol: str | None = None,
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

    def query_signal_decisions(
        self,
        symbol: str | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Query signal tracking decisions (GENERATED/BLOCKED/WAITING/COOLDOWN).

        These are stored as position_events with event_type starting with 'SIGNAL_'.
        """
        with self._lock:
            query = "SELECT * FROM position_events WHERE event_type LIKE 'SIGNAL_%'"
            params: list[Any] = []
            if symbol:
                query += " AND symbol = ?"
                params.append(symbol)
            query += " ORDER BY created_at DESC LIMIT ?"
            params.append(limit)
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

    def kv_set(self, key: str, value: Any) -> None:
        """Persist a key-value pair (upsert)."""
        if isinstance(value, (dict, list, tuple)):
            import json
            value = json.dumps(value)
        elif not isinstance(value, str):
            value = str(value)
            
        with self._lock:
            try:
                self._conn.execute(
                    "INSERT INTO kv_store (key, value, updated_at) VALUES (?, ?, datetime('now', '+330 minutes')) "
                    "ON CONFLICT(key) DO UPDATE SET value=excluded.value, updated_at=excluded.updated_at",
                    (key, value),
                )
                self._conn.commit()
            except sqlite3.Error:
                self._conn.rollback()  # Exception already caught at call site or handled above
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
            except sqlite3.Error:
                self._conn.rollback()  # Exception already caught at call site or handled above
                raise

    def mark_npoc_filled(
        self, underlying: str, session_date: str, filled_at: str
    ) -> None:
        """Mark an NPOC as filled when price revisits the level."""
        with self._lock:
            try:
                self._conn.execute(
                    "UPDATE npoc_records SET is_filled = 1, filled_at = ? "
                    "WHERE underlying = ? AND session_date = ? AND is_filled = 0",
                    (filled_at, underlying, session_date),
                )
                self._conn.commit()
            except sqlite3.Error:
                self._conn.rollback()  # Exception already caught at call site or handled above
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
                "SELECT value FROM kv_store WHERE key = ?",
                (key,),
            ).fetchone()
            return row[0] if row else None

    # ------------------------------------------------------------------
    # Composite profile queries (Gap #4)
    # ------------------------------------------------------------------

    def load_composite_profiles(
        self,
        symbol: str,
        market: str = "NSE",
        limit: int = 5,
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

    def close(self) -> None:
        """Close the database connection and cancel any pending flush timer."""
        if self._flush_timer is not None and self._flush_timer.is_alive():
            self._flush_timer.cancel()
            self._flush_timer = None
        with self._lock:
            try:
                self._conn.close()
            except sqlite3.Error:
                logger.debug("Error closing database connection", exc_info=True)
            logger.info("SQLite database connection closed")
