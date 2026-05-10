"""Position repository — handles open positions and position events."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

import sqlite3


class PositionRepository:
    """Handles position and event database operations."""

    INSERT_OPEN_POSITION_SQL = "INSERT OR REPLACE INTO open_positions (id, symbol, side, entry_price, size, stop_loss, take_profit, source, opened_at, extra) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    DELETE_OPEN_POSITION_SQL = "DELETE FROM open_positions WHERE id = ?"
    SELECT_OPEN_POSITIONS_SQL = "SELECT * FROM open_positions"
    CLEAR_ALL_OPEN_POSITIONS_SQL = "DELETE FROM open_positions"

    INSERT_POSITION_EVENT_SQL = "INSERT INTO position_events (position_id, event_type, symbol, side, price, size, reason, timestamp, extra) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
    SELECT_POSITION_EVENTS_SQL = "SELECT * FROM position_events"

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def save_open_position(self, position: dict[str, Any]) -> None:
        """Save an open position."""
        params = self.build_open_position_params(position)
        self._conn.execute(PositionRepository.INSERT_OPEN_POSITION_SQL, params)
        self._conn.commit()

    def delete_open_position(self, position_id: str) -> None:
        """Delete an open position by ID."""
        self._conn.execute(PositionRepository.DELETE_OPEN_POSITION_SQL, (str(position_id),))
        self._conn.commit()

    def load_open_positions(self) -> List[Dict[str, Any]]:
        """Load all open positions."""
        cursor = self._conn.execute(PositionRepository.SELECT_OPEN_POSITIONS_SQL)
        return [dict(row) for row in cursor.fetchall()]

    def clear_all_open_positions(self) -> int:
        """Clear all open positions; returns number of rows deleted."""
        cur = self._conn.execute(PositionRepository.CLEAR_ALL_OPEN_POSITIONS_SQL)
        self._conn.commit()
        return cur.rowcount

    def save_position_event(self, event: dict[str, Any]) -> None:
        """Save a position event."""
        params = self.build_position_event_params(event)
        self._conn.execute(PositionRepository.INSERT_POSITION_EVENT_SQL, params)
        self._conn.commit()

    def query_position_events(self, position_id: str | None = None, symbol: str | None = None) -> List[Dict[str, Any]]:
        """Query position events with optional filters."""
        sql, params = self.build_position_events_query_params(position_id, symbol)
        cursor = self._conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def build_open_position_params(position: dict[str, Any]) -> Tuple:
        """Build parameters for open position insert."""
        return (
            str(position.get("id", "")),
            str(position.get("symbol", "")),
            str(position.get("side", "")),
            float(position.get("entry_price", 0)),
            float(position.get("size", 0)),
            float(position.get("stop_loss", 0)),
            float(position.get("take_profit", 0)),
            str(position.get("source", "")),
            str(position.get("opened_at", "")),
            json.dumps(position.get("extra", {})),
        )

    @staticmethod
    def build_position_event_params(event: dict[str, Any]) -> Tuple:
        """Build parameters for position event insert."""
        return (
            str(event.get("position_id", "")),
            str(event.get("event_type", "")),
            str(event.get("symbol", "")),
            str(event.get("side", "")),
            float(event.get("price", 0)),
            float(event.get("size", 0)),
            str(event.get("reason", "")),
            str(event.get("timestamp", "")),
            json.dumps(event.get("extra", {})),
        )

    @staticmethod
    def build_position_events_query_params(
        position_id: str | None = None, symbol: str | None = None
    ) -> Tuple[str, list]:
        """Build SQL and params for position events query."""
        sql = PositionRepository.SELECT_POSITION_EVENTS_SQL
        params = []
        conditions = []
        if position_id:
            conditions.append("position_id = ?")
            params.append(str(position_id))
        if symbol:
            conditions.append("symbol = ?")
            params.append(str(symbol))
        if conditions:
            sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY timestamp DESC"
        return sql, params
