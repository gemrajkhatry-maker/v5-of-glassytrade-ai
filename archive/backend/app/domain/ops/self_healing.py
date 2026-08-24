"""Self-Healing Mechanisms — order rejection recovery + DB write fallback.

Handles failures gracefully without blocking trade decisions:
  1. Order rejection recovery (retry with backoff)
  2. DB write failure fallback (in-memory buffer)
  3. WebSocket reconnect (exponential backoff)
  4. LLM timeout recovery (disable after N consecutive timeouts)
"""

from __future__ import annotations

import inspect
import json
import logging
import os
import threading
import time
from datetime import datetime, timedelta, timezone
from collections import deque
from contextlib import contextmanager
from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path
from uuid import uuid4

from app.core.async_boundary import ensure_sync_adapter_result

try:  # ``fcntl`` is available on the supported Linux deployment targets.
    import fcntl
except ImportError:  # pragma: no cover - defensive portability fallback
    fcntl = None


_FALLBACK_ID_KEY = "__db_fallback_id"
_FALLBACK_TIME_KEY = "__db_fallback_time"
_SHARED_FALLBACK_ATTR = "_shared_db_fallback_buffer"


class _LocalFallbackSpool:
    """Crash-safe JSONL spool used when the SQLite outbox is unavailable.

    The spool is deliberately small and stdlib-only. Every append and
    acknowledgement is fsynced, and a separate lock file serializes access
    across threads and processes. Acknowledged records are compacted while the
    lock is held so a long outage cannot grow the file without bound.
    """

    def __init__(self, path: str | os.PathLike[str] | None) -> None:
        if path is None:
            self._path = None
        else:
            try:
                self._path = Path(os.fspath(path))
            except TypeError:
                # Test doubles and incomplete adapters may expose arbitrary
                # attributes named ``fallback_spool_path``. They must not
                # become a filesystem dependency.
                self._path = None
        self._lock_path = (
            self._path.with_name(f"{self._path.name}.lock")
            if self._path is not None
            else None
        )
        self._quarantine_path = (
            self._path.with_name(f"{self._path.name}.quarantine.jsonl")
            if self._path is not None
            else None
        )
        self._thread_lock = threading.RLock()

    @contextmanager
    def locked(self):
        if self._path is None or fcntl is None:
            yield
            return

        self._path.parent.mkdir(parents=True, exist_ok=True)
        with self._thread_lock:
            with self._lock_path.open("a+", encoding="utf-8") as lock_file:
                fcntl.flock(lock_file.fileno(), fcntl.LOCK_EX)
                try:
                    yield
                finally:
                    fcntl.flock(lock_file.fileno(), fcntl.LOCK_UN)

    def _quarantine_unlocked(self, raw: str, error: str) -> None:
        if self._quarantine_path is None:
            return
        try:
            with self._quarantine_path.open("a", encoding="utf-8") as quarantine:
                quarantine.write(
                    json.dumps({"raw": raw, "error": error, "time": time.time()}) + "\n"
                )
                quarantine.flush()
                os.fsync(quarantine.fileno())
        except OSError:
            logger.critical("Failed to persist malformed fallback quarantine record", exc_info=True)

    def _read_unlocked(self) -> list[dict]:
        if self._path is None or not self._path.exists():
            return []

        writes: dict[str, dict] = {}
        acknowledged: set[str] = set()
        clean_records: list[dict] = []
        needs_compaction = False
        try:
            with self._path.open("r", encoding="utf-8") as spool_file:
                for line in spool_file:
                    raw_line = line.rstrip("\n")
                    try:
                        record = json.loads(raw_line)
                    except (TypeError, ValueError) as exc:
                        self._quarantine_unlocked(raw_line, str(exc))
                        logger.warning("Quarantined malformed fallback spool record")
                        needs_compaction = True
                        continue
                    record_type = record.get("type") if isinstance(record, dict) else None
                    record_id = str(record.get("retry_id", "")) if isinstance(record, dict) else ""
                    if record_type not in {"write", "ack"} or not record_id:
                        self._quarantine_unlocked(raw_line, "missing/invalid type or retry_id")
                        logger.warning("Quarantined malformed fallback spool record")
                        needs_compaction = True
                        continue
                    clean_records.append(record)
                    if record_type == "write":
                        writes.setdefault(record_id, record)
                    else:
                        acknowledged.add(record_id)
        except OSError:
            logger.warning("Failed to read local fallback spool", exc_info=True)
            return []

        restored: list[dict] = []
        valid_ids: set[str] = set()
        for record_id, record in writes.items():
            if record_id in acknowledged:
                continue
            if not isinstance(record.get("key"), str) or not isinstance(record.get("data"), dict):
                self._quarantine_unlocked(json.dumps(record, default=str), "invalid key/data shape")
                logger.error("Quarantined malformed fallback spool record %s", record_id)
                needs_compaction = True
                continue
            valid_ids.add(record_id)
            restored.append(
                {
                    "retry_id": record_id,
                    "key": record["key"],
                    "data": dict(record.get("data") or {}),
                    "time": record.get("time", 0),
                }
            )

        if needs_compaction:
            temporary = self._path.with_name(f".{self._path.name}.recover.tmp")
            try:
                with temporary.open("w", encoding="utf-8") as spool_file:
                    for record in clean_records:
                        record_id = str(record.get("retry_id", ""))
                        if record.get("type") == "ack" or record_id in valid_ids:
                            spool_file.write(json.dumps(record, default=str) + "\n")
                    spool_file.flush()
                    os.fsync(spool_file.fileno())
                os.replace(temporary, self._path)
            except OSError:
                logger.error("Failed to compact recovered fallback spool", exc_info=True)
                try:
                    temporary.unlink(missing_ok=True)
                except OSError:
                    pass
        return restored

    def load(self) -> list[dict]:
        with self.locked():
            return self._read_unlocked()

    def append(self, item: dict) -> None:
        if self._path is None:
            return
        record = {
            "type": "write",
            "retry_id": str(item["retry_id"]),
            "key": item["key"],
            "data": item["data"],
            "time": item.get("time", time.time()),
        }
        with self.locked():
            with self._path.open("a", encoding="utf-8") as spool_file:
                spool_file.write(json.dumps(record, default=str) + "\n")
                spool_file.flush()
                os.fsync(spool_file.fileno())
            try:
                directory_fd = os.open(self._path.parent, os.O_DIRECTORY)
                try:
                    os.fsync(directory_fd)
                finally:
                    os.close(directory_fd)
            except OSError:
                logger.warning("Failed to fsync fallback spool directory", exc_info=True)

    def _ack_unlocked(self, retry_id: str) -> None:
        if self._path is None:
            return
        with self._path.open("a", encoding="utf-8") as spool_file:
            spool_file.write(
                json.dumps({"type": "ack", "retry_id": str(retry_id)}) + "\n"
            )
            spool_file.flush()
            os.fsync(spool_file.fileno())

        # Rewrite only pending writes. This both removes acknowledgements and
        # makes the empty-spool state explicit after a successful flush.
        pending = self._read_unlocked()
        temporary = self._path.with_name(f".{self._path.name}.tmp")
        with temporary.open("w", encoding="utf-8") as spool_file:
            for item in pending:
                spool_file.write(
                    json.dumps(
                        {
                            "type": "write",
                            "retry_id": item["retry_id"],
                            "key": item["key"],
                            "data": item["data"],
                            "time": item.get("time", time.time()),
                        },
                        default=str,
                    )
                    + "\n"
                )
            spool_file.flush()
            os.fsync(spool_file.fileno())
        os.replace(temporary, self._path)
        try:
            directory_fd = os.open(self._path.parent, os.O_DIRECTORY)
            try:
                os.fsync(directory_fd)
            finally:
                os.close(directory_fd)
        except OSError:
            logger.warning("Failed to fsync fallback spool directory", exc_info=True)

    def ack(self, retry_id: str) -> None:
        if self._path is None or not self._path.exists():
            return
        with self.locked():
            self._ack_unlocked(retry_id)

