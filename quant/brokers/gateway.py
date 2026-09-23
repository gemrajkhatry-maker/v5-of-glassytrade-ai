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
    # Local arrival epoch (seconds) when the packet was converted/enqueued.
    # Health freshness must prefer this over exchange LTT: an illiquid
    # contract's last_trade_time can be minutes old while quote/depth
    # packets still arrive, which falsely reported the engine as stale.
    arrived_at: float = 0.0


class BrokerGateway(Protocol):
    def subscribe(self, symbol: str) -> None: ...

    def next_tick(self) -> Tick | None: ...
