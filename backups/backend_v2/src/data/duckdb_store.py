"""
DuckDB persistence layer for GlassyTrade AI V2.

Stores ticks, session profiles, signals, trades, and session risk state.
"""

import duckdb
from datetime import date, datetime
from decimal import Decimal
from pathlib import Path
from typing import Any, Optional

import structlog

logger = structlog.get_logger()


class DuckDBStore:
    """DuckDB persistence for trading data."""

    def __init__(self, db_path: str = "data/db/glassytrade.db"):
        self._db_path = db_path
        self._conn: Optional[duckdb.DuckDBPyConnection] = None

    def connect(self) -> None:
        """Connect to DuckDB and initialize schema."""
        Path(self._db_path).parent.mkdir(parents=True, exist_ok=True)
        self._conn = duckdb.connect(self._db_path)
        self.initialize_schema()
        logger.info("duckdb_connected", path=self._db_path)

    def close(self) -> None:
        """Close DuckDB connection."""
        if self._conn:
            self._conn.close()
            self._conn = None
            logger.info("duckdb_closed")

    def initialize_schema(self) -> None:
        """Initialize database schema (idempotent)."""
        if not self._conn:
            raise RuntimeError("Not connected to DuckDB")

        # Session profiles persisted at close
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS session_profiles (
                date        DATE,
                symbol      VARCHAR,
                poc         DECIMAL(10,2),
                vah         DECIMAL(10,2),
                val         DECIMAL(10,2),
                total_vol   BIGINT,
                profile_json JSON,
                created_at  TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # All ticks stored intraday, purged daily
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS ticks (
                timestamp   TIMESTAMP,
                symbol      VARCHAR,
                price       DECIMAL(10,2),
                ask_vol     INTEGER,
                bid_vol     INTEGER,
                trade_size  INTEGER,
                delta       INTEGER
            )
        """)

        # Signal log - every output schema written here
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS signals (
                timestamp       TIMESTAMP,
                symbol          VARCHAR,
                direction       VARCHAR,
                confidence      VARCHAR,
                aggression_score DECIMAL(4,2),
                entry_zone      DECIMAL(10,2),
                stop_loss       DECIMAL(10,2),
                target          DECIMAL(10,2),
                risk_reward     DECIMAL(4,2),
                market_state    VARCHAR,
                drive_number    INTEGER,
                rationale       TEXT,
                full_json       JSON
            )
        """)

        # Trade log - entries, exits, PnL
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS trades (
                trade_id        VARCHAR,
                symbol          VARCHAR,
                entry_time      TIMESTAMP,
                exit_time       TIMESTAMP,
                direction       VARCHAR,
                entry_price     DECIMAL(10,2),
                exit_price      DECIMAL(10,2),
                lots            INTEGER,
                pnl             DECIMAL(10,2),
                risk_pct        DECIMAL(5,3),
                partition       INTEGER,
                exit_reason     VARCHAR
            )
        """)

        # Open trades (survives restart)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS open_trades (
                trade_id        VARCHAR PRIMARY KEY,
                symbol          VARCHAR,
                entry_time      TIMESTAMP,
                direction       VARCHAR,
                entry_price     DECIMAL(10,2),
                stop_loss       DECIMAL(10,2),
                target          DECIMAL(10,2),
                lots            INTEGER,
                initial_risk    DECIMAL(10,2),
                p1_taken        BOOLEAN DEFAULT FALSE,
                p2_taken        BOOLEAN DEFAULT FALSE,
                p3_taken        BOOLEAN DEFAULT FALSE,
                breakeven_set   BOOLEAN DEFAULT FALSE,
                add_count       INTEGER DEFAULT 0,
                full_json       JSON
            )
        """)

        # Session risk log
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS session_risk (
                date            DATE,
                symbol          VARCHAR,
                daily_pnl       DECIMAL(10,2),
                max_drawdown    DECIMAL(5,3),
                total_trades    INTEGER,
                win_rate        DECIMAL(4,3),
                consecutive_losses INTEGER,
                session_killed  BOOLEAN
            )
        """)

        # Economic events (EIA releases, etc.)
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS economic_events (
                event_date      DATE,
                event_time      TIME,
                event_type      VARCHAR,
                symbol          VARCHAR,
                suppress_start  TIME,
                suppress_end    TIME
            )
        """)

        # Key-value store for session state
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS kv_store (
                key     VARCHAR PRIMARY KEY,
                value   JSON,
                updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)

        # Create indexes for common queries
        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_ticks_symbol_time 
            ON ticks(symbol, timestamp)
        """)

        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_signals_symbol_time 
            ON signals(symbol, timestamp)
        """)

        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_trades_symbol 
            ON trades(symbol)
        """)

        self._conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_session_profiles_symbol_date 
            ON session_profiles(symbol, date)
        """)

        logger.info("duckdb_schema_initialized")

    def save_session_profile(
        self,
        symbol: str,
        session_date: date,
        poc: float,
        vah: float,
        val: float,
        total_vol: int,
        profile_json: str,
    ) -> None:
        """Save session profile at close."""
        if not self._conn:
            raise RuntimeError("Not connected to DuckDB")

        self._conn.execute(
            """
            INSERT INTO session_profiles (date, symbol, poc, vah, val, total_vol, profile_json)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [session_date, symbol, poc, vah, val, total_vol, profile_json],
        )
        logger.info("session_profile_saved", symbol=symbol, date=session_date)

    def load_prev_session_profile(self, symbol: str) -> Optional[dict]:
        """Load previous session profile for gap analysis."""
        if not self._conn:
            raise RuntimeError("Not connected to DuckDB")

        result = self._conn.execute(
            """
            SELECT poc, vah, val, total_vol, profile_json
            FROM session_profiles
            WHERE symbol = ?
            ORDER BY date DESC
            LIMIT 1
            """,
            [symbol],
        ).fetchone()

        if result:
            return {
                "POC": float(result[0]),
                "VAH": float(result[1]),
                "VAL": float(result[2]),
                "total_vol": result[3],
                "profile_json": result[4],
            }
        return None

    def save_tick(
        self,
        timestamp: datetime,
        symbol: str,
        price: float,
        ask_vol: int,
        bid_vol: int,
        trade_size: int,
        delta: int,
    ) -> None:
        """Save a tick to the database."""
        if not self._conn:
            raise RuntimeError("Not connected to DuckDB")

        self._conn.execute(
            """
            INSERT INTO ticks (timestamp, symbol, price, ask_vol, bid_vol, trade_size, delta)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            [timestamp, symbol, price, ask_vol, bid_vol, trade_size, delta],
        )

    def save_signal(
        self,
        timestamp: datetime,
        symbol: str,
        direction: str,
        confidence: str,
        aggression_score: float,
        entry_zone: float,
        stop_loss: float,
        target: float,
        risk_reward: float,
        market_state: str,
        drive_number: int,
        rationale: str,
        full_json: str,
    ) -> None:
        """Save a signal to the database."""
        if not self._conn:
            raise RuntimeError("Not connected to DuckDB")

        self._conn.execute(
            """
            INSERT INTO signals (
                timestamp, symbol, direction, confidence, aggression_score,
                entry_zone, stop_loss, target, risk_reward, market_state,
                drive_number, rationale, full_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                timestamp, symbol, direction, confidence, aggression_score,
                entry_zone, stop_loss, target, risk_reward, market_state,
                drive_number, rationale, full_json,
            ],
        )

    def save_open_trade(
        self,
        trade_id: str,
        symbol: str,
        entry_time: datetime,
        direction: str,
        entry_price: float,
        stop_loss: float,
        target: float,
        lots: int,
        initial_risk: float,
        full_json: str,
    ) -> None:
        """Save an open trade (persists across restarts)."""
        if not self._conn:
            raise RuntimeError("Not connected to DuckDB")

        self._conn.execute(
            """
            INSERT INTO open_trades (
                trade_id, symbol, entry_time, direction, entry_price,
                stop_loss, target, lots, initial_risk, full_json
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            [
                trade_id, symbol, entry_time, direction, entry_price,
                stop_loss, target, lots, initial_risk, full_json,
            ],
        )

    def close_trade(
        self,
        trade_id: str,
        exit_time: datetime,
        exit_price: float,
        pnl: float,
        exit_reason: str,
    ) -> None:
        """Move trade from open_trades to trades table."""
        if not self._conn:
            raise RuntimeError("Not connected to DuckDB")

        # Get open trade
        trade = self._conn.execute(
            "SELECT * FROM open_trades WHERE trade_id = ?", [trade_id]
        ).fetchone()

        if trade:
            # Insert into trades
            self._conn.execute(
                """
                INSERT INTO trades (
                    trade_id, symbol, entry_time, exit_time, direction,
                    entry_price, exit_price, lots, pnl, risk_pct, partition, exit_reason
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                [
                    trade_id, trade[1], trade[2], exit_time, trade[3],
                    float(trade[4]), exit_price, trade[7], pnl, 0.005, 0, exit_reason,
                ],
            )

            # Delete from open_trades
            self._conn.execute(
                "DELETE FROM open_trades WHERE trade_id = ?", [trade_id]
            )

    def load_open_trades(self) -> list[dict]:
        """Load all open trades (for crash recovery)."""
        if not self._conn:
            raise RuntimeError("Not connected to DuckDB")

        results = self._conn.execute("SELECT * FROM open_trades").fetchall()
        trades = []
        for row in results:
            trades.append({
                "trade_id": row[0],
                "symbol": row[1],
                "entry_time": row[2],
                "direction": row[3],
                "entry_price": float(row[4]),
                "stop_loss": float(row[5]),
                "target": float(row[6]),
                "lots": row[7],
                "initial_risk": float(row[8]),
                "p1_taken": row[9],
                "p2_taken": row[10],
                "p3_taken": row[11],
                "breakeven_set": row[12],
                "add_count": row[13],
            })
        return trades

    def kv_set(self, key: str, value: str) -> None:
        """Set a key-value pair."""
        if not self._conn:
            raise RuntimeError("Not connected to DuckDB")

        self._conn.execute(
            """
            INSERT INTO kv_store (key, value, updated_at)
            VALUES (?, ?, CURRENT_TIMESTAMP)
            ON CONFLICT (key) DO UPDATE SET value = ?, updated_at = CURRENT_TIMESTAMP
            """,
            [key, value, value],
        )

    def kv_get(self, key: str) -> Optional[str]:
        """Get a value by key."""
        if not self._conn:
            raise RuntimeError("Not connected to DuckDB")

        result = self._conn.execute(
            "SELECT value FROM kv_store WHERE key = ?", [key]
        ).fetchone()

        return result[0] if result else None

    def purge_old_ticks(self, older_than: date) -> int:
        """Purge ticks older than specified date."""
        if not self._conn:
            raise RuntimeError("Not connected to DuckDB")

        result = self._conn.execute(
            "DELETE FROM ticks WHERE timestamp < ?", [older_than]
        )
        count = result.rowcount
        logger.info("ticks_purged", count=count, older_than=older_than)
        return count