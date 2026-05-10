"""Trade repository — handles trade database operations."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

import sqlite3


class TradeRepository:
    """Handles trade database operations."""

    INSERT_SQL = "INSERT INTO trades (position_id, symbol, side, entry_price, exit_price, size, pnl, source, reason, opened_at, closed_at, extra, llm_analysis) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    SELECT_SQL = "SELECT * FROM trades"

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def save(self, trade_data: dict[str, Any]) -> None:
        """Save a trade record."""
        params = self.build_insert_params(trade_data)
        self._conn.execute(TradeRepository.INSERT_SQL, params)
        self._conn.commit()

    def query(self, start: str | None = None, end: str | None = None) -> List[Dict[str, Any]]:
        """Query trades with optional date range filters."""
        sql, params = self.build_query_params(start, end)
        cursor = self._conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def build_insert_params(trade_data: dict[str, Any]) -> Tuple:
        """Build parameters for trade insert."""
        return (
            str(trade_data.get("position_id", "")),
            str(trade_data.get("symbol", "")),
            str(trade_data.get("side", "")),
            float(trade_data.get("entry_price", 0)),
            float(trade_data.get("exit_price", 0)),
            float(trade_data.get("size", 0)),
            float(trade_data.get("pnl", 0)),
            str(trade_data.get("source", "")),
            str(trade_data.get("reason", "")),
            str(trade_data.get("opened_at", "")),
            str(trade_data.get("closed_at", "")),
            json.dumps(trade_data.get("extra", {})),
            json.dumps(trade_data.get("llm_analysis", {})),
        )

    @staticmethod
    def build_query_params(start: str | None = None, end: str | None = None) -> Tuple[str, list]:
        """Build SQL and parameters for trade query."""
        sql = TradeRepository.SELECT_SQL
        params = []
        if start or end:
            conditions = []
            if start:
                conditions.append("opened_at >= ?")
                params.append(start)
            if end:
                conditions.append("opened_at <= ?")
                params.append(end)
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
        return sql, params