logger = logging.getLogger(__name__)


class OrderRejectionAction(str, Enum):
    RETRY = "RETRY"
    ALERT = "ALERT"
    SKIP = "SKIP"


@dataclass
class OrderRejectionHandler:
    """Handles broker order rejections with retry logic.

    Rules per spec:
      Entry rejection: do NOT retry (signal may be stale)
      SL order rejection: CRITICAL alert + retry once after 2s
      Exit order rejection: retry 3 times with 1s gap, then alert
    """

    _sl_retry_count: dict[str, int] = field(default_factory=dict)
    _exit_retry_count: dict[str, int] = field(default_factory=dict)
    _max_sl_retries: int = 1
    _max_exit_retries: int = 3

    def handle_entry_rejection(
        self,
        order_id: str,
        reason: str,
    ) -> OrderRejectionAction:
        """Handle entry order rejection — do NOT retry."""
        logger.warning(
            "Entry order rejected (%s): %s — not retrying (signal may be stale)",
            order_id,
            reason,
        )
        return OrderRejectionAction.SKIP

    def handle_sl_rejection(
        self,
        order_id: str,
        reason: str,
    ) -> OrderRejectionAction:
        """Handle SL order rejection — retry once, then alert."""
        retries = self._sl_retry_count.get(order_id, 0)
        if retries < self._max_sl_retries:
            self._sl_retry_count[order_id] = retries + 1
            logger.warning(
                "SL order rejected (%s): %s — retrying (attempt %d/%d)",
                order_id,
                reason,
                retries + 1,
                self._max_sl_retries,
            )
            return OrderRejectionAction.RETRY
        else:
            logger.critical(
                "SL order rejected (%s): %s — max retries reached — ALERT",
                order_id,
                reason,
            )
            return OrderRejectionAction.ALERT

    def handle_exit_rejection(
        self,
        order_id: str,
        reason: str,
    ) -> OrderRejectionAction:
        """Handle exit order rejection — retry 3 times, then alert."""
        retries = self._exit_retry_count.get(order_id, 0)
        if retries < self._max_exit_retries:
            self._exit_retry_count[order_id] = retries + 1
            logger.warning(
                "Exit order rejected (%s): %s — retrying (attempt %d/%d)",
                order_id,
                reason,
                retries + 1,
                self._max_exit_retries,
            )
            return OrderRejectionAction.RETRY
        else:
            logger.critical(
                "Exit order rejected (%s): %s — max retries — ALERT + manual intervention",
                order_id,
                reason,
            )
            return OrderRejectionAction.ALERT

    def reset(self) -> None:
        self._sl_retry_count.clear()
        self._exit_retry_count.clear()


