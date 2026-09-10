"""Phase 3: Event sourcing foundation.

EventStore is an append-only log of events. It is the source of truth.
State is derived by folding events through apply_event().

This module provides:
- EventStore: append-only event log with sequence numbers
- fold(): derive state from events
- export/import: persistence support

Hardening features:
- SHA-256 checksum chain (tamper-evident)
- Dead-letter queue for failed handlers
"""

from __future__ import annotations

import hashlib
import hmac
import json
import logging
import os
import threading
import time as _time
from collections.abc import Sequence
from dataclasses import fields, is_dataclass
from datetime import datetime
from enum import Enum
from typing import Any, Callable, TypeVar

from quant.contracts.timezones import IST
from quant.events import Event
from quant.state_machine import EngineState
from quant.transitions import apply_event

E = TypeVar("E", bound=Event)

# Genesis secret — in production, load from env or secure key store
# This ensures checksums cannot be forged without the secret
_GENESIS_SECRET = os.environ.get("EVENT_STORE_SECRET", "glassytrade-genesis-secret-2026")
logger = logging.getLogger(__name__)


_EPOCH_2000 = 946684800


def _time_epoch(text: str) -> float | None:
    """Parse an ISO-8601 or unix-epoch time string to an epoch, or None.

    Unparseable synthetic ids (``"t0"``, ``"fake1"``) return None so the
    timestamp validation never rejects them.
    """
    try:
        dt = datetime.fromisoformat(text.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=IST)
        return dt.timestamp()
    except (TypeError, ValueError):  # silent-except - non-ISO timestamp returned as unparseable epoch
        pass
    try:
        epoch = float(text)
    except (TypeError, ValueError):
        return None
    if epoch < _EPOCH_2000:
        return None
    return epoch


def _validate_event_time(time) -> None:
    """Reject empty or implausibly-future event timestamps.

    - ``None`` is allowed (unset metadata, pinned by tests).
    - Empty strings are rejected (audit trail integrity).
    - Parseable timestamps more than one hour in the future are rejected
      (clock-skew / data-quality guard). Synthetic ids like ``"t0"`` pass.
    """
    if time is None:
        return
    text = str(time).strip()
    if not text:
        raise ValueError("event time is empty — refusing to append")
    epoch = _time_epoch(text)
    if epoch is not None and epoch > _time.time() + 3600:
        raise ValueError(f"event time {text!r} is in the future — refusing to append")


def _json_value(value: Any, _seen: frozenset[int] = frozenset()) -> Any:
    """Return a deterministic JSON-compatible representation of a payload.

    Self-referential structures (a dataclass/dict holding itself) collapse to
    ``"<cycle>"`` instead of raising RecursionError — a broken payload must
    append (and checksum) rather than crash the emit path. ``_seen`` tracks
    container identity on the CURRENT recursion path only, so the same object
    legitimately appearing twice (a DAG, not a cycle) still serializes fully.
    """
    if value is None or isinstance(value, (str, int, float, bool)):
        return value
    if isinstance(value, Enum):
        return value.value
    if (
        isinstance(value, (dict, list, tuple, set, frozenset))
        or is_dataclass(value)
        or hasattr(value, "__dict__")
    ):
        if id(value) in _seen:
            return "<cycle>"
        _seen = _seen | {id(value)}
    if is_dataclass(value):
        return {
            field.name: _json_value(getattr(value, field.name), _seen)
            for field in fields(value)
        }
    if isinstance(value, dict):
        return {
            str(key): _json_value(item, _seen)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
        }
    if isinstance(value, (list, tuple)):
        return [_json_value(item, _seen) for item in value]
    if isinstance(value, (set, frozenset)):
        # Sets have no stable iteration order; sort their serialized values so
        # the checksum is reproducible across processes.
        serialized = [_json_value(item, _seen) for item in value]
        return sorted(serialized, key=lambda item: json.dumps(item, sort_keys=True))
    if hasattr(value, "__dict__"):
        return {
            str(key): _json_value(item, _seen)
            for key, item in sorted(vars(value).items())
            if not key.startswith("__")
        }
    return repr(value)


def _export_row(event: Event, sequence: int, checksum: str) -> dict[str, Any]:
    """Serialize one event to the export row format.

    Shared by the lazy :class:`EventExport` view so export rows are always
    produced the same way, whether accessed by index or by iteration.
    """
    return {
        "sequence": sequence,
        "symbol": event.symbol,
        "time": event.time,
        "event_type": type(event).__name__,
        "payload": EventStore._event_to_dict(event),
        "checksum": checksum,
    }


