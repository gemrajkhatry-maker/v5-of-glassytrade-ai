"""Event store for audit trail."""

import json
import sqlite3
from dataclasses import dataclass, field, asdict
from datetime import datetime, timezone
from typing import Any
from app.core.correlation import get_correlation_id


@dataclass
class Event:
    """Domain event with correlation ID for tracing."""
    event_type: str
    correlation_id: str
    timestamp: str
    component: str
    symbol: str | None = None
    phase: str | None = None
    data: dict[str, Any] = field(default_factory=dict)


class EventStore:
    """SQLite-based event store for audit and diagnostics."""
    
    _instance = None
    _conn: sqlite3.Connection | None = None
    
    def __new__(cls):
        if cls._instance is None:
            cls._instance = super().__new__(cls)
        return cls._instance
    
    def __init__(self, db_path: str = "glassytrade.db"):
        if self._conn is not None:
            return
        self._conn = sqlite3.connect(db_path, check_same_thread=False)
        self._init_schema()
    
    def _init_schema(self):
        """Create events table if not exists."""
        self._conn.execute("""
            CREATE TABLE IF NOT EXISTS events (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                correlation_id TEXT NOT NULL,
                timestamp TEXT NOT NULL,
                event_type TEXT NOT NULL,
                component TEXT NOT NULL,
                symbol TEXT,
                phase TEXT,
                data TEXT,
                created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
            )
        """)
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_events_correlation ON events(correlation_id)")
        self._conn.execute("CREATE INDEX IF NOT EXISTS idx_events_timestamp ON events(timestamp)")
        self._conn.commit()
    
    def save(self, event: Event) -> int:
        """Persist an event and return its ID."""
        cursor = self._conn.execute(
            """
            INSERT INTO events 
            (correlation_id, timestamp, event_type, component, symbol, phase, data)
            VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event.correlation_id,
                event.timestamp,
                event.event_type,
                event.component,
                event.symbol,
                event.phase,
                json.dumps(event.data),
            ),
        )
        self._conn.commit()
        return cursor.lastrowid
    
    def query(self, correlation_id: str | None = None, 
              event_type: str | None = None,
              symbol: str | None = None,
              limit: int = 1000) -> list[Event]:
        """Query events by correlation ID or event type."""
        query = "SELECT * FROM events WHERE 1=1"
        params = []
        
        if correlation_id:
            query += " AND correlation_id = ?"
            params.append(correlation_id)
        if event_type:
            query += " AND event_type = ?"
            params.append(event_type)
        if symbol:
            query += " AND symbol = ?"
            params.append(symbol)
        
        query += " ORDER BY timestamp DESC LIMIT ?"
        params.append(limit)
        
        rows = self._conn.execute(query, params).fetchall()
        
        return [
            Event(
                correlation_id=row[1],
                timestamp=row[2],
                event_type=row[3],
                component=row[4],
                symbol=row[5],
                phase=row[6],
                data=json.loads(row[7] or "{}"),
            )
            for row in rows
        ]
    
    def get_timeline(self, symbol: str, limit: int = 100) -> list[dict]:
        """Get event timeline for a symbol."""
        rows = self._conn.execute(
            """
            SELECT timestamp, event_type, component, data
            FROM events
            WHERE symbol = ?
            ORDER BY timestamp DESC
            LIMIT ?
            """,
            (symbol, limit),
        ).fetchall()
        
        return [
            {
                "timestamp": row[0],
                "eventType": row[1],
                "component": row[2],
                "data": json.loads(row[3] or "{}"),
            }
            for row in rows
        ]


# Global event store instance
_event_store = None


def get_event_store() -> EventStore:
    global _event_store
    if _event_store is None:
        _event_store = EventStore()
    return _event_store


def publish_event(event_type: str, component: str, 
                symbol: str | None = None, 
                phase: str | None = None,
                data: dict | None = None) -> int:
    """Publish an event to the store."""
    event = Event(
        event_type=event_type,
        correlation_id=get_correlation_id(),
        timestamp=datetime.now(timezone.utc).isoformat(),
        component=component,
        symbol=symbol,
        phase=phase,
        data=data or {},
    )
    return get_event_store().save(event)