def get_shared_fallback_buffer(storage: object | None) -> "DBFallbackBuffer":
    """Return one fallback owner for all services sharing a storage adapter.

    This removes the hidden second queue previously created by standalone
    ``EntryCoordinator`` construction. The storage adapter is the composition
    boundary; callers that share it now share one flushable queue.
    """
    if storage is None:
        return DBFallbackBuffer()
    existing = getattr(storage, _SHARED_FALLBACK_ATTR, None)
    if isinstance(existing, DBFallbackBuffer):
        return existing
    buffer = DBFallbackBuffer(
        persistence=storage
        if callable(getattr(storage, "enqueue_fallback_write", None))
        and callable(getattr(storage, "load_fallback_writes", None))
        and callable(getattr(storage, "delete_fallback_write", None))
        else None
    )
    try:
        setattr(storage, _SHARED_FALLBACK_ATTR, buffer)
    except Exception:
        logger.debug("Storage adapter does not allow shared fallback ownership", exc_info=True)
    return buffer


@dataclass
class DBFallbackBuffer:
    """Durable FIFO fallback for DB write failures.

    The normal path stores retry records in the SQLite outbox. If that enqueue
    itself fails, an fsynced local JSONL spool is used so a process restart does
    not turn a temporary database outage into a silent data loss. Trade
    decisions are never blocked by either persistence path.
    """

    _buffer: deque = field(default_factory=lambda: deque(maxlen=10000))
    _write_failures: int = 0
    _flush_attempts: int = 0
    _flush_successes: int = 0
    _durability_degraded: bool = False
    _last_durability_error: str = ""
    _memory_only_writes: int = 0
    persistence: object | None = None
    spool_path: str | os.PathLike[str] | None = None
    _lock: threading.RLock = field(default_factory=threading.RLock, init=False, repr=False)
    _spool: _LocalFallbackSpool = field(init=False, repr=False)

    def __post_init__(self) -> None:
        """Restore and de-duplicate pending SQLite and local-spool writes."""
        resolved_spool_path = self.spool_path
        if resolved_spool_path is None and self.persistence is not None:
            spool_path = getattr(self.persistence, "fallback_spool_path", None)
            if callable(spool_path):
                try:
                    resolved_spool_path = spool_path()
                except Exception:
                    logger.debug("Failed to resolve fallback spool path", exc_info=True)
            elif spool_path:
                resolved_spool_path = spool_path
        self._spool = _LocalFallbackSpool(resolved_spool_path)

        restored: list[dict] = []
        if self.persistence is not None:
            try:
                load = getattr(self.persistence, "load_fallback_writes", None)
                if load:
                    restored.extend(load())
            except Exception:
                logger.warning("Failed to restore durable fallback writes", exc_info=True)
        try:
            restored.extend(self._spool.load())
        except Exception:
            logger.warning("Failed to restore local fallback spool", exc_info=True)

        seen: set[str] = set()
        normalized = [self._normalize_item(item) for item in restored]
        normalized.sort(key=self._recovery_order_key)
        for item in normalized:
            retry_id = item["retry_id"]
            if retry_id not in seen:
                self._buffer.append(item)
                seen.add(retry_id)

    @staticmethod
    def _recovery_order_key(item: dict) -> tuple[int, float | str]:
        """Order SQLite timestamps and spool epoch times on one timeline."""
        value = item.get("time", 0)
        if isinstance(value, (int, float)):
            return (0, float(value))
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone(timedelta(hours=5, minutes=30)))
            return (0, parsed.timestamp())
        except (TypeError, ValueError, OverflowError):
            return (1, str(value))

    @staticmethod
    def _normalize_item(raw_item: dict) -> dict:
        """Return the internal shape while keeping retry metadata out of writes."""
        item = dict(raw_item)
        data = dict(item.get("data") or {})
        embedded_retry_id = data.pop(_FALLBACK_ID_KEY, None)
        data.pop(_FALLBACK_TIME_KEY, None)
        retry_id = item.get("retry_id") or embedded_retry_id
        if retry_id is None and item.get("outbox_id") is not None:
            retry_id = f"legacy-outbox-{item['outbox_id']}"
        retry_id = str(retry_id or f"legacy-{uuid4()}")
        item["retry_id"] = retry_id
        item["data"] = data
        item.setdefault("time", time.time())
        return item

    def buffer_write(self, key: str, data: dict) -> None:
        """Buffer a failed DB write and durably spool it when SQLite is down."""
        with self._lock:
            retry_id = str(uuid4())
            item = self._normalize_item(
                {"key": key, "data": dict(data), "time": time.time(), "retry_id": retry_id}
            )
            persisted = False
            if self.persistence is not None:
                try:
                    enqueue = getattr(self.persistence, "enqueue_fallback_write", None)
                    if enqueue:
                        stored_data = dict(item["data"])
                        try:
                            parameters = inspect.signature(enqueue).parameters
                            supports_metadata = (
                                "retry_id" in parameters
                                or any(
                                    parameter.kind is inspect.Parameter.VAR_KEYWORD
                                    for parameter in parameters.values()
                                )
                            )
                        except (TypeError, ValueError):
                            supports_metadata = False
                        if supports_metadata:
                            item["outbox_id"] = enqueue(
                                key,
                                stored_data,
                                retry_id=retry_id,
                                created_at_epoch=float(item["time"]),
                            )
                        else:
                            # Compatibility with older storage doubles/adapters;
                            # business payloads are not mutated on the new path.
                            stored_data[_FALLBACK_ID_KEY] = retry_id
                            stored_data[_FALLBACK_TIME_KEY] = item["time"]
                            item["outbox_id"] = enqueue(key, stored_data)
                        persisted = True
                except Exception as exc:
                    # This includes an exception after SQLite committed. The
                    # same retry_id is therefore written to the local spool;
                    # recovery de-duplicates the two copies before replay.
                    logger.warning(
                        "Failed to persist fallback write; switching to local spool",
                        exc_info=True,
                    )
                    self._last_durability_error = str(exc)
            if not persisted:
                try:
                    if self._spool._path is None:
                        raise OSError("local fallback spool is unavailable")
                    self._spool.append(item)
                    persisted = True
                except Exception as exc:
                    # Memory remains the final non-blocking safety net, but it
                    # is explicitly degraded: callers must block new entries.
                    self._durability_degraded = True
                    self._last_durability_error = str(exc)
                    self._memory_only_writes += 1
                    logger.critical(
                        "Fallback local spool append failed; write is memory-only",
                        exc_info=True,
                    )
            self._buffer.append(item)
            self._write_failures += 1

    def try_flush(self, storage) -> int:
        """Attempt FIFO replay, acknowledging durable copies only after success."""
        with self._lock:
            self._flush_attempts += 1
            flushed = 0
            remaining = []

            while self._buffer:
                item = self._buffer.popleft()
                try:
                    data = item["data"]
                    if item["key"] == "save_performance_snapshot":
                        data = dict(data)
                        data[_FALLBACK_ID_KEY] = item["retry_id"]
                        data[_FALLBACK_TIME_KEY] = item.get("time", time.time())
                    if item["key"] == "save_trade":
                        ensure_sync_adapter_result("storage.save_trade", storage.save_trade, data)
                    elif item["key"] == "save_tick":
                        ensure_sync_adapter_result(
                            "storage.save_tick", storage.save_tick, data.get("symbol", ""), data
                        )
                    elif item["key"] == "save_performance_snapshot":
                        ensure_sync_adapter_result("storage.save_performance_snapshot", storage.save_performance_snapshot, data)
                    elif item["key"] == "save_open_position":
                        ensure_sync_adapter_result("storage.save_open_position", storage.save_open_position, data)
                    else:
                        raise KeyError(f"Unsupported fallback write key: {item['key']}")

                    if self.persistence is not None:
                        delete_by_retry_id = getattr(
                            self.persistence, "delete_fallback_write_by_retry_id", None
                        )
                        if delete_by_retry_id:
                            delete_by_retry_id(item["retry_id"])
                        else:
                            outbox_id = item.get("outbox_id")
                            delete = getattr(self.persistence, "delete_fallback_write", None)
                            if outbox_id is not None and delete:
                                delete(outbox_id)
                    self._spool.ack(item["retry_id"])
                    flushed += 1
                    self._flush_successes += 1
                except Exception:
                    # Preserve the failed item and every item behind it. A
                    # later event must not overtake an earlier durable write.
                    remaining.append(item)
                    break

            for item in reversed(remaining):
                self._buffer.appendleft(item)
            if self._durability_degraded and flushed > 0 and not self._buffer:
                self._durability_degraded = False
                self._last_durability_error = ""
                self._memory_only_writes = 0
            return flushed

    @property
    def buffer_size(self) -> int:
        return len(self._buffer)

    @property
    def durability_degraded(self) -> bool:
        """Whether a persistence failure forced a write into memory only."""
        return self._durability_degraded

    @property
    def durability_status(self) -> dict:
        """Expose persistence health for readiness and operator telemetry."""
        return {
            "degraded": self._durability_degraded,
            "last_error": self._last_durability_error,
            "memory_only_writes": self._memory_only_writes,
            "pending_writes": self.buffer_size,
        }

    def get_stats(self) -> dict:
        return {
            "buffer_size": self.buffer_size,
            "write_failures": self._write_failures,
            "flush_attempts": self._flush_attempts,
            "flush_successes": self._flush_successes,
            **self.durability_status,
        }