class EventExport(Sequence[dict[str, Any]]):
    """Lazy, list-compatible view over an ``EventStore`` export.

    ``export()`` must not materialize every row up front: on a 1M-event log
    that is ~500MB of dicts even when the caller only streams rows to disk.
    But the pinned export() contract is list-like, not generator-like:

    - indexing (``exported[0]``), ``len()``, repeatable iteration, ``==``;
    - in-place mutation of a returned row
      (``exported[0]["payload"]["x"] = …``) must be observable on a later
      full iteration — the tamper-resistance suites tamper an exported row
      and expect ``import_`` to reject it;
    - ``.append()`` (the import-integrity suites forge an extra row by
      appending to an export).

    Rows are therefore produced lazily on first access and MEMOIZED only
    when reached through ``__getitem__`` (the mutation path). Iteration
    streams rows without retaining them (cache hits aside), so a consumer
    that writes the export to disk holds one row at a time. The store
    snapshot is taken at construction, so the view is stable even if the
    store grows afterwards.
    """

    __slots__ = ("_events", "_checksums", "_cache", "_extras")

    def __init__(
        self,
        events: Sequence[Event],
        checksums: Sequence[str],
    ) -> None:
        self._events = list(events)
        self._checksums = list(checksums)
        # Rows built through __getitem__ (indexing / mutation path). Iteration
        # consults this cache first so an in-place payload mutation of an
        # indexed row is re-observed on later passes.
        self._cache: dict[int, dict[str, Any]] = {}
        # Rows appended by the caller (forgery tests) — already materialized.
        self._extras: list[dict[str, Any]] = []

    def __len__(self) -> int:
        return len(self._events) + len(self._extras)

    def _build(self, index: int) -> dict[str, Any]:
        base_len = len(self._events)
        if index < base_len:
            return _export_row(
                self._events[index], index + 1, self._checksums[index]
            )
        return self._extras[index - base_len]

    def _row(self, index: int) -> dict[str, Any]:
        """Return the row at ``index``, memoizing it (mutation path)."""
        row = self._cache.get(index)
        if row is None:
            row = self._build(index)
            self._cache[index] = row
        return row

    def __getitem__(self, index):
        if isinstance(index, slice):
            return [self._row(i) for i in range(*index.indices(len(self)))]
        if index < 0:
            index += len(self)
        if index < 0 or index >= len(self):
            raise IndexError("EventExport index out of range")
        return self._row(index)

    def __iter__(self):
        """Stream rows lazily, honoring mutations of previously indexed rows.

        Only memoized (indexed) rows are retained; the rest are serialized on
        the fly and dropped, so a full iteration of a 1M-event export holds
        one row at a time rather than the whole export in memory.
        """
        for i in range(len(self)):
            row = self._cache.get(i)
            if row is not None:
                yield row
            else:
                yield self._build(i)

    def append(self, item: dict[str, Any]) -> None:
        self._extras.append(item)

    def __eq__(self, other) -> bool:
        if not isinstance(other, (list, tuple, EventExport)):
            return NotImplemented
        if len(self) != len(other):
            return False
        return all(a == b for a, b in zip(self, other))

    __hash__ = None

    def __repr__(self) -> str:
        return f"EventExport({len(self)} rows)"


