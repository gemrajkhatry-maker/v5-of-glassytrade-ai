"""LLM decision repository — handles LLM decision database operations."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

import sqlite3


class DecisionRepository:
    """Handles LLM decision database operations."""

    INSERT_SQL = "INSERT INTO llm_decisions (symbol, direction, confidence, rationale, input_prompt, raw_output, market_state, aggression, price, vah, val, poc, delta, volume, profile_shape, extra) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)"
    SELECT_SQL = "SELECT * FROM llm_decisions"

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def save(self, decision_data: dict[str, Any]) -> None:
        """Save an LLM decision record."""
        params = self.build_insert_params(decision_data)
        self._conn.execute(DecisionRepository.INSERT_SQL, params)
        self._conn.commit()

    def query(self, start: str | None = None, end: str | None = None) -> List[Dict[str, Any]]:
        """Query LLM decisions with optional date range."""
        sql, params = self.build_query_params(start, end)
        cursor = self._conn.execute(sql, params)
        return [dict(row) for row in cursor.fetchall()]

    @staticmethod
    def build_insert_params(decision_data: dict[str, Any]) -> Tuple:
        """Build parameters for decision insert."""
        return (
            str(decision_data.get("symbol", "")),
            str(decision_data.get("direction", "")),
            str(decision_data.get("confidence", "")),
            str(decision_data.get("rationale", "")),
            str(decision_data.get("input_prompt", "")),
            str(decision_data.get("raw_output", "")),
            str(decision_data.get("market_state", "")),
            str(decision_data.get("aggression", "")),
            float(decision_data.get("price", 0)),
            float(decision_data.get("vah", 0)),
            float(decision_data.get("val", 0)),
            float(decision_data.get("poc", 0)),
            float(decision_data.get("delta", 0)),
            float(decision_data.get("volume", 0)),
            str(decision_data.get("profile_shape", "")),
            json.dumps(decision_data.get("extra", {})),
        )

    @staticmethod
    def build_query_params(start: str | None = None, end: str | None = None) -> Tuple[str, list]:
        """Build SQL and parameters for decision query."""
        sql = DecisionRepository.SELECT_SQL
        params = []
        if start or end:
            conditions = []
            if start:
                conditions.append("created_at >= ?")
                params.append(start)
            if end:
                conditions.append("created_at <= ?")
                params.append(end)
            if conditions:
                sql += " WHERE " + " AND ".join(conditions)
        sql += " ORDER BY created_at DESC"
        return sql, params
