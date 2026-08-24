"""Prior-session level persistence — per-symbol POC/VAH/VAL + NPOC records.

Pure ``quant.*``/stdlib module (no backend imports). QuantEngine uses it to
(1) carry the previous session's POC/value-area into the AMT analyzer so the
Triple-A take-profit can target the *previous balance area* (Fabio's rule)
instead of a bare 2R placeholder, and (2) act as the storage port for
:class:`quant.amt.session.npoc.NPOCTracker` (unfilled prior-session POCs as
magnets/targets).

Thread safety: the store is shared across per-symbol engine threads, so all
mutations happen under a lock and writes are atomic (temp file + ``os.replace``).
``path=None`` keeps the store fully in-memory (tests / replay).
"""

from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
from typing import Optional

logger = logging.getLogger(__name__)


class SessionLevelStore:
    """Persist/load per-symbol prior-session levels and NPOC records.

    JSON shape::

        {
          "levels": {"SYM": {"date": "2026-08-10", "poc": 100.0,
                              "vah": 102.0, "val": 98.0}},
          "npocs":  {"NIFTY": [{"price": 100.0, "session_date": "2026-08-10",
                                "is_filled": false, "filled_at": null}]}
        }

    ``path=None`` (default) is memory-only — no disk I/O, used by replay/tests.
    """

    def __init__(self, path: Optional[str] = None) -> None:
        self._path = path
        self._lock = threading.RLock()
        self._levels: dict[str, dict] = {}
        self._npocs: dict[str, list[dict]] = {}
        self._kv: dict[str, str] = {}
        if path:
            self._load()

    # ------------------------------------------------------------------
    # KV store port (SessionRisk persistence — daily-loss budget)
    # ------------------------------------------------------------------

    def kv_set(self, key: str, value: str) -> bool:
        """Crash-safe key/value write, persisted alongside session levels.

        Mirrors ``Database.kv_set``'s contract: dict/list values are
        JSON-encoded so a later ``json.loads`` round-trips them.

        Returns whether the write actually reached disk. Callers that persist
        safety-critical state (e.g. ``SessionRisk.halt()``) must check this —
        a halt that only lives in memory does not survive a restart.
        """
        if isinstance(value, (dict, list, tuple)):
            value = json.dumps(value)
        with self._lock:
            self._kv[str(key)] = str(value)
            return self._flush()

    def kv_get(self, key: str) -> str | None:
        with self._lock:
            return self._kv.get(str(key))

    # ------------------------------------------------------------------
    # Prior-session levels
    # ------------------------------------------------------------------

    def save_levels(self, symbol: str, date: str, poc: float, vah: float, val: float) -> None:
        """Record a completed session's POC/VAH/VAL for ``symbol``."""
        with self._lock:
            self._levels[symbol] = {
                "date": str(date),
                "poc": float(poc),
                "vah": float(vah),
                "val": float(val),
            }
            self._flush()

    def load_levels(self, symbol: str) -> dict:
        """Return ``{date, poc, vah, val}`` for ``symbol`` (zeros when absent)."""
        with self._lock:
            rec = self._levels.get(symbol) or {}
        return {
            "date": rec.get("date", ""),
            "poc": float(rec.get("poc") or 0.0),
            "vah": float(rec.get("vah") or 0.0),
            "val": float(rec.get("val") or 0.0),
        }

    # ------------------------------------------------------------------
    # NPOC storage port (NPOCTracker compatibility)
    # ------------------------------------------------------------------

    def save_npoc(self, underlying: str, date: str, poc: float) -> None:
        """Record a session POC as an unfilled NPOC for ``underlying``."""
        with self._lock:
            rows = self._npocs.setdefault(underlying, [])
            if any(r.get("session_date") == str(date) for r in rows):
                return  # duplicate session — keep the first record
            rows.append(
                {
                    "price": float(poc),
                    "session_date": str(date),
                    "is_filled": False,
                    "filled_at": None,
                }
            )
            self._flush()

    def mark_npoc_filled(self, underlying: str, date: str, filled_at: str) -> None:
        with self._lock:
            rows = self._npocs.get(underlying, [])
            for r in rows:
                if r.get("session_date") == str(date):
                    r["is_filled"] = True
                    r["filled_at"] = str(filled_at)
            self._flush()

    def get_active_npocs(self, underlying: str) -> list[dict]:
        """Return unfilled NPOCs in the storage shape NPOCTracker expects.

        ``NPOCTracker.load_from_storage`` reads ``poc_price``/``underlying``
        keys (the SQLite adapter's contract), so the store maps its internal
        ``price`` field to that shape here.
        """
        with self._lock:
            return [
                {
                    "poc_price": r.get("price"),
                    "session_date": r.get("session_date"),
                    "underlying": underlying,
                    "is_filled": r.get("is_filled", False),
                    "filled_at": r.get("filled_at"),
                }
                for r in self._npocs.get(underlying, [])
                if not r.get("is_filled")
            ]

    # ------------------------------------------------------------------
    # Disk I/O
    # ------------------------------------------------------------------

    def _load(self) -> None:
        try:
            with open(self._path, encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        self._levels = data.get("levels") or {}
        self._npocs = data.get("npocs") or {}
        self._kv = data.get("kv") or {}

    def _flush(self) -> bool:
        """Write the in-memory store to disk. Returns True on success.

        ``path=None`` (memory-only mode, e.g. tests/replay) reports success
        since there is nothing to persist by design. A disk write failure is
        reported (not raised) so most callers (levels/NPOC bookkeeping) keep
        degrading gracefully; safety-critical callers like ``SessionRisk``
        must check the return value themselves.
        """
        if not self._path:
            return True
        payload = {"levels": self._levels, "npocs": self._npocs, "kv": self._kv}
        dir_name = os.path.dirname(self._path) or "."
        fd, tmp = tempfile.mkstemp(dir=dir_name, prefix=".session-levels-", suffix=".tmp")
        try:
            with os.fdopen(fd, "w", encoding="utf-8") as f:
                json.dump(payload, f, indent=2)
                f.flush()
                os.fsync(f.fileno())
            os.replace(tmp, self._path)
            return True
        except OSError:
            logger.warning("Failed to persist session levels to %s", self._path, exc_info=True)
            try:
                os.unlink(tmp)
            except OSError:
                pass
            return False
