"""Tick repository — handles tick database operations."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

import sqlite3


class TickRepository:
    """Handles tick database operations."""

    INSERT_SQL = "INSERT OR REPLACE INTO ticks (symbol, time, open, high, low, close, volume, delta, extra) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
    SELECT_SQL = "SELECT * FROM ticks WHERE symbol = ?"

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def batch_insert(self, rows: list[Tuple]) -> None:
        """Batch insert ticks."""
        if not rows:
            return
        self._conn.executemany(TickRepository.INSERT_SQL, rows)
        self._conn.commit()

    def query(
        self, symbol: str, start: str | None = None, end: str | None = None, limit: int = 1000
    ) -> List[Dict[str, Any]]:
        """Query ticks with optional filters."""
        params = [symbol]
        where_clauses = []
        if start:
            where_clauses.append("time >= ?")
            params.append(start)
        if end:
            where_clauses.append("time <= ?")
            params.append(end)
        sql = TickRepository.SELECT_SQL
        if where_clauses:
            sql += " AND " + " AND ".join(where_clauses)
        sql += " ORDER BY time DESC LIMIT ?"
        params.append(limit)
        cursor = self._conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def prepare_row(symbol: str, tick_data: dict[str, Any]) -> Tuple:
        """Build row tuple for insertion."""
        extra = {k: v for k, v in tick_data.items() if k not in ("time", "open", "high", "low", "close", "volume", "delta")}
        return (
            symbol,
            tick_data.get("time", ""),
            tick_data.get("open", 0.0),
            tick_data.get("high", 0.0),
            tick_data.get("low", 0.0),
            tick_data.get("close", 0.0),
            tick_data.get("volume", 0.0),
            tick_data.get("delta", 0.0),
            json.dumps(extra),
        )
