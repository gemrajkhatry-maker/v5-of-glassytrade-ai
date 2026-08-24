"""Durable event journal + deterministic replay (P0-2).

Every :class:`DomainEvent` published on a :class:`ReactiveBus` can be recorded
to an append-only JSONL file — one serialized event per line, flushed on every
append — and later replayed through a fresh engine. Because events carry their
payload's market timestamp (and the backtest clock drives deterministic time),
a journaled session reproduces the same order/fill/position outcomes on replay
(audit, debugging, and replay == live parity checks).

Format: one JSON object per line, produced by ``tradex_domain.to_dict`` (which
embeds a ``__type__`` marker so ``from_dict(DomainEvent, ...)`` reconstructs
the concrete subclass).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterator
from pathlib import Path
from typing import Any, TextIO

from tradex_domain.events import DomainEvent
from tradex_domain.serialization import from_dict, to_dict

from tradex_trading.reactive.bus import ReactiveBus
from tradex_trading.reactive.thread_safe_bus import ThreadSafeReactiveBus

log = logging.getLogger(__name__)


class EventJournal:
    """Append-only JSONL recorder attached to a :class:`ReactiveBus`.

    Records every ``DomainEvent`` published after :meth:`attach` (or
    construction with ``bus``). Durable: each line is flushed to the OS on
    write; ``close()``/``__exit__`` fsyncs and releases the file. Idempotent
    close (safe under ``with`` + explicit close).
    """

    def __init__(
        self,
        path: str | Path,
        *,
        bus: ReactiveBus | ThreadSafeReactiveBus | None = None,
    ) -> None:
        self._path = Path(path)
        self._file: TextIO | None = self._path.open("a", encoding="utf-8")
        self._count = 0
        self._sub: Any = None
        if bus is not None:
            self.attach(bus)

    # -- recording ---------------------------------------------------------

    def attach(self, bus: ReactiveBus | ThreadSafeReactiveBus) -> None:
        """Start recording every DomainEvent published on *bus*."""
        if self._sub is not None:
            raise RuntimeError("EventJournal already attached to a bus")
        self._sub = bus.of_type(DomainEvent).subscribe(self._on_event)

    def _on_event(self, event: DomainEvent) -> None:
        payload = to_dict(event)
        if self._file is not None:
            self._file.write(json.dumps(payload) + "\n")
            self._file.flush()
        self._count += 1

    @property
    def count(self) -> int:
        """Number of events recorded so far."""
        return self._count

    @property
    def path(self) -> Path:
        """Journal file path."""
        return self._path

    def close(self) -> None:
        """Detach from the bus, fsync, and close the journal file.

        Idempotent — safe to call after a ``with`` block already closed it.
        """
        if self._sub is not None:
            self._sub.dispose()
            self._sub = None
        if self._file is not None:
            try:
                self._file.flush()
                self._file.close()
            finally:
                self._file = None

    def __enter__(self) -> EventJournal:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover – defensive teardown
        try:
            self.close()
        except Exception:
            pass


def iter_journal_events(path: str | Path) -> Iterator[DomainEvent]:
    """Yield the recorded events from *path* in journal order."""
    for line in Path(path).read_text(encoding="utf-8").splitlines():
        if not line.strip():
            continue
        yield from_dict(DomainEvent, json.loads(line))


def replay_journal(path: str | Path, *, bus: ReactiveBus | None = None) -> ReactiveBus:
    """Re-publish every recorded event, in order, onto a fresh (or given) bus.

    Attach an :class:`ExecutionEngine` (or other subscribers) to the returned
    bus before replaying if you want the events to drive execution.
    """
    target = bus if bus is not None else ReactiveBus()
    for event in iter_journal_events(path):
        target.publish(event)
    return target


__all__ = ["EventJournal", "iter_journal_events", "replay_journal"]