class EventStore:
    """Append-only event log. Source of truth for engine state.

    Events are never modified or deleted. State is derived by folding
    events through apply_event().

    Thread safety: this class is NOT thread-safe. It should only be
    accessed from the engine's single thread.
    """

    def __init__(self) -> None:
        self._events: list[Event] = []
        self._sequence: int = 0
        self._checksums: list[str] = []  # Stored HMAC checksums for tamper detection
        self._handlers: dict[type[Event], list[tuple[int, Callable[[Event], None]]]] = {}
        self._dead_letter_queue: list[tuple[Event, Exception]] = []
        # Incremental fold cache: derived state up to ``_fold_base`` events.
        # ``append()`` does NOT invalidate it — the next fold() applies only
        # the delta, keeping repeated snapshot folds O(Δ) instead of O(n).
        self._fold_state: EngineState | None = None
        self._fold_base: int = 0
        # Serializes the append critical section (sequence increment + list
        # append + checksum) so concurrent appenders cannot tear _sequence vs
        # _events vs _checksums. The engine still serializes emits through its
        # own _emit_lock; this lock additionally protects external appenders.
        self._append_lock = threading.Lock()

    def append(self, event: Event) -> int:
        """Append an event. Returns the sequence number.

        Args:
            event: Event to append (immutable)

        Returns:
            Sequence number (1-based, monotonic)

        Raises:
            TypeError: If ``event`` is not an Event (type-check contract).
            ValueError: If the event carries an empty or future timestamp.
        """
        if not isinstance(event, Event):
            raise TypeError(
                f"EventStore.append expects an Event, got {type(event).__name__}"
            )
        _validate_event_time(event.time)
        with self._append_lock:
            self._sequence += 1
            sequence = self._sequence
            self._events.append(event)
            # Compute and store HMAC checksum (tamper-evident)
            prev_checksum = self._checksums[-1] if self._checksums else "GENESIS"
            checksum = self._compute_checksum(prev_checksum, event, sequence)
            self._checksums.append(checksum)
        return self._sequence

    def _compute_checksum(
        self, prev_checksum: str, event: Event, sequence: int | None = None
    ) -> str:
        """Compute HMAC-SHA256 checksum of previous checksum + full event payload.

        Uses HMAC with a secret key so checksums cannot be forged
        without access to the secret.
        """
        payload = self._event_to_dict(event)
        return self._checksum_for_payload(
            prev_checksum,
            self._sequence if sequence is None else sequence,
            payload,
        )

    def _checksum_for_payload(
        self, prev_checksum: str, sequence: int, payload: dict[str, Any]
    ) -> str:
        """HMAC-SHA256 of previous checksum + sequence + an exported payload.

        Shared by ``_compute_checksum`` (live appends) and ``import_`` (log
        verification) so both sides of a round-trip agree on the exact bytes
        being signed.
        """
        data = json.dumps(
            {
                "prev": prev_checksum,
                "sequence": sequence,
                "payload": payload,
            },
            sort_keys=True,
        )
        return hmac.new(
            _GENESIS_SECRET.encode(),
            data.encode(),
            hashlib.sha256,
        ).hexdigest()

    def verify_chain(self) -> bool:
        """Verify the integrity of the checksum chain.

        Recomputes the entire chain from genesis using HMAC-SHA256
        and compares against stored checksums. Any modification to
        events, sequence, or checksums will be detected.

        Returns True if the chain is intact, False if tampering detected.
        """
        if len(self._events) != len(self._checksums):
            return False  # Length mismatch indicates tampering

        prev_checksum = "GENESIS"
        for i, event in enumerate(self._events, 1):
            expected = self._compute_checksum(prev_checksum, event, i)
            if self._checksums[i - 1] != expected:
                return False  # Checksum mismatch indicates tampering
            prev_checksum = expected
        return True

    @staticmethod
    def _event_to_dict(event: Event) -> dict[str, Any]:
        """Convert an event and nested payloads to deterministic JSON data."""
        value = _json_value(event)
        return value if isinstance(value, dict) else {"value": value}

    def subscribe(
        self,
        event_type: type[E],
        handler: Callable[[E], None],
        priority: int = 0,
    ) -> None:
        """Subscribe a handler to an event type with optional priority.

        Handlers stay sorted by descending priority. Insertion is O(n) into
        the sorted position instead of a full O(n log n) re-sort per call,
        so bulk subscription at setup time stays cheap.
        """
        handlers = self._handlers.setdefault(event_type, [])
        index = 0
        while index < len(handlers) and handlers[index][0] >= priority:
            index += 1
        handlers.insert(index, (priority, handler))

    def publish_with_dead_letter(self, event: Event) -> None:
        """Publish an event to all subscribed handlers with dead-letter queue.

        Failed handlers are captured in the dead-letter queue instead of
        propagating exceptions.
        """
        import logging

        logger = logging.getLogger(__name__)
        for _, handler in self._handlers.get(type(event), ()):
            try:
                handler(event)
            except Exception as exc:
                self._dead_letter_queue.append((event, exc))
                logger.exception(
                    "Handler %r failed for %s — moved to dead-letter queue",
                    getattr(handler, "__name__", repr(handler)),
                    type(event).__name__,
                )

    def get_dead_letter_queue(self) -> list[tuple[Event, Exception]]:
        """Return the dead-letter queue."""
        return list(self._dead_letter_queue)

    def clear_dead_letter_queue(self) -> None:
        """Clear the dead-letter queue."""
        self._dead_letter_queue = []

    def get_all(self) -> list[Event]:
        """Return all events in insertion order."""
        return list(self._events)

    def get_since(self, sequence: int) -> list[Event]:
        """Return events from a sequence number onward.

        Args:
            sequence: Starting sequence number (inclusive)

        Returns:
            List of events with sequence >= given sequence
        """
        # Events are 1-indexed in sequence
        start_idx = max(0, sequence - 1)
        return list(self._events[start_idx:])

    def get_last(self) -> Event | None:
        """Return the most recent event, or None if empty."""
        if not self._events:
            return None
        return self._events[-1]

    def fold(self) -> EngineState:
        """Derive current state from event log.

        Applies each event in sequence through apply_event().
        This is the ONLY way to derive state from events.

        Integrity guarantees:

        - **Invalid transitions raise**: guard violations (double-open of a
          different id, unmatched close id, close-before-open) and malformed
          payloads propagate as ``ValueError`` — a corrupt log is never
          silently folded into plausible-but-wrong state. Replayed events of
          the same id are handled idempotently inside ``apply_event``.
        - **Truncation is refused**: if events were removed while the sequence
          counter still counts them (``len(_events) < _sequence``), state is
          NOT derived — an empty ``EngineState`` is returned so callers treat
          the log as unreadable rather than trading on partial state.
        - **Incremental**: repeated folds only re-apply events appended since
          the last fold (O(Δ) instead of O(n)).

        Returns:
            Current engine state (empty if no events or log truncated)
        """
        if not self._events:
            self._fold_state = None
            self._fold_base = 0
            return EngineState(symbol="")

        if len(self._events) < self._sequence:
            # Truncated log (events deleted, sequence not renumbered) — refuse
            # to derive state. Reset the cache so a later repair is seen.
            logger.warning(
                "EventStore.fold: event log truncated (%d events, sequence %d) "
                "— returning empty state instead of folding partial state",
                len(self._events), self._sequence,
            )
            self._fold_state = None
            self._fold_base = 0
            return EngineState(symbol="")

        # Cache hit: no new events since the last fold.
        if self._fold_state is not None and self._fold_base == len(self._events):
            return self._fold_state

        # Cache warm and events were appended since: apply only the delta.
        if self._fold_state is not None and len(self._events) > self._fold_base:
            state = self._fold_state
            start = self._fold_base
        else:
            # Initialize symbol from first event
            state = EngineState(symbol=self._events[0].symbol)
            start = 0

        for event in self._events[start:]:
            state = apply_event(state, event)

        self._fold_state = state
        self._fold_base = len(self._events)
        return state

    def prune(self, keep_last: int = 10) -> None:
        """Drop all but the most recent ``keep_last`` events (snapshot support).

        Bounds memory for long-running engines: after the caller has folded
        and snapshotted the current state, old events are no longer needed to
        rebuild it and can be discarded.

        Integrity semantics:

        - **The retained slice is re-rooted as its own checksum chain**
          (recomputed from ``GENESIS``), so ``verify_chain()`` stays True and
          ``export()`` → ``import_()`` round-trips still verify. Keeping the
          original chained HMACs would break both — they sign through the
          discarded prefix.
        - **``keep_last <= 0`` discards the entire log** (full compact). The
          pre-prune slice trap ``events[-0:] == events[0:]`` is avoided by
          treating 0/negative as "keep nothing".
        - **The fold cache is reset**: the retained slice alone cannot
          reproduce the full-log fold (transitions may start before the
          slice), so ``fold()`` after pruning derives state from the retained
          events only. If the slice begins mid-transition (e.g. a
          ``PositionClosed`` whose open was pruned), ``fold()`` raises rather
          than silently folding partial state — the caller must keep the
          pre-prune snapshot for state and use the retained events for
          recent-history replay.

        Args:
            keep_last: Number of most-recent events to retain.
                ``<= 0`` clears the log entirely.
        """
        if not self._events:
            return  # nothing to prune
        with self._append_lock:
            if keep_last <= 0:
                logger.warning(
                    "EventStore.prune(%d): discarded the entire event log "
                    "(%d events) — only the caller's snapshot can rebuild "
                    "state", keep_last, len(self._events),
                )
                self._events = []
                self._checksums = []
                self._sequence = 0
                self._fold_state = None
                self._fold_base = 0
                return
            if keep_last >= len(self._events):
                return  # nothing to drop; chain stays as-is

            keep = self._events[-keep_last:]
            # Re-root the retained events from GENESIS so the pruned log is
            # its own verifiable chain (same recomputation import_ uses).
            prev = "GENESIS"
            re_rooted: list[str] = []
            for i, event in enumerate(keep, 1):
                checksum = self._compute_checksum(prev, event, i)
                re_rooted.append(checksum)
                prev = checksum
            self._events = keep
            self._checksums = re_rooted
            self._sequence = len(keep)
            self._fold_state = None
            self._fold_base = 0

    def export(self) -> EventExport:
        """Export events as dictionaries for persistence.

        Returns a lazy, list-compatible :class:`EventExport` view — calling
        ``export()`` itself is O(1) and rows are produced on first access, so
        streaming a large log to disk does not first materialize every row
        (~500MB of dicts at 1M events). The view keeps the pinned list
        contract the persistence suites rely on: indexing, ``len()``,
        repeatable iteration, ``==`` against lists, in-place row mutation
        (memoized, so tampering is re-observed by ``import_``), and
        ``append()``.

        Each row carries the event's ``sequence`` and its chain ``checksum``
        so ``import_`` can validate contiguity and verify the log integrity.
        The store snapshot is taken at call time: the returned view is stable
        even if events are appended afterwards.

        Returns:
            Lazy export view (indexable sequence of event dictionaries)
        """
        with self._append_lock:
            events_snapshot = list(self._events)
            checksums_snapshot = list(self._checksums)
        return EventExport(events_snapshot, checksums_snapshot)

    def export_to_jsonl(
        self,
        path: str | os.PathLike[str],
        *,
        fsync: bool = False,
    ) -> int:
        """Stream export rows to a JSONL file, one row per line.

        Consumes the lazy :class:`EventExport` view through its streaming
        ``__iter__`` path: each row is serialized on the fly and dropped, so
        the full export never materializes as dicts in memory (~500MB of
        dicts at 1M events). Only rows the caller already indexed are
        retained by the view; this method adds no retention of its own.

        The written file is a plain JSONL sequence of the exact row dicts
        ``export()`` produces — including the ``sequence`` and ``checksum``
        metadata — so it round-trips through ``import_()`` (pass it a list of
        parsed lines) and tamper detection stays intact: a modified row is
        rejected by ``import_``'s checksum verification. Rows are serialized
        with ``sort_keys=True`` for byte-stable output.

        Args:
            path: Destination file (created or truncated).
            fsync: fsync the file on close for crash durability.

        Returns:
            Number of rows written.
        """
        rows = 0
        with open(path, "w", encoding="utf-8") as fh:
            for row in self.export():
                fh.write(json.dumps(row, sort_keys=True) + "\n")
                rows += 1
            fh.flush()
            if fsync:
                os.fsync(fh.fileno())
        return rows

    def import_(self, events: Sequence[dict[str, Any]]) -> None:
        """Import events from dictionaries (export format).

        Integrity guarantees:

        - **Sequence metadata is validated**: sequences must be contiguous
          integers starting at 1. Gaps, duplicates, out-of-order or missing
          sequences raise ``ValueError`` instead of being silently renumbered.
        - **Checksum chain is verified** when the exported dicts carry
          checksums: the whole chain is recomputed over the exported payloads
          before anything is imported, so tampered or corrupted logs raise
          ``ValueError``. Hand-built dicts without checksum metadata (legacy
          fixtures) skip this verification; partially-signed logs are rejected.
        - **Forged position events are rejected**: a ``PositionOpened`` /
          ``PositionClosed`` / ``PositionReduced`` dict WITHOUT checksum
          metadata is indistinguishable from an attacker's forgery — position
          events mutate the trade book, so they must be authenticated by the
          chain. Unsigned bar/risk/unknown events remain importable for
          legacy view-state fixtures.
        - **Atomic**: the existing store is left untouched on any validation or
          reconstruction error — no partial clear/import.

        Args:
            events: List of event dictionaries (from export)
        """
        # 1. Validate sequence metadata before touching any state.
        expected = 1
        for event_dict in events:
            seq = event_dict.get("sequence")
            if seq != expected:
                raise ValueError(
                    f"import: invalid sequence metadata — expected {expected}, "
                    f"got {seq!r} (sequences must be contiguous starting at 1)"
                )
            expected += 1

        # 1b. Reject unsigned position/risk-mutating events (forgery defense).
        # A forged RiskUpdated (e.g., halted=False to lift an emergency halt)
        # is as dangerous as a forged position, so risk events must also be
        # authenticated by the checksum chain.
        position_types = {"PositionOpened", "PositionClosed", "PositionReduced", "RiskUpdated"}
        for event_dict in events:
            if (
                event_dict.get("checksum") is None
                and event_dict.get("event_type") in position_types
            ):
                raise ValueError(
                    f"import: {event_dict.get('event_type')} event at sequence "
                    f"{event_dict.get('sequence')} has no checksum metadata — "
                    f"cannot authenticate; refusing to import a forged "
                    f"position event"
                )

        # 2. Verify the exported checksum chain when checksums are present.
        stored_checksums = [event_dict.get("checksum") for event_dict in events]
        signed = [c for c in stored_checksums if c is not None]
        if signed and len(signed) != len(events):
            raise ValueError(
                "import: inconsistent checksum metadata — all events must "
                "carry a checksum or none may"
            )
        if signed:
            prev = "GENESIS"
            for event_dict, stored in zip(events, stored_checksums):
                recomputed = self._checksum_for_payload(
                    prev,
                    event_dict.get("sequence"),
                    event_dict.get("payload", {}),
                )
                if recomputed != stored:
                    raise ValueError(
                        f"import: checksum mismatch at sequence "
                        f"{event_dict.get('sequence')} — log is tampered "
                        f"or corrupted"
                    )
                prev = stored

        # 3. Reconstruct into temporary lists; commit only on full success.
        new_events: list[Event] = []
        new_checksums: list[str] = []
        prev_checksum = "GENESIS"
        for event_dict in events:
            event = self._dict_to_event(event_dict)
            if event is not None:
                new_events.append(event)
                checksum = self._compute_checksum(
                    prev_checksum, event, len(new_events)
                )
                new_checksums.append(checksum)
                prev_checksum = checksum

        self._events = new_events
        self._sequence = len(events)
        self._checksums = new_checksums
        self._fold_state = None
        self._fold_base = 0

    @staticmethod
    def _dict_to_event(event_dict: dict[str, Any]) -> Event | None:
        """Reconstruct an Event from a dictionary.

        Args:
            event_dict: Event dictionary from export

        Returns:
            Reconstructed Event, or None if type is unknown
        """
        from quant.events import (
            BarClosed,
            PositionClosed,
            PositionOpened,
            PositionReduced,
            RiskUpdated,
        )
        from quant.decision.signal_builder import Signal
        from quant.execution.order import Fill, Order, Position
        from quant.execution.risk import RiskState
        from quant.execution.trade_costs import TradeCosts
        from quant.state_machine import Bar, PositionState

        event_type = event_dict.get("event_type", "")
        payload = event_dict.get("payload", {})
        symbol = event_dict.get("symbol", "")
        time = event_dict.get("time", "")

        def _decode_costs(data):
            if not data:
                return None
            return TradeCosts(**{
                key: float(data.get(key, 0.0))
                for key in ("slippage", "stt", "exchange_fee", "brokerage", "gst", "sebi_charges", "total")
            })

        def _decode_signal(data: dict) -> Signal:
            return Signal(
                type=str(data.get("type") or "LONG"),
                reason=str(data.get("reason") or ""),
                entry=float(data.get("entry") or 0.0),
                sl=float(data.get("sl") or 0.0),
                tp=float(data.get("tp") or 0.0),
                rr=float(data.get("rr") or 0.0),
                model_label=str(data.get("model_label") or ""),
                symbol=str(data.get("symbol") or ""),
                timestamp=str(data.get("timestamp") or ""),
            )

        def _decode_position(data: dict) -> Position | PositionState:
            """Decode a position payload in either of its two serialized shapes:

            - Execution ``Position`` (order/open_price/_id…) — emitted by the
              live engine; reconstructed as the REAL type so downstream
              consumers (projector, transitions) see the true book.
            - Legacy ``PositionState`` fixture (id/entry/sl/tp/side) — the
              pre-sourcing shape some tests still export; kept as-is for
              backward compatibility (its ``.id`` field is pinned by tests).
            """
            if "order" in data or "open_price" in data or "_id" in data:
                order_data = data.get("order") or {}
                signal = _decode_signal(order_data.get("signal") or {})
                size = float(data.get("size") or 0.0)
                order = Order(
                    signal=signal,
                    quantity=float(
                        order_data.get("quantity") or abs(size)
                    ),
                )
                return Position(
                    order=order,
                    open_price=float(data.get("open_price") or signal.entry),
                    open_time=str(data.get("open_time") or ""),
                    size=size,
                    realized_pnl=float(data.get("realized_pnl") or 0.0),
                    pyramid_level=int(data.get("pyramid_level") or 0),
                    is_pyramid=bool(data.get("is_pyramid") or False),
                    _id=str(data.get("_id") or data.get("id") or ""),
                    entry_costs=_decode_costs(data.get("entry_costs")),
                )
            return PositionState(
                id=str(data.get("id") or ""),
                entry=float(data.get("entry") or 0.0),
                size=float(data.get("size") or 0.0),
                sl=float(data.get("sl") or 0.0),
                tp=float(data.get("tp") or 0.0),
                side=str(data.get("side") or "LONG"),
                pyramid_level=int(data.get("pyramid_level") or 0),
                is_pyramid=bool(data.get("is_pyramid") or False),
            )

        def _decode_fill(data: dict) -> Fill:
            pos = _decode_position(data.get("position") or {})
            return Fill(
                position=pos,
                close_price=float(data.get("close_price") or 0.0),
                close_time=str(data.get("close_time") or ""),
                reason=str(data.get("reason") or ""),
                pnl=float(data.get("pnl") or 0.0),
                costs=_decode_costs(data.get("costs")),
                logical_id=str(data.get("logical_id") or ""),
            )

        if event_type == "BarClosed":
            bar_data = payload.get("bar", {})
            bar = Bar(
                time=bar_data.get("time", ""),
                open=float(bar_data.get("open") or 0.0),
                high=float(bar_data.get("high") or 0.0),
                low=float(bar_data.get("low") or 0.0),
                close=float(bar_data.get("close") or 0.0),
                volume=float(bar_data.get("volume") or 0.0),
                vwap=float(bar_data.get("vwap") or 0.0),
                buy_volume=float(bar_data.get("buy_volume") or 0.0),
                sell_volume=float(bar_data.get("sell_volume") or 0.0),
                oi=float(bar_data.get("oi") or 0.0),
                delta=float(bar_data.get("delta") or 0.0),
            )
            return BarClosed(symbol=symbol, time=time, bar=bar)

        elif event_type == "PositionOpened":
            return PositionOpened(
                symbol=symbol,
                time=time,
                position=_decode_position(payload.get("position") or {}),
            )

        elif event_type == "PositionReduced":
            return PositionReduced(
                symbol=symbol,
                time=time,
                fill=_decode_fill(payload.get("fill") or {}),
                remaining=_decode_position(payload.get("remaining") or {}),
            )

        elif event_type == "PositionClosed":
            return PositionClosed(
                symbol=symbol,
                time=time,
                fill=_decode_fill(payload.get("fill") or {}),
            )

        elif event_type == "RiskUpdated":
            risk_data = payload.get("risk", {})
            risk = RiskState(
                daily_pnl=float(risk_data.get("daily_pnl") or 0.0),
                consecutive_losses=int(risk_data.get("consecutive_losses") or 0),
                halted=bool(risk_data.get("halted") or False),
                halt_reason=str(risk_data.get("halt_reason") or ""),
                risk_per_trade_pct=float(risk_data.get("risk_per_trade_pct") or 0.0),
                trades_today=int(risk_data.get("trades_today") or 0),
                equity=float(risk_data.get("equity") or 0.0),
                cushion_tier=str(risk_data.get("cushion_tier") or "CONSERVATIVE"),
            )
            return RiskUpdated(symbol=symbol, time=time, risk=risk)

        else:
            # Unknown event type - return base Event
            return Event(symbol=symbol, time=time)

    def __len__(self) -> int:
        return len(self._events)

    def __repr__(self) -> str:
        return f"EventStore(events={len(self._events)}, sequence={self._sequence})"
