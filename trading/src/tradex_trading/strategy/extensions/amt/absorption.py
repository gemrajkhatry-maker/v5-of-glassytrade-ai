"""AMT absorption detector over candles (enriched orderflow or plain OHLCV).

Plain candles use the close-vs-open direction as the delta proxy, so the same
volume-spike + compressed-range rule works over the standard datalake.
"""

from __future__ import annotations

from dataclasses import dataclass
from decimal import Decimal

from tradex_domain.market import Candle

from tradex_trading.analytics.orderflow_types import OrderflowCandle


@dataclass(frozen=True, slots=True)
class Absorption:
    side: str
    price: Decimal
    strength: Decimal
    bar_age: int


class AbsorptionDetector:
    """Detect volume spikes trapped inside a compressed bar range."""

    def __init__(
        self,
        volume_mult: Decimal = Decimal("1.5"),
        range_ratio: Decimal = Decimal("0.5"),
        lookback: int = 20,
    ) -> None:
        if volume_mult <= 0 or not 0 < range_ratio <= 1:
            raise ValueError("absorption thresholds are invalid")
        if lookback < 1:
            raise ValueError("lookback must be positive")
        self.volume_mult = volume_mult
        self.range_ratio = range_ratio
        self.lookback = lookback
        self._history: list[Candle | OrderflowCandle] = []
        self._latest: Absorption | None = None

    def reset(self) -> None:
        self._history.clear()
        self._latest = None

    def update(self, candle: Candle | OrderflowCandle) -> Absorption | None:
        prior = self._history[-self.lookback :]
        avg_volume = self._average(
            [Decimal(str(item.volume.value)) for item in prior]
        )
        avg_range = self._average(
            [
                Decimal(str(item.ohlc.high.value - item.ohlc.low.value))
                for item in prior
            ]
        )
        volume = Decimal(str(candle.volume.value))
        bar_range = candle.ohlc.high.value - candle.ohlc.low.value
        detected = (
            avg_volume > 0
            and avg_range > 0
            and volume > self.volume_mult * avg_volume
            and bar_range <= self.range_ratio * avg_range
        )
        if detected:
            side = self._side(candle)
            if side is not None:
                excess = volume / avg_volume - Decimal("1")
                strength = min(Decimal("1"), max(Decimal("0"), excess / Decimal("3")))
                self._latest = Absorption(
                    side=side,
                    price=candle.ohlc.close.value,
                    strength=strength,
                    bar_age=0,
                )
        elif self._latest is not None:
            self._latest = Absorption(
                side=self._latest.side,
                price=self._latest.price,
                strength=self._latest.strength,
                bar_age=self._latest.bar_age + 1,
            )
        self._history.append(candle)
        return self._latest

    @staticmethod
    def _average(values: list[Decimal]) -> Decimal:
        return sum(values, Decimal("0")) / len(values) if values else Decimal("0")

    @staticmethod
    def _side(candle: Candle | OrderflowCandle) -> str | None:
        if isinstance(candle, OrderflowCandle):
            buy = Decimal(str(candle.buy_volume))
            sell = Decimal(str(candle.sell_volume))
            total = buy + sell
            if total <= 0:
                return None
            if buy / total >= Decimal("0.55"):
                return "BUY"
            if sell / total >= Decimal("0.55"):
                return "SELL"
            return None
        if candle.ohlc.close.value > candle.ohlc.open.value:
            return "BUY"
        if candle.ohlc.close.value < candle.ohlc.open.value:
            return "SELL"
        return None

    def snapshot(self) -> Absorption | None:
        return self._latest


__all__ = ["Absorption", "AbsorptionDetector"]
