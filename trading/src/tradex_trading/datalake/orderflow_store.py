"""SQLite persistence for orderflow artifacts (candles, profiles, signals).

Complements ``ParquetStorage`` (OHLCV datalake) and ``SQLiteOrderStore``
(orders). Stores the analytics layer's enriched candles and engine outputs so
multi-day volume-profile merges and signal history survive restarts.

Thread-safe (``RLock`` + ``check_same_thread=False``), matching the rest of
the trading persistence layer. Timestamps are stored as UTC ISO-8601 strings;
footprints/levels serialize to JSON with stringified price keys.
"""

from __future__ import annotations

import json
import sqlite3
import threading
from pathlib import Path

from tradex_domain.enums import Timeframe
from tradex_domain.strategy import Signal

from tradex_trading.analytics.orderflow_types import OrderflowCandle, VolumeProfile

_SCHEMA = """
CREATE TABLE IF NOT EXISTS orderflow_candles (
    instrument TEXT NOT NULL,
    timeframe TEXT NOT NULL,
    timestamp TEXT NOT NULL,
    open REAL, high REAL, low REAL, close REAL,
    volume REAL, buy_volume REAL, sell_volume REAL, tick_count INTEGER,
    footprint_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_of_candles ON orderflow_candles(instrument, timeframe, timestamp);

CREATE TABLE IF NOT EXISTS volume_profiles (
    instrument TEXT NOT NULL,
    session_date TEXT NOT NULL,
    poc REAL, vah REAL, val REAL, total_volume REAL,
    shape TEXT, poc_position_pct REAL,
    lvn_json TEXT, vap_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_of_vp ON volume_profiles(instrument, session_date);

CREATE TABLE IF NOT EXISTS signals (
    instrument TEXT NOT NULL,
    timestamp TEXT,
    direction TEXT NOT NULL,
    strength REAL,
    reason TEXT,
    metadata_json TEXT
);
CREATE INDEX IF NOT EXISTS idx_of_signals ON signals(instrument, timestamp);
"""


class OrderflowStore:
    """Minimal SQLite store for orderflow analytics output."""

    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        self._lock = threading.RLock()
        self._conn: sqlite3.Connection | None = None

    # ------------------------------------------------------------------ lifecycle

    def connect(self) -> None:
        with self._lock:
            if self._conn is not None:
                return
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            self._conn = sqlite3.connect(self.path, check_same_thread=False)
            self._conn.executescript(_SCHEMA)
            self._conn.commit()

    def close(self) -> None:
        with self._lock:
            if self._conn is not None:
                self._conn.close()
                self._conn = None

    def __enter__(self) -> OrderflowStore:
        self.connect()
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def _db(self) -> sqlite3.Connection:
        if self._conn is None:
            raise RuntimeError("OrderflowStore is not connected")
        return self._conn

    # ------------------------------------------------------------------ write

    def insert_candle(self, candle: OrderflowCandle) -> None:
        footprint = {
            str(price): {"bid": fp.bid_volume, "ask": fp.ask_volume}
            for price, fp in candle.footprint.items()
        }
        with self._lock:
            self._db().execute(
                "INSERT INTO orderflow_candles "
                "(instrument, timeframe, timestamp, open, high, low, close, "
                "volume, buy_volume, sell_volume, tick_count, footprint_json) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    str(candle.instrument),
                    candle.timeframe.value,
                    candle.timestamp.isoformat(),
                    float(candle.ohlc.open.value),
                    float(candle.ohlc.high.value),
                    float(candle.ohlc.low.value),
                    float(candle.ohlc.close.value),
                    float(candle.volume.value),
                    candle.buy_volume,
                    candle.sell_volume,
                    candle.tick_count,
                    json.dumps(footprint),
                ),
            )
            self._db().commit()

    def insert_volume_profile(self, instrument: str, vp: VolumeProfile) -> None:
        with self._lock:
            self._db().execute(
                "INSERT INTO volume_profiles "
                "(instrument, session_date, poc, vah, val, total_volume, shape, "
                "poc_position_pct, lvn_json, vap_json) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    instrument,
                    vp.session_date,
                    vp.poc,
                    vp.vah,
                    vp.val,
                    vp.total_volume,
                    vp.shape,
                    vp.poc_position_pct,
                    json.dumps(list(vp.lvn_levels)),
                    json.dumps({str(k): v for k, v in vp.volume_at_price.items()}),
                ),
            )
            self._db().commit()

    def insert_signal(self, instrument: str, signal: Signal) -> None:
        with self._lock:
            self._db().execute(
                "INSERT INTO signals "
                "(instrument, timestamp, direction, strength, reason, metadata_json) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                (
                    instrument,
                    signal.timestamp.isoformat() if signal.timestamp else None,
                    signal.direction.value,
                    signal.strength,
                    signal.reason,
                    json.dumps(signal.metadata, default=str),
                ),
            )
            self._db().commit()

    # ------------------------------------------------------------------ read

    def recent_candles(
        self, instrument: str, timeframe: Timeframe, limit: int = 500
    ) -> list[tuple[str, float, float, float, float, float, float, float, int]]:
        """Return (timestamp, o,h,l,c,vol,buy,sell,tick_count) rows, oldest first."""
        with self._lock:
            cur = self._db().execute(
                "SELECT timestamp, open, high, low, close, volume, "
                "buy_volume, sell_volume, tick_count "
                "FROM orderflow_candles WHERE instrument = ? AND timeframe = ? "
                "ORDER BY timestamp DESC LIMIT ?",
                (instrument, timeframe.value, limit),
            )
            rows = cur.fetchall()
        return list(reversed(rows))

    def recent_profiles(self, instrument: str, days: int = 5) -> list[VolumeProfile]:
        with self._lock:
            cur = self._db().execute(
                "SELECT session_date, poc, vah, val, total_volume, shape, "
                "poc_position_pct, lvn_json, vap_json "
                "FROM volume_profiles WHERE instrument = ? "
                "ORDER BY session_date DESC LIMIT ?",
                (instrument, days),
            )
            rows = cur.fetchall()
        profiles = []
        for row in rows:
            vap = json.loads(row[8]) if row[8] else {}
            profiles.append(
                VolumeProfile(
                    session_date=row[0],
                    poc=row[1],
                    vah=row[2],
                    val=row[3],
                    total_volume=row[4],
                    shape=row[5],
                    poc_position_pct=row[6],
                    lvn_levels=tuple(json.loads(row[7]) if row[7] else []),
                    volume_at_price={float(k): v for k, v in vap.items()},
                )
            )
        return list(reversed(profiles))

    def recent_signal_reasons(self, instrument: str, limit: int = 100) -> list[str]:
        with self._lock:
            cur = self._db().execute(
                "SELECT reason FROM signals WHERE instrument = ? ORDER BY timestamp DESC LIMIT ?",
                (instrument, limit),
            )
            return [r[0] for r in cur.fetchall()]


__all__ = ["OrderflowStore"]