class LLMTimeoutRecovery:
    """Manages LLM timeout recovery.

    Rules:
      On timeout: action = HOLD (never exit on timeout)
      Consecutive timeouts >= 5: disable LLM overseer for this session
      Log: LLM unavailable → rule-based exit only
    """

    def __init__(self, max_consecutive_timeouts: int = 5) -> None:
        self._max_timeouts = max_consecutive_timeouts
        self._consecutive_timeouts: dict[str, int] = {}
        self._disabled_symbols: set[str] = set()

    def record_timeout(self, symbol: str) -> bool:
        """Record a timeout. Returns True if LLM should be disabled."""
        count = self._consecutive_timeouts.get(symbol, 0) + 1
        self._consecutive_timeouts[symbol] = count

        if count >= self._max_timeouts:
            self._disabled_symbols.add(symbol)
            logger.warning(
                "LLM disabled for %s — %d consecutive timeouts (rule-based exit only)",
                symbol,
                count,
            )
            return True
        return False

    def record_success(self, symbol: str) -> None:
        """Record a successful LLM call — resets timeout counter."""
        self._consecutive_timeouts[symbol] = 0
        if symbol in self._disabled_symbols:
            self._disabled_symbols.discard(symbol)
            logger.info("LLM re-enabled for %s", symbol)

    def is_disabled(self, symbol: str) -> bool:
        """Check if LLM is disabled for this symbol."""
        return symbol in self._disabled_symbols

    def get_status(self) -> dict:
        return {
            "disabled_symbols": list(self._disabled_symbols),
            "consecutive_timeouts": dict(self._consecutive_timeouts),
        }
