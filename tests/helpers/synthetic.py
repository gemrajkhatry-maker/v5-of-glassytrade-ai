"""Synthetic broker gateway — replays a recorded tick list by index."""

from __future__ import annotations

from quant.brokers.gateway import Tick


class SyntheticGateway:
    """Replays recorded ticks or a generated sequence, bar by bar."""

    def __init__(self, ticks: list[Tick]) -> None:
        self._ticks = ticks
        self._index = 0

    def subscribe(self, symbol: str) -> None:
        self._index = 0

    def next_tick(self) -> Tick | None:
        if self._index >= len(self._ticks):
            return None
        tick = self._ticks[self._index]
        self._index += 1
        return tick

    def try_next_tick(self) -> Tick | None:
        """Non-blocking read — same semantics as next_tick for a replay."""
        return self.next_tick()
