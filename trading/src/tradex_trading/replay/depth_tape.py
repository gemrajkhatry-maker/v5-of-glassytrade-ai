"""Depth tape — capture live ``Depth`` snapshots and replay them into backtests.

The datalake stores OHLCV only, so real order-book depth must be captured at
the source. ``DepthTapeRecorder`` attaches to a reactive bus and appends every
``Depth`` snapshot to a durable JSONL tape (one serialized ``Depth`` per line,
flushed on write) — the same durability style as ``EventJournal``, but for
market data. ``load_depth_tape`` reads a tape back into ``Depth`` objects, and
``interleave_tape`` merges candles + depths by timestamp into the event stream
``BacktestEngine.run`` expects, so a captured live session's book can drive a
``BookFillSource`` backtest exactly as it traded (tick-level L2 realism from
real data).
"""

from __future__ import annotations

import json
import logging
from collections.abc import Iterable
from datetime import datetime
from pathlib import Path
from typing import Any, TextIO, TypeVar

from tradex_domain import Candle, Depth
from tradex_domain.serialization import from_dict, to_dict

from tradex_trading.reactive.bus import ReactiveBus
from tradex_trading.reactive.thread_safe_bus import ThreadSafeReactiveBus

log = logging.getLogger(__name__)

_T = TypeVar("_T", Candle, Depth)


class DepthTapeRecorder:
    """Append-only JSONL recorder for ``Depth`` snapshots on a bus.

    Records every ``Depth`` published after :meth:`attach` (or construction
    with ``bus``). Durable: each line is flushed to the OS on write;
    ``close()``/``__exit__`` fsyncs and releases the file.
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
        self._sub: Any | None = None
        if bus is not None:
            self.attach(bus)

    def attach(self, bus: ReactiveBus | ThreadSafeReactiveBus) -> None:
        """Start recording every Depth snapshot published on *bus*."""
        if self._sub is not None:
            raise RuntimeError("DepthTapeRecorder already attached to a bus")
        self._sub = bus.of_type(Depth).subscribe(self._on_depth)

    def _on_depth(self, depth: Depth) -> None:
        payload = to_dict(depth)
        if self._file is not None:
            self._file.write(json.dumps(payload) + "\n")
            self._file.flush()
        self._count += 1

    @property
    def count(self) -> int:
        """Number of snapshots recorded so far."""
        return self._count

    @property
    def path(self) -> Path:
        """Tape file path."""
        return self._path

    def close(self) -> None:
        """Detach from the bus, fsync, and close the tape file."""
        if self._sub is not None:
            self._sub.dispose()
            self._sub = None
        if self._file is not None:
            self._file.flush()
            import os

            os.fsync(self._file.fileno())
            self._file.close()
            self._file = None

    def __enter__(self) -> DepthTapeRecorder:
        return self

    def __exit__(self, *exc: object) -> None:
        self.close()

    def __del__(self) -> None:  # pragma: no cover - defensive
        try:
            self.close()
        except Exception:
            pass


def load_depth_tape(path: str | Path) -> list[Depth]:
    """Read a tape file back into ``Depth`` snapshots, in recorded order."""
    depths: list[Depth] = []
    with Path(path).open(encoding="utf-8") as f:
        for line in f:
            if not line.strip():
                continue
            depths.append(from_dict(Depth, json.loads(line)))
    return depths


def interleave_tape(
    candles: Iterable[Candle],
    depths: Iterable[Depth],
) -> list[Candle | Depth]:
    """Merge candles + depth snapshots into one time-ordered event stream.

    A ``Depth`` snapshot is stamped at (or just past) its bar's close, so on a
    timestamp tie the depth is emitted AFTER the candle — the book the next
    order sees is the snapshot that followed the signal bar, exactly as in a
    live feed.
    """
    events: list[tuple[datetime, int, Candle | Depth]] = [
        (c.timestamp, 0, c) for c in candles
    ]
    for d in depths:
        ts = d.timestamp
        if ts is None:
            raise ValueError("DepthTapeRecorder tapes always carry timestamps")
        events.append((ts, 1, d))
    # Stable sort: same-timestamp events keep candle-before-depth order.
    events.sort(key=lambda e: (e[0], e[1]))
    return [e[2] for e in events]


__all__ = ["DepthTapeRecorder", "interleave_tape", "load_depth_tape"]
