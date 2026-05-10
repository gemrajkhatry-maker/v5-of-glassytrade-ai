"""Session profile repository — handles session profile persistence."""
from __future__ import annotations

import json
from typing import Any, Dict, List, Tuple

import sqlite3


class SessionProfileRepository:
    """Handles session profile database operations."""

    INSERT_SQL = "INSERT INTO session_profiles (symbol, market, session_date, poc, vah, val, profile_shape, total_volume, extra) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)"
    SELECT_PREVIOUS_SQL = "SELECT * FROM session_profiles WHERE symbol = ? AND market = ? ORDER BY session_date DESC LIMIT 1"

    def __init__(self, conn: sqlite3.Connection):
        self._conn = conn

    def save(self, profile_data: dict[str, Any]) -> None:
        """Save a session profile."""
        params = self.build_save_params(profile_data)
        self._conn.execute(SessionProfileRepository.INSERT_SQL, params)
        self._conn.commit()

    def get_previous_session_profile(self, symbol: str, market: str = "NSE") -> Dict[str, Any] | None:
        """Get the most recent completed session profile for a symbol."""
        cursor = self._conn.execute(
            SessionProfileRepository.SELECT_PREVIOUS_SQL,
            (str(symbol), str(market)),
        )
        row = cursor.fetchone()
        return dict(row) if row else None

    @staticmethod
    def build_save_params(profile_data: dict[str, Any]) -> Tuple:
        """Build parameters for session profile insert."""
        return (
            str(profile_data.get("symbol", "")),
            str(profile_data.get("market", "NSE")),
            str(profile_data.get("session_date", "")),
            float(profile_data.get("poc", 0)),
            float(profile_data.get("vah", 0)),
            float(profile_data.get("val", 0)),
            str(profile_data.get("profile_shape", "")),
            float(profile_data.get("total_volume", 0)),
            json.dumps(profile_data.get("extra", {})),
        )
