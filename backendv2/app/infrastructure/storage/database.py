"""SQLite storage adapter — persists ticks, trades, LLM decisions, positions.

Refactored to use repository classes for data access.
"""

from __future__ import annotations

import json
import logging
import os
import sqlite3
import threading
import time
from typing import Any

from app.domain.shared.port.storage import IStorage
from app.infrastructure.storage.repositories.decision_repository import DecisionRepository
from app.infrastructure.storage.repositories.npoc_repository import NPOCRepository
from app.infrastructure.storage.repositories.position_repository import PositionRepository
from app.infrastructure.storage.repositories.session_profile_repository import SessionProfileRepository
from app.infrastructure.storage.repositories.tick_repository import TickRepository
from app.infrastructure.storage.repositories.trade_repository import TradeRepository

logger = logging.getLogger(__name__)

_TICK_BATCH_SIZE = 50
_TICK_FLUSH_INTERVAL = 5.0  # seconds


class SQLiteStorageAdapter(IStorage):
    """Thread-safe SQLite storage with repository delegation."""

    def __init__(self, db_path: str = "data/trades.db"):
        self._db_path = db_path
        self._conn: sqlite3.Connection | None = None
        self._lock = threading.RLock()
        self._tick_buffer: list[tuple] = []
        self._last_flush_time = 0.0
        self._initialize_db()

    def _initialize_db(self) -> None:
        os.makedirs(os.path.dirname(self._db_path), exist_ok=True)
        self._conn = sqlite3.connect(
            self._db_path, check_same_thread=False, isolation_level=None, timeout=30.0
        )
        self._conn.execute("PRAGMA journal_mode=WAL")
        self._create_tables()
        self._repositories = {
            "tick": TickRepository(self._conn),
            "trade": TradeRepository(self._conn),
            "decision": DecisionRepository(self._conn),
            "position": PositionRepository(self._conn),
            "session_profile": SessionProfileRepository(self._conn),
            "npoc": NPOCRepository(self._conn),
        }

    def _create_tables(self) -> None:
        schema = """
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
            position_id TEXT,
            event_type TEXT,
            symbol TEXT,
            side TEXT,
            price REAL,
            size REAL,
            reason TEXT,
            timestamp TEXT,
            extra TEXT
        );
        CREATE TABLE IF NOT EXISTS npoc_records (
            underlying TEXT NOT NULL,
            session_date TEXT NOT NULL,
            poc_price REAL NOT NULL,
            is_filled INTEGER DEFAULT 0,
            filled_at TEXT,
            PRIMARY KEY (underlying, session_date)
        );
        """
        with self._lock:
            self._conn.executescript(schema)

    # ── Tick methods ────────────────────────────────────────────────────────────
    def save_tick(self, symbol: str, tick_data: dict[str, Any]) -> None:
        row = TickRepository.prepare_row(symbol, tick_data)
        with self._lock:
            self._tick_buffer.append(row)
            if len(self._tick_buffer) >= _TICK_BATCH_SIZE:
                self._flush_ticks_locked()
            else:
                self._schedule_flush()

    def _flush_ticks(self) -> None:
        with self._lock:
            self._flush_ticks_locked()

    def _flush_ticks_locked(self) -> None:
        if not self._tick_buffer:
            self._last_flush_time = time.time()
            return
        batch = self._tick_buffer[:]
        self._tick_buffer.clear()
        try:
            self._repositories["tick"].batch_insert(batch)
            self._last_flush_time = time.time()
        except Exception:
            logger.exception("Failed to flush ticks")

    def _schedule_flush(self) -> None:
        now = time.time()
        if now - self._last_flush_time >= _TICK_FLUSH_INTERVAL:
            self._flush_ticks()

    # ── Trade methods ───────────────────────────────────────────────────────────
    def save_trade(self, trade_data: dict[str, Any]) -> None:
        with self._lock:
            self._repositories["trade"].save(trade_data)

    def query_trades(self, start: str | None = None, end: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            return self._repositories["trade"].query(start, end)

    # ── LLM decision methods ────────────────────────────────────────────────────
    def save_llm_decision(self, decision_data: dict[str, Any]) -> None:
        with self._lock:
            self._repositories["decision"].save(decision_data)

    def query_llm_decisions(self, start: str | None = None, end: str | None = None) -> list[dict[str, Any]]:
        with self._lock:
            return self._repositories["decision"].query(start, end)

    # ── Position methods ────────────────────────────────────────────────────────
    def save_position_event(self, event: dict[str, Any]) -> None:
        with self._lock:
            self._repositories["position"].save_position_event(event)

    def query_position_events(
        self, position_id: str | None = None, symbol: str | None = None
    ) -> list[dict[str, Any]]:
        with self._lock:
            return self._repositories["position"].query_position_events(position_id, symbol)

    def save_open_position(self, position: dict[str, Any]) -> None:
        with self._lock:
            self._repositories["position"].save_open_position(position)

    def delete_open_position(self, position_id: str) -> None:
        with self._lock:
            self._repositories["position"].delete_open_position(position_id)

    def load_open_positions(self) -> list[dict[str, Any]]:
        with self._lock:
            return self._repositories["position"].load_open_positions()

    def clear_all_open_positions(self) -> int:
        with self._lock:
            return self._repositories["position"].clear_all_open_positions()

    # ── Performance snapshot ────────────────────────────────────────────────────
    def save_performance_snapshot(self, snapshot: dict[str, Any]) -> None:
        with self._lock:
            self._conn.execute(
                "INSERT INTO performance_snapshots (symbol, equity, balance, open_pnl, open_positions, total_trades, win_rate, extra) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(snapshot.get("symbol", "")),
                    float(snapshot.get("equity", 0)),
                    float(snapshot.get("balance", 0)),
                    float(snapshot.get("open_pnl", 0)),
                    int(snapshot.get("open_positions", 0)),
                    int(snapshot.get("total_trades", 0)),
                    float(snapshot.get("win_rate", 0)),
                    json.dumps(snapshot.get("extra", {})),
                ),
            )

    # ── Session profile ─────────────────────────────────────────────────────────
    def save_session_profile(self, profile_data: dict[str, Any]) -> None:
        with self._lock:
            self._repositories["session_profile"].save(profile_data)

    def get_previous_session_profile(self, symbol: str, market: str = "NSE") -> dict[str, Any] | None:
        with self._lock:
            return self._repositories["session_profile"].get_previous_session_profile(symbol, market)

    # ── NPOC ────────────────────────────────────────────────────────────────────
    def save_npoc(self, underlying: str, date: str, poc: float) -> None:
        with self._lock:
            self._repositories["npoc"].save(underlying, date, poc)

    def mark_npoc_filled(self, underlying: str, session_date: str, filled_at: str) -> None:
        with self._lock:
            self._repositories["npoc"].mark_filled(underlying, session_date, filled_at)

    def get_active_npocs(self, underlying: str) -> list[dict[str, Any]]:
        with self._lock:
            return self._repositories["npoc"].get_active(underlying)

    # ── Lifecycle ───────────────────────────────────────────────────────────────
    def flush(self) -> None:
        self._flush_ticks()

    def teardown(self) -> None:
        self.flush()
        with self._lock:
            if self._conn:
                self._conn.close()

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "tick_buffer_len": len(self._tick_buffer),
                "last_flush": self._last_flush_time,
            }

    def restore(self, payload: dict[str, Any]) -> None:
        with self._lock:
            if "tick_buffer" in payload:
                self._tick_buffer = payload["tick_buffer"][:2048]
