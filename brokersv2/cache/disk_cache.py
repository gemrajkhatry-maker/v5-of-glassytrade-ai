"""
SQLite Disk Cache - Persistent cache using SQLite database.
"""

from __future__ import annotations

import json
import sqlite3
import time
from pathlib import Path
from typing import Any, Optional

from brokersv2.cache.base import CacheInterface, CacheStats


class SQLiteDiskCache(CacheInterface):
    """
    Persistent cache using SQLite database.
    
    Features:
    - Survives application restarts
    - TTL-based expiry
    - Automatic cleanup of expired entries
    - JSON serialization for complex objects
    
    Usage:
        cache = SQLiteDiskCache(db_path="/tmp/market_data.db")
        await cache.set("key", value, ttl_seconds=3600)
        value = await cache.get("key")
    """
    
    def __init__(self, db_path: str = "/tmp/market_data_cache.db"):
        """
        Initialize SQLite cache.
        
        Args:
            db_path: Path to SQLite database file
        """
        self._db_path = Path(db_path)
        self._stats = CacheStats()
        self._init_db()
    
    def _init_db(self):
        """Initialize database schema."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("""
                CREATE TABLE IF NOT EXISTS cache (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL,
                    created_at REAL NOT NULL,
                    expires_at REAL,
                    access_count INTEGER DEFAULT 0,
                    last_accessed REAL NOT NULL
                )
            """)
            conn.execute("""
                CREATE INDEX IF NOT EXISTS idx_expires_at 
                ON cache(expires_at)
            """)
    
    async def get(self, key: str) -> Optional[Any]:
        """
        Get value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            Cached value or None if not found/expired
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(
                "SELECT value, expires_at FROM cache WHERE key = ?",
                (key,)
            )
            row = cursor.fetchone()
            
            if not row:
                self._stats.record_miss()
                return None
            
            value_json, expires_at = row
            
            # Check expiry
            if expires_at and time.time() > expires_at:
                self._delete_key(key, conn)
                self._stats.record_miss()
                return None
            
            # Update access stats
            conn.execute(
                """UPDATE cache 
                   SET access_count = access_count + 1, 
                       last_accessed = ? 
                   WHERE key = ?""",
                (time.time(), key)
            )
            
            self._stats.record_hit()
            return json.loads(value_json)
    
    async def set(self, key: str, value: Any, ttl_seconds: Optional[int] = None) -> None:
        """
        Set value in cache.
        
        Args:
            key: Cache key
            value: Value to cache (must be JSON-serializable)
            ttl_seconds: Time-to-live in seconds (optional)
        """
        value_json = json.dumps(value)
        created_at = time.time()
        expires_at = created_at + ttl_seconds if ttl_seconds else None
        
        with sqlite3.connect(self._db_path) as conn:
            # Try to insert, update if exists
            try:
                conn.execute(
                    """INSERT INTO cache 
                       (key, value, created_at, expires_at, access_count, last_accessed)
                       VALUES (?, ?, ?, ?, 0, ?)""",
                    (key, value_json, created_at, expires_at, created_at)
                )
            except sqlite3.IntegrityError:
                # Key exists, update it
                conn.execute(
                    """UPDATE cache 
                       SET value = ?, created_at = ?, expires_at = ?, 
                           last_accessed = ?
                       WHERE key = ?""",
                    (value_json, created_at, expires_at, created_at, key)
                )
    
    async def delete(self, key: str) -> bool:
        """
        Delete value from cache.
        
        Args:
            key: Cache key
            
        Returns:
            True if key was deleted, False if not found
        """
        with sqlite3.connect(self._db_path) as conn:
            return self._delete_key(key, conn)
    
    def _delete_key(self, key: str, conn: sqlite3.Connection) -> bool:
        """Delete key from database (internal)."""
        cursor = conn.execute("DELETE FROM cache WHERE key = ?", (key,))
        return cursor.rowcount > 0
    
    async def clear(self) -> None:
        """Clear all cached data."""
        with sqlite3.connect(self._db_path) as conn:
            conn.execute("DELETE FROM cache")
        self._stats.reset()
    
    def get_stats(self) -> CacheStats:
        """
        Get cache statistics.
        
        Returns:
            CacheStats with current metrics
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM cache")
            self._stats.item_count = cursor.fetchone()[0]
            
            # Get approximate size
            self._stats.size_bytes = self._db_path.stat().st_size if self._db_path.exists() else 0
        
        return self._stats
    
    def __len__(self) -> int:
        """Return number of items in cache."""
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute("SELECT COUNT(*) FROM cache")
            return cursor.fetchone()[0]
    
    async def cleanup_expired(self) -> int:
        """
        Remove all expired entries.
        
        Returns:
            Number of entries removed
        """
        with sqlite3.connect(self._db_path) as conn:
            cursor = conn.execute(
                "DELETE FROM cache WHERE expires_at IS NOT NULL AND expires_at < ?",
                (time.time(),)
            )
            return cursor.rowcount
