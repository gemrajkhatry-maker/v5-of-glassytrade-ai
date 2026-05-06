"""Route updates to per-underlying incremental profiles."""
from __future__ import annotations

from typing import TYPE_CHECKING

from app.domain.fabio_ai.services.profile_factory import IncrementalProfileFactory
from app.domain.trading.model.value_objects import OHLC

if TYPE_CHECKING:
    from app.domain.fabio_ai.services.profile_factory import _SimpleIncrementalProfile


def _extract_underlying(symbol: str) -> str:
    clean = symbol.replace("NSE:", "").replace("MCX:", "").replace("BSE:", "").strip()
    if "-" in clean:
        return clean.split("-")[0].strip()
    parts = clean.split()
    return parts[0] if parts else clean


class UnderlyingProfileRouter:
    def __init__(self, profile_factory: IncrementalProfileFactory) -> None:
        self._engines: dict[str, object] = {}
        self._factory = profile_factory
        self._tick_counts: dict[str, int] = {}

    def get_engine(self, underlying: str):
        if underlying not in self._engines:
            self._engines[underlying] = self._factory.create(underlying)
            self._tick_counts[underlying] = 0
        return self._engines[underlying]

    def update(self, underlying: str, underlying_price: float, volume: int | float, delta: float = 0.0) -> None:
        if underlying_price <= 0 or volume <= 0:
            return
        engine = self.get_engine(underlying)
        vol = float(volume)
        buy_vol = max(0.0, (vol + float(delta)) / 2.0)
        candle = OHLC.create(
            time="",
            open=underlying_price,
            high=underlying_price,
            low=underlying_price,
            close=underlying_price,
            volume=vol,
            taker_buy_volume=buy_vol,
            delta=delta,
        )
        engine.update(candle)
        self._tick_counts[underlying] = self._tick_counts.get(underlying, 0) + 1

    def update_from_candle(self, underlying: str, candle: OHLC) -> None:
        if float(candle.close) <= 0 or float(candle.volume) <= 0:
            return
        self.get_engine(underlying).update(candle)
        self._tick_counts[underlying] = self._tick_counts.get(underlying, 0) + 1

    def get_tick_count(self, underlying: str) -> int:
        return self._tick_counts.get(underlying, 0)

    def has_engine(self, underlying: str) -> bool:
        return underlying in self._engines

    @property
    def active_underlyings(self) -> list[str]:
        return list(self._engines.keys())

    @property
    def engine_count(self) -> int:
        return len(self._engines)

    def clear(self, underlying: str | None = None) -> None:
        if underlying:
            self._engines.pop(underlying, None)
            self._tick_counts.pop(underlying, None)
        else:
            self._engines.clear()
            self._tick_counts.clear()
