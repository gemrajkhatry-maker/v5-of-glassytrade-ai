"""NPOC repository — handles naked POC of the day records."""
from __future__ import annotations

from typing import Any, Dict, List, Tuple

import sqlite3


class NPOCRepository:
    """Handles NPOC records persistence."""

    INSERT_SQL = "INSERT OR REPLACE INTO npoc_records (underlying, session_date, poc_price, is_filled) VALUES (?, ?, ?, 0)"
    MARK_FILLED_SQL = "UPDATE npoc_records SET is_filled = 1, filled_at = ? WHERE underlying = ? AND session_date = ?"
    SELECT_ACTIVE_SQL = "SELECT * FROM npoc_records WHERE underlying = ? AND is_filled = 0 ORDER BY session_date DESC"

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def save(self, underlying: str, date: str, poc: float) -> None:
        """Save a new NPOC candidate."""
        self._conn.execute(NPOCRepository.INSERT_SQL, (str(underlying), str(date), float(poc)))
        self._conn.commit()

    def mark_filled(self, underlying: str, session_date: str, filled_at: str) -> None:
        """Mark an NPOC as filled."""
        self._conn.execute(
            NPOCRepository.MARK_FILLED_SQL,
            (str(filled_at), str(underlying), str(session_date)),
        )
        self._conn.commit()

    def get_active(self, underlying: str) -> List[Dict[str, Any]]:
        """Get unfilled NPOCs for an underlying."""
        cursor = self._conn.execute(NPOCRepository.SELECT_ACTIVE_SQL, (str(underlying),))
        return [dict(row) for row in cursor.fetchall()]
