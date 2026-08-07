"""Broker gateway protocol — the seam between live feeds and the kernel."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class Tick:
    time: str
    price: float
    volume: float
    buy_volume: float = 0.0
    sell_volume: float = 0.0
    oi: float = 0.0
    depth: dict | None = None


class BrokerGateway(Protocol):
    def subscribe(self, symbol: str) -> None: ...

    def next_tick(self) -> Tick | None: ...
