from __future__ import annotations
from typing import Protocol


class TickTransport(Protocol):
    def frames(self): ...


class DhanFeed:
    def __init__(self, coordinator, security_ids: dict[str, int], transport, clock=None) -> None:
        self.coordinator = coordinator
        self._symbol_to_id: dict[str, int] = {str(k): int(v) for k, v in security_ids.items()}
        self.by_id: dict[int, str] = {int(v): str(k) for k, v in security_ids.items()}
        self.transport = transport
        self.clock = clock
        self._last_price: dict[str, float] = {}

    def by_id_inverted(self) -> dict[str, int]:
        return dict(self._symbol_to_id)

    def handle_frame(self, msg: dict) -> int:
        sid = msg.get("security_id")
        symbol = self.by_id.get(int(sid)) if sid is not None else msg.get("symbol")
        if symbol is None or symbol not in self.coordinator.engines:
            return 0
        price = float(msg.get("ltp") or 0.0)
        vol = float(msg.get("volume") or 0.0)
        if price <= 0:
            return 0
        prev = self._last_price.get(symbol)
        self._last_price[symbol] = price
        if prev is None:
            delta = 0.0
        else:
            # tick rule: direction of price change carries the signed volume
            delta = (1.0 if price > prev else (-1.0 if price < prev else 0.0)) * vol
        ts = float(msg.get("ts") or 0.0)
        self.coordinator.on_tick(symbol, ts, price, vol, delta)
        return 1

    def run_once(self) -> int:
        n = 0
        for frame in self.transport.frames():
            n += self.handle_frame(frame)
        return n

    def run(self) -> None:
        while True:
            for frame in self.transport.frames():
                self.handle_frame(frame)