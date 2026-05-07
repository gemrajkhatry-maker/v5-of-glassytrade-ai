"""TickSequencer — assign monotonic sequence numbers to ticks.

Owns: atomic sequence counter, dedup cache per symbol.
Hot path: sequence increment, timestamp dedup check.
Zero allocations.
"""

from __future__ import annotations

import logging
import threading
from typing import Optional

from app.runtime.pipeline import PipelineStage, StageMetrics
from app.runtime.pipeline.events import Tick, SequencedTick

logger = logging.getLogger(__name__)


class TickSequencer:
    """Assign monotonic sequence numbers and enforce per-symbol monotonic input order."""

    def __init__(self, max_symbols: int = 100):
        self._counter = 0
        self._lock = threading.Lock()
        self._max_symbols = max_symbols
        self._max_sequence = (1 << 63) - 1
        # Dedup and ordering state: last timestamp per symbol
        self._last_seen: dict[str, float] = {}
        self._out_of_order_count = 0
        self._order_violation_count = 0
        self._symbol_stall_count: dict[str, int] = {}
        self._metrics = StageMetrics(stage_name="TickSequencer")
        self._drop_count = 0

    @property
    def metrics(self) -> StageMetrics:
        return self._metrics

    @property
    def sequence_count(self) -> int:
        return self._counter

    @property
    def dropped_duplicates(self) -> int:
        return self._drop_count

    def snapshot(self) -> dict:
        with self._lock:
            return {
                "counter": self._counter,
                "max_sequence": self._max_sequence,
                "last_seen": dict(self._last_seen),
                "out_of_order_count": self._out_of_order_count,
                "order_violation_count": self._order_violation_count,
                "symbol_stall_count": dict(self._symbol_stall_count),
                "max_symbols": self._max_symbols,
            }

    def process(self, tick: Tick) -> Optional[SequencedTick]:
        """Process one tick. Returns None if duplicate or out-of-order."""
        with self._lock:
            if self._counter >= self._max_sequence:
                raise OverflowError("TickSequencer sequence counter overflow")
            last = self._last_seen.get(tick.symbol)

            if tick.symbol == "":
                self._metrics.record_error()
                return None

            if last is not None and tick.timestamp < last:
                # Guard against stale/out-of-order ticks per symbol.
                self._drop_count += 1
                self._out_of_order_count += 1
                self._order_violation_count += 1
                self._symbol_stall_count[tick.symbol] = self._symbol_stall_count.get(tick.symbol, 0) + 1
                logger.debug(
                    "Dropping out-of-order tick: %s @ %s (last=%s)",
                    tick.symbol,
                    tick.timestamp,
                    last,
                )
                self._metrics.record_error()
                return None

            if last is not None and tick.timestamp == last:
                # Duplicate timestamp for this symbol.
                logger.debug("Dropping duplicate tick: %s @ %s", tick.symbol, tick.timestamp)
                self._metrics.record_error()
                self._drop_count += 1
                return None

            self._counter += 1
            seq = self._counter
            self._last_seen[tick.symbol] = tick.timestamp

            if self._max_symbols and len(self._last_seen) > self._max_symbols:
                logger.warning(
                    "TickSequencer has exceeded max_symbols=%s. Consider tuning session scope.",
                    self._max_symbols,
                )

        result = SequencedTick(tick=tick, sequence=seq)
        self._metrics.record(0)
        return result

    def process_batch(self, ticks: list[Tick]) -> list[SequencedTick]:
        """Process multiple ticks. Returns sequenced ticks, drops duplicates."""
        results: list[SequencedTick] = []
        for tick in ticks:
            result = self.process(tick)
            if result is not None:
                results.append(result)
        return results

    def warmup(self) -> None:
        """Pre-allocate dedup cache."""
        self._last_seen = {}
        self._counter = 0
        self._out_of_order_count = 0
        self._order_violation_count = 0
        self._symbol_stall_count = {}
        self._drop_count = 0
        self._metrics.reset()
        logger.info("TickSequencer warmed up")

    def teardown(self) -> None:
        """No persistence needed for sequencer."""
        logger.info("TickSequencer teardown: %d ticks sequenced", self._counter)

    def reset(self) -> None:
        """Reset for consistent runtime restart and state reinitialization."""
        self._counter = 0
        self._last_seen = {}
        self._out_of_order_count = 0
        self._order_violation_count = 0
        self._symbol_stall_count = {}
        self._drop_count = 0
        self._metrics.reset()

    def restore(self, snapshot: dict) -> None:
        """Restore state from a checkpoint."""
        if not snapshot:
            return
        with self._lock:
            self._counter = int(snapshot.get("counter", 0))
            self._last_seen = dict(snapshot.get("last_seen", {}))
            self._max_sequence = int(snapshot.get("max_sequence", self._max_sequence))
            self._out_of_order_count = int(snapshot.get("out_of_order_count", 0))
            self._order_violation_count = int(snapshot.get("order_violation_count", 0))
            self._symbol_stall_count = {
                str(symbol): int(count)
                for symbol, count in (snapshot.get("symbol_stall_count", {}) or {}).items()
            }
            self._max_symbols = int(snapshot.get("max_symbols", self._max_symbols